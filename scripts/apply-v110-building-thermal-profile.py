from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# -----------------------------------------------------------------------------
# 1) Building thermal profile: user-facing physical priors, persisted separately.
# -----------------------------------------------------------------------------
profile_path = "app/src/main/java/com/fabdata/app/ThermalProfile.kt"
profile = r'''package com.fabdata.app

import android.content.Context
import kotlin.math.sqrt

enum class ThermalInertia(val label: String) {
    LIGHT("Faible"),
    MEDIUM("Moyenne"),
    HEAVY("Forte")
}

enum class ThermalExposure(val label: String) {
    LOW("Faible"),
    MEDIUM("Moyenne"),
    HIGH("Forte")
}

data class ThermalBuildingProfile(
    val surfaceM2: Double = 70.0,
    val floor: Int = 4,
    val insulation: String = "D",
    val inertia: ThermalInertia = ThermalInertia.MEDIUM,
    val exposure: ThermalExposure = ThermalExposure.MEDIUM,
    val initialMassOverrideC: Double? = null
) {
    fun normalized(): ThermalBuildingProfile = copy(
        surfaceM2 = surfaceM2.coerceIn(15.0, 400.0),
        floor = floor.coerceIn(0, 50),
        insulation = insulation.uppercase().takeIf { it in listOf("A", "B", "C", "D", "E", "F", "G") } ?: "D",
        initialMassOverrideC = initialMassOverrideC?.coerceIn(5.0, 40.0)
    )

    /** Plus l'indice est mauvais, plus l'extérieur agit vite sur la masse du logement. */
    fun insulationExchangeFactor(): Double = when (insulation.uppercase()) {
        "A" -> 0.62
        "B" -> 0.74
        "C" -> 0.86
        "D" -> 1.00
        "E" -> 1.15
        "F" -> 1.32
        "G" -> 1.50
        else -> 1.00
    }

    fun massTauHours(): Double {
        val inertiaFactor = when (inertia) {
            ThermalInertia.LIGHT -> 0.55
            ThermalInertia.MEDIUM -> 1.00
            ThermalInertia.HEAVY -> 1.85
        }
        val sizeFactor = sqrt(surfaceM2.coerceAtLeast(20.0) / 70.0).coerceIn(0.60, 2.20)
        val retention = when (insulation.uppercase()) {
            "A" -> 1.35
            "B" -> 1.22
            "C" -> 1.10
            "D" -> 1.00
            "E" -> 0.90
            "F" -> 0.80
            "G" -> 0.70
            else -> 1.00
        }
        return (72.0 * inertiaFactor * sizeFactor * retention).coerceIn(18.0, 260.0)
    }

    fun massOutdoorWeight(): Double {
        val exposureFactor = when (exposure) {
            ThermalExposure.LOW -> 0.78
            ThermalExposure.MEDIUM -> 1.00
            ThermalExposure.HIGH -> 1.28
        }
        // Effet volontairement modéré : l'étage seul ne dit pas si l'on est sous toiture.
        val floorFactor = (1.0 + (floor - 4) * 0.012).coerceIn(0.88, 1.20)
        return (0.12 * insulationExchangeFactor() * exposureFactor * floorFactor).coerceIn(0.05, 0.34)
    }

    fun massCoupling(): Double {
        val inertiaFactor = when (inertia) {
            ThermalInertia.LIGHT -> 0.60
            ThermalInertia.MEDIUM -> 1.00
            ThermalInertia.HEAVY -> 1.45
        }
        val sizeFactor = sqrt(surfaceM2.coerceAtLeast(20.0) / 70.0).coerceIn(0.70, 1.70)
        return (0.022 * inertiaFactor / sizeFactor).coerceIn(0.010, 0.050)
    }

    /** Amplifie ou amortit la charge saisonnière calculée autour de J-30. */
    fun seasonalTrendGain(): Double {
        val inertiaFactor = when (inertia) {
            ThermalInertia.LIGHT -> 0.42
            ThermalInertia.MEDIUM -> 0.72
            ThermalInertia.HEAVY -> 1.05
        }
        val exchange = insulationExchangeFactor().coerceIn(0.65, 1.45)
        return (inertiaFactor * (0.82 + 0.18 * exchange)).coerceIn(0.25, 1.25)
    }

    fun summary(): String = buildString {
        append("${surfaceM2.toInt()} m² · étage $floor · isolation ${insulation.uppercase()} · inertie ${inertia.label.lowercase()}")
        append(" · exposition ${exposure.label.lowercase()}")
        if (initialMassOverrideC == null) append(" · état initial auto")
        else append(" · état initial ${String.format(java.util.Locale.FRANCE, "%.1f", initialMassOverrideC)} °C")
    }
}

class ThermalProfileStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_thermal_profile", Context.MODE_PRIVATE)

    fun load(): ThermalBuildingProfile = ThermalBuildingProfile(
        surfaceM2 = java.lang.Double.longBitsToDouble(
            prefs.getLong("surface_bits", java.lang.Double.doubleToRawLongBits(70.0))
        ),
        floor = prefs.getInt("floor", 4),
        insulation = prefs.getString("insulation", "D") ?: "D",
        inertia = runCatching { ThermalInertia.valueOf(prefs.getString("inertia", ThermalInertia.MEDIUM.name)!!) }
            .getOrDefault(ThermalInertia.MEDIUM),
        exposure = runCatching { ThermalExposure.valueOf(prefs.getString("exposure", ThermalExposure.MEDIUM.name)!!) }
            .getOrDefault(ThermalExposure.MEDIUM),
        initialMassOverrideC = if (prefs.getBoolean("initial_override_enabled", false)) {
            java.lang.Double.longBitsToDouble(
                prefs.getLong("initial_override_bits", java.lang.Double.doubleToRawLongBits(22.0))
            )
        } else null
    ).normalized()

    fun save(raw: ThermalBuildingProfile) {
        val p = raw.normalized()
        prefs.edit()
            .putLong("surface_bits", java.lang.Double.doubleToRawLongBits(p.surfaceM2))
            .putInt("floor", p.floor)
            .putString("insulation", p.insulation)
            .putString("inertia", p.inertia.name)
            .putString("exposure", p.exposure.name)
            .putBoolean("initial_override_enabled", p.initialMassOverrideC != null)
            .apply {
                if (p.initialMassOverrideC != null) {
                    putLong("initial_override_bits", java.lang.Double.doubleToRawLongBits(p.initialMassOverrideC))
                }
            }
            .apply()
    }

    fun reset(): ThermalBuildingProfile = ThermalBuildingProfile().also(::save)
}
'''
write(profile_path, profile)
print("ThermalProfile: profil bâtiment créé")


# -----------------------------------------------------------------------------
# 2) Thermal engine: keep learned fast RC, add a slow thermal-mass state.
#    Also validate free multi-hour propagation to detect drift before backcasting.
# -----------------------------------------------------------------------------
engine_path = "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
engine = read(engine_path)

old_model = '''data class ThermalModel(
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
}'''
new_model = '''data class ThermalModel(
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
    val longHorizonRmse: Double,
    val confidence: Double,
    val tauHours: Double
) {
    val acceptable: Boolean
        get() = realDays >= MIN_REAL_DAYS && usablePoints >= 120 && metrics.rmse <= 2.0 && metrics.mae <= 1.5 &&
            longHorizonRmse <= 2.5 && confidence >= 0.35
}'''
if old_model in engine:
    engine = engine.replace(old_model, new_model, 1)
elif "longHorizonRmse" not in engine:
    raise SystemExit("ThermalEngine: bloc ThermalModel introuvable")

engine = engine.replace(
    "fun status(reference: WeatherReference, selectedSensorId: Long? = null): ThermalStatus {",
    "fun status(reference: WeatherReference, selectedSensorId: Long? = null, profile: ThermalBuildingProfile = ThermalBuildingProfile()): ThermalStatus {",
    1,
)
engine = engine.replace(
    "val model = if (days >= MIN_REAL_DAYS) runCatching { calibrate(sensor, reference) }.getOrNull() else null",
    "val model = if (days >= MIN_REAL_DAYS) runCatching { calibrate(sensor, reference, profile) }.getOrNull() else null",
    1,
)
engine = engine.replace(
    "fun calibrate(sensor: Sensor, reference: WeatherReference): ThermalModel {",
    "fun calibrate(sensor: Sensor, reference: WeatherReference, profile: ThermalBuildingProfile = ThermalBuildingProfile()): ThermalModel {",
    1,
)

old_cal = '''            val metrics = validate(coeff, valid)
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
            if (best == null || model.metrics.rmse < best.metrics.rmse) best = model'''
new_cal = '''            val metrics = validate(coeff, valid)
            val driftRmse = validateLongHorizon(coeff, valid, profile)
            val exchange = coeff[0] + coeff[1]
            if (!exchange.isFinite() || exchange <= 0.002 || exchange >= 0.65) continue
            val tau = (1.0 / exchange).coerceIn(1.0, 500.0)
            val dataFactor = min(1.0, realDays / 35.0) * min(1.0, rows.size / 500.0)
            val errorFactor = (1.0 - metrics.rmse / 2.8).coerceIn(0.0, 1.0)
            val biasFactor = (1.0 - abs(metrics.bias) / 1.3).coerceIn(0.0, 1.0)
            val driftFactor = (1.0 - driftRmse / 3.2).coerceIn(0.0, 1.0)
            val confidence = (0.12 + 0.40 * errorFactor + 0.16 * biasFactor + 0.17 * dataFactor + 0.15 * driftFactor).coerceIn(0.0, 1.0)
            val model = ThermalModel(
                sensor.id, sensor.name, sensor.room, reference.key, reference.stationId, reference.city,
                lag, coeff, train.first().timestamp, train.last().timestamp, rows.size, realDays,
                metrics, driftRmse, confidence, tau
            )
            if (best == null || (model.metrics.rmse + 0.35 * model.longHorizonRmse) <
                (best!!.metrics.rmse + 0.35 * best!!.longHorizonRmse)) best = model'''
if old_cal in engine:
    engine = engine.replace(old_cal, new_cal, 1)
elif "validateLongHorizon(coeff" not in engine:
    raise SystemExit("ThermalEngine: bloc calibration introuvable")

# Reconstruction signature and calls.
engine = engine.replace(
    '''    fun reconstructHistory(
        reference: WeatherReference,
        requestedDays: Int,
        sensorId: Long? = null
    ): ThermalWriteSummary {''',
    '''    fun reconstructHistory(
        reference: WeatherReference,
        requestedDays: Int,
        sensorId: Long? = null,
        profile: ThermalBuildingProfile = ThermalBuildingProfile()
    ): ThermalWriteSummary {''',
    1,
)
engine = engine.replace("val model = runCatching { calibrate(sensor, reference) }.getOrNull()", "val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()", 1)
engine = engine.replace(
    "val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap)",
    "val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap, profile)",
    1,
)
engine = engine.replace(
    "val gaps = fillInteriorGapsForward(sensor, model, reference)",
    "val gaps = fillInteriorGapsForward(sensor, model, reference, profile)",
    1,
)

# Forecast signature and calibration call.
engine = engine.replace(
    "fun refreshForecasts(reference: WeatherReference, sensorId: Long? = null): ThermalWriteSummary {",
    "fun refreshForecasts(reference: WeatherReference, sensorId: Long? = null, profile: ThermalBuildingProfile = ThermalBuildingProfile()): ThermalWriteSummary {",
    1,
)
# There is a second calibrate call inside forecasts after the first reconstructed call replacement.
engine = engine.replace("val model = runCatching { calibrate(sensor, reference) }.getOrNull()", "val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()", 1)

# Replace the forecast propagation block with mass-aware propagation.
old_forecast_seed = '''            var currentT = latest.temperature
            var currentH = latest.humidity
            for (horizon in 1..6) {'''
new_forecast_seed = '''            var currentT = latest.temperature
            var currentH = latest.humidity
            var currentMass = estimateCurrentMass(profile, measured, outMap)
            for (horizon in 1..6) {'''
engine = engine.replace(old_forecast_seed, new_forecast_seed, 1)
old_forecast_delta = '''                val modelDelta = predictDelta(model.coefficients, currentT, tout, avg6, hour)
                val momentum = (recentSlope + 0.45 * curvature) * exp(-(horizon - 1).toDouble() / 1.7)
                val delta = (modelDelta + 0.30 * momentum).coerceIn(-1.2, 1.2)
                currentT += delta
                currentH += 0.08 * (outHum - currentH)'''
new_forecast_delta = '''                val modelDelta = massAwareDelta(model.coefficients, currentT, currentMass, tout, avg6, hour, profile)
                val momentum = (recentSlope + 0.45 * curvature) * exp(-(horizon - 1).toDouble() / 1.7)
                val delta = (modelDelta + 0.30 * momentum).coerceIn(-1.2, 1.2)
                val nextMass = advanceMass(profile, currentT, currentMass, avg6)
                currentT += delta
                currentMass = nextMass
                currentH += 0.08 * (outHum - currentH)'''
if old_forecast_delta in engine:
    engine = engine.replace(old_forecast_delta, new_forecast_delta, 1)

new_before = r'''    private fun reconstructBeforeFirst(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        first: HourPoint,
        startAt: Long,
        outside: Map<Long, HourPoint>,
        profile: ThermalBuildingProfile
    ): ForwardFillSummary {
        val start = hourBucket(startAt)
        val firstHour = hourBucket(first.timestamp)
        if (start >= firstHour) return ForwardFillSummary(diagnostic = "Période historique vide.")

        val initial = estimateInitialStateForward(model, first, start, firstHour, outside, profile)
            ?: return ForwardFillSummary(diagnostic = "Impossible d'initialiser un état air/masse thermique plausible avec ${reference.city}.")

        var current = initial.first
        var currentH = initial.second
        var currentMass = initial.third
        var created = 0
        var ts = start

        while (ts < firstHour) {
            val horizonDays = (first.timestamp - ts).toDouble() / THERMAL_DAY_MS.toDouble()
            val confidence = (model.confidence * (1.0 - 0.0065 * horizonDays)).coerceIn(0.20, model.confidence)
            val write = PointSourceStore.upsertByPriority(
                db, sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
            )
            if (write == PriorityWriteResult.INSERTED || write == PriorityWriteResult.REPLACED) created++

            val extTs = ts - model.lagHours * THERMAL_HOUR_MS
            val ext = outsideAt(outside, extTs)
                ?: return ForwardFillSummary(created, 0, 0.0, "Propagation arrêtée : météo extérieure absente vers ${Instant.ofEpochMilli(ts).atZone(zone).toLocalDateTime()}.")
            val extAvg6 = outsideAverage(outside, extTs, 6) ?: ext
            val stepHour = Instant.ofEpochMilli(ts).atZone(zone).hour
            val delta = massAwareDelta(model.coefficients, current, currentMass, ext, extAvg6, stepHour, profile)
                .coerceIn(-1.2, 1.2)
            val next = current + delta
            if (!plausibleIndoor(next)) {
                return ForwardFillSummary(created, 0, 0.0, "Propagation arrêtée avant dérive physique abusive (${round2(next)} °C).")
            }
            val nextMass = advanceMass(profile, current, currentMass, extAvg6)
            val outHum = outside[hourBucket(ts)]?.humidity ?: currentH
            currentH += 0.08 * (outHum - currentH)
            current = next
            currentMass = nextMass
            ts += THERMAL_HOUR_MS
        }

        val drift = abs(current - first.temperature)
        return ForwardFillSummary(
            created, 1, drift,
            "État masse initiale ${round2(initial.third)} °C · ${profile.summary()}"
        )
    }

    private fun estimateInitialStateForward(
        model: ThermalModel,
        first: HourPoint,
        start: Long,
        firstHour: Long,
        outside: Map<Long, HourPoint>,
        profile: ThermalBuildingProfile
    ): Triple<Double, Double, Double>? {
        val initialMass = initialMassTemperature(profile, start, firstHour, outside) ?: return null
        val low = (initialMass - 7.0).coerceAtLeast(5.0)
        val high = (initialMass + 7.0).coerceAtMost(42.0)
        var candidate = low
        var bestStart: Double? = null
        var bestError = Double.POSITIVE_INFINITY

        while (candidate <= high + 1e-9) {
            var current = candidate
            var mass = initialMass
            var ts = start
            var valid = true
            while (ts < firstHour) {
                val extTs = ts - model.lagHours * THERMAL_HOUR_MS
                val ext = outsideAt(outside, extTs)
                if (ext == null) {
                    valid = false
                    break
                }
                val avg6 = outsideAverage(outside, extTs, 6) ?: ext
                val hour = Instant.ofEpochMilli(ts).atZone(zone).hour
                val delta = massAwareDelta(model.coefficients, current, mass, ext, avg6, hour, profile)
                    .coerceIn(-1.2, 1.2)
                val next = current + delta
                if (!plausibleIndoor(next)) {
                    valid = false
                    break
                }
                val nextMass = advanceMass(profile, current, mass, avg6)
                current = next
                mass = nextMass
                ts += THERMAL_HOUR_MS
            }
            if (valid && ts >= firstHour) {
                // Le premier vrai point juge le départ, mais une petite pénalité évite
                // de choisir une température d'air initiale artificiellement éloignée de la masse.
                val error = abs(current - first.temperature) + 0.035 * abs(candidate - initialMass)
                if (error < bestError) {
                    bestError = error
                    bestStart = candidate
                }
            }
            candidate += 0.25
        }

        val startTemp = bestStart ?: return null
        val startHumidity = outside[hourBucket(start)]?.humidity ?: first.humidity
        return Triple(startTemp, startHumidity, initialMass)
    }
'''
pattern_before = re.compile(
    r'''    private fun reconstructBeforeFirst\(.*?\n    \}\n\n    private fun fillInteriorGapsForward\(''',
    re.S,
)
match = pattern_before.search(engine)
if not match:
    raise SystemExit("ThermalEngine: reconstructBeforeFirst introuvable")
engine = engine[:match.start()] + new_before + "\n    private fun fillInteriorGapsForward(" + engine[match.end():]

new_gaps = r'''    private fun fillInteriorGapsForward(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        profile: ThermalBuildingProfile
    ): ForwardFillSummary {
        val measured = measuredHourly(sensor.id)
        if (measured.size < 2) return ForwardFillSummary()
        val out = referenceHourly(
            reference.key,
            measured.first().timestamp - 18L * THERMAL_HOUR_MS,
            measured.last().timestamp,
            false
        )
        val outMap = out.associateBy { hourBucket(it.timestamp) }
        var created = 0
        var raccords = 0
        var maxDrift = 0.0

        measured.zipWithNext().forEach { (left, right) ->
            val gapHours = ((right.timestamp - left.timestamp) / THERMAL_HOUR_MS).toInt()
            if (gapHours !in 2..(14 * 24)) return@forEach
            var current = left.temperature
            var currentH = left.humidity
            var currentMass = left.temperature
            var completed = true

            for (step in 1 until gapHours) {
                val previousTs = hourBucket(left.timestamp) + (step - 1) * THERMAL_HOUR_MS
                val ts = previousTs + THERMAL_HOUR_MS
                val extTs = previousTs - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs)
                if (tout == null) {
                    completed = false
                    break
                }
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
                val hour = Instant.ofEpochMilli(previousTs).atZone(zone).hour
                val delta = massAwareDelta(model.coefficients, current, currentMass, tout, avg6, hour, profile)
                    .coerceIn(-1.2, 1.2)
                val predicted = current + delta
                if (!plausibleIndoor(predicted)) { completed = false; break }
                val nextMass = advanceMass(profile, current, currentMass, avg6)
                current = predicted
                currentMass = nextMass
                val outHum = outMap[hourBucket(ts)]?.humidity ?: currentH
                currentH += 0.08 * (outHum - currentH)
                val confidence = (model.confidence * 0.82).coerceIn(0.20, 0.85)
                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) created++
            }

            if (completed) {
                val previousTs = hourBucket(right.timestamp) - THERMAL_HOUR_MS
                val extTs = previousTs - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs)
                val avg6 = if (tout != null) outsideAverage(outMap, extTs, 6) ?: tout else null
                if (tout != null && avg6 != null) {
                    val hour = Instant.ofEpochMilli(previousTs).atZone(zone).hour
                    val projectedAtRight = current + massAwareDelta(
                        model.coefficients, current, currentMass, tout, avg6, hour, profile
                    ).coerceIn(-1.2, 1.2)
                    if (plausibleIndoor(projectedAtRight)) {
                        raccords++
                        maxDrift = max(maxDrift, abs(projectedAtRight - right.temperature))
                    }
                }
            }
        }
        return ForwardFillSummary(created, raccords, maxDrift)
    }
'''
pattern_gaps = re.compile(
    r'''    private fun fillInteriorGapsForward\(.*?\n    \}\n\n    private fun equilibriumTemperature\(''',
    re.S,
)
match = pattern_gaps.search(engine)
if not match:
    raise SystemExit("ThermalEngine: fillInteriorGapsForward introuvable")
engine = engine[:match.start()] + new_gaps + "\n    private fun equilibriumTemperature(" + engine[match.end():]

helpers = r'''    private fun validateLongHorizon(
        coeff: DoubleArray,
        rows: List<TrainingRow>,
        profile: ThermalBuildingProfile
    ): Double {
        if (rows.size < 12) return 99.0
        val selected = rows.takeLast(120)
        var current = selected.first().tin
        var mass = current
        var previousTimestamp = selected.first().timestamp - THERMAL_HOUR_MS
        val errors = mutableListOf<Double>()

        selected.forEach { row ->
            val contiguous = row.timestamp - previousTimestamp in
                (45L * 60L * 1000L)..(90L * 60L * 1000L)
            if (!contiguous) {
                current = row.tin
                mass = row.tin
            }
            val delta = massAwareDelta(coeff, current, mass, row.tout, row.toutAvg6, row.hourOfDay, profile)
                .coerceIn(-1.2, 1.2)
            val predicted = current + delta
            if (!plausibleIndoor(predicted)) return 99.0
            errors += predicted - row.nextTin
            val nextMass = advanceMass(profile, current, mass, row.toutAvg6)
            current = predicted
            mass = nextMass
            previousTimestamp = row.timestamp
        }
        return sqrt(errors.map { it * it }.average())
    }

    /**
     * Etat lent du bâtiment. Priorité au réglage manuel ; sinon température moyenne de J-30
     * lorsqu'elle existe, corrigée par la tendance saisonnière. Si J-30 exact n'existe pas,
     * FabData utilise la meilleure fenêtre disponible dans la longue référence météo.
     */
    private fun initialMassTemperature(
        profile: ThermalBuildingProfile,
        start: Long,
        firstRealHour: Long,
        outside: Map<Long, HourPoint>
    ): Double? {
        profile.initialMassOverrideC?.let { return it.coerceIn(5.0, 40.0) }
        if (outside.isEmpty()) return null

        fun meanBetween(from: Long, to: Long): Double? {
            val values = outside.values.asSequence()
                .filter { it.timestamp in from..to }
                .map { it.temperature }
                .toList()
            return values.takeIf { it.size >= 6 }?.average()
        }

        val day = THERMAL_DAY_MS
        val preferredAnchor = start - 30L * day
        val fallbackAnchor = firstRealHour - 30L * day
        val anchor = when {
            meanBetween(preferredAnchor, preferredAnchor + day) != null -> preferredAnchor
            meanBetween(fallbackAnchor, fallbackAnchor + day) != null -> fallbackAnchor
            else -> start
        }
        val base = meanBetween(anchor, anchor + day)
            ?: meanBetween(start, start + 2L * day)
            ?: outside.values.minByOrNull { abs(it.timestamp - start) }?.temperature
            ?: return null

        val before7 = meanBetween(anchor - 7L * day, anchor - THERMAL_HOUR_MS)
        val after7 = meanBetween(anchor + day, anchor + 8L * day)
        val trend = when {
            before7 != null && after7 != null -> (after7 - before7).coerceIn(-7.0, 7.0)
            else -> {
                val first7 = meanBetween(start, start + 7L * day)
                val next7 = meanBetween(start + 7L * day, start + 14L * day)
                if (first7 != null && next7 != null) (next7 - first7).coerceIn(-7.0, 7.0) else 0.0
            }
        }
        return (base + trend * profile.seasonalTrendGain()).coerceIn(5.0, 40.0)
    }

    private fun advanceMass(
        profile: ThermalBuildingProfile,
        indoor: Double,
        mass: Double,
        outsideAvg: Double
    ): Double {
        val w = profile.massOutdoorWeight()
        val target = indoor * (1.0 - w) + outsideAvg * w
        return mass + (target - mass) / profile.massTauHours()
    }

    private fun massAwareDelta(
        coeff: DoubleArray,
        indoor: Double,
        mass: Double,
        outside: Double,
        outsideAvg6: Double,
        hour: Int,
        profile: ThermalBuildingProfile
    ): Double {
        val learned = predictDelta(coeff, indoor, outside, outsideAvg6, hour)
        val slowMemory = profile.massCoupling() * (mass - indoor)
        return learned + slowMemory
    }

    private fun estimateCurrentMass(
        profile: ThermalBuildingProfile,
        measured: List<HourPoint>,
        outside: Map<Long, HourPoint>
    ): Double {
        val recent = measured.takeLast(7 * 24).ifEmpty { measured }
        var mass = recent.firstOrNull()?.temperature ?: return 22.0
        recent.forEach { p ->
            val out = outsideAt(outside, p.timestamp) ?: return@forEach
            val avg6 = outsideAverage(outside, p.timestamp, 6) ?: out
            mass = advanceMass(profile, p.temperature, mass, avg6)
        }
        return mass
    }

'''
marker = "    private fun equilibriumTemperature("
if helpers.strip() not in engine:
    idx = engine.find(marker)
    if idx < 0:
        raise SystemExit("ThermalEngine: marker equilibrium introuvable")
    engine = engine[:idx] + helpers + engine[idx:]

write(engine_path, engine)
print("ThermalEngine: masse thermique lente + validation de dérive appliquées")


# -----------------------------------------------------------------------------
# 3) UI: editable physical profile. Defaults requested: floor 4, insulation D.
# -----------------------------------------------------------------------------
ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)

for imp, after in [
    ("import androidx.compose.material3.FilterChip\n", "import androidx.compose.material3.DropdownMenuItem\n"),
    ("import androidx.compose.material3.OutlinedTextField\n", "import androidx.compose.material3.OutlinedButton\n"),
    ("import androidx.compose.foundation.text.KeyboardOptions\n", "import androidx.compose.foundation.shape.RoundedCornerShape\n"),
    ("import androidx.compose.ui.text.input.KeyboardType\n", "import androidx.compose.ui.text.font.FontWeight\n"),
]:
    if imp.strip() not in ui:
        ui = ui.replace(after, after + imp, 1)

ui = ui.replace(
    '''    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val scope = rememberCoroutineScope()''',
    '''    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val profileStore = remember { ThermalProfileStore(context) }
    var profile by remember { mutableStateOf(profileStore.load()) }
    val scope = rememberCoroutineScope()''',
    1,
)
ui = ui.replace(
    "    var selectedSensorId by remember { mutableStateOf<Long?>(null) }",
    "    var selectedSensorId by remember { mutableStateOf<Long?>(null) }\n    var profileDialog by remember { mutableStateOf(false) }",
    1,
)
ui = ui.replace("val thermalStatus = engine.status(reference, selectedSensorId)", "val thermalStatus = engine.status(reference, selectedSensorId, profile)")
ui = ui.replace(
    "engine.refreshForecasts(reference, selectedSensorId ?: thermalStatus.preferred?.sensor?.id)",
    "engine.refreshForecasts(reference, selectedSensorId ?: thermalStatus.preferred?.sensor?.id, profile)",
)
ui = ui.replace(
    "LaunchedEffect(dataVersion, selectedKey, selectedSensorId) {",
    "LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile) {",
    1,
)

# Add long-horizon metric chip.
chip_marker = 'AssistChip(onClick = {}, label = { Text("RMSE ${fmt(model.metrics.rmse)} °C") })'
if "Dérive libre" not in ui:
    ui = ui.replace(
        chip_marker,
        chip_marker + '\n                        AssistChip(onClick = {}, label = { Text("Dérive libre ${fmt(model.longHorizonRmse)} °C") })',
        1,
    )

# Add profile summary/button before weather-history button.
weather_button = '''            OutlinedButton(
                onClick = { weatherHistoryDialog = true },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Étendre historique météo") }'''
profile_block = '''            Card(shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Profil thermique du bâtiment", fontWeight = FontWeight.SemiBold)
                    Text(profile.summary(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(
                        "L'état initial Auto part de la météo autour de J-30 puis applique la tendance chaude/froide. Les mesures réelles restent toujours prioritaires.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    OutlinedButton(onClick = { profileDialog = true }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                        Text("Ajuster le profil")
                    }
                }
            }

''' + weather_button
if "Ajuster le profil" not in ui:
    if weather_button not in ui:
        raise SystemExit("ThermalUi: bouton météo introuvable")
    ui = ui.replace(weather_button, profile_block, 1)

# Pass profile to reconstruction-time validation and reconstruction.
ui = ui.replace("val checked = engine.status(reference, selectedSensorId)", "val checked = engine.status(reference, selectedSensorId, profile)")
ui = ui.replace(
    "engine.reconstructHistory(reference, historyDays, selectedSensorId ?: checked.preferred?.sensor?.id)",
    "engine.reconstructHistory(reference, historyDays, selectedSensorId ?: checked.preferred?.sensor?.id, profile)",
)

# Insert profile dialog before history/weather dialogs.
insert_marker = "    if (weatherHistoryDialog) {"
profile_dialog_call = '''    if (profileDialog) {
        ThermalProfileDialog(
            profile = profile,
            onDismiss = { profileDialog = false },
            onSave = { updated ->
                profile = updated.normalized()
                profileStore.save(profile)
                profileDialog = false
            },
            onReset = {
                profile = profileStore.reset()
                profileDialog = false
            }
        )
    }

'''
if "ThermalProfileDialog(" not in ui.split(insert_marker)[0]:
    ui = ui.replace(insert_marker, profile_dialog_call + insert_marker, 1)

# Append dialog composable before fmt.
fmt_marker = 'private fun fmt(v: Double): String = String.format(Locale.FRANCE, "%.2f", v)'
profile_dialog = r'''@Composable
private fun ThermalProfileDialog(
    profile: ThermalBuildingProfile,
    onDismiss: () -> Unit,
    onSave: (ThermalBuildingProfile) -> Unit,
    onReset: () -> Unit
) {
    var surface by remember(profile) { mutableStateOf(profile.surfaceM2.toString()) }
    var floor by remember(profile) { mutableStateOf(profile.floor.toString()) }
    var insulation by remember(profile) { mutableStateOf(profile.insulation) }
    var inertia by remember(profile) { mutableStateOf(profile.inertia) }
    var exposure by remember(profile) { mutableStateOf(profile.exposure) }
    var initialOverride by remember(profile) { mutableStateOf(profile.initialMassOverrideC?.toString().orEmpty()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Profil thermique du bâtiment") },
        text = {
            Column(
                Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                OutlinedTextField(
                    value = surface,
                    onValueChange = { surface = it },
                    label = { Text("Surface (m²)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = floor,
                    onValueChange = { floor = it },
                    label = { Text("Étage") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )

                Text("Isolation thermique", style = MaterialTheme.typography.labelMedium)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    listOf("A", "B", "C", "D", "E", "F", "G").forEach { rating ->
                        FilterChip(
                            selected = insulation == rating,
                            onClick = { insulation = rating },
                            label = { Text(rating) }
                        )
                    }
                }

                Text("Inertie du bâtiment", style = MaterialTheme.typography.labelMedium)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    ThermalInertia.entries.forEach { value ->
                        FilterChip(
                            selected = inertia == value,
                            onClick = { inertia = value },
                            label = { Text(value.label) }
                        )
                    }
                }

                Text("Exposition / accumulation solaire", style = MaterialTheme.typography.labelMedium)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    ThermalExposure.entries.forEach { value ->
                        FilterChip(
                            selected = exposure == value,
                            onClick = { exposure = value },
                            label = { Text(value.label) }
                        )
                    }
                }

                OutlinedTextField(
                    value = initialOverride,
                    onValueChange = { initialOverride = it },
                    label = { Text("État thermique initial °C (vide = Auto)") },
                    supportingText = { Text("Auto : météo J-30 + tendance saisonnière chaude/froide") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth()
                )
                Text(
                    "Valeurs par défaut : 70 m² · 4e étage · isolation D · inertie moyenne · exposition moyenne.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            Button(onClick = {
                val s = surface.replace(',', '.').toDoubleOrNull() ?: profile.surfaceM2
                val f = floor.toIntOrNull() ?: profile.floor
                val initial = initialOverride.trim().replace(',', '.').toDoubleOrNull()
                onSave(
                    ThermalBuildingProfile(
                        surfaceM2 = s,
                        floor = f,
                        insulation = insulation,
                        inertia = inertia,
                        exposure = exposure,
                        initialMassOverrideC = initial
                    )
                )
            }) { Text("Enregistrer") }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = onReset) { Text("Défaut") }
                TextButton(onClick = onDismiss) { Text("Annuler") }
            }
        }
    )
}

'''
if "private fun ThermalProfileDialog(" not in ui:
    if fmt_marker not in ui:
        raise SystemExit("ThermalUi: fmt marker introuvable")
    ui = ui.replace(fmt_marker, profile_dialog + fmt_marker, 1)

write(ui_path, ui)
print("ThermalUi: profil bâtiment éditable ajouté")


# -----------------------------------------------------------------------------
# 4) Provenance model version + app version.
# -----------------------------------------------------------------------------
source_path = "app/src/main/java/com/fabdata/app/PointSourceLayer.kt"
source = read(source_path)
source = source.replace('const val MODEL_VERSION = "thermal-rc-1"', 'const val MODEL_VERSION = "thermal-rc-mass-2"')
write(source_path, source)

gradle_path = "app/build.gradle.kts"
gradle = read(gradle_path)
gradle = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 23', gradle, count=1)
gradle = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.11.0"', gradle, count=1)
write(gradle_path, gradle)
print("Version: 0.11.0 / code 23")
