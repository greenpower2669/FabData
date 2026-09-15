package com.fabdata.app

import android.content.ContentValues
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase

/**
 * Persistent life-cycle for the canonical ten-minute multiverse dial strip.
 *
 * A target is born as the single FUTURE slot, is enriched while it is the single PRESENT,
 * then is sealed forever when it enters one of the nine visible HISTORY slots. The original
 * forecast fields never move after creation; only terrain/error fields may be enriched before
 * the row is sealed. Older rows remain in the full archive after leaving the nine-slot strip.
 */
data class ForecastDialRecord(
    val referenceKey: String,
    val targetTs: Long,
    val weatherHorizon: Int,
    val adaptiveHorizon: Int,
    val officialTemp: Double?,
    val localTemp: Double?,
    val actualTemp: Double?,
    val actualIsMeasured: Boolean,
    val officialSlope: Double?,
    val localSlope: Double?,
    val actualSlope: Double?,
    val officialAcceleration: Double?,
    val localAcceleration: Double?,
    val actualAcceleration: Double?,
    val officialError: Double?,
    val localError: Double?,
    val trainingSamples: Int,
    val phase: String,
    val locked: Boolean,
    val createdAt: Long,
    val updatedAt: Long
)

object ForecastDialHistoryStore {
    const val TABLE = "forecast_dial_history"
    const val PHASE_FUTURE = "future"
    const val PHASE_PRESENT = "present"
    const val PHASE_HISTORY = "history"

    fun ensure(sql: SQLiteDatabase) {
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE (
                reference_key TEXT NOT NULL,
                target_ts INTEGER NOT NULL,
                weather_horizon INTEGER NOT NULL,
                adaptive_horizon INTEGER NOT NULL,
                official_temp REAL,
                local_temp REAL,
                actual_temp REAL,
                actual_is_measured INTEGER NOT NULL DEFAULT 0,
                official_slope REAL,
                local_slope REAL,
                actual_slope REAL,
                official_acceleration REAL,
                local_acceleration REAL,
                actual_acceleration REAL,
                official_error REAL,
                local_error REAL,
                training_samples INTEGER NOT NULL DEFAULT 0,
                phase TEXT NOT NULL,
                locked INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(reference_key, target_ts, weather_horizon, adaptive_horizon)
            )
            """.trimIndent()
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_dial_history_target ON $TABLE(reference_key, target_ts, locked)"
        )
    }

    fun get(
        sql: SQLiteDatabase,
        referenceKey: String,
        targetTs: Long,
        weatherHorizon: Int,
        adaptiveHorizon: Int
    ): ForecastDialRecord? {
        ensure(sql)
        return sql.rawQuery(
            """
            SELECT reference_key, target_ts, weather_horizon, adaptive_horizon,
                   official_temp, local_temp, actual_temp, actual_is_measured,
                   official_slope, local_slope, actual_slope,
                   official_acceleration, local_acceleration, actual_acceleration,
                   official_error, local_error, training_samples, phase, locked,
                   created_at, updated_at
            FROM $TABLE
            WHERE reference_key=? AND target_ts=? AND weather_horizon=? AND adaptive_horizon=?
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey,
                targetTs.toString(),
                weatherHorizon.toString(),
                adaptiveHorizon.toString()
            )
        ).use { c -> if (c.moveToFirst()) c.toRecord() else null }
    }

    /**
     * Saves an unsealed row. If a row is already sealed, it is returned unchanged.
     */
    fun save(sql: SQLiteDatabase, record: ForecastDialRecord): ForecastDialRecord {
        ensure(sql)
        val current = get(sql, record.referenceKey, record.targetTs, record.weatherHorizon, record.adaptiveHorizon)
        if (current?.locked == true) return current
        val createdAt = current?.createdAt ?: record.createdAt
        val normalized = record.copy(createdAt = createdAt)
        sql.insertWithOnConflict(TABLE, null, normalized.toValues(), SQLiteDatabase.CONFLICT_REPLACE)
        return normalized
    }

    /** Restore is intentionally authoritative: a backup may contain an already sealed history. */
    fun restore(sql: SQLiteDatabase, record: ForecastDialRecord) {
        ensure(sql)
        sql.insertWithOnConflict(TABLE, null, record.toValues(), SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun all(sql: SQLiteDatabase): List<ForecastDialRecord> {
        ensure(sql)
        val out = mutableListOf<ForecastDialRecord>()
        sql.rawQuery(
            """
            SELECT reference_key, target_ts, weather_horizon, adaptive_horizon,
                   official_temp, local_temp, actual_temp, actual_is_measured,
                   official_slope, local_slope, actual_slope,
                   official_acceleration, local_acceleration, actual_acceleration,
                   official_error, local_error, training_samples, phase, locked,
                   created_at, updated_at
            FROM $TABLE
            ORDER BY reference_key, target_ts, weather_horizon, adaptive_horizon
            """.trimIndent(), null
        ).use { c -> while (c.moveToNext()) out += c.toRecord() }
        return out
    }

    private fun ForecastDialRecord.toValues(): ContentValues = ContentValues().apply {
        put("reference_key", referenceKey)
        put("target_ts", targetTs)
        put("weather_horizon", weatherHorizon)
        put("adaptive_horizon", adaptiveHorizon)
        putNullable("official_temp", officialTemp)
        putNullable("local_temp", localTemp)
        putNullable("actual_temp", actualTemp)
        put("actual_is_measured", if (actualIsMeasured) 1 else 0)
        putNullable("official_slope", officialSlope)
        putNullable("local_slope", localSlope)
        putNullable("actual_slope", actualSlope)
        putNullable("official_acceleration", officialAcceleration)
        putNullable("local_acceleration", localAcceleration)
        putNullable("actual_acceleration", actualAcceleration)
        putNullable("official_error", officialError)
        putNullable("local_error", localError)
        put("training_samples", trainingSamples.coerceAtLeast(0))
        put("phase", phase)
        put("locked", if (locked) 1 else 0)
        put("created_at", createdAt)
        put("updated_at", updatedAt)
    }

    private fun ContentValues.putNullable(key: String, value: Double?) {
        if (value == null || !value.isFinite()) putNull(key) else put(key, value)
    }

    private fun Cursor.doubleOrNull(index: Int): Double? =
        if (isNull(index)) null else getDouble(index).takeIf { it.isFinite() }

    private fun Cursor.toRecord() = ForecastDialRecord(
        referenceKey = getString(0),
        targetTs = getLong(1),
        weatherHorizon = getInt(2),
        adaptiveHorizon = getInt(3),
        officialTemp = doubleOrNull(4),
        localTemp = doubleOrNull(5),
        actualTemp = doubleOrNull(6),
        actualIsMeasured = getInt(7) != 0,
        officialSlope = doubleOrNull(8),
        localSlope = doubleOrNull(9),
        actualSlope = doubleOrNull(10),
        officialAcceleration = doubleOrNull(11),
        localAcceleration = doubleOrNull(12),
        actualAcceleration = doubleOrNull(13),
        officialError = doubleOrNull(14),
        localError = doubleOrNull(15),
        trainingSamples = getInt(16),
        phase = getString(17),
        locked = getInt(18) != 0,
        createdAt = getLong(19),
        updatedAt = getLong(20)
    )
}
