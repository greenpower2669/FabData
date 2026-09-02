package com.fabdata.app

import java.time.Instant
import java.time.ZoneId
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

private const val THERMAL_HOUR_MS = 60L * 60L * 1000L
private const val THERMAL_DAY_MS = 24L * THERMAL_HOUR_MS
private const val MIN_REAL_DAYS = 15
private const val MAX_HISTORY_DAYS = 90

data class ThermalMetrics(
    val mae: Double,
    val rmse: Double,
    val bias: Double,
    val maxError: Double,
    val validationPoints: Int
)

data class ThermalModel(
    val sensorId: Long,
    val sensorName: String,
    val room: String,
    val referenceKey: String,
    val referenceStationId: String,
    val referenceCity: String,
    val lagHours: Int,
    val coefficients: DoubleArray,
    val calibrationFrom: Long,
    val calibrationTo: Long,
    val usablePoints: Int,
    val realDays: Int,
    val metrics: ThermalMetrics,
    val confidence: Double,
    val tauHours: Double
) {
    val acceptable: Boolean
        get() = realDays >= MIN_REAL_DAYS && usablePoints >= 120 && metrics.rmse <= 2.0 && metrics.mae <= 1.5 && confidence >= 0.35
}

data class ThermalSensorStatus(
    val sensor: Sensor,
    val realDays: Int,
    val model: ThermalModel?
)

data class ThermalStatus(
    val reference: WeatherReference,
    val sensors: List<ThermalSensorStatus>,
    val preferred: ThermalSensorStatus?,
    val message: String
) {
    val canReconstruct: Boolean get() = sensors.any { it.model?.acceptable == true }
}

data class ThermalWriteSummary(
    val reconstructed: Int,
    val forecast: Int,
    val skippedSensors: Int
)

private data class HourPoint(
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val source: PointSource,
    val confidence: Double = 1.0
)

private data class TrainingRow(
    val timestamp: Long,
    val tin: Double,
    val nextTin: Double,
    val tout: Double,
    val toutAvg6: Double,
    val hourOfDay: Int,
    val features: DoubleArray,
    val delta: Double
)

/**
 * Modèle thermique grey-box RC discret :
 * ΔTin = a(Tout_lag-Tin) + b(Tout_moy6h-Tin) + c.sin(h) + d.cos(h) + e
 *
 * Les termes a/b représentent échange + accumulation thermique. Les termes jour/nuit
 * ne forcent aucune sinusoïde sur la courbe : ils corrigent seulement le résidu horaire
 * appris sur les vraies mesures. Les reconstructions/prévisions passent toujours par
 * PointSourceStore et sa priorité stricte.
 */
class ThermalEngine(
    private val db: FabDataDb,
    private val referenceStore: WeatherReferenceStore
) {
    private val zone = ZoneId.of("Europe/Paris")

    fun status(reference: WeatherReference): ThermalStatus {
        val candidates = physicalSensors().map { sensor ->
            val real = measuredHourly(sensor.id)
            val days = distinctDays(real)
            val model = if (days >= MIN_REAL_DAYS) runCatching { calibrate(sensor, reference) }.getOrNull() else null
            ThermalSensorStatus(sensor, days, model)
        }
        val preferred = candidates.sortedWith(
            compareBy<ThermalSensorStatus> { preferenceRank(it.sensor.room) }
                .thenByDescending { it.realDays }
        ).firstOrNull()
        val enough = candidates.any { it.realDays >= MIN_REAL_DAYS }
        val message = if (!enough) {
            "FabData ne dispose pas encore de suffisamment de mesures pour apprendre correctement l'inertie thermique du bâtiment. Il est préférable d'attendre davantage de données plutôt que de produire une reconstruction incertaine."
        } else if (candidates.none { it.model?.acceptable == true }) {
            "Les données sont assez longues, mais la validation rétrospective n'est pas encore assez bonne pour autoriser une reconstruction fiable."
        } else {
            "Modèle thermique RC validé. Les périodes perturbées sont écartées autant que possible avant calibration."
        }
        return ThermalStatus(reference, candidates, preferred, message)
    }

    fun calibrate(sensor: Sensor, reference: WeatherReference): ThermalModel {
        val measured = measuredHourly(sensor.id)
        val realDays = distinctDays(measured)
        require(realDays >= MIN_REAL_DAYS) { "Moins de 15 jours réels exploitables" }
        require(measured.size >= 180) { "Pas assez de points horaires réels" }

        val from = measured.first().timestamp - 18L * THERMAL_HOUR_MS
        val to = measured.last().timestamp
        val outside = referenceHourly(reference.key, from, to, includeForecast = false)
        require(outside.size >= 120) { "Référence météo extérieure insuffisante" }
        val outMap = outside.associateBy { hourBucket(it.timestamp) }
        val medianDeltas = buildingMedianDeltaByHour(measured.first().timestamp, measured.last().timestamp)

        var best: ThermalModel? = null
        for (lag in 0..12) {
            val rows = buildTrainingRows(measured, outMap, medianDeltas, lag)
            if (rows.size < 120) continue
            val split = (rows.size * 0.80).toInt().coerceIn(80, rows.size - 24)
            val train = rows.take(split)
            val valid = rows.drop(split)
            val coeff = ridgeRegression(train) ?: continue
            val metrics = validate(coeff, valid)
            val exchange = coeff[0] + coeff[1]
            if (!exchange.isFinite() || exchange <= 0.002 || exchange >= 0.65) continue
            val tau = (1.0 / exchange).coerceIn(1.0, 500.0)
            val dataFactor = min(1.0, realDays / 35.0) * min(1.0, rows.size / 500.0)
            val errorFactor = (1.0 - metrics.rmse / 2.8).coerceIn(0.0, 1.0)
            val biasFactor = (1.0 - abs(metrics.bias) / 1.3).coerceIn(0.0, 1.0)
            val confidence = (0.15 + 0.50 * errorFactor + 0.20 * biasFactor + 0.15 * dataFactor).coerceIn(0.0, 1.0)
            val model = ThermalModel(
                sensor.id, sensor.name, sensor.room, reference.key, reference.stationId, reference.city,
                lag, coeff, train.first().timestamp, train.last().timestamp, rows.size, realDays,
                metrics, confidence, tau
            )
            if (best == null || model.metrics.rmse < best.metrics.rmse) best = model
        }
        return best ?: error("Aucun modèle RC stable n'a passé la calibration")
    }

    /** Reconstruction consentie : jusqu'à 90 jours avant la première mesure réelle + petits trous internes. */
    fun reconstructHistory(reference: WeatherReference, requestedDays: Int): ThermalWriteSummary {
        val days = requestedDays.coerceIn(1, MAX_HISTORY_DAYS)
        var total = 0
        var skipped = 0
        physicalSensors().forEach { sensor ->
            val model = runCatching { calibrate(sensor, reference) }.getOrNull()
            if (model == null || !model.acceptable) {
                skipped++
                return@forEach
            }
            val measured = measuredHourly(sensor.id)
            if (measured.isEmpty()) { skipped++; return@forEach }
            val first = measured.first()
            val refBounds = referenceStore.bounds(reference.key) ?: run { skipped++; return@forEach }
            val requestedStart = first.timestamp - days.toLong() * THERMAL_DAY_MS
            val start = max(requestedStart, refBounds.first)
            if (start >= first.timestamp) { skipped++; return@forEach }
            val outside = referenceHourly(reference.key, start - 18L * THERMAL_HOUR_MS, first.timestamp, includeForecast = false)
            if (outside.size < 24) { skipped++; return@forEach }
            val outMap = outside.associateBy { hourBucket(it.timestamp) }

            var knownNext = first.temperature
            var ts = hourBucket(first.timestamp) - THERMAL_HOUR_MS
            while (ts >= hourBucket(start)) {
                val tout = outsideAt(outMap, ts - model.lagHours * THERMAL_HOUR_MS) ?: break
                val avg6 = outsideAverage(outMap, ts - model.lagHours * THERMAL_HOUR_MS, 6) ?: tout
                val hour = Instant.ofEpochMilli(ts).atZone(zone).hour
                val c = model.coefficients
                val seasonal = c[2] * sin(2.0 * PI * hour / 24.0) + c[3] * cos(2.0 * PI * hour / 24.0) + c[4]
                val denom = 1.0 - c[0] - c[1]
                if (abs(denom) < 0.25) break
                val rawPrev = (knownNext - c[0] * tout - c[1] * avg6 - seasonal) / denom
                val prev = rawPrev.coerceIn(knownNext - 1.5, knownNext + 1.5)
                val horizonDays = (first.timestamp - ts).toDouble() / THERMAL_DAY_MS.toDouble()
                val confidence = (model.confidence * (1.0 - 0.0065 * horizonDays)).coerceIn(0.25, model.confidence)
                val provenance = provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, ts, prev, first.humidity, provenance
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) total++
                knownNext = prev
                ts -= THERMAL_HOUR_MS
            }
            total += fillInteriorGaps(sensor, model, reference)
        }
        return ThermalWriteSummary(total, 0, skipped)
    }

    /** Prévision courte automatique H+6, toujours recalculée depuis la dernière vraie mesure. */
    fun refreshForecasts(reference: WeatherReference): ThermalWriteSummary {
        var total = 0
        var skipped = 0
        physicalSensors().forEach { sensor ->
            val model = runCatching { calibrate(sensor, reference) }.getOrNull()
            if (model == null || !model.acceptable) { skipped++; return@forEach }
            val measured = measuredHourly(sensor.id)
            val latest = measured.lastOrNull() ?: run { skipped++; return@forEach }
            val recent = measured.takeLast(4)
            PointSourceStore.deleteForecastsAtOrAfter(db, sensor.id, latest.timestamp + 1L)

            val from = latest.timestamp - 18L * THERMAL_HOUR_MS
            val to = latest.timestamp + 7L * THERMAL_HOUR_MS
            val outside = referenceHourly(reference.key, from, to, includeForecast = true)
            val outMap = outside.associateBy { hourBucket(it.timestamp) }
            if (outside.none { it.source == PointSource.FORECAST }) { skipped++; return@forEach }

            val slopes = recent.zipWithNext().mapNotNull { (a, b) ->
                val dt = (b.timestamp - a.timestamp).toDouble() / THERMAL_HOUR_MS.toDouble()
                if (dt <= 0.0 || dt > 2.5) null else (b.temperature - a.temperature) / dt
            }
            val recentSlope = slopes.takeLast(3).averageOrZero()
            val curvature = if (slopes.size >= 2) slopes.last() - slopes[slopes.lastIndex - 1] else 0.0

            var currentT = latest.temperature
            var currentH = latest.humidity
            for (horizon in 1..6) {
                val ts = hourBucket(latest.timestamp) + horizon * THERMAL_HOUR_MS
                val extTs = ts - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs) ?: continue
                val outHum = outMap[hourBucket(ts)]?.humidity ?: currentH
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
                val hour = Instant.ofEpochMilli(ts - THERMAL_HOUR_MS).atZone(zone).hour
                val modelDelta = predictDelta(model.coefficients, currentT, tout, avg6, hour)
                val momentum = (recentSlope + 0.45 * curvature) * exp(-(horizon - 1).toDouble() / 1.7)
                val delta = (modelDelta + 0.30 * momentum).coerceIn(-1.2, 1.2)
                currentT += delta
                currentH += 0.08 * (outHum - currentH)
                val confidence = (model.confidence * (1.0 - 0.085 * horizon)).coerceIn(0.20, model.confidence)
                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, ts, round2(currentT), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.FORECAST, confidence)
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) total++
            }
        }
        return ThermalWriteSummary(0, total, skipped)
    }

    private fun fillInteriorGaps(sensor: Sensor, model: ThermalModel, reference: WeatherReference): Int {
        val measured = measuredHourly(sensor.id)
        if (measured.size < 2) return 0
        val out = referenceHourly(reference.key, measured.first().timestamp - 18L * THERMAL_HOUR_MS, measured.last().timestamp, false)
        val outMap = out.associateBy { hourBucket(it.timestamp) }
        var created = 0
        measured.zipWithNext().forEach { (left, right) ->
            val gapHours = ((right.timestamp - left.timestamp) / THERMAL_HOUR_MS).toInt()
            if (gapHours !in 2..24) return@forEach
            var current = left.temperature
            for (step in 1 until gapHours) {
                val ts = hourBucket(left.timestamp) + step * THERMAL_HOUR_MS
                val extTs = ts - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs) ?: break
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
                val hour = Instant.ofEpochMilli(ts - THERMAL_HOUR_MS).atZone(zone).hour
                val predicted = current + predictDelta(model.coefficients, current, tout, avg6, hour)
                // Ancrage progressif sur la vraie mesure de droite pour éviter une dérive libre.
                val remaining = gapHours - step
                val correction = (right.temperature - predicted) / (remaining + 1).toDouble()
                current = (predicted + correction).coerceIn(min(left.temperature, right.temperature) - 3.0, max(left.temperature, right.temperature) + 3.0)
                val confidence = (model.confidence * 0.82).coerceIn(0.25, 0.85)
                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, ts, round2(current), (left.humidity + (right.humidity - left.humidity) * step / gapHours.toDouble()).coerceIn(0.0, 100.0),
                    provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) created++
            }
        }
        return created
    }

    private fun provenance(model: ThermalModel, reference: WeatherReference, source: PointSource, confidence: Double) = PointProvenance(
        source = source,
        confidence = confidence,
        referenceKey = reference.key,
        referenceStationId = reference.stationId,
        referenceCity = reference.city,
        calibrationFrom = model.calibrationFrom,
        calibrationTo = model.calibrationTo,
        modelVersion = PointSourceStore.MODEL_VERSION
    )

    private fun buildTrainingRows(
        indoor: List<HourPoint>,
        outside: Map<Long, HourPoint>,
        medianDeltas: Map<Long, Double>,
        lagHours: Int
    ): List<TrainingRow> {
        val rows = mutableListOf<TrainingRow>()
        indoor.zipWithNext().forEach { (a, b) ->
            val dt = b.timestamp - a.timestamp
            if (dt !in (45L * 60L * 1000L)..(90L * 60L * 1000L)) return@forEach
            val dTin = b.temperature - a.temperature
            // Clim, fenêtre, douche/chauffage et excursions intérieures rapides.
            if (abs(dTin) > 1.35) return@forEach
            if (abs(b.humidity - a.humidity) > 18.0) return@forEach
            val buildingDelta = medianDeltas[hourBucket(a.timestamp)]
            if (buildingDelta != null && abs(dTin - buildingDelta) > 1.25) return@forEach

            val extTs = hourBucket(a.timestamp) - lagHours * THERMAL_HOUR_MS
            val tout = outsideAt(outside, extTs) ?: return@forEach
            val avg6 = outsideAverage(outside, extTs, 6) ?: return@forEach
            val hour = Instant.ofEpochMilli(a.timestamp).atZone(zone).hour
            val features = doubleArrayOf(
                tout - a.temperature,
                avg6 - a.temperature,
                sin(2.0 * PI * hour / 24.0),
                cos(2.0 * PI * hour / 24.0),
                1.0
            )
            rows += TrainingRow(a.timestamp, a.temperature, b.temperature, tout, avg6, hour, features, dTin)
        }
        return rows
    }

    private fun ridgeRegression(rows: List<TrainingRow>): DoubleArray? {
        val n = 5
        val a = Array(n) { DoubleArray(n) }
        val b = DoubleArray(n)
        rows.forEach { row ->
            for (i in 0 until n) {
                b[i] += row.features[i] * row.delta
                for (j in 0 until n) a[i][j] += row.features[i] * row.features[j]
            }
        }
        val ridge = 0.015
        for (i in 0 until n) a[i][i] += ridge
        return solve(a, b)
    }

    private fun validate(coeff: DoubleArray, rows: List<TrainingRow>): ThermalMetrics {
        val errors = rows.map { row ->
            val predicted = row.tin + dot(coeff, row.features)
            predicted - row.nextTin
        }
        if (errors.isEmpty()) return ThermalMetrics(99.0, 99.0, 99.0, 99.0, 0)
        val mae = errors.map(::abs).average()
        val rmse = sqrt(errors.map { it * it }.average())
        val bias = errors.average()
        val maxErr = errors.maxOf { abs(it) }
        return ThermalMetrics(mae, rmse, bias, maxErr, errors.size)
    }

    private fun predictDelta(coeff: DoubleArray, tin: Double, tout: Double, toutAvg6: Double, hour: Int): Double {
        val f = doubleArrayOf(
            tout - tin,
            toutAvg6 - tin,
            sin(2.0 * PI * hour / 24.0),
            cos(2.0 * PI * hour / 24.0),
            1.0
        )
        return dot(coeff, f)
    }

    private fun solve(inputA: Array<DoubleArray>, inputB: DoubleArray): DoubleArray? {
        val n = inputB.size
        val a = Array(n) { inputA[it].clone() }
        val b = inputB.clone()
        for (col in 0 until n) {
            var pivot = col
            for (row in col + 1 until n) if (abs(a[row][col]) > abs(a[pivot][col])) pivot = row
            if (abs(a[pivot][col]) < 1e-10) return null
            if (pivot != col) {
                val tmp = a[col]; a[col] = a[pivot]; a[pivot] = tmp
                val tb = b[col]; b[col] = b[pivot]; b[pivot] = tb
            }
            val div = a[col][col]
            for (j in col until n) a[col][j] /= div
            b[col] /= div
            for (row in 0 until n) {
                if (row == col) continue
                val factor = a[row][col]
                if (abs(factor) < 1e-14) continue
                for (j in col until n) a[row][j] -= factor * a[col][j]
                b[row] -= factor * b[col]
            }
        }
        return b
    }

    private fun measuredHourly(sensorId: Long): List<HourPoint> {
        PointSourceStore.ensure(db.readableDatabase)
        val raw = mutableListOf<HourPoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity
            FROM samples p
            LEFT JOIN point_sources s ON s.sensor_id=p.sensor_id AND s.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (s.source IS NULL OR s.source='measured')
            ORDER BY p.timestamp
            """.trimIndent(), arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) raw += HourPoint(c.getLong(0), c.getDouble(1), c.getDouble(2), PointSource.MEASURED)
        }
        return aggregateHourly(raw)
    }

    private fun referenceHourly(referenceKey: String, from: Long, to: Long, includeForecast: Boolean): List<HourPoint> {
        val raw = referenceStore.query(referenceKey, from, to)
            .filter { includeForecast || it.source != PointSource.FORECAST }
            .map { HourPoint(it.timestamp, it.temperature, it.humidity, it.source, it.confidence) }
        return aggregateHourly(raw)
    }

    private fun aggregateHourly(points: List<HourPoint>): List<HourPoint> {
        if (points.isEmpty()) return emptyList()
        return points.groupBy { hourBucket(it.timestamp) }.map { (bucket, values) ->
            val bestPriority = values.maxOf { it.source.priority }
            val best = values.filter { it.source.priority == bestPriority }
            HourPoint(
                bucket,
                best.map { it.temperature }.average(),
                best.map { it.humidity }.average(),
                best.first().source,
                best.map { it.confidence }.average()
            )
        }.sortedBy { it.timestamp }
    }

    private fun buildingMedianDeltaByHour(from: Long, to: Long): Map<Long, Double> {
        val byHour = mutableMapOf<Long, MutableList<Double>>()
        physicalSensors().forEach { sensor ->
            val pts = measuredHourly(sensor.id).filter { it.timestamp in from..to }
            pts.zipWithNext().forEach { (a, b) ->
                if (b.timestamp - a.timestamp in (45L * 60L * 1000L)..(90L * 60L * 1000L)) {
                    byHour.getOrPut(hourBucket(a.timestamp)) { mutableListOf() } += b.temperature - a.temperature
                }
            }
        }
        return byHour.mapValues { (_, values) ->
            val s = values.sorted()
            if (s.size % 2 == 1) s[s.size / 2] else (s[s.size / 2 - 1] + s[s.size / 2]) / 2.0
        }
    }

    private fun physicalSensors(): List<Sensor> = db.sensors().filter { s ->
        !s.stableKey.startsWith("meteo-") && !s.stableKey.startsWith("http-get-") && s.id >= 0L
    }

    private fun distinctDays(points: List<HourPoint>): Int = points.map {
        Instant.ofEpochMilli(it.timestamp).atZone(zone).toLocalDate()
    }.distinct().size

    private fun preferenceRank(roomRaw: String): Int {
        val room = roomRaw.lowercase()
            .replace("é", "e").replace("è", "e").replace("ê", "e").replace("-", " ")
        return when {
            "salle de bain" in room || "sdb" in room -> 0
            "chambre" in room && ("sud est" in room || "sudest" in room) -> 1
            else -> 2
        }
    }

    private fun outsideAt(map: Map<Long, HourPoint>, timestamp: Long): Double? {
        val bucket = hourBucket(timestamp)
        map[bucket]?.let { return it.temperature }
        val candidates = listOfNotNull(map[bucket - THERMAL_HOUR_MS], map[bucket + THERMAL_HOUR_MS])
        return candidates.minByOrNull { abs(it.timestamp - timestamp) }?.temperature
    }

    private fun outsideAverage(map: Map<Long, HourPoint>, timestamp: Long, hours: Int): Double? {
        val values = (0 until hours).mapNotNull { i -> outsideAt(map, timestamp - i * THERMAL_HOUR_MS) }
        return values.takeIf { it.size >= max(2, hours / 2) }?.average()
    }

    private fun hourBucket(ts: Long): Long = (ts / THERMAL_HOUR_MS) * THERMAL_HOUR_MS
    private fun dot(a: DoubleArray, b: DoubleArray): Double = a.indices.sumOf { a[it] * b[it] }
    private fun round2(v: Double): Double = kotlin.math.round(v * 100.0) / 100.0
    private fun List<Double>.averageOrZero(): Double = if (isEmpty()) 0.0 else average()
}
