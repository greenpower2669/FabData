package com.fabdata.app

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Causal Fab adaptive forecast at four fixed horizons.
 *
 * The weather forecast remains the baseline. Fab learns the baseline residual for the same
 * horizon, learns the usual error of a present-time tangent projection, and changes the blend
 * when the current slope/acceleration indicates a regime shift. Historical adaptive outputs are
 * never retro-invented: only predictions that really exist while their target is still future are
 * frozen in [ForecastAdaptiveStore].
 */
val FORECAST_ADAPTIVE_HORIZONS: List<Int> = listOf(3, 6, 12, 24)
private const val FORECAST_ADAPTIVE_SENSOR_ID_BASE = -6902900400L
private const val ADAPTIVE_HOUR_MS = 60L * 60L * 1000L
private const val ADAPTIVE_DAY_MS = 24L * ADAPTIVE_HOUR_MS
private const val ADAPTIVE_STEP_MS = 10L * 60L * 1000L

fun forecastAdaptiveSensorId(horizonHour: Int): Long {
    require(horizonHour in FORECAST_ADAPTIVE_HORIZONS)
    return FORECAST_ADAPTIVE_SENSOR_ID_BASE - horizonHour
}

fun forecastAdaptiveStableKey(horizonHour: Int): String = "forecast-fab-adaptive-h$horizonHour"

fun forecastAdaptiveLeadForSensorId(sensorId: Long): Int? {
    val lead = (FORECAST_ADAPTIVE_SENSOR_ID_BASE - sensorId).toInt()
    return lead.takeIf { it in FORECAST_ADAPTIVE_HORIZONS && forecastAdaptiveSensorId(it) == sensorId }
}

fun isAdaptiveForecastSensorId(sensorId: Long): Boolean = forecastAdaptiveLeadForSensorId(sensorId) != null

data class ForecastAdaptiveCurrent(
    val horizonHour: Int,
    val issuedAt: Long,
    val targetAt: Long,
    val baselineTemperature: Double,
    val adaptiveTemperature: Double,
    val tangentTemperature: Double,
    val regimeScore: Double,
    val historySamples: Int,
    val confidence: Double
)

data class ForecastAdaptiveEvaluation(
    val horizonHour: Int,
    val samples: Int,
    val baselineMae: Double?,
    val adaptiveMae: Double?
) {
    val gainC: Double? get() = if (baselineMae != null && adaptiveMae != null) baselineMae - adaptiveMae else null
}

data class ForecastAdaptiveSummary(
    val current: List<ForecastAdaptiveCurrent>,
    val evaluations: List<ForecastAdaptiveEvaluation>
)

data class ForecastAdaptiveCurveSet(
    val byLead: Map<Int, List<SamplePoint>>
) {
    companion object { val EMPTY = ForecastAdaptiveCurveSet(emptyMap()) }
}

private data class AdaptiveSourceRow(
    val horizonHour: Int,
    val issuedAt: Long,
    val targetAt: Long,
    val baselineTemperature: Double,
    val humidity: Double,
    val confidence: Double,
    val provider: String
)

private data class AdaptiveTerrainPoint(
    val timestamp: Long,
    val temperature: Double,
    val measured: Boolean
)

private data class AdaptiveKinematics(
    val temperature: Double,
    val slopePerHour: Double,
    val accelerationPerHour2: Double
)

private data class AdaptiveTrainingRow(
    val issuedAt: Long,
    val targetAt: Long,
    val baselineTemperature: Double
)

private data class AdaptiveTrainingSample(
    val residual: Double,
    val tangentError: Double?,
    val issueKinematics: AdaptiveKinematics,
    val ageDays: Double
)

object ForecastAdaptiveStore {
    const val TABLE = "forecast_adaptive_archive"
    const val MODEL_VERSION = "fab-adaptive-regime-tangent-v1"

    fun ensure(sql: SQLiteDatabase) {
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE (
                reference_key TEXT NOT NULL,
                horizon_hour INTEGER NOT NULL,
                issued_at INTEGER NOT NULL,
                target_ts INTEGER NOT NULL,
                baseline_temperature REAL NOT NULL,
                adaptive_temperature REAL NOT NULL,
                tangent_temperature REAL NOT NULL,
                history_bias REAL NOT NULL,
                tangent_bias REAL NOT NULL,
                regime_score REAL NOT NULL,
                history_samples INTEGER NOT NULL,
                humidity REAL NOT NULL,
                confidence REAL NOT NULL,
                provider TEXT NOT NULL,
                model_version TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(reference_key, horizon_hour, issued_at, target_ts, model_version)
            )
            """.trimIndent()
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_adaptive_target ON $TABLE(reference_key, horizon_hour, target_ts, issued_at)"
        )
    }

    fun restore(
        sql: SQLiteDatabase,
        referenceKey: String,
        horizonHour: Int,
        issuedAt: Long,
        targetAt: Long,
        baselineTemperature: Double,
        adaptiveTemperature: Double,
        tangentTemperature: Double,
        historyBias: Double,
        tangentBias: Double,
        regimeScore: Double,
        historySamples: Int,
        humidity: Double,
        confidence: Double,
        provider: String,
        modelVersion: String = MODEL_VERSION,
        createdAt: Long
    ) {
        if (referenceKey.isBlank() || horizonHour !in FORECAST_ADAPTIVE_HORIZONS) return
        if (!baselineTemperature.isFinite() || !adaptiveTemperature.isFinite() || !tangentTemperature.isFinite()) return
        ensure(sql)
        val values = ContentValues().apply {
            put("reference_key", referenceKey)
            put("horizon_hour", horizonHour)
            put("issued_at", issuedAt)
            put("target_ts", targetAt)
            put("baseline_temperature", baselineTemperature)
            put("adaptive_temperature", adaptiveTemperature)
            put("tangent_temperature", tangentTemperature)
            put("history_bias", historyBias)
            put("tangent_bias", tangentBias)
            put("regime_score", regimeScore.coerceIn(0.0, 1.0))
            put("history_samples", historySamples.coerceAtLeast(0))
            put("humidity", humidity.coerceIn(0.0, 100.0))
            put("confidence", confidence.coerceIn(0.0, 1.0))
            put("provider", provider.ifBlank { "active_reference" })
            put("model_version", modelVersion.ifBlank { MODEL_VERSION })
            put("created_at", createdAt)
        }
        sql.insertWithOnConflict(TABLE, null, values, SQLiteDatabase.CONFLICT_IGNORE)
    }
}

class ForecastAdaptiveEngine(private val db: FabDataDb) {
    fun refresh(referenceKey: String, now: Long = System.currentTimeMillis()): Int {
        if (referenceKey.isBlank()) return 0
        ForecastMemoryStore.ensure(db.writableDatabase)
        ForecastHorizonArchiveStore.ensure(db.writableDatabase)
        ForecastAdaptiveStore.ensure(db.writableDatabase)

        // Re-materialise a bounded source window only. This remains an informational side layer.
        runCatching {
            ForecastHorizonArchive(db).materialize(
                referenceKey,
                now - 120L * ADAPTIVE_DAY_MS,
                now + 26L * ADAPTIVE_HOUR_MS,
                now
            )
        }

        val terrain = loadTerrain(
            referenceKey,
            now - 125L * ADAPTIVE_DAY_MS,
            now
        )
        var inserted = 0
        FORECAST_ADAPTIVE_HORIZONS.forEach { horizon ->
            val source = currentSource(referenceKey, horizon, now) ?: return@forEach
            if (source.targetAt <= source.issuedAt || source.targetAt <= now) return@forEach
            if (now - source.issuedAt > 3L * ADAPTIVE_HOUR_MS) return@forEach
            if (exists(referenceKey, source)) return@forEach

            val prediction = buildPrediction(referenceKey, source, terrain)
            ForecastAdaptiveStore.restore(
                sql = db.writableDatabase,
                referenceKey = referenceKey,
                horizonHour = horizon,
                issuedAt = source.issuedAt,
                targetAt = source.targetAt,
                baselineTemperature = source.baselineTemperature,
                adaptiveTemperature = prediction.adaptive,
                tangentTemperature = prediction.tangent,
                historyBias = prediction.historyBias,
                tangentBias = prediction.tangentBias,
                regimeScore = prediction.regimeScore,
                historySamples = prediction.samples,
                humidity = source.humidity,
                confidence = prediction.confidence,
                provider = source.provider,
                createdAt = now
            )
            inserted++
        }
        return inserted
    }

    fun queryCurves(
        referenceKey: String,
        from: Long,
        to: Long,
        now: Long = System.currentTimeMillis()
    ): ForecastAdaptiveCurveSet {
        if (to <= from) return ForecastAdaptiveCurveSet.EMPTY
        refresh(referenceKey, now)
        ForecastAdaptiveStore.ensure(db.writableDatabase)
        val grouped = mutableMapOf<Int, MutableMap<Long, Pair<Long, SamplePoint>>>()
        db.readableDatabase.rawQuery(
            """
            SELECT horizon_hour, issued_at, target_ts, adaptive_temperature, humidity, confidence
            FROM ${ForecastAdaptiveStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND model_version=?
            ORDER BY horizon_hour, target_ts, issued_at
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString(), ForecastAdaptiveStore.MODEL_VERSION)
        ).use { c ->
            while (c.moveToNext()) {
                val horizon = c.getInt(0)
                val issuedAt = c.getLong(1)
                val targetAt = c.getLong(2)
                val point = SamplePoint(
                    sensorId = forecastAdaptiveSensorId(horizon),
                    timestamp = targetAt,
                    temperature = c.getDouble(3),
                    humidity = c.getDouble(4),
                    source = PointSource.FORECAST,
                    confidence = c.getDouble(5).coerceIn(0.0, 1.0)
                )
                val targetMap = grouped.getOrPut(horizon) { linkedMapOf() }
                val previous = targetMap[targetAt]
                if (previous == null || issuedAt > previous.first) targetMap[targetAt] = issuedAt to point
            }
        }
        return ForecastAdaptiveCurveSet(
            grouped.mapValues { (_, targetMap) ->
                interpolate10Minutes(targetMap.values.map { it.second }.sortedBy { it.timestamp })
            }
        )
    }

    fun summary(referenceKey: String, now: Long = System.currentTimeMillis()): ForecastAdaptiveSummary {
        refresh(referenceKey, now)
        return ForecastAdaptiveSummary(
            current = FORECAST_ADAPTIVE_HORIZONS.mapNotNull { latestCurrent(referenceKey, it, now) },
            evaluations = FORECAST_ADAPTIVE_HORIZONS.map { evaluate(referenceKey, it, now) }
        )
    }

    private data class BuiltPrediction(
        val adaptive: Double,
        val tangent: Double,
        val historyBias: Double,
        val tangentBias: Double,
        val regimeScore: Double,
        val samples: Int,
        val confidence: Double
    )

    private fun buildPrediction(
        referenceKey: String,
        source: AdaptiveSourceRow,
        terrain: List<AdaptiveTerrainPoint>
    ): BuiltPrediction {
        val horizon = source.horizonHour
        val issueKinematics = kinematicsAt(source.issuedAt, terrain)
        val tangent = issueKinematics?.let { projectTangent(it, horizon.toDouble()) }
            ?: source.baselineTemperature

        val slopeScore = issueKinematics?.let { (abs(it.slopePerHour) / 1.15).coerceIn(0.0, 1.0) } ?: 0.0
        val accelerationScore = issueKinematics?.let { (abs(it.accelerationPerHour2) / 0.45).coerceIn(0.0, 1.0) } ?: 0.0
        val disagreementScale = 4.0 + horizon * 0.20
        val disagreementScore = (abs(tangent - source.baselineTemperature) / disagreementScale).coerceIn(0.0, 1.0)
        val regimeScore = (0.50 * slopeScore + 0.35 * accelerationScore + 0.15 * disagreementScore)
            .coerceIn(0.0, 1.0)

        val trainingRows = loadTrainingRows(referenceKey, horizon, source.issuedAt)
        val samples = trainingRows.mapNotNull { row ->
            val actual = actualAt(row.targetAt, terrain) ?: return@mapNotNull null
            val issue = kinematicsAt(row.issuedAt, terrain) ?: return@mapNotNull null
            val histHours = ((row.targetAt - row.issuedAt).toDouble() / ADAPTIVE_HOUR_MS.toDouble())
                .coerceIn(0.5, 30.0)
            val histTangent = projectTangent(issue, histHours)
            AdaptiveTrainingSample(
                residual = actual.temperature - row.baselineTemperature,
                tangentError = actual.temperature - histTangent,
                issueKinematics = issue,
                ageDays = ((source.issuedAt - row.targetAt).coerceAtLeast(0L)).toDouble() / ADAPTIVE_DAY_MS.toDouble()
            )
        }

        var sumW = 0.0
        var residualW = 0.0
        var tangentW = 0.0
        val tauDays = max(5.0, 50.0 * (1.0 - 0.82 * regimeScore))
        samples.forEach { sample ->
            val similarity = if (issueKinematics == null) 1.0 else {
                exp(
                    -abs(sample.issueKinematics.slopePerHour - issueKinematics.slopePerHour) / 0.60 -
                        abs(sample.issueKinematics.accelerationPerHour2 - issueKinematics.accelerationPerHour2) / 0.32 -
                        abs(sample.issueKinematics.temperature - issueKinematics.temperature) / 7.0
                )
            }
            val recency = exp(-sample.ageDays / tauDays)
            val w = (similarity * recency).coerceAtLeast(1e-5)
            sumW += w
            residualW += w * sample.residual
            tangentW += w * (sample.tangentError ?: 0.0)
        }

        val sampleFactor = (samples.size / 20.0).coerceIn(0.0, 1.0)
        val historyBiasRaw = if (sumW > 0.0) residualW / sumW else 0.0
        val tangentBiasRaw = if (sumW > 0.0) tangentW / sumW else 0.0
        val historyInfluence = (1.0 - 0.85 * regimeScore).coerceIn(0.12, 1.0)
        val historyBias = (historyBiasRaw * sampleFactor * historyInfluence).coerceIn(-4.5, 4.5)
        val tangentBias = (tangentBiasRaw * sampleFactor * (1.0 - 0.70 * regimeScore)).coerceIn(-3.0, 3.0)

        val correctedBaseline = source.baselineTemperature + historyBias
        val correctedTangent = tangent + tangentBias
        val horizonAttenuation = (0.88 - 0.38 * (horizon / 24.0)).coerceIn(0.50, 0.84)
        val tangentBlend = if (issueKinematics == null) 0.0
            else ((0.08 + 0.68 * regimeScore) * horizonAttenuation).coerceIn(0.06, 0.66)
        val rawAdaptive = correctedBaseline * (1.0 - tangentBlend) + correctedTangent * tangentBlend
        val maxCorrection = 2.2 + 0.18 * horizon
        val adaptive = source.baselineTemperature +
            (rawAdaptive - source.baselineTemperature).coerceIn(-maxCorrection, maxCorrection)
        val confidence = (
            source.confidence * (0.55 + 0.35 * sampleFactor) * (1.0 - 0.16 * regimeScore)
        ).coerceIn(0.15, 0.95)

        return BuiltPrediction(
            adaptive = adaptive.coerceIn(-70.0, 70.0),
            tangent = tangent.coerceIn(-70.0, 70.0),
            historyBias = historyBias,
            tangentBias = tangentBias,
            regimeScore = regimeScore,
            samples = samples.size,
            confidence = confidence
        )
    }

    private fun currentSource(referenceKey: String, horizon: Int, now: Long): AdaptiveSourceRow? {
        val expectedTarget = now + horizon * ADAPTIVE_HOUR_MS
        return db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, weather_temperature, humidity, weather_confidence, provider
            FROM ${ForecastHorizonArchiveStore.TABLE}
            WHERE reference_key=? AND lead_hour=? AND target_ts>? AND issued_at<=? AND policy_version=?
            ORDER BY ABS(issued_at-?) ASC, ABS(target_ts-?) ASC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey,
                horizon.toString(),
                now.toString(),
                now.toString(),
                ForecastHorizonArchiveStore.POLICY_VERSION,
                now.toString(),
                expectedTarget.toString()
            )
        ).use { c ->
            if (!c.moveToFirst()) return null
            AdaptiveSourceRow(
                horizonHour = horizon,
                issuedAt = c.getLong(0),
                targetAt = c.getLong(1),
                baselineTemperature = c.getDouble(2),
                humidity = c.getDouble(3),
                confidence = c.getDouble(4).coerceIn(0.0, 1.0),
                provider = c.getString(5)
            )
        }
    }

    private fun exists(referenceKey: String, source: AdaptiveSourceRow): Boolean =
        db.readableDatabase.rawQuery(
            """
            SELECT 1 FROM ${ForecastAdaptiveStore.TABLE}
            WHERE reference_key=? AND horizon_hour=? AND issued_at=? AND target_ts=? AND model_version=?
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey, source.horizonHour.toString(), source.issuedAt.toString(),
                source.targetAt.toString(), ForecastAdaptiveStore.MODEL_VERSION
            )
        ).use { it.moveToFirst() }

    private fun loadTrainingRows(referenceKey: String, horizon: Int, asOf: Long): List<AdaptiveTrainingRow> {
        val out = mutableListOf<AdaptiveTrainingRow>()
        db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, weather_temperature
            FROM ${ForecastHorizonArchiveStore.TABLE}
            WHERE reference_key=? AND lead_hour=? AND target_ts<=? AND target_ts>=? AND policy_version=?
            ORDER BY target_ts DESC
            LIMIT 180
            """.trimIndent(),
            arrayOf(
                referenceKey,
                horizon.toString(),
                asOf.toString(),
                (asOf - 120L * ADAPTIVE_DAY_MS).toString(),
                ForecastHorizonArchiveStore.POLICY_VERSION
            )
        ).use { c ->
            while (c.moveToNext()) {
                out += AdaptiveTrainingRow(c.getLong(0), c.getLong(1), c.getDouble(2))
            }
        }
        return out
    }

    private fun loadTerrain(referenceKey: String, from: Long, to: Long): List<AdaptiveTerrainPoint> {
        val out = mutableListOf<AdaptiveTerrainPoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT timestamp, temperature, source
            FROM weather_reference_samples
            WHERE reference_key=? AND timestamp BETWEEN ? AND ? AND source IN ('measured','reconstructed')
            ORDER BY timestamp
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += AdaptiveTerrainPoint(
                    timestamp = c.getLong(0),
                    temperature = c.getDouble(1),
                    measured = c.getString(2).equals("measured", ignoreCase = true)
                )
            }
        }
        return out
    }

    private fun actualAt(target: Long, terrain: List<AdaptiveTerrainPoint>): AdaptiveTerrainPoint? {
        val measured = terrain.asSequence()
            .filter { it.measured && abs(it.timestamp - target) <= 40L * 60L * 1000L }
            .minByOrNull { abs(it.timestamp - target) }
        if (measured != null) return measured
        return terrain.asSequence()
            .filter { abs(it.timestamp - target) <= 75L * 60L * 1000L }
            .minByOrNull { abs(it.timestamp - target) }
    }

    private fun kinematicsAt(asOf: Long, terrain: List<AdaptiveTerrainPoint>): AdaptiveKinematics? {
        fun atOrBefore(target: Long, tolerance: Long): AdaptiveTerrainPoint? =
            terrain.asSequence()
                .filter { it.timestamp <= target && target - it.timestamp <= tolerance }
                .maxWithOrNull(compareBy<AdaptiveTerrainPoint> { it.timestamp }.thenBy { it.measured })

        val p0 = atOrBefore(asOf, 90L * 60L * 1000L) ?: return null
        val p1 = atOrBefore(asOf - ADAPTIVE_HOUR_MS, 85L * 60L * 1000L) ?: return null
        val dt1 = (p0.timestamp - p1.timestamp).toDouble() / ADAPTIVE_HOUR_MS.toDouble()
        if (dt1 !in 0.45..2.0) return null
        val slopeNow = ((p0.temperature - p1.temperature) / dt1).coerceIn(-3.0, 3.0)
        val p2 = atOrBefore(asOf - 2L * ADAPTIVE_HOUR_MS, 85L * 60L * 1000L)
        val acceleration = if (p2 != null) {
            val dt2 = (p1.timestamp - p2.timestamp).toDouble() / ADAPTIVE_HOUR_MS.toDouble()
            if (dt2 in 0.45..2.0) {
                val slopeBefore = (p1.temperature - p2.temperature) / dt2
                ((slopeNow - slopeBefore) / max(0.5, (dt1 + dt2) / 2.0)).coerceIn(-1.5, 1.5)
            } else 0.0
        } else 0.0
        return AdaptiveKinematics(p0.temperature, slopeNow, acceleration)
    }

    private fun projectTangent(k: AdaptiveKinematics, hours: Double): Double {
        val delta = k.slopePerHour * hours + 0.5 * k.accelerationPerHour2 * hours * hours
        val cap = 3.0 + 0.55 * hours
        return k.temperature + delta.coerceIn(-cap, cap)
    }

    private fun latestCurrent(referenceKey: String, horizon: Int, now: Long): ForecastAdaptiveCurrent? {
        val expected = now + horizon * ADAPTIVE_HOUR_MS
        return db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, baseline_temperature, adaptive_temperature,
                   tangent_temperature, regime_score, history_samples, confidence
            FROM ${ForecastAdaptiveStore.TABLE}
            WHERE reference_key=? AND horizon_hour=? AND target_ts>? AND model_version=?
            ORDER BY ABS(target_ts-?) ASC, issued_at DESC
            LIMIT 1
            """.trimIndent(),
            arrayOf(referenceKey, horizon.toString(), now.toString(), ForecastAdaptiveStore.MODEL_VERSION, expected.toString())
        ).use { c ->
            if (!c.moveToFirst()) return null
            ForecastAdaptiveCurrent(
                horizonHour = horizon,
                issuedAt = c.getLong(0),
                targetAt = c.getLong(1),
                baselineTemperature = c.getDouble(2),
                adaptiveTemperature = c.getDouble(3),
                tangentTemperature = c.getDouble(4),
                regimeScore = c.getDouble(5).coerceIn(0.0, 1.0),
                historySamples = c.getInt(6),
                confidence = c.getDouble(7).coerceIn(0.0, 1.0)
            )
        }
    }

    private fun evaluate(referenceKey: String, horizon: Int, now: Long): ForecastAdaptiveEvaluation {
        ForecastAdaptiveStore.ensure(db.writableDatabase)
        val rows = mutableListOf<Triple<Long, Double, Double>>()
        db.readableDatabase.rawQuery(
            """
            SELECT target_ts, baseline_temperature, adaptive_temperature
            FROM ${ForecastAdaptiveStore.TABLE}
            WHERE reference_key=? AND horizon_hour=? AND target_ts<=? AND target_ts>=? AND model_version=?
            ORDER BY target_ts DESC
            LIMIT 500
            """.trimIndent(),
            arrayOf(
                referenceKey, horizon.toString(), now.toString(),
                (now - 180L * ADAPTIVE_DAY_MS).toString(), ForecastAdaptiveStore.MODEL_VERSION
            )
        ).use { c ->
            while (c.moveToNext()) rows += Triple(c.getLong(0), c.getDouble(1), c.getDouble(2))
        }
        if (rows.isEmpty()) return ForecastAdaptiveEvaluation(horizon, 0, null, null)
        val terrain = loadTerrain(referenceKey, rows.minOf { it.first } - ADAPTIVE_HOUR_MS, now)
        var count = 0
        var baselineError = 0.0
        var adaptiveError = 0.0
        rows.forEach { (target, baseline, adaptive) ->
            val actual = actualAt(target, terrain)?.temperature ?: return@forEach
            baselineError += abs(baseline - actual)
            adaptiveError += abs(adaptive - actual)
            count++
        }
        return if (count == 0) ForecastAdaptiveEvaluation(horizon, 0, null, null)
        else ForecastAdaptiveEvaluation(horizon, count, baselineError / count, adaptiveError / count)
    }

    private fun interpolate10Minutes(points: List<SamplePoint>): List<SamplePoint> {
        val sorted = points.distinctBy { it.timestamp }.sortedBy { it.timestamp }
        if (sorted.size < 2) return sorted
        val out = mutableListOf<SamplePoint>()
        sorted.zipWithNext().forEach { (left, right) ->
            out += left
            val gap = right.timestamp - left.timestamp
            if (gap in 20L * 60L * 1000L..95L * 60L * 1000L) {
                var ts = ((left.timestamp / ADAPTIVE_STEP_MS) + 1L) * ADAPTIVE_STEP_MS
                while (ts < right.timestamp) {
                    val linear = ((ts - left.timestamp).toDouble() / gap.toDouble()).coerceIn(0.0, 1.0)
                    val smooth = 0.5 - 0.5 * cos(PI * linear)
                    val leftConfidence = left.confidence ?: 0.5
                    val rightConfidence = right.confidence ?: 0.5
                    out += SamplePoint(
                        sensorId = left.sensorId,
                        timestamp = ts,
                        temperature = left.temperature + (right.temperature - left.temperature) * smooth,
                        humidity = left.humidity + (right.humidity - left.humidity) * smooth,
                        source = PointSource.FORECAST,
                        confidence = (leftConfidence + (rightConfidence - leftConfidence) * linear).coerceIn(0.0, 1.0)
                    )
                    ts += ADAPTIVE_STEP_MS
                }
            }
        }
        out += sorted.last()
        return out
    }
}
