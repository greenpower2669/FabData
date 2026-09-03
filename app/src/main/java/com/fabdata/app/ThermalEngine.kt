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
private const val MIN_REAL_DAYS = 16
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
    val longHorizonRmse: Double,
    val confidence: Double,
    val tauHours: Double
) {
    /**
     * Confiance historique compatible v0.11 : la dérive libre ne doit jamais
     * empêcher de reconstruire le passé lorsqu'un modèle court terme était valide.
     */
    val historyConfidence: Double
        get() {
            val dataFactor = min(1.0, realDays / 35.0) * min(1.0, usablePoints / 500.0)
            val errorFactor = (1.0 - metrics.rmse / 2.8).coerceIn(0.0, 1.0)
            val biasFactor = (1.0 - abs(metrics.bias) / 1.3).coerceIn(0.0, 1.0)
            return (0.15 + 0.50 * errorFactor + 0.20 * biasFactor + 0.15 * dataFactor).coerceIn(0.0, 1.0)
        }

    val acceptableForHistory: Boolean
        get() = realDays >= MIN_REAL_DAYS && usablePoints >= 120 &&
            metrics.rmse <= 2.0 && metrics.mae <= 1.5 && historyConfidence >= 0.35

    val acceptableForForecast: Boolean
        get() = acceptableForHistory && longHorizonRmse <= 2.5 && confidence >= 0.35

    // Compatibilité interne : tout ancien appel restant doit être prudent et viser le futur.
    val acceptable: Boolean get() = acceptableForForecast
}

data class ThermalSensorStatus(
    val sensor: Sensor,
    val realDays: Int,
    val model: ThermalModel?,
    val measuredHours: Int = 0,
    val ignoredHours: Int = 0
) {
    val retainedRatio: Double
        get() {
            val transitions = (measuredHours - 1).coerceAtLeast(1)
            return ((transitions - ignoredHours).coerceAtLeast(0)).toDouble() / transitions.toDouble()
        }
}

data class ThermalStatus(
    val reference: WeatherReference,
    val sensors: List<ThermalSensorStatus>,
    val preferred: ThermalSensorStatus?,
    val message: String
) {
    // Le tourniquet pilote réellement la sonde active : si elle ne passe pas les garde-fous,
    // la reconstruction reste désactivée même si une autre sonde serait acceptable.
    val canReconstruct: Boolean get() = preferred?.model?.acceptableForHistory == true
    val canForecast: Boolean get() = preferred?.model?.acceptableForForecast == true
}

data class ThermalWriteSummary(
    val reconstructed: Int,
    val forecast: Int,
    val skippedSensors: Int,
    val raccords: Int = 0,
    val maxRaccordDrift: Double = 0.0,
    val diagnostic: String? = null,
    val forecastHorizonHours: Int = 0,
    val maxForecastSigma: Double = 0.0,
    val analogCount: Int = 0
)

data class ThermalProgress(
    val stage: String,
    val processed: Int = 0,
    val total: Int = 0,
    val changed: Int = 0
)

private data class ForwardFillSummary(
    val created: Int = 0,
    val raccords: Int = 0,
    val maxDrift: Double = 0.0,
    val diagnostic: String? = null
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

private data class ForecastAnalogStats(
    val meanDelta: Double? = null,
    val sigma: Double? = null,
    val count: Int = 0
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

    fun status(reference: WeatherReference, selectedSensorId: Long? = null, profile: ThermalBuildingProfile = ThermalBuildingProfile()): ThermalStatus {
        val candidates = physicalSensors().map { sensor ->
            val real = measuredHourly(sensor.id)
            val days = distinctDays(real)
            val model = if (days >= MIN_REAL_DAYS) runCatching { calibrate(sensor, reference, profile) }.getOrNull() else null
            val transitions = (real.size - 1).coerceAtLeast(0)
            val usable = model?.usablePoints?.coerceAtMost(transitions) ?: 0
            ThermalSensorStatus(
                sensor = sensor,
                realDays = days,
                model = model,
                measuredHours = real.size,
                ignoredHours = (transitions - usable).coerceAtLeast(0)
            )
        }
        // Par défaut : la courbe qui garde le plus de données après filtrage des perturbations.
        // Salle de bain / chambre sud-est ne servent plus que de départage en cas d'égalité.
        val automatic = candidates
            .filter { it.model?.acceptableForHistory == true }
            .sortedWith(
                compareByDescending<ThermalSensorStatus> { it.retainedRatio }
                    .thenByDescending { it.realDays }
                    .thenBy { preferenceRank(it.sensor.room) }
            )
            .firstOrNull()
            ?: candidates.sortedWith(
                compareByDescending<ThermalSensorStatus> { it.realDays }
                    .thenBy { preferenceRank(it.sensor.room) }
            ).firstOrNull()
        val preferred = candidates.firstOrNull { it.sensor.id == selectedSensorId } ?: automatic
        val enough = candidates.any { it.realDays >= MIN_REAL_DAYS }
        val message = if (!enough) {
            "FabData ne dispose pas encore d'au moins 16 jours de mesures réelles exploitables. Il est préférable d'attendre davantage de données plutôt que de produire une reconstruction incertaine."
        } else if (candidates.none { it.model?.acceptableForHistory == true }) {
            "Les données sont assez longues, mais la validation rétrospective n'est pas encore assez bonne pour autoriser une reconstruction fiable."
        } else {
            "Modèle thermique RC validé. FabData utilise toutes les données réelles propres disponibles au-delà du minimum de 16 jours."
        }
        return ThermalStatus(reference, candidates, preferred, message)
    }

    fun calibrate(
        sensor: Sensor,
        reference: WeatherReference,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        preferLongHorizon: Boolean = false
    ): ThermalModel {
        val measured = measuredHourly(sensor.id)
        val realDays = distinctDays(measured)
        require(realDays >= MIN_REAL_DAYS) { "Moins de 16 jours réels exploitables" }
        require(measured.size >= 180) { "Pas assez de points horaires réels" }

        val from = measured.first().timestamp - 18L * THERMAL_HOUR_MS
        val to = measured.last().timestamp
        val outside = referenceHourly(reference.key, from, to, includeForecast = false)
        require(outside.size >= 120) { "Référence météo extérieure insuffisante" }
        require(referenceCoverageReady(outside, from, to)) {
            "Référence météo extérieure incomplète : reconstruire/compléter ${reference.city} avant de calibrer le bâtiment"
        }
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
            val better = if (best == null) {
                true
            } else if (preferLongHorizon) {
                (model.metrics.rmse + 0.35 * model.longHorizonRmse) <
                    (best!!.metrics.rmse + 0.35 * best!!.longHorizonRmse)
            } else {
                // Historique : comportement v0.11, meilleur RMSE court terme.
                model.metrics.rmse < best!!.metrics.rmse
            }
            if (better) best = model
        }
        return best ?: error("Aucun modèle RC stable n'a passé la calibration")
    }

    /**
     * Reconstruction consentie, FORWARD depuis le point le plus ancien.
     * Le modèle RC n'est pas inversé. Lyon (réel + reconstruit) pilote la propagation,
     * puis chaque vraie mesure intérieure sert de raccord observable et non de correction cachée.
     */
    fun reconstructHistory(
        reference: WeatherReference,
        requestedDays: Int,
        sensorId: Long? = null,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        precalibratedModel: ThermalModel? = null,
        progress: ((ThermalProgress) -> Unit)? = null
    ): ThermalWriteSummary {
        val days = requestedDays.coerceIn(1, MAX_HISTORY_DAYS)
        var total = 0
        var skipped = 0
        var raccords = 0
        var maxDrift = 0.0
        var diagnostic: String? = null
        PointSourceStore.ensure(db.writableDatabase)
        val targets = physicalSensors().filter { sensorId == null || it.id == sensorId }
        targets.forEach { sensor ->
            progress?.invoke(ThermalProgress("Calibration · ${sensor.room}"))
            val model = precalibratedModel?.takeIf {
                it.sensorId == sensor.id && it.referenceKey == reference.key
            } ?: runCatching { calibrate(sensor, reference, profile) }.getOrNull()
            if (model == null || !model.acceptableForHistory) {
                skipped++
                if (diagnostic == null) diagnostic = "Modèle de ${sensor.room} non validé pour la reconstruction."
                return@forEach
            }
            val measured = measuredHourly(sensor.id)
            if (measured.isEmpty()) {
                skipped++
                if (diagnostic == null) diagnostic = "Aucune vraie mesure intérieure disponible."
                return@forEach
            }
            val first = measured.first()
            val refBounds = referenceStore.bounds(reference.key)
            if (refBounds == null) {
                skipped++
                if (diagnostic == null) diagnostic = "Référence ${reference.city} absente : actualiser/reconstruire la référence d'abord."
                return@forEach
            }
            val requestedStart = first.timestamp - days.toLong() * THERMAL_DAY_MS
            val startAt = max(requestedStart, refBounds.first)
            if (startAt >= first.timestamp) {
                skipped++
                if (diagnostic == null) diagnostic = "${reference.city} ne remonte pas avant la première mesure intérieure."
                return@forEach
            }

            val outside = referenceHourly(
                reference.key,
                startAt - 18L * THERMAL_HOUR_MS,
                measured.last().timestamp,
                includeForecast = false
            )
            if (outside.size < 24) {
                skipped++
                if (diagnostic == null) diagnostic = "Référence ${reference.city} insuffisante sur la période demandée."
                return@forEach
            }
            // v0.10.3 : la première heure du RC consomme déjà Tout(t-lag) et sa moyenne 6 h.
            // La couverture doit donc être valide AVANT startAt, pas seulement à partir de startAt.
            val requiredReferenceStart = startAt - (model.lagHours + 5L) * THERMAL_HOUR_MS
            if (!referenceCoverageReady(outside, requiredReferenceStart, first.timestamp)) {
                skipped++
                if (diagnostic == null) diagnostic = "Référence ${reference.city} encore trop trouée avec la marge de retard du modèle."
                return@forEach
            }
            val outMap = outside.associateBy { hourBucket(it.timestamp) }

            progress?.invoke(ThermalProgress("État initial · ${sensor.room}"))
            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap, profile, progress)
            total += before.created
            raccords += before.raccords
            maxDrift = max(maxDrift, before.maxDrift)
            if (diagnostic == null && before.diagnostic != null) diagnostic = before.diagnostic

            val gaps = fillInteriorGapsForward(sensor, model, reference, profile, progress)
            total += gaps.created
            raccords += gaps.raccords
            maxDrift = max(maxDrift, gaps.maxDrift)
            if (diagnostic == null && gaps.diagnostic != null) diagnostic = gaps.diagnostic
        }
        if (diagnostic == null && total == 0) {
            diagnostic = "Aucun trou reconstruisible détecté sur la période choisie."
        }
        return ThermalWriteSummary(total, 0, skipped, raccords, maxDrift, diagnostic)
    }

    /**
     * Une nouvelle vraie mesure invalide déjà les forecasts via PointSourceStore.
     * Si la sonde possédait un historique reconstruit consentie auparavant, on le
     * recalcule avec le modèle enrichi sans toucher aux points MEASURED.
     */
    fun refreshExistingReconstructions(
        reference: WeatherReference,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        sensorId: Long? = null
    ): ThermalWriteSummary {
        var total = 0
        var skipped = 0
        var raccords = 0
        var maxDrift = 0.0
        var diagnostic: String? = null
        physicalSensors().filter { sensorId == null || it.id == sensorId }.forEach { sensor ->
            val existing = PointSourceStore.reconstructedBounds(db, sensor.id) ?: return@forEach
            val measured = measuredHourly(sensor.id)
            val first = measured.firstOrNull() ?: return@forEach
            if (existing.first < first.timestamp) {
                val span = (first.timestamp - existing.first).coerceAtLeast(THERMAL_DAY_MS)
                val days = ((span + THERMAL_DAY_MS - 1L) / THERMAL_DAY_MS).toInt().coerceIn(1, MAX_HISTORY_DAYS)
                val r = reconstructHistory(reference, days, sensor.id, profile)
                total += r.reconstructed
                skipped += r.skippedSensors
                raccords += r.raccords
                maxDrift = max(maxDrift, r.maxRaccordDrift)
                if (diagnostic == null && r.diagnostic != null) diagnostic = r.diagnostic
            } else {
                val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()
                if (model == null || !model.acceptableForHistory) { skipped++; return@forEach }
                val r = fillInteriorGapsForward(sensor, model, reference, profile)
                total += r.created
                raccords += r.raccords
                maxDrift = max(maxDrift, r.maxDrift)
                if (diagnostic == null && r.diagnostic != null) diagnostic = r.diagnostic
            }
        }
        return ThermalWriteSummary(total, 0, skipped, raccords, maxDrift, diagnostic)
    }

    /**
     * Prévision adaptative. La courbe centrale reste RC + masse thermique.
     * L'incertitude combine validation du modèle, météo et dispersion de situations
     * historiques analogues. En Auto, on peut aller jusqu'à H+24 mais on s'arrête
     * dès que sigma dépasse 1,5 °C après les trois premières heures.
     */
    fun refreshForecasts(
        reference: WeatherReference,
        sensorId: Long? = null,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        mode: ForecastHorizonMode = ForecastHorizonMode.AUTO
    ): ThermalWriteSummary {
        var total = 0
        var skipped = 0
        var furthest = 0
        var maxSigma = 0.0
        var bestAnalogCount = 0

        physicalSensors().filter { sensorId == null || it.id == sensorId }.forEach { sensor ->
            val model = runCatching { calibrate(sensor, reference, profile, preferLongHorizon = true) }.getOrNull()
            if (model == null || !model.acceptableForForecast) { skipped++; return@forEach }
            val measured = measuredHourly(sensor.id)
            val latest = measured.lastOrNull() ?: run { skipped++; return@forEach }
            val recent = measured.takeLast(5)
            PointSourceStore.deleteForecastsAtOrAfter(db, sensor.id, latest.timestamp + 1L)

            val from = latest.timestamp - 18L * THERMAL_HOUR_MS
            val to = latest.timestamp + (mode.maxHours + 1L) * THERMAL_HOUR_MS
            val outside = referenceHourly(reference.key, from, to, includeForecast = true)
            val outMap = outside.associateBy { hourBucket(it.timestamp) }
            if (outside.none { it.timestamp > latest.timestamp }) { skipped++; return@forEach }

            val slopes = recent.zipWithNext().mapNotNull { (a, b) ->
                val dt = (b.timestamp - a.timestamp).toDouble() / THERMAL_HOUR_MS.toDouble()
                if (dt <= 0.0 || dt > 2.5) null else (b.temperature - a.temperature) / dt
            }
            val recentSlope = slopes.takeLast(3).averageOrZero()
            val curvature = if (slopes.size >= 2) slopes.last() - slopes[slopes.lastIndex - 1] else 0.0

            var currentT = latest.temperature
            var currentH = latest.humidity
            var currentMass = estimateCurrentMass(profile, measured, outMap)

            for (horizon in 1..mode.maxHours) {
                val ts = hourBucket(latest.timestamp) + horizon * THERMAL_HOUR_MS
                val extTs = ts - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs) ?: break
                val weatherPoint = outMap[hourBucket(ts)]
                val outHum = weatherPoint?.humidity ?: currentH
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
                val hour = Instant.ofEpochMilli(ts - THERMAL_HOUR_MS).atZone(zone).hour

                val modelDelta = massAwareDelta(model.coefficients, currentT, currentMass, tout, avg6, hour, profile)
                val momentum = (recentSlope + 0.45 * curvature) * exp(-(horizon - 1).toDouble() / 1.7)
                val rawNext = currentT + (modelDelta + 0.30 * momentum).coerceIn(-1.2, 1.2)

                val analog = forecastAnalogs(measured, latest, horizon, recentSlope)
                val analogueReliability = (analog.count / 12.0).coerceIn(0.0, 1.0)
                val analogueCoherence = analog.sigma?.let { (1.0 - it / 1.5).coerceIn(0.0, 1.0) } ?: 0.0
                val analogueWeight = 0.28 * analogueReliability * analogueCoherence
                val cumulativeRaw = rawNext - latest.temperature
                val analogueTarget = analog.meanDelta
                val adjustedNext = if (analogueTarget != null) {
                    rawNext + analogueWeight * (analogueTarget - cumulativeRaw)
                } else rawNext
                val delta = (adjustedNext - currentT).coerceIn(-1.2, 1.2)

                val validationSigma =
                    model.metrics.rmse * 0.45 * sqrt(horizon.toDouble()) +
                    model.longHorizonRmse * 0.10 * (horizon.toDouble() / 6.0)
                val historicalSigma = analog.sigma ?: (validationSigma * 1.25)
                val mixedSigma = validationSigma * (1.0 - 0.55 * analogueReliability) +
                    historicalSigma * (0.55 * analogueReliability)
                val weatherConfidence = weatherPoint?.confidence?.coerceIn(0.20, 1.0) ?: 0.65
                val weatherSigma = (1.0 - weatherConfidence) * (0.35 + 0.055 * horizon)
                val sigma = sqrt(mixedSigma * mixedSigma + weatherSigma * weatherSigma).coerceIn(0.08, 3.0)

                // Trois heures minimum pour un modèle validé ; ensuite arrêt honnête si l'incertitude explose.
                if (horizon > 3 && sigma > 1.50) break

                val nextMass = advanceMass(profile, currentT, currentMass, avg6)
                currentT += delta
                currentMass = nextMass
                currentH += 0.08 * (outHum - currentH)
                val confidence = (
                    model.confidence * exp(-sigma / 1.45) * (0.72 + 0.28 * weatherConfidence)
                ).coerceIn(0.08, model.confidence)

                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, ts, round2(currentT), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.FORECAST, confidence, sigma, analog.count)
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) total++
                furthest = max(furthest, horizon)
                maxSigma = max(maxSigma, sigma)
                bestAnalogCount = max(bestAnalogCount, analog.count)
            }
        }
        return ThermalWriteSummary(
            reconstructed = 0,
            forecast = total,
            skippedSensors = skipped,
            forecastHorizonHours = furthest,
            maxForecastSigma = maxSigma,
            analogCount = bestAnalogCount
        )
    }

    private fun forecastAnalogs(
        measured: List<HourPoint>,
        latest: HourPoint,
        horizon: Int,
        currentSlope: Double
    ): ForecastAnalogStats {
        if (measured.size < 24) return ForecastAnalogStats()
        val byHour = measured.associateBy { hourBucket(it.timestamp) }
        val latestBucket = hourBucket(latest.timestamp)
        val latestHour = Instant.ofEpochMilli(latest.timestamp).atZone(zone).hour
        val candidates = mutableListOf<Pair<Double, Double>>()

        measured.forEach { candidate ->
            val ts = hourBucket(candidate.timestamp)
            // Garde une vraie séparation entre l'état actuel et les analogues d'apprentissage.
            if (ts >= latestBucket - (horizon + 12L) * THERMAL_HOUR_MS) return@forEach
            val previous = byHour[ts - THERMAL_HOUR_MS] ?: return@forEach
            val future = byHour[ts + horizon * THERMAL_HOUR_MS] ?: return@forEach
            val candidateSlope = candidate.temperature - previous.temperature
            val candidateHour = Instant.ofEpochMilli(candidate.timestamp).atZone(zone).hour
            val rawHourDiff = abs(candidateHour - latestHour)
            val hourDiff = min(rawHourDiff, 24 - rawHourDiff)

            val score =
                abs(candidate.temperature - latest.temperature) / 1.20 +
                abs(candidateSlope - currentSlope) / 0.45 +
                hourDiff / 6.0
            if (score <= 3.2) candidates += score to (future.temperature - candidate.temperature)
        }

        val chosen = candidates.sortedBy { it.first }.take(16).map { it.second }
        if (chosen.size < 3) return ForecastAnalogStats(count = chosen.size)
        val mean = chosen.average()
        val variance = chosen.sumOf { (it - mean) * (it - mean) } / chosen.size.toDouble()
        return ForecastAnalogStats(mean, sqrt(variance).coerceAtLeast(0.03), chosen.size)
    }

    private fun reconstructBeforeFirst(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        first: HourPoint,
        startAt: Long,
        outside: Map<Long, HourPoint>,
        profile: ThermalBuildingProfile,
        progress: ((ThermalProgress) -> Unit)? = null
    ): ForwardFillSummary {
        val start = hourBucket(startAt)
        val firstHour = hourBucket(first.timestamp)
        if (start >= firstHour) return ForwardFillSummary(diagnostic = "Période historique vide.")

        val initial = estimateInitialStateForward(model, first, start, firstHour, outside, profile)
            ?: return ForwardFillSummary(diagnostic = "Impossible d'initialiser un état air/masse thermique plausible avec ${reference.city}.")

        var current = initial.first
        var currentH = initial.second
        var currentMass = initial.third
        var ts = start
        var stopDiagnostic: String? = null
        val writes = ArrayList<PriorityPointWrite>(((firstHour - start) / THERMAL_HOUR_MS).toInt().coerceAtLeast(0))

        // Calcul pur d'abord : aucune écriture SQLite dans la boucle RC.
        while (ts < firstHour) {
            val horizonDays = (first.timestamp - ts).toDouble() / THERMAL_DAY_MS.toDouble()
            val confidence = (model.confidence * (1.0 - 0.0065 * horizonDays)).coerceIn(0.20, model.confidence)
            writes += PriorityPointWrite(
                sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
            )

            val extTs = ts - model.lagHours * THERMAL_HOUR_MS
            val ext = outsideAt(outside, extTs)
            if (ext == null) {
                stopDiagnostic = "Propagation arrêtée : météo extérieure absente vers ${Instant.ofEpochMilli(ts).atZone(zone).toLocalDateTime()}."
                break
            }
            val extAvg6 = outsideAverage(outside, extTs, 6) ?: ext
            val stepHour = Instant.ofEpochMilli(ts).atZone(zone).hour
            val delta = massAwareDelta(model.coefficients, current, currentMass, ext, extAvg6, stepHour, profile)
                .coerceIn(-1.2, 1.2)
            val next = current + delta
            if (!plausibleIndoor(next)) {
                stopDiagnostic = "Propagation arrêtée avant dérive physique abusive (${round2(next)} °C)."
                break
            }
            val nextMass = advanceMass(profile, current, currentMass, extAvg6)
            val outHum = outside[hourBucket(ts)]?.humidity ?: currentH
            currentH += 0.08 * (outHum - currentH)
            current = next
            currentMass = nextMass
            ts += THERMAL_HOUR_MS
        }

        val created = PointSourceStore.upsertBatchByPriority(db, writes, 256) { processed, changed ->
            progress?.invoke(
                ThermalProgress("Écriture historique · ${sensor.room}", processed, writes.size, changed)
            )
        }
        if (stopDiagnostic != null) return ForwardFillSummary(created, 0, 0.0, stopDiagnostic)

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

    private fun fillInteriorGapsForward(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        profile: ThermalBuildingProfile,
        progress: ((ThermalProgress) -> Unit)? = null
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
        var raccords = 0
        var maxDrift = 0.0
        val writes = ArrayList<PriorityPointWrite>()

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
                writes += PriorityPointWrite(
                    sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
                )
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

        val created = PointSourceStore.upsertBatchByPriority(db, writes, 256) { processed, changed ->
            progress?.invoke(ThermalProgress("Comblement des trous · ${sensor.room}", processed, writes.size, changed))
        }
        return ForwardFillSummary(created, raccords, maxDrift)
    }

    private fun validateLongHorizon(
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

    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {
        val exchange = coeff[0] + coeff[1]
        if (!exchange.isFinite() || abs(exchange) < 0.002) return null
        val seasonal = coeff[2] * sin(2.0 * PI * hour / 24.0) +
            coeff[3] * cos(2.0 * PI * hour / 24.0) + coeff[4]
        val value = (coeff[0] * tout + coeff[1] * avg6 + seasonal) / exchange
        return value.takeIf { it.isFinite() }
    }

    private fun plausibleIndoor(value: Double): Boolean = value.isFinite() && value in -5.0..50.0

    private fun referenceCoverageReady(points: List<HourPoint>, from: Long, to: Long): Boolean {
        if (to <= from) return false
        val start = hourBucket(from)
        val end = hourBucket(to)
        val expected = (((end - start) / THERMAL_HOUR_MS) + 1L).coerceAtLeast(1L)
        val buckets = points.asSequence()
            .map { hourBucket(it.timestamp) }
            .filter { it in start..end }
            .distinct()
            .sorted()
            .toList()
        if (buckets.isEmpty()) return false
        val coverage = buckets.size.toDouble() / expected.toDouble()
        val maxGapHours = buckets.zipWithNext().maxOfOrNull { (a, b) ->
            ((b - a) / THERMAL_HOUR_MS).toInt()
        } ?: 1
        return coverage >= 0.90 && maxGapHours <= 3
    }

    private fun provenance(
        model: ThermalModel,
        reference: WeatherReference,
        source: PointSource,
        confidence: Double,
        sigmaC: Double? = null,
        analogCount: Int? = null
    ) = PointProvenance(
        source = source,
        confidence = confidence,
        referenceKey = reference.key,
        referenceStationId = reference.stationId,
        referenceCity = reference.city,
        calibrationFrom = model.calibrationFrom,
        calibrationTo = model.calibrationTo,
        modelVersion = PointSourceStore.MODEL_VERSION,
        sigmaC = sigmaC,
        analogCount = analogCount
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
