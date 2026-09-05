package com.fabdata.app

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase

/**
 * Période que l'utilisateur juge non représentative pour l'apprentissage thermique.
 *
 * IMPORTANT : une exclusion ne supprime ni ne modifie aucune donnée RAW. Elle ne fait
 * qu'empêcher les points concernés de participer au fit / à la validation du modèle.
 * L'état thermique continue, lui, à être propagé à travers la période.
 */
data class ThermalTrainingExclusion(
    val id: Long,
    val sensorId: Long,
    val from: Long,
    val to: Long,
    val reason: String,
    val enabled: Boolean,
    val createdAt: Long,
    val updatedAt: Long
) {
    fun contains(timestamp: Long): Boolean = enabled && timestamp in from..to
}

object ThermalTrainingMaskSchema {
    fun ensure(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS thermal_training_exclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id INTEGER NOT NULL,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                CHECK(end_ts >= start_ts)
            )
            """.trimIndent()
        )
        db.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_thermal_training_exclusions_sensor_time " +
                "ON thermal_training_exclusions(sensor_id, start_ts, end_ts)"
        )
    }
}

class ThermalTrainingMaskStore(private val db: FabDataDb) {
    init {
        ThermalTrainingMaskSchema.ensure(db.writableDatabase)
    }

    fun add(sensorId: Long, from: Long, to: Long, reason: String = ""): Long {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        require(sensorId >= 0L) { "Une exclusion d'apprentissage doit viser une sonde physique." }
        val now = System.currentTimeMillis()
        val values = ContentValues().apply {
            put("sensor_id", sensorId)
            put("start_ts", start)
            put("end_ts", end)
            put("reason", reason.trim())
            put("enabled", 1)
            put("created_at", now)
            put("updated_at", now)
        }
        return db.writableDatabase.insertOrThrow("thermal_training_exclusions", null, values)
    }

    fun update(id: Long, from: Long, to: Long, reason: String, enabled: Boolean = true): Boolean {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        val values = ContentValues().apply {
            put("start_ts", start)
            put("end_ts", end)
            put("reason", reason.trim())
            put("enabled", if (enabled) 1 else 0)
            put("updated_at", System.currentTimeMillis())
        }
        return db.writableDatabase.update(
            "thermal_training_exclusions", values, "id=?", arrayOf(id.toString())
        ) > 0
    }

    fun setEnabled(id: Long, enabled: Boolean): Boolean {
        val values = ContentValues().apply {
            put("enabled", if (enabled) 1 else 0)
            put("updated_at", System.currentTimeMillis())
        }
        return db.writableDatabase.update(
            "thermal_training_exclusions", values, "id=?", arrayOf(id.toString())
        ) > 0
    }

    fun delete(id: Long): Boolean =
        db.writableDatabase.delete("thermal_training_exclusions", "id=?", arrayOf(id.toString())) > 0

    fun query(sensorId: Long, from: Long, to: Long, enabledOnly: Boolean = true): List<ThermalTrainingExclusion> {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        val enabledClause = if (enabledOnly) " AND enabled=1" else ""
        val out = mutableListOf<ThermalTrainingExclusion>()
        db.readableDatabase.rawQuery(
            """
            SELECT id, sensor_id, start_ts, end_ts, reason, enabled, created_at, updated_at
            FROM thermal_training_exclusions
            WHERE sensor_id=? AND end_ts>=? AND start_ts<=?$enabledClause
            ORDER BY start_ts, end_ts, id
            """.trimIndent(),
            arrayOf(sensorId.toString(), start.toString(), end.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += ThermalTrainingExclusion(
                    id = c.getLong(0),
                    sensorId = c.getLong(1),
                    from = c.getLong(2),
                    to = c.getLong(3),
                    reason = c.getString(4),
                    enabled = c.getInt(5) != 0,
                    createdAt = c.getLong(6),
                    updatedAt = c.getLong(7)
                )
            }
        }
        return out
    }

    /**
     * Signature stable utilisée dans la clé de cache du moteur inertiel.
     * sensorId=null couvre toutes les sondes, utile avant la sélection automatique
     * de la sonde la plus riche.
     */
    fun signature(sensorId: Long? = null): String {
        val where = if (sensorId == null) "" else " WHERE sensor_id=?"
        val args = sensorId?.let { arrayOf(it.toString()) }
        val parts = mutableListOf<String>()
        db.readableDatabase.rawQuery(
            """
            SELECT id, sensor_id, start_ts, end_ts, enabled, updated_at
            FROM thermal_training_exclusions$where
            ORDER BY sensor_id, start_ts, end_ts, id
            """.trimIndent(),
            args
        ).use { c ->
            while (c.moveToNext()) {
                parts += "${c.getLong(0)}:${c.getLong(1)}:${c.getLong(2)}:${c.getLong(3)}:${c.getInt(4)}:${c.getLong(5)}"
            }
        }
        return if (parts.isEmpty()) "none" else parts.joinToString("|")
    }
}
