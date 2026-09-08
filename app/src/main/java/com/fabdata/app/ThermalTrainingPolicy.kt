package com.fabdata.app

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase

enum class ThermalTrainingRangeMode {
    INCLUDE,
    EXCLUDE,
    EXCLUSIVE
}

data class ThermalTrainingPolicyRange(
    val id: Long,
    val target: ThermalTrainingTarget,
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
 * Engine-specific training policy.
 *
 * EXCLUSIVE is kept as the persisted name for compatibility, but it is an operation,
 * not a third per-zone state: "exclude everything except this zone". Applying it resets
 * the positive whitelist to the current single selection. Once that whitelist mode is
 * active, INCLUDE adds another selected zone to the whitelist, one selection at a time.
 * EXCLUDE removes/blocks a selected slice. Everything outside the whitelist is ignored.
 *
 * RAW data are never deleted or modified. Physical state propagation can continue
 * through ignored ranges; only the parameter fit/validation is masked.
 */
class ThermalTrainingPolicyStore(private val db: FabDataDb) {
    companion object {
        fun ensure(sql: SQLiteDatabase) {
            sql.execSQL(
                """
                CREATE TABLE IF NOT EXISTS thermal_training_policy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target TEXT NOT NULL,
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
                "CREATE INDEX IF NOT EXISTS idx_thermal_training_policy_target_time " +
                    "ON thermal_training_policy(target, mode, start_ts, end_ts)"
            )
        }
    }

    init { ensure(db.writableDatabase) }

    fun apply(target: ThermalTrainingTarget, mode: ThermalTrainingRangeMode, from: Long, to: Long) {
        targets(target).forEach { actual ->
            when (mode) {
                ThermalTrainingRangeMode.INCLUDE -> includeRange(actual, from, to)
                ThermalTrainingRangeMode.EXCLUDE -> addMerged(actual, ThermalTrainingRangeMode.EXCLUDE, from, to)
                ThermalTrainingRangeMode.EXCLUSIVE -> startOnlySelected(actual, from, to)
            }
        }
    }

    fun accepts(target: ThermalTrainingTarget, timestamp: Long): Boolean {
        val actual = normalizeTarget(target)
        val rows = ranges(actual)
        val excludes = rows.filter { it.enabled && it.mode == ThermalTrainingRangeMode.EXCLUDE }
        if (excludes.any { it.contains(timestamp) }) return false
        val exclusive = rows.filter { it.enabled && it.mode == ThermalTrainingRangeMode.EXCLUSIVE }
        return exclusive.isEmpty() || exclusive.any { it.contains(timestamp) }
    }

    fun ranges(target: ThermalTrainingTarget, enabledOnly: Boolean = true): List<ThermalTrainingPolicyRange> {
        val actual = normalizeTarget(target)
        val enabledClause = if (enabledOnly) " AND enabled=1" else ""
        val out = mutableListOf<ThermalTrainingPolicyRange>()
        db.readableDatabase.rawQuery(
            """
            SELECT id, target, mode, start_ts, end_ts, enabled, created_at, updated_at
            FROM thermal_training_policy
            WHERE target=?$enabledClause
            ORDER BY start_ts, end_ts, id
            """.trimIndent(),
            arrayOf(actual.name)
        ).use { c ->
            while (c.moveToNext()) {
                val parsedTarget = runCatching { ThermalTrainingTarget.valueOf(c.getString(1)) }
                    .getOrDefault(actual)
                val parsedMode = runCatching { ThermalTrainingRangeMode.valueOf(c.getString(2)) }
                    .getOrDefault(ThermalTrainingRangeMode.EXCLUDE)
                out += ThermalTrainingPolicyRange(
                    id = c.getLong(0),
                    target = parsedTarget,
                    mode = parsedMode,
                    from = c.getLong(3),
                    to = c.getLong(4),
                    enabled = c.getInt(5) != 0,
                    createdAt = c.getLong(6),
                    updatedAt = c.getLong(7)
                )
            }
        }
        return out
    }

    fun allRanges(enabledOnly: Boolean = false): List<ThermalTrainingPolicyRange> =
        listOf(ThermalTrainingTarget.INERTIA, ThermalTrainingTarget.SOLAR)
            .flatMap { ranges(it, enabledOnly) }

    fun clear(target: ThermalTrainingTarget) {
        targets(target).forEach { actual ->
            db.writableDatabase.delete("thermal_training_policy", "target=?", arrayOf(actual.name))
        }
    }

    fun signature(target: ThermalTrainingTarget): String {
        val parts = targets(target).flatMap { ranges(it, enabledOnly = false) }
            .sortedWith(compareBy<ThermalTrainingPolicyRange> { it.target.name }.thenBy { it.id })
            .map { "${it.target.name}:${it.mode.name}:${it.from}:${it.to}:${if (it.enabled) 1 else 0}:${it.updatedAt}" }
        return if (parts.isEmpty()) "none" else parts.joinToString("|")
    }

    /**
     * Converts the global engine policy to synthetic exclusion ranges so the existing
     * bi-mass estimator can preserve state propagation while masking only its fit.
     */
    fun asExclusions(
        target: ThermalTrainingTarget,
        from: Long,
        to: Long,
        sensorId: Long
    ): List<ThermalTrainingExclusion> {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        if (end < start) return emptyList()
        val rows = ranges(normalizeTarget(target)).filter { it.enabled }
        val explicit = merge(
            rows.filter { it.mode == ThermalTrainingRangeMode.EXCLUDE }
                .mapNotNull { clip(it.from, it.to, start, end) }
        ).toMutableList()
        val exclusive = merge(
            rows.filter { it.mode == ThermalTrainingRangeMode.EXCLUSIVE }
                .mapNotNull { clip(it.from, it.to, start, end) }
        )
        if (exclusive.isNotEmpty()) {
            var cursor = start
            exclusive.forEach { allowed ->
                if (cursor < allowed.first) explicit += cursor..(allowed.first - 1L)
                cursor = maxOf(cursor, allowed.last + 1L)
            }
            if (cursor <= end) explicit += cursor..end
        }
        return merge(explicit).mapIndexed { index, range ->
            ThermalTrainingExclusion(
                id = Long.MIN_VALUE + index,
                sensorId = sensorId,
                from = range.first,
                to = range.last,
                reason = "Politique ${normalizeTarget(target).name}",
                enabled = true,
                createdAt = 0L,
                updatedAt = 0L
            )
        }
    }

    /**
     * Activates/restarts "only selected zones" mode with exactly the current range.
     * This is deliberately NOT additive: the wording "exclude everything except this
     * zone" means this selection becomes the new base whitelist. The user can then make
     * another single selection and use INCLUDE to add it to the allowed union.
     */
    private fun startOnlySelected(target: ThermalTrainingTarget, from: Long, to: Long) {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        val sql = db.writableDatabase
        val now = System.currentTimeMillis()
        sql.beginTransaction()
        try {
            // Reset only the whitelist rows for this engine; explicit exclusions outside
            // the new allowed range may stay because they are irrelevant while whitelist
            // mode is active. Any exclusion overlapping the chosen range is removed below.
            sql.delete(
                "thermal_training_policy",
                "target=? AND mode=?",
                arrayOf(target.name, ThermalTrainingRangeMode.EXCLUSIVE.name)
            )
            insert(target, ThermalTrainingRangeMode.EXCLUSIVE, start, end, now, now)
            sql.setTransactionSuccessful()
        } finally {
            sql.endTransaction()
        }
        // The selected base zone must really be usable: clear any old explicit exclusion
        // that intersects it. RAW data are never touched.
        removeSlice(target, ThermalTrainingRangeMode.EXCLUDE, start, end)
    }

    private fun includeRange(target: ThermalTrainingTarget, from: Long, to: Long) {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        removeSlice(target, ThermalTrainingRangeMode.EXCLUDE, start, end)
        if (ranges(target).any { it.mode == ThermalTrainingRangeMode.EXCLUSIVE }) {
            addMerged(target, ThermalTrainingRangeMode.EXCLUSIVE, start, end)
        }
    }

    private fun removeSlice(target: ThermalTrainingTarget, mode: ThermalTrainingRangeMode, from: Long, to: Long) {
        val overlapping = ranges(target).filter { it.mode == mode && it.to >= from && it.from <= to }
        if (overlapping.isEmpty()) return
        val sql = db.writableDatabase
        val now = System.currentTimeMillis()
        sql.beginTransaction()
        try {
            overlapping.forEach { row ->
                sql.delete("thermal_training_policy", "id=?", arrayOf(row.id.toString()))
                if (row.from < from) insert(target, mode, row.from, from - 1L, row.createdAt, now)
                if (row.to > to) insert(target, mode, to + 1L, row.to, row.createdAt, now)
            }
            sql.setTransactionSuccessful()
        } finally {
            sql.endTransaction()
        }
    }

    private fun addMerged(target: ThermalTrainingTarget, mode: ThermalTrainingRangeMode, from: Long, to: Long) {
        require(mode != ThermalTrainingRangeMode.INCLUDE)
        var start = minOf(from, to)
        var end = maxOf(from, to)
        val overlapping = ranges(target).filter {
            it.mode == mode && it.from <= end + 1L && it.to + 1L >= start
        }
        overlapping.forEach {
            start = minOf(start, it.from)
            end = maxOf(end, it.to)
        }
        val sql = db.writableDatabase
        sql.beginTransaction()
        try {
            overlapping.forEach { sql.delete("thermal_training_policy", "id=?", arrayOf(it.id.toString())) }
            insert(target, mode, start, end, System.currentTimeMillis(), System.currentTimeMillis())
            sql.setTransactionSuccessful()
        } finally {
            sql.endTransaction()
        }
    }

    private fun insert(
        target: ThermalTrainingTarget,
        mode: ThermalTrainingRangeMode,
        from: Long,
        to: Long,
        createdAt: Long,
        updatedAt: Long
    ): Long {
        val values = ContentValues().apply {
            put("target", normalizeTarget(target).name)
            put("mode", mode.name)
            put("start_ts", from)
            put("end_ts", to)
            put("enabled", 1)
            put("created_at", createdAt)
            put("updated_at", updatedAt)
        }
        return db.writableDatabase.insertOrThrow("thermal_training_policy", null, values)
    }

    private fun targets(target: ThermalTrainingTarget): List<ThermalTrainingTarget> = when (target) {
        ThermalTrainingTarget.BOTH -> listOf(ThermalTrainingTarget.INERTIA, ThermalTrainingTarget.SOLAR)
        else -> listOf(target)
    }

    private fun normalizeTarget(target: ThermalTrainingTarget): ThermalTrainingTarget =
        if (target == ThermalTrainingTarget.BOTH) ThermalTrainingTarget.INERTIA else target

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
