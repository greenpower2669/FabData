package com.fabdata.app

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase

/**
 * Frozen display/backtest points for comparing weather forecast vs Fab local forecast.
 *
 * These are DERIVED points, never raw model runs and never observations. Keeping them in a
 * separate table lets backups restore the exact 10-minute visual/backtest without downloading
 * the historical forecast API again or silently changing an old curve after an app update.
 */
data class ForecastCurve10mPoint(
    val targetAt: Long,
    val weatherTemperature: Double,
    val fabTemperature: Double,
    val humidity: Double,
    val weatherConfidence: Double,
    val fabConfidence: Double,
    val origin: String,
    val modelVersion: String
)

object ForecastCurve10mStore {
    const val TABLE = "forecast_curve_10m_archive"
    const val MODEL_VERSION = "fab-local-causal-h24-terrain-v3"
    const val ORIGIN = "meteofrance-h24-terrain-cosine-10m"

    fun ensure(sql: SQLiteDatabase) {
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE (
                reference_key TEXT NOT NULL,
                target_ts INTEGER NOT NULL,
                weather_temperature REAL NOT NULL,
                fab_temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                weather_confidence REAL NOT NULL,
                fab_confidence REAL NOT NULL,
                origin TEXT NOT NULL,
                model_version TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(reference_key, target_ts, model_version)
            )
            """.trimIndent()
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_curve10m_target ON $TABLE(reference_key, target_ts, model_version)"
        )
    }

    fun insertFrozen(
        sql: SQLiteDatabase,
        referenceKey: String,
        point: ForecastCurve10mPoint,
        createdAt: Long = System.currentTimeMillis()
    ) {
        ensure(sql)
        val values = ContentValues().apply {
            put("reference_key", referenceKey)
            put("target_ts", point.targetAt)
            put("weather_temperature", point.weatherTemperature)
            put("fab_temperature", point.fabTemperature)
            put("humidity", point.humidity.coerceIn(0.0, 100.0))
            put("weather_confidence", point.weatherConfidence.coerceIn(0.0, 1.0))
            put("fab_confidence", point.fabConfidence.coerceIn(0.0, 1.0))
            put("origin", point.origin)
            put("model_version", point.modelVersion)
            put("created_at", createdAt)
        }
        // Frozen by model version: an app update never rewrites an already backed-up backtest.
        sql.insertWithOnConflict(TABLE, null, values, SQLiteDatabase.CONFLICT_IGNORE)
    }

    fun persistAlignedPast(
        db: FabDataDb,
        referenceKey: String,
        weather: List<SamplePoint>,
        fab: List<SamplePoint>,
        now: Long,
        modelVersion: String = MODEL_VERSION
    ) {
        ensure(db.writableDatabase)
        val fabByTs = fab.associateBy { it.timestamp }
        db.inTransaction {
            weather.asSequence()
                .filter { it.timestamp <= now }
                .forEach { w ->
                    val f = fabByTs[w.timestamp] ?: return@forEach
                    insertFrozen(
                        db.writableDatabase,
                        referenceKey,
                        ForecastCurve10mPoint(
                            targetAt = w.timestamp,
                            weatherTemperature = w.temperature,
                            fabTemperature = f.temperature,
                            humidity = w.humidity,
                            weatherConfidence = w.confidence ?: 0.65,
                            fabConfidence = f.confidence ?: 0.45,
                            origin = ORIGIN,
                            modelVersion = modelVersion
                        )
                    )
                }
        }
    }

    fun query(
        db: FabDataDb,
        referenceKey: String,
        from: Long,
        to: Long,
        modelVersion: String = MODEL_VERSION
    ): List<ForecastCurve10mPoint> {
        ensure(db.writableDatabase)
        val out = mutableListOf<ForecastCurve10mPoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT target_ts, weather_temperature, fab_temperature, humidity,
                   weather_confidence, fab_confidence, origin, model_version
            FROM $TABLE
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND model_version=?
            ORDER BY target_ts
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString(), modelVersion)
        ).use { c ->
            while (c.moveToNext()) {
                out += ForecastCurve10mPoint(
                    targetAt = c.getLong(0),
                    weatherTemperature = c.getDouble(1),
                    fabTemperature = c.getDouble(2),
                    humidity = c.getDouble(3),
                    weatherConfidence = c.getDouble(4).coerceIn(0.0, 1.0),
                    fabConfidence = c.getDouble(5).coerceIn(0.0, 1.0),
                    origin = c.getString(6),
                    modelVersion = c.getString(7)
                )
            }
        }
        return out
    }

    fun restore(
        sql: SQLiteDatabase,
        referenceKey: String,
        targetAt: Long,
        weatherTemperature: Double,
        fabTemperature: Double,
        humidity: Double,
        weatherConfidence: Double,
        fabConfidence: Double,
        origin: String,
        modelVersion: String,
        createdAt: Long
    ) {
        ensure(sql)
        val values = ContentValues().apply {
            put("reference_key", referenceKey)
            put("target_ts", targetAt)
            put("weather_temperature", weatherTemperature)
            put("fab_temperature", fabTemperature)
            put("humidity", humidity.coerceIn(0.0, 100.0))
            put("weather_confidence", weatherConfidence.coerceIn(0.0, 1.0))
            put("fab_confidence", fabConfidence.coerceIn(0.0, 1.0))
            put("origin", origin.ifBlank { ORIGIN })
            put("model_version", modelVersion.ifBlank { MODEL_VERSION })
            put("created_at", createdAt)
        }
        // A backup is authoritative for the same model version.
        sql.insertWithOnConflict(TABLE, null, values, SQLiteDatabase.CONFLICT_REPLACE)
    }
}
