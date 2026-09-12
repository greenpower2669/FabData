package com.fabdata.app

import android.database.sqlite.SQLiteDatabase
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.roundToInt

/**
 * Immutable forecast memory by fixed lead.
 *
 * Météo applications naturally replace an older H+24 value with fresher H+23...H+1 values.
 * FabData keeps that live/gliding view, but also freezes one representative snapshot for every
 * fixed lead H+1..H+24 so the old forecast is never lost and can later be compared with terrain.
 *
 * This layer is additive only: it never writes to weather_reference_samples and it never changes
 * the H+24 cockpit/dials. ForecastMemoryStore remains the raw source of truth.
 */
const val FORECAST_ACTIVE_SENSOR_ID = -6902900110L
const val FORECAST_ACTIVE_STABLE_KEY = "forecast-weather-active"
private const val FORECAST_HORIZON_SENSOR_ID_BASE = -6902900200L
private const val FORECAST_FAB_HORIZON_SENSOR_ID_BASE = -6902900300L
val FORECAST_HORIZON_HOURS: IntRange = 1..24

fun forecastHorizonSensorId(leadHour: Int): Long {
    require(leadHour in FORECAST_HORIZON_HOURS)
    return FORECAST_HORIZON_SENSOR_ID_BASE - leadHour
}

fun forecastFabHorizonSensorId(leadHour: Int): Long {
    require(leadHour in FORECAST_HORIZON_HOURS)
    return FORECAST_FAB_HORIZON_SENSOR_ID_BASE - leadHour
}

fun forecastHorizonLeadForSensorId(sensorId: Long): Int? {
    val lead = (FORECAST_HORIZON_SENSOR_ID_BASE - sensorId).toInt()
    return lead.takeIf { it in FORECAST_HORIZON_HOURS && forecastHorizonSensorId(it) == sensorId }
}

fun isForecastArchiveSensorId(sensorId: Long): Boolean =
    sensorId == FORECAST_ACTIVE_SENSOR_ID || forecastHorizonLeadForSensorId(sensorId) != null

private const val HORIZON_HOUR_MS = 60L * 60L * 1000L
private const val HORIZON_MINUTE_MS = 60L * 1000L
private const val HORIZON_STEP_10M_MS = 10L * HORIZON_MINUTE_MS
private const val HORIZON_MATCH_TOLERANCE_MIN = 35

private fun horizonHourBucket(timestamp: Long): Long =
    (timestamp / HORIZON_HOUR_MS) * HORIZON_HOUR_MS

data class ForecastHorizonCurveSet(
    val activeWeather: List<SamplePoint>,
    val weatherByLead: Map<Int, List<SamplePoint>>,
    val fabByLead: Map<Int, List<SamplePoint>>
) {
    companion object {
        val EMPTY = ForecastHorizonCurveSet(emptyList(), emptyMap(), emptyMap())
    }
}

object ForecastHorizonArchiveStore {
    const val TABLE = "forecast_horizon_archive"
    const val POLICY_VERSION = "fixed-lead-hour-v1"

    fun ensure(sql: SQLiteDatabase) {
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE (
                reference_key TEXT NOT NULL,
                lead_hour INTEGER NOT NULL,
                target_ts INTEGER NOT NULL,
                issued_at INTEGER NOT NULL,
                lead_error_minutes INTEGER NOT NULL,
                weather_temperature REAL NOT NULL,
                fab_temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                weather_confidence REAL NOT NULL,
                fab_confidence REAL NOT NULL,
                provider TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(reference_key, lead_hour, target_ts, policy_version)
            )
            """.trimIndent()
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_horizon_target ON $TABLE(reference_key, target_ts, lead_hour, policy_version)"
        )
    }

    fun restore(
        sql: SQLiteDatabase,
        referenceKey: String,
        leadHour: Int,
        targetAt: Long,
        issuedAt: Long,
        leadErrorMinutes: Int,
        weatherTemperature: Double,
        fabTemperature: Double,
        humidity: Double,
        weatherConfidence: Double,
        fabConfidence: Double,
        provider: String,
        policyVersion: String = POLICY_VERSION,
        createdAt: Long
    ) {
        if (leadHour !in FORECAST_HORIZON_HOURS) return
        ensure(sql)
        sql.execSQL(
            """
            INSERT OR REPLACE INTO $TABLE(
                reference_key, lead_hour, target_ts, issued_at, lead_error_minutes,
                weather_temperature, fab_temperature, humidity, weather_confidence,
                fab_confidence, provider, policy_version, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """.trimIndent(),
            arrayOf(
                referenceKey, leadHour, targetAt, issuedAt, leadErrorMinutes,
                weatherTemperature, fabTemperature, humidity.coerceIn(0.0, 100.0),
                weatherConfidence.coerceIn(0.0, 1.0), fabConfidence.coerceIn(0.0, 1.0),
                provider.ifBlank { "active_reference" }, policyVersion.ifBlank { POLICY_VERSION }, createdAt
            )
        )
    }
}

private data class RawHorizonForecast(
    val issuedAt: Long,
    val targetAt: Long,
    val temperature: Double,
    val humidity: Double,
    val confidence: Double,
    val provider: String
)

class ForecastHorizonArchive(private val db: FabDataDb) {
    fun materialize(
        referenceKey: String,
        from: Long,
        to: Long,
        now: Long = System.currentTimeMillis()
    ) {
        if (to <= from) return
        ForecastMemoryStore.ensure(db.writableDatabase)
        ForecastLocalSnapshotStore.ensure(db.writableDatabase)
        ForecastHorizonArchiveStore.ensure(db.writableDatabase)

        // Ensure a Fab-local value exists for every raw snapshot before we freeze its horizon.
        ForecastSelectableCurveStore(db).materializeLocalSnapshots(
            referenceKey = referenceKey,
            from = from - 25L * HORIZON_HOUR_MS,
            to = to,
            now = now
        )

        val localByKey = mutableMapOf<Pair<Long, Long>, Pair<Double, Double?>>()
        db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, fab_temperature, confidence
            FROM ${ForecastLocalSnapshotStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ?
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                localByKey[c.getLong(0) to c.getLong(1)] =
                    c.getDouble(2) to if (c.isNull(3)) null else c.getDouble(3)
            }
        }

        val rows = rawRows(referenceKey, from, to, now)
        db.inTransaction {
            rows.forEach { row ->
                val leadMs = row.targetAt - row.issuedAt
                if (leadMs <= 5L * HORIZON_MINUTE_MS) return@forEach
                val leadHour = (leadMs.toDouble() / HORIZON_HOUR_MS.toDouble()).roundToInt()
                if (leadHour !in FORECAST_HORIZON_HOURS) return@forEach
                val errorMinutes = (abs(leadMs - leadHour * HORIZON_HOUR_MS) / HORIZON_MINUTE_MS).toInt()
                if (errorMinutes > HORIZON_MATCH_TOLERANCE_MIN) return@forEach

                val current = db.readableDatabase.rawQuery(
                    """
                    SELECT issued_at, lead_error_minutes
                    FROM ${ForecastHorizonArchiveStore.TABLE}
                    WHERE reference_key=? AND lead_hour=? AND target_ts=? AND policy_version=?
                    LIMIT 1
                    """.trimIndent(),
                    arrayOf(
                        referenceKey, leadHour.toString(), row.targetAt.toString(),
                        ForecastHorizonArchiveStore.POLICY_VERSION
                    )
                ).use { c ->
                    if (c.moveToFirst()) c.getLong(0) to c.getInt(1) else null
                }
                if (current != null) {
                    val (oldIssuedAt, oldErrorMinutes) = current
                    if (oldErrorMinutes < errorMinutes ||
                        (oldErrorMinutes == errorMinutes && oldIssuedAt >= row.issuedAt)
                    ) return@forEach
                }

                val local = localByKey[row.issuedAt to row.targetAt]
                ForecastHorizonArchiveStore.restore(
                    sql = db.writableDatabase,
                    referenceKey = referenceKey,
                    leadHour = leadHour,
                    targetAt = row.targetAt,
                    issuedAt = row.issuedAt,
                    leadErrorMinutes = errorMinutes,
                    weatherTemperature = row.temperature,
                    fabTemperature = local?.first ?: row.temperature,
                    humidity = row.humidity,
                    weatherConfidence = row.confidence,
                    fabConfidence = local?.second ?: (row.confidence * 0.45),
                    provider = row.provider,
                    createdAt = System.currentTimeMillis()
                )
            }
        }
    }

    fun query(
        referenceKey: String,
        from: Long,
        to: Long,
        now: Long = System.currentTimeMillis()
    ): ForecastHorizonCurveSet {
        if (to <= from) return ForecastHorizonCurveSet.EMPTY
        materialize(referenceKey, from, to, now)

        val weather = mutableMapOf<Int, MutableList<SamplePoint>>()
        val fab = mutableMapOf<Int, MutableList<SamplePoint>>()
        db.readableDatabase.rawQuery(
            """
            SELECT lead_hour, target_ts, weather_temperature, fab_temperature, humidity,
                   weather_confidence, fab_confidence
            FROM ${ForecastHorizonArchiveStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND policy_version=?
            ORDER BY lead_hour, target_ts
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString(), ForecastHorizonArchiveStore.POLICY_VERSION)
        ).use { c ->
            while (c.moveToNext()) {
                val lead = c.getInt(0)
                weather.getOrPut(lead) { mutableListOf() } += SamplePoint(
                    sensorId = forecastHorizonSensorId(lead),
                    timestamp = c.getLong(1),
                    temperature = c.getDouble(2),
                    humidity = c.getDouble(4),
                    source = PointSource.FORECAST,
                    confidence = c.getDouble(5).coerceIn(0.0, 1.0)
                )
                fab.getOrPut(lead) { mutableListOf() } += SamplePoint(
                    sensorId = forecastFabHorizonSensorId(lead),
                    timestamp = c.getLong(1),
                    temperature = c.getDouble(3),
                    humidity = c.getDouble(4),
                    source = PointSource.FORECAST,
                    confidence = c.getDouble(6).coerceIn(0.0, 1.0)
                )
            }
        }

        return ForecastHorizonCurveSet(
            activeWeather = interpolate10Minutes(activeRows(referenceKey, from, to, now).map { row ->
                SamplePoint(
                    sensorId = FORECAST_ACTIVE_SENSOR_ID,
                    timestamp = row.targetAt,
                    temperature = row.temperature,
                    humidity = row.humidity,
                    source = PointSource.FORECAST,
                    confidence = row.confidence
                )
            }),
            weatherByLead = weather.mapValues { (_, points) -> interpolate10Minutes(points) },
            fabByLead = fab.mapValues { (_, points) -> interpolate10Minutes(points) }
        )
    }

    private fun rawRows(referenceKey: String, from: Long, to: Long, now: Long): List<RawHorizonForecast> {
        val out = mutableListOf<RawHorizonForecast>()
        db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, temperature, humidity, confidence, provider
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND issued_at<=?
            ORDER BY target_ts, issued_at
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString(), now.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += RawHorizonForecast(
                    issuedAt = c.getLong(0),
                    targetAt = c.getLong(1),
                    temperature = c.getDouble(2),
                    humidity = if (c.isNull(3)) 50.0 else c.getDouble(3),
                    confidence = if (c.isNull(4)) 0.65 else c.getDouble(4).coerceIn(0.0, 1.0),
                    provider = if (c.isNull(5)) "active_reference" else c.getString(5)
                )
            }
        }
        return out
    }

    /**
     * Météo-France-like gliding curve: for each target, use the freshest forecast that existed
     * before that target. In the future this is the current latest forecast; once the target is
     * past the last pre-target snapshot naturally becomes immutable.
     */
    private fun activeRows(referenceKey: String, from: Long, to: Long, now: Long): List<RawHorizonForecast> {
        val best = linkedMapOf<Long, RawHorizonForecast>()
        rawRows(referenceKey, from, to, now).forEach { row ->
            if (row.issuedAt >= row.targetAt - 5L * HORIZON_MINUTE_MS) return@forEach
            val bucket = horizonHourBucket(row.targetAt)
            val previous = best[bucket]
            if (previous == null || row.issuedAt > previous.issuedAt) best[bucket] = row
        }
        return best.values.sortedBy { it.targetAt }
    }

    private fun interpolate10Minutes(points: List<SamplePoint>): List<SamplePoint> {
        val sorted = points.distinctBy { it.timestamp }.sortedBy { it.timestamp }
        if (sorted.size < 2) return sorted
        val out = mutableListOf<SamplePoint>()
        sorted.zipWithNext().forEach { (left, right) ->
            out += left
            val gap = right.timestamp - left.timestamp
            if (gap in 20L * HORIZON_MINUTE_MS..95L * HORIZON_MINUTE_MS) {
                var ts = ((left.timestamp / HORIZON_STEP_10M_MS) + 1L) * HORIZON_STEP_10M_MS
                while (ts < right.timestamp) {
                    val linear = ((ts - left.timestamp).toDouble() / gap.toDouble()).coerceIn(0.0, 1.0)
                    val smooth = 0.5 - 0.5 * cos(PI * linear)
                    val confidence = (left.confidence ?: 0.6) +
                        ((right.confidence ?: 0.6) - (left.confidence ?: 0.6)) * linear
                    out += SamplePoint(
                        sensorId = left.sensorId,
                        timestamp = ts,
                        temperature = left.temperature + (right.temperature - left.temperature) * smooth,
                        humidity = left.humidity + (right.humidity - left.humidity) * smooth,
                        source = PointSource.FORECAST,
                        confidence = confidence.coerceIn(0.0, 1.0)
                    )
                    ts += HORIZON_STEP_10M_MS
                }
            }
        }
        out += sorted.last()
        return out
    }
}
