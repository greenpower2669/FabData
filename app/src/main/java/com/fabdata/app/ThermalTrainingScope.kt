package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase

enum class ThermalTrainingFocus {
    INERTIA,
    SOLAR
}

object ThermalTrainingSubject {
    fun inertia(sensorId: Long): String = "sensor:$sensorId"
    fun solar(wallId: String): String = "wall:$wallId"
}

class ThermalTrainingTargetPrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_thermal_training_target", Context.MODE_PRIVATE)

    fun focus(): ThermalTrainingFocus = runCatching {
        ThermalTrainingFocus.valueOf(prefs.getString("focus", ThermalTrainingFocus.INERTIA.name)!!)
    }.getOrDefault(ThermalTrainingFocus.INERTIA)

    fun setFocus(value: ThermalTrainingFocus) {
        prefs.edit().putString("focus", value.name).apply()
    }

    fun indoorSensorId(): Long? = prefs.getLong("indoor_sensor_id", -1L).takeIf { it >= 0L }
    fun setIndoorSensorId(id: Long?) {
        prefs.edit().apply {
            if (id == null) remove("indoor_sensor_id") else putLong("indoor_sensor_id", id)
        }.apply()
    }

    fun wallId(): String? = prefs.getString("wall_id", null)?.takeIf { it.isNotBlank() }
    fun setWallId(id: String?) {
        prefs.edit().apply {
            if (id.isNullOrBlank()) remove("wall_id") else putString("wall_id", id)
        }.apply()
    }

    fun wallSensorId(): Long? = prefs.getLong("wall_sensor_id", -1L).takeIf { it >= 0L }
    fun setWallSensorId(id: Long?) {
        prefs.edit().apply {
            if (id == null) remove("wall_sensor_id") else putLong("wall_sensor_id", id)
        }.apply()
    }
}

data class ThermalScopedTrainingRange(
    val id: Long,
    val target: ThermalTrainingTarget,
    val subjectKey: String,
    val mode: ThermalTrainingRangeMode,
    val from: Long,
    val to: Long,
    val enabled: Boolean,
    val createdAt: Long,
    val updatedAt: Long
) {
    fun contains(timestamp: Long): Boolean = enabled && timestamp in from..to
}

/**
 * v0.20.6: per-model training windows.
 *
 * The old thermal_training_policy table is intentionally left untouched for backward
 * compatibility. Once a scoped policy exists for a subject, it becomes authoritative
 * for that subject only: one indoor sensor or one wall. This prevents a solar selection
 * for the south wall from silently changing the west wall, and prevents an inertia
 * selection for one room from leaking to another room.
 */
class ThermalTrainingScopedPolicyStore(private val db: FabDataDb) {
    companion object {
        fun ensure(sql: SQLiteDatabase) {
            sql.execSQL(
                """
                CREATE TABLE IF NOT EXISTS thermal_training_policy_scoped (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target TEXT NOT NULL,
                    subject_key TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    start_ts INTEGER NOT NULL,
                    end_ts INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    CHECK(end_ts >= start_ts)
                )
                """.trimIndent()
            )
            sql.execSQL(
                "CREATE INDEX IF NOT EXISTS idx_thermal_training_policy_scoped " +
                    "ON thermal_training_policy_scoped(target, subject_key, mode, start_ts, end_ts)"
            )
        }
    }

    init { ensure(db.writableDatabase) }

    fun hasAny(target: ThermalTrainingTarget, subjectKey: String): Boolean =
        exactRanges(target, subjectKey, enabledOnly = true).isNotEmpty()

    fun apply(
        target: ThermalTrainingTarget,
        subjectKey: String,
        mode: ThermalTrainingRangeMode,
        from: Long,
        to: Long
    ) {
        require(target != ThermalTrainingTarget.BOTH) { "BOTH doit être réparti avant stockage" }
        require(subjectKey.isNotBlank()) { "Sujet d'entraînement manquant" }
        when (mode) {
            ThermalTrainingRangeMode.INCLUDE -> includeRange(target, subjectKey, from, to)
            ThermalTrainingRangeMode.EXCLUDE -> addMerged(target, subjectKey, mode, from, to)
            ThermalTrainingRangeMode.EXCLUSIVE -> startOnlySelected(target, subjectKey, from, to)
        }
    }

    fun accepts(target: ThermalTrainingTarget, subjectKey: String, timestamp: Long): Boolean {
        val rows = exactRanges(target, subjectKey, enabledOnly = true)
        if (rows.isEmpty()) return true
        if (rows.any { it.mode == ThermalTrainingRangeMode.EXCLUDE && it.contains(timestamp) }) return false
        val whitelist = rows.filter { it.mode == ThermalTrainingRangeMode.EXCLUSIVE }
        return whitelist.isEmpty() || whitelist.any { it.contains(timestamp) }
    }

    fun signature(target: ThermalTrainingTarget, subjectKey: String): String {
        val rows = exactRanges(target, subjectKey, enabledOnly = false)
        if (rows.isEmpty()) return "none"
        return rows.joinToString("|") {
            "${it.target.name}:${it.subjectKey}:${it.mode.name}:${it.from}:${it.to}:${if (it.enabled) 1 else 0}:${it.updatedAt}"
        }
    }

    fun asExclusions(
        target: ThermalTrainingTarget,
        subjectKey: String,
        from: Long,
        to: Long,
        sensorId: Long
    ): List<ThermalTrainingExclusion> {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        val rows = exactRanges(target, subjectKey, enabledOnly = true)
        if (rows.isEmpty()) return emptyList()
        val blocked = rows.filter { it.mode == ThermalTrainingRangeMode.EXCLUDE }
            .mapNotNull { clip(it.from, it.to, start, end) }
            .toMutableList()
        val allowed = merge(rows.filter { it.mode == ThermalTrainingRangeMode.EXCLUSIVE }
            .mapNotNull { clip(it.from, it.to, start, end) })
        if (allowed.isNotEmpty()) {
            var cursor = start
            allowed.forEach { range ->
                if (cursor < range.first) blocked += cursor..(range.first - 1L)
                cursor = maxOf(cursor, range.last + 1L)
            }
            if (cursor <= end) blocked += cursor..end
        }
        return merge(blocked).mapIndexed { index, range ->
            ThermalTrainingExclusion(
                id = Long.MIN_VALUE + 10_000L + index,
                sensorId = sensorId,
                from = range.first,
                to = range.last,
                reason = "Politique ciblée ${target.name} · $subjectKey",
                enabled = true,
                createdAt = 0L,
                updatedAt = 0L
            )
        }
    }

    private fun exactRanges(
        target: ThermalTrainingTarget,
        subjectKey: String,
        enabledOnly: Boolean
    ): List<ThermalScopedTrainingRange> {
        val enabledClause = if (enabledOnly) " AND enabled=1" else ""
        val out = mutableListOf<ThermalScopedTrainingRange>()
        db.readableDatabase.rawQuery(
            """
            SELECT id, target, subject_key, mode, start_ts, end_ts, enabled, created_at, updated_at
            FROM thermal_training_policy_scoped
            WHERE target=? AND subject_key=?$enabledClause
            ORDER BY start_ts, end_ts, id
            """.trimIndent(),
            arrayOf(target.name, subjectKey)
        ).use { c ->
            while (c.moveToNext()) {
                out += ThermalScopedTrainingRange(
                    id = c.getLong(0),
                    target = runCatching { ThermalTrainingTarget.valueOf(c.getString(1)) }.getOrDefault(target),
                    subjectKey = c.getString(2),
                    mode = runCatching { ThermalTrainingRangeMode.valueOf(c.getString(3)) }
                        .getOrDefault(ThermalTrainingRangeMode.EXCLUDE),
                    from = c.getLong(4),
                    to = c.getLong(5),
                    enabled = c.getInt(6) != 0,
                    createdAt = c.getLong(7),
                    updatedAt = c.getLong(8)
                )
            }
        }
        return out
    }

    private fun startOnlySelected(
        target: ThermalTrainingTarget,
        subjectKey: String,
        from: Long,
        to: Long
    ) {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        val sql = db.writableDatabase
        sql.beginTransaction()
        try {
            sql.delete(
                "thermal_training_policy_scoped",
                "target=? AND subject_key=? AND mode=?",
                arrayOf(target.name, subjectKey, ThermalTrainingRangeMode.EXCLUSIVE.name)
            )
            insert(target, subjectKey, ThermalTrainingRangeMode.EXCLUSIVE, start, end)
            sql.setTransactionSuccessful()
        } finally {
            sql.endTransaction()
        }
        removeSlice(target, subjectKey, ThermalTrainingRangeMode.EXCLUDE, start, end)
    }

    private fun includeRange(
        target: ThermalTrainingTarget,
        subjectKey: String,
        from: Long,
        to: Long
    ) {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        removeSlice(target, subjectKey, ThermalTrainingRangeMode.EXCLUDE, start, end)
        if (exactRanges(target, subjectKey, true).any { it.mode == ThermalTrainingRangeMode.EXCLUSIVE }) {
            addMerged(target, subjectKey, ThermalTrainingRangeMode.EXCLUSIVE, start, end)
        }
    }

    private fun removeSlice(
        target: ThermalTrainingTarget,
        subjectKey: String,
        mode: ThermalTrainingRangeMode,
        from: Long,
        to: Long
    ) {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        val overlapping = exactRanges(target, subjectKey, true)
            .filter { it.mode == mode && it.to >= start && it.from <= end }
        if (overlapping.isEmpty()) return
        val sql = db.writableDatabase
        sql.beginTransaction()
        try {
            overlapping.forEach { row ->
                sql.delete("thermal_training_policy_scoped", "id=?", arrayOf(row.id.toString()))
                if (row.from < start) insert(target, subjectKey, mode, row.from, start - 1L, row.createdAt)
                if (row.to > end) insert(target, subjectKey, mode, end + 1L, row.to, row.createdAt)
            }
            sql.setTransactionSuccessful()
        } finally {
            sql.endTransaction()
        }
    }

    private fun addMerged(
        target: ThermalTrainingTarget,
        subjectKey: String,
        mode: ThermalTrainingRangeMode,
        from: Long,
        to: Long
    ) {
        var start = minOf(from, to)
        var end = maxOf(from, to)
        val overlapping = exactRanges(target, subjectKey, true).filter {
            it.mode == mode && it.from <= end + 1L && it.to + 1L >= start
        }
        overlapping.forEach {
            start = minOf(start, it.from)
            end = maxOf(end, it.to)
        }
        val sql = db.writableDatabase
        sql.beginTransaction()
        try {
            overlapping.forEach { sql.delete("thermal_training_policy_scoped", "id=?", arrayOf(it.id.toString())) }
            insert(target, subjectKey, mode, start, end)
            sql.setTransactionSuccessful()
        } finally {
            sql.endTransaction()
        }
    }

    private fun insert(
        target: ThermalTrainingTarget,
        subjectKey: String,
        mode: ThermalTrainingRangeMode,
        from: Long,
        to: Long,
        createdAt: Long = System.currentTimeMillis()
    ) {
        val now = System.currentTimeMillis()
        val values = ContentValues().apply {
            put("target", target.name)
            put("subject_key", subjectKey)
            put("mode", mode.name)
            put("start_ts", minOf(from, to))
            put("end_ts", maxOf(from, to))
            put("enabled", 1)
            put("created_at", createdAt)
            put("updated_at", now)
        }
        db.writableDatabase.insertOrThrow("thermal_training_policy_scoped", null, values)
    }

    private fun clip(from: Long, to: Long, min: Long, max: Long): LongRange? {
        val start = maxOf(minOf(from, to), min)
        val end = minOf(maxOf(from, to), max)
        return if (start <= end) start..end else null
    }

    private fun merge(input: List<LongRange>): List<LongRange> {
        if (input.isEmpty()) return emptyList()
        val sorted = input.sortedBy { it.first }
        val out = mutableListOf<LongRange>()
        var start = sorted.first().first
        var end = sorted.first().last
        sorted.drop(1).forEach { range ->
            if (range.first <= end + 1L) end = maxOf(end, range.last)
            else {
                out += start..end
                start = range.first
                end = range.last
            }
        }
        out += start..end
        return out
    }
}
