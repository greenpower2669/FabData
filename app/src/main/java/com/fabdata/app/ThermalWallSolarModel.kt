package com.fabdata.app

import java.time.Instant
import java.time.ZoneId
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

private const val WALL_HOUR_MS = 60L * 60L * 1000L

/** A real facade observation aligned with the official outdoor reference. */
data class WallSolarObservation(
    val timestamp: Long,
    val officialOutsideC: Double,
    val measuredWallC: Double
)

data class WallSolarModel(
    val wallId: String,
    val orientationDeg: Double,
    val orientationWasUserFixed: Boolean,
    val baselineOffsetC: Double,
    val solarGainC: Double,
    val responseTauHours: Double,
    val fitRmseC: Double,
    val trainingHours: Int,
    val realDays: Int,
    val daylightHours: Int,
    val confidence: Double,
    val calibrationFrom: Long,
    val calibrationTo: Long
)

data class WallReconstructedPoint(
    val timestamp: Long,
    val temperature: Double,
    val confidence: Double,
    val source: PointSource = PointSource.RECONSTRUCTED
)

data class SolarPosition(
    val elevationDeg: Double,
    /** Degrees clockwise from geographic north. */
    val azimuthDeg: Double
)

/**
 * Lightweight facade model.
 *
 * It intentionally does NOT use a fixed time shift between walls. The forcing is
 * recomputed from solar azimuth/elevation at every timestamp, therefore sunrise,
 * sunset and facade exposure naturally move with date/season. A first-order thermal
 * state then gives each facade its own inertia/phase response.
 *
 * Surface area is intentionally absent from the temperature fit: for a wall of the
 * same construction, area mainly changes the energy coupled into the building, not
 * the facade temperature itself. SurfaceM2 is consumed later by the building model.
 */
class ThermalWallSolarTrainer {

    fun train(
        reference: WeatherReference,
        wall: ThermalWallSegment,
        observations: List<WallSolarObservation>
    ): WallSolarModel? {
        val clean = observations
            .asSequence()
            .filter { it.officialOutsideC in -100.0..150.0 && it.measuredWallC in -100.0..150.0 }
            .sortedBy { it.timestamp }
            .distinctBy { hourBucket(it.timestamp) }
            .toList()
        if (clean.size < 6) return null

        val orientationCandidates = wall.orientationDeg?.let { listOf(normalizeDegrees(it)) }
            ?: (0 until 360 step 5).map(Int::toDouble)
        val tauCandidates = doubleArrayOf(0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 18.0, 24.0, 36.0)

        var best: Candidate? = null
        orientationCandidates.forEach { orientation ->
            val direct = clean.map { o ->
                solarIncidence(
                    solarPosition(o.timestamp, reference.latitude, reference.longitude),
                    orientation
                )
            }.toDoubleArray()

            tauCandidates.forEach { tau ->
                val state = propagateSolarState(clean, direct, tau)
                val y = DoubleArray(clean.size) { i -> clean[i].measuredWallC - clean[i].officialOutsideC }
                val fit = fitOffsetAndGain(state, y) ?: return@forEach
                val predicted = DoubleArray(clean.size) { i -> fit.first + fit.second * state[i] }
                val rmse = rmse(y, predicted)
                val penalty = if (fit.second > 25.0) (fit.second - 25.0) * 0.10 else 0.0
                val score = rmse + penalty
                if (best == null || score < best!!.score) {
                    best = Candidate(orientation, tau, fit.first, fit.second, rmse, score, direct, state)
                }
            }
        }

        val chosen = best ?: return null
        val realDays = clean.map { Instant.ofEpochMilli(it.timestamp).atZone(ZoneId.of("Europe/Paris")).toLocalDate() }
            .distinct().size
        val daylightHours = chosen.direct.count { it > 0.05 }
        val dataFactor = min(1.0, clean.size / 120.0)
        val dayFactor = min(1.0, realDays / 8.0)
        val sunFactor = min(1.0, daylightHours / 30.0)
        val errorFactor = (1.0 - chosen.rmse / 3.0).coerceIn(0.0, 1.0)
        val orientationFactor = if (wall.orientationDeg != null) 1.0 else min(1.0, daylightHours / 18.0)
        val confidence = (
            0.10 + 0.27 * errorFactor + 0.18 * dataFactor + 0.16 * dayFactor +
                0.17 * sunFactor + 0.12 * orientationFactor
            ).coerceIn(0.08, 0.95)

        return WallSolarModel(
            wallId = wall.id,
            orientationDeg = chosen.orientation,
            orientationWasUserFixed = wall.orientationDeg != null,
            baselineOffsetC = chosen.offset,
            solarGainC = chosen.gain,
            responseTauHours = chosen.tau,
            fitRmseC = chosen.rmse,
            trainingHours = clean.size,
            realDays = realDays,
            daylightHours = daylightHours,
            confidence = confidence,
            calibrationFrom = clean.first().timestamp,
            calibrationTo = clean.last().timestamp
        )
    }

    /**
     * Rebuilds a facade curve from the official reference. The caller may provide
     * extra reference points before `from` as thermal warm-up; only [from, to] is returned.
     */
    fun reconstruct(
        reference: WeatherReference,
        model: WallSolarModel,
        official: List<WeatherReferencePoint>,
        from: Long,
        to: Long
    ): List<WallReconstructedPoint> {
        if (official.isEmpty() || to < from) return emptyList()
        val ordered = official
            .asSequence()
            .filter { it.timestamp <= to && it.temperature in -100.0..150.0 }
            .sortedBy { it.timestamp }
            .distinctBy { hourBucket(it.timestamp) }
            .toList()
        if (ordered.isEmpty()) return emptyList()

        var state = 0.0
        var previousTs = ordered.first().timestamp
        val out = ArrayList<WallReconstructedPoint>()
        ordered.forEach { p ->
            val dtHours = ((p.timestamp - previousTs).coerceAtLeast(0L) / WALL_HOUR_MS.toDouble()).coerceIn(0.0, 12.0)
            val incidence = solarIncidence(
                solarPosition(p.timestamp, reference.latitude, reference.longitude),
                model.orientationDeg
            )
            val alpha = if (dtHours <= 0.0) 1.0 else 1.0 - exp(-dtHours / model.responseTauHours.coerceAtLeast(0.25))
            state += alpha * (incidence - state)
            previousTs = p.timestamp
            if (p.timestamp in from..to) {
                val temp = p.temperature + model.baselineOffsetC + model.solarGainC * state
                val sourceFactor = when (p.source) {
                    PointSource.MEASURED -> 1.0
                    PointSource.RECONSTRUCTED -> 0.82
                    PointSource.FORECAST -> 0.68
                }
                out += WallReconstructedPoint(
                    timestamp = p.timestamp,
                    temperature = temp.coerceIn(-100.0, 150.0),
                    confidence = (model.confidence * sourceFactor).coerceIn(0.05, 0.95)
                )
            }
        }
        return out
    }

    private data class Candidate(
        val orientation: Double,
        val tau: Double,
        val offset: Double,
        val gain: Double,
        val rmse: Double,
        val score: Double,
        val direct: DoubleArray,
        val state: DoubleArray
    )

    private fun propagateSolarState(
        observations: List<WallSolarObservation>,
        direct: DoubleArray,
        tauHours: Double
    ): DoubleArray {
        val state = DoubleArray(observations.size)
        var current = direct.firstOrNull() ?: 0.0
        state[0] = current
        for (i in 1 until observations.size) {
            val dtHours = ((observations[i].timestamp - observations[i - 1].timestamp).coerceAtLeast(0L) /
                WALL_HOUR_MS.toDouble()).coerceIn(0.0, 12.0)
            val alpha = if (dtHours <= 0.0) 0.0 else 1.0 - exp(-dtHours / tauHours.coerceAtLeast(0.25))
            current += alpha * (direct[i] - current)
            state[i] = current
        }
        return state
    }

    /** Returns offset, positive solar gain. */
    private fun fitOffsetAndGain(x: DoubleArray, y: DoubleArray): Pair<Double, Double>? {
        if (x.size != y.size || x.isEmpty()) return null
        val meanX = x.average()
        val meanY = y.average()
        var num = 0.0
        var den = 0.0
        for (i in x.indices) {
            val dx = x[i] - meanX
            num += dx * (y[i] - meanY)
            den += dx * dx
        }
        val gain = if (den < 1e-8) 0.0 else (num / den).coerceIn(0.0, 35.0)
        val offset = (meanY - gain * meanX).coerceIn(-20.0, 20.0)
        return offset to gain
    }

    private fun rmse(actual: DoubleArray, predicted: DoubleArray): Double {
        if (actual.isEmpty() || actual.size != predicted.size) return Double.POSITIVE_INFINITY
        var sum = 0.0
        for (i in actual.indices) {
            val d = predicted[i] - actual[i]
            sum += d * d
        }
        return sqrt(sum / actual.size)
    }
}

/**
 * Approximate NOAA-style solar geometry, sufficient for learning facade timing.
 * Azimuth is clockwise from north. DST/local UTC offset is taken from Europe/Paris
 * at the actual timestamp, so seasonal clock changes do not become fake facade lag.
 */
fun solarPosition(timestamp: Long, latitude: Double, longitude: Double): SolarPosition {
    val zone = ZoneId.of("Europe/Paris")
    val zdt = Instant.ofEpochMilli(timestamp).atZone(zone)
    val day = zdt.dayOfYear.toDouble()
    val localHour = zdt.hour + zdt.minute / 60.0 + zdt.second / 3600.0
    val gamma = 2.0 * PI / 365.0 * (day - 1.0 + (localHour - 12.0) / 24.0)

    val eqTime = 229.18 * (
        0.000075 + 0.001868 * cos(gamma) - 0.032077 * sin(gamma) -
            0.014615 * cos(2.0 * gamma) - 0.040849 * sin(2.0 * gamma)
        )
    val decl = 0.006918 - 0.399912 * cos(gamma) + 0.070257 * sin(gamma) -
        0.006758 * cos(2.0 * gamma) + 0.000907 * sin(2.0 * gamma) -
        0.002697 * cos(3.0 * gamma) + 0.00148 * sin(3.0 * gamma)

    val utcOffsetHours = zdt.offset.totalSeconds / 3600.0
    val timeOffsetMin = eqTime + 4.0 * longitude - 60.0 * utcOffsetHours
    var trueSolarMinutes = localHour * 60.0 + timeOffsetMin
    while (trueSolarMinutes < 0.0) trueSolarMinutes += 1440.0
    while (trueSolarMinutes >= 1440.0) trueSolarMinutes -= 1440.0
    val hourAngle = Math.toRadians(trueSolarMinutes / 4.0 - 180.0)
    val lat = Math.toRadians(latitude.coerceIn(-89.9, 89.9))

    val cosZenith = (sin(lat) * sin(decl) + cos(lat) * cos(decl) * cos(hourAngle)).coerceIn(-1.0, 1.0)
    val zenith = acos(cosZenith)
    val elevation = 90.0 - Math.toDegrees(zenith)

    val azimuthRaw = Math.toDegrees(
        atan2(
            sin(hourAngle),
            cos(hourAngle) * sin(lat) - tan(decl) * cos(lat)
        )
    ) + 180.0

    return SolarPosition(
        elevationDeg = elevation,
        azimuthDeg = normalizeDegrees(azimuthRaw)
    )
}

/** Direct-beam incidence on a vertical facade normal. 0 means no direct sun. */
fun solarIncidence(position: SolarPosition, wallOrientationDeg: Double): Double {
    if (position.elevationDeg <= 0.0) return 0.0
    val elevation = Math.toRadians(position.elevationDeg)
    var delta = abs(normalizeDegrees(position.azimuthDeg) - normalizeDegrees(wallOrientationDeg))
    if (delta > 180.0) delta = 360.0 - delta
    if (delta >= 90.0) return 0.0
    return (cos(elevation) * cos(Math.toRadians(delta))).coerceIn(0.0, 1.0)
}

private fun hourBucket(timestamp: Long): Long = timestamp / WALL_HOUR_MS
