package com.fabdata.app

import android.database.sqlite.SQLiteDatabase
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.min

const val FORECAST_RECONSTRUCTED_SENSOR_ID = -6902900104L
const val FORECAST_RECONSTRUCTED_STABLE_KEY = "forecast-reconstructed"
const val FORECAST_FAB_SENSOR_ID = -6902900105L
const val FORECAST_FAB_STABLE_KEY = "forecast-fab-local"

private const val CURVE_HOUR_MS = 60L * 60L * 1000L

/**
 * Two selectable, prediction-only chart series.
 *
 * reconstructed = what the external forecast really predicted (archived past + current future).
 * fab = the immutable local Fab correction captured for the same forecast snapshot.
 *
 * Neither series uses MEASURED nor RECONSTRUCTED weather to fill visual gaps. Missing short
 * gaps are interpolated only between two prediction anchors and those estimated points stay
 * in memory; they are never persisted or exported.
 */
data class ForecastSelectableCurves(
    val reconstructed: List<SamplePoint>,
    val fab: List<SamplePoint>
) {
    companion object {
        val EMPTY = ForecastSelectableCurves(emptyList(), emptyList())
    }
}

object ForecastLocalSnapshotStore {
    const val TABLE = "forecast_local_snapshot_archive"

    fun ensure(sql: SQLiteDatabase) {
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE (
                reference_key TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                target_ts INTEGER NOT NULL,
                baseline_temperature REAL NOT NULL,
                fab_temperature REAL NOT NULL,
                confidence REAL,
                model_samples INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(reference_key, issued_at, target_ts)
            )
            """.trimIndent()
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_local_target ON $TABLE(reference_key, target_ts, issued_at)"
        )
    }

    fun restore(
        sql: SQLiteDatabase,
        referenceKey: String,
        issuedAt: Long,
        targetAt: Long,
        baselineTemperature: Double,
        fabTemperature: Double,
        confidence: Double?,
        modelSamples: Int,
        createdAt: Long
    ) {
        ensure(sql)
        sql.execSQL(
            """
            INSERT OR IGNORE INTO $TABLE(
                reference_key, issued_at, target_ts, baseline_temperature, fab_temperature,
                confidence, model_samples, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """.trimIndent(),
            arrayOf(
                referenceKey, issuedAt, targetAt, baselineTemperature, fabTemperature,
                confidence, modelSamples, createdAt
            )
        )
    }
}

private data class SelectableForecastRow(
    val issuedAt: Long,
    val targetAt: Long,
    val temperature: Double,
    val humidity: Double,
    val confidence: Double
)

private data class SelectableResidualPoint(
    val targetAt: Long,
    val residual: Double
)

private data class SelectableResidualModel(
    val biasNow: Double = 0.0,
    val slopePerHour: Double = 0.0,
    val accelerationPerHour2: Double = 0.0,
    val samples: Int = 0
) {
    fun residualAt(targetAt: Long, asOf: Long): Double {
        val horizon = (targetAt - asOf).toDouble() / CURVE_HOUR_MS.toDouble()
        return (biasNow + slopePerHour * horizon + 0.5 * accelerationPerHour2 * horizon * horizon)
            .coerceIn(-5.0, 5.0)
    }
}

class ForecastSelectableCurveStore(private val db: FabDataDb) {
    fun materializeLocalSnapshots(
        referenceKey: String,
        from: Long,
        to: Long,
        now: Long = System.currentTimeMillis()
    ) {
        val writable = db.writableDatabase
        ForecastMemoryStore.ensure(writable)
        ForecastLocalSnapshotStore.ensure(writable)
        val rows = loadArchive(referenceKey, from, to)
            .filter { it.issuedAt <= now && it.issuedAt < it.targetAt - 5L * 60L * 1000L }
        rows.forEach { ensureLocalSnapshot(referenceKey, it) }
    }

    fun query(
        referenceKey: String,
        from: Long,
        to: Long,
        now: Long = System.currentTimeMillis()
    ): ForecastSelectableCurves {
        if (to <= from) return ForecastSelectableCurves.EMPTY
        val writable = db.writableDatabase
        ForecastMemoryStore.ensure(writable)
        ForecastLocalSnapshotStore.ensure(writable)

        val archive = loadArchive(referenceKey, from, to)
            .filter { it.issuedAt <= now && it.issuedAt < it.targetAt - 5L * 60L * 1000L }
        val anchors = selectReplayAnchors(archive, now)
        anchors.forEach { ensureLocalSnapshot(referenceKey, it) }

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

        val reconstructedAnchors = anchors.map {
            SamplePoint(
                sensorId = FORECAST_RECONSTRUCTED_SENSOR_ID,
                timestamp = it.targetAt,
                temperature = it.temperature,
                humidity = it.humidity,
                source = PointSource.FORECAST,
                confidence = it.confidence
            )
        }
        val fabAnchors = anchors.mapNotNull { row ->
            localByKey[row.issuedAt to row.targetAt]?.let { (temperature, confidence) ->
                SamplePoint(
                    sensorId = FORECAST_FAB_SENSOR_ID,
                    timestamp = row.targetAt,
                    temperature = temperature,
                    humidity = row.humidity,
                    source = PointSource.FORECAST,
                    confidence = confidence ?: row.confidence
                )
            }
        }

        return ForecastSelectableCurves(
            reconstructed = interpolatePredictionOnly(reconstructedAnchors),
            fab = interpolatePredictionOnly(fabAnchors)
        )
    }

    private fun loadArchive(referenceKey: String, from: Long, to: Long): List<SelectableForecastRow> {
        val out = mutableListOf<SelectableForecastRow>()
        db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, temperature, humidity, confidence
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ?
            ORDER BY target_ts, issued_at
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += SelectableForecastRow(
                    issuedAt = c.getLong(0),
                    targetAt = c.getLong(1),
                    temperature = c.getDouble(2),
                    humidity = if (c.isNull(3)) 50.0 else c.getDouble(3),
                    confidence = if (c.isNull(4)) 0.65 else c.getDouble(4).coerceIn(0.0, 1.0)
                )
            }
        }
        return out
    }

    private fun selectReplayAnchors(rows: List<SelectableForecastRow>, now: Long): List<SelectableForecastRow> {
        val past = rows.filter { it.targetAt <= now }
            .groupBy { hourBucket(it.targetAt) }
            .values
            .mapNotNull { group ->
                group.minByOrNull { abs((it.targetAt - it.issuedAt) - CURVE_HOUR_MS) }
            }
        val future = rows.filter { it.targetAt > now && it.issuedAt <= now }
            .groupBy { hourBucket(it.targetAt) }
            .values
            .mapNotNull { group -> group.maxByOrNull { it.issuedAt } }
        return (past + future)
            .associateBy { hourBucket(it.targetAt) }
            .values
            .sortedBy { it.targetAt }
    }

    private fun ensureLocalSnapshot(referenceKey: String, row: SelectableForecastRow) {
        val exists = db.readableDatabase.rawQuery(
            """
            SELECT 1 FROM ${ForecastLocalSnapshotStore.TABLE}
            WHERE reference_key=? AND issued_at=? AND target_ts=? LIMIT 1
            """.trimIndent(),
            arrayOf(referenceKey, row.issuedAt.toString(), row.targetAt.toString())
        ).use { it.moveToFirst() }
        if (exists) return

        val model = residualModel(referenceKey, row.issuedAt)
        val corrected = (row.temperature + model.residualAt(row.targetAt, row.issuedAt)).coerceIn(-70.0, 70.0)
        val confidenceFactor = (0.45 + min(model.samples, 12) / 12.0 * 0.55).coerceIn(0.45, 1.0)
        ForecastLocalSnapshotStore.restore(
            sql = db.writableDatabase,
            referenceKey = referenceKey,
            issuedAt = row.issuedAt,
            targetAt = row.targetAt,
            baselineTemperature = row.temperature,
            fabTemperature = corrected,
            confidence = (row.confidence * confidenceFactor).coerceIn(0.0, 1.0),
            modelSamples = model.samples,
            createdAt = System.currentTimeMillis()
        )
    }

    private fun residualModel(referenceKey: String, asOf: Long): SelectableResidualModel {
        val from = asOf - 24L * CURVE_HOUR_MS
        val candidates = loadArchive(referenceKey, from, asOf)
            .filter {
                it.issuedAt < it.targetAt - 5L * 60L * 1000L &&
                    it.targetAt - it.issuedAt in 20L * 60L * 1000L..3L * CURVE_HOUR_MS
            }
        if (candidates.isEmpty()) return SelectableResidualModel()

        val selected = candidates.groupBy { hourBucket(it.targetAt) }
            .values
            .mapNotNull { group -> group.minByOrNull { abs((it.targetAt - it.issuedAt) - CURVE_HOUR_MS) } }
            .sortedBy { it.targetAt }
        val residuals = selected.mapNotNull { forecast ->
            measuredAt(referenceKey, forecast.targetAt)
                ?.let { actual -> SelectableResidualPoint(forecast.targetAt, actual - forecast.temperature) }
        }
        if (residuals.isEmpty()) return SelectableResidualModel()
        if (residuals.size == 1) {
            return SelectableResidualModel(
                biasNow = residuals.first().residual.coerceIn(-4.0, 4.0),
                samples = 1
            )
        }

        var sw = 0.0
        var sx = 0.0
        var sy = 0.0
        var sxx = 0.0
        var sxy = 0.0
        residuals.forEach { p ->
            val x = (p.targetAt - asOf).toDouble() / CURVE_HOUR_MS.toDouble()
            val w = exp(x / 6.0).coerceAtLeast(0.01)
            sw += w
            sx += w * x
            sy += w * p.residual
            sxx += w * x * x
            sxy += w * x * p.residual
        }
        val denom = sw * sxx - sx * sx
        val slope = if (abs(denom) > 1e-9) {
            ((sw * sxy - sx * sy) / denom).coerceIn(-1.2, 1.2)
        } else 0.0
        val bias = if (sw > 0.0) ((sy - slope * sx) / sw).coerceIn(-4.0, 4.0) else 0.0

        val accelerations = residuals.zipWithNext().zipWithNext().mapNotNull { (leftPair, rightPair) ->
            val (a, b) = leftPair
            val (_, c) = rightPair
            val dt1 = (b.targetAt - a.targetAt).toDouble() / CURVE_HOUR_MS.toDouble()
            val dt2 = (c.targetAt - b.targetAt).toDouble() / CURVE_HOUR_MS.toDouble()
            if (dt1 !in 0.5..2.0 || dt2 !in 0.5..2.0) return@mapNotNull null
            val s1 = (b.residual - a.residual) / dt1
            val s2 = (c.residual - b.residual) / dt2
            (((s2 - s1) / ((dt1 + dt2) / 2.0)).coerceIn(-1.5, 1.5)) to c.targetAt
        }
        var acceleration = 0.0
        if (accelerations.isNotEmpty()) {
            var aw = 0.0
            var av = 0.0
            accelerations.forEach { (value, ts) ->
                val x = (ts - asOf).toDouble() / CURVE_HOUR_MS.toDouble()
                val w = exp(x / 4.0).coerceAtLeast(0.01)
                aw += w
                av += w * value
            }
            if (aw > 0.0) acceleration = (av / aw).coerceIn(-0.8, 0.8)
        }
        return SelectableResidualModel(bias, slope, acceleration, residuals.size)
    }

    private fun measuredAt(referenceKey: String, target: Long): Double? {
        val tolerance = 36L * 60L * 1000L
        return db.readableDatabase.rawQuery(
            """
            SELECT temperature
            FROM weather_reference_samples
            WHERE reference_key=? AND source='measured' AND timestamp BETWEEN ? AND ?
            ORDER BY ABS(timestamp-?) ASC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey,
                (target - tolerance).toString(),
                (target + tolerance).toString(),
                target.toString()
            )
        ).use { c -> if (c.moveToFirst()) c.getDouble(0) else null }
    }

    private fun interpolatePredictionOnly(points: List<SamplePoint>): List<SamplePoint> {
        if (points.size < 2) return points.sortedBy { it.timestamp }
        val sorted = points.sortedBy { it.timestamp }
        val out = mutableListOf<SamplePoint>()
        sorted.zipWithNext().forEach { (left, right) ->
            out += left
            val gap = right.timestamp - left.timestamp
            if (gap > CURVE_HOUR_MS + 10L * 60L * 1000L && gap <= 6L * CURVE_HOUR_MS) {
                var ts = hourBucket(left.timestamp) + CURVE_HOUR_MS
                while (ts < right.timestamp) {
                    val fraction = ((ts - left.timestamp).toDouble() / gap.toDouble()).coerceIn(0.0, 1.0)
                    val confidence = min(left.confidence ?: 0.6, right.confidence ?: 0.6) * 0.72
                    out += SamplePoint(
                        sensorId = left.sensorId,
                        timestamp = ts,
                        temperature = left.temperature + (right.temperature - left.temperature) * fraction,
                        humidity = left.humidity + (right.humidity - left.humidity) * fraction,
                        source = PointSource.FORECAST,
                        confidence = confidence.coerceIn(0.0, 1.0)
                    )
                    ts += CURVE_HOUR_MS
                }
            }
        }
        out += sorted.last()
        return out
    }
}
