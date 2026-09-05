package com.fabdata.app

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

const val THERMAL_INERTIA_SENSOR_ID = -6902900104L
const val THERMAL_INERTIA_STABLE_KEY = "thermal-inertia-estimated"
private const val INERTIA_HOUR_MS = 60L * 60L * 1000L

data class ThermalInertiaDiagnostics(
    val sourceSensorId: Long,
    val sourceRoom: String,
    val currentC: Double,
    val trendCPerDay: Double,
    val tauHours: Double,
    val couplingPerHour: Double,
    val outsideWeight: Double,
    val confidence: Double,
    val cleanHours: Int,
    val plateauHours: Int,
    val fitRmse: Double,
    val currentFluxCPerHour: Double,
    val tangentPenalty: Double = 0.0,
    val regimeHours: Int = 0,
    val surfaceTauHours: Double = 48.0,
    val deepTauHours: Double = 336.0,
    val deepShare: Double = 0.72
) {
    val trendLabel: String get() = when {
        trendCPerDay > 0.06 -> "↑ charge thermique"
        trendCPerDay < -0.06 -> "↓ décharge thermique"
        else -> "→ quasi stable"
    }
    val couplingLabel: String get() = when {
        couplingPerHour < 0.008 -> "faible"
        couplingPerHour < 0.025 -> "moyen"
        else -> "fort"
    }
    val confidenceLabel: String get() = when {
        confidence >= 0.72 -> "forte"
        confidence >= 0.46 -> "moyenne"
        else -> "faible"
    }
    val fluxLabel: String get() = when {
        currentFluxCPerHour > 0.01 -> "haut · masse → air"
        currentFluxCPerHour < -0.01 -> "bas · air → masse"
        else -> "quasi nul"
    }
}

data class ThermalInertiaEstimate(
    val points: List<SamplePoint>,
    val diagnostics: ThermalInertiaDiagnostics
) {
    fun window(from: Long, to: Long, maxPoints: Int = 5000): List<SamplePoint> {
        val selected = points.filter { it.timestamp in from..to }
        if (selected.size <= maxPoints || maxPoints < 2) return selected
        val step = ((selected.size + maxPoints - 1) / maxPoints).coerceAtLeast(1)
        val out = selected.filterIndexed { index, _ -> index % step == 0 }.toMutableList()
        selected.lastOrNull()?.let { last -> if (out.lastOrNull()?.timestamp != last.timestamp) out += last }
        return out
    }
}

private data class InertiaHour(
    val timestamp: Long,
    val air: Double,
    val humidity: Double,
    val outside: Double,
    val smoothAir: Double
)

private data class InertiaCandidate(
    val tauHours: Double,
    val surfaceTauHours: Double,
    val deepTauHours: Double,
    val deepShare: Double,
    val outsideWeight: Double,
    val mass: DoubleArray,
    val kOutside: Double,
    val kMass: Double,
    val rmse: Double,
    val score: Double,
    val cleanHours: Int,
    val plateauHours: Int,
    val tangentPenalty: Double,
    val regimeHours: Int
)

/**
 * Estimateur inertiel couplé bi-masse v0.19.5.
 *
 * v0.19 ajoute une lecture tangentielle explicitement normalisée par Δt :
 * la valeur reste inertielle et continue, mais un changement de régime persistant
 * peut faire pivoter plus tôt la pente sans suivre les oscillations rapides.
 *
 * - les paramètres sont appris uniquement sur les points intérieurs MEASURED ;
 * - les périodes perturbées/douteuses sont exclues par les masques mais restent visibles ;
 * - la météo sert de variable explicative lente ;
 * - l'estimateur ne persiste aucune donnée et ne modifie jamais les points MEASURED ;
 * - T_mass devient une entrée obligatoire du modèle d'historique et de prévision.
 *
 * T_mass est la moyenne énergétique interne de deux états latents : une couche
 * superficielle réactive et une masse profonde lente du bâtiment. Depuis v0.19.6 cet
 * état n'est plus tracé sur le graphe principal : le moteur l'utilise comme référence
 * cachée pour reconstruire la température de surface / sol équivalente observable.
 * Un changement extérieur modifie immédiatement la dérivée de la couche de surface
 * sans faire sauter aucune température ; s'il persiste, il se transmet à la masse profonde.
 */
class ThermalInertiaEstimator(
    private val db: FabDataDb,
    private val referenceStore: WeatherReferenceStore
) {
    private var cachedKey: String? = null
    private var cached: ThermalInertiaEstimate? = null

    fun estimate(reference: WeatherReference, sensorId: Long? = null, includeHistory: Boolean = true): ThermalInertiaEstimate? {
        val measuredRevision = db.physicalMeasuredRevision() ?: return null
        val weatherSignature = weatherSignature(reference.key) ?: return null
        val trainingMaskStore = ThermalTrainingMaskStore(db)
        // Une modification d'une zone utilisateur invalide immédiatement le cache,
        // même si aucune donnée RAW n'a changé.
        val trainingMaskSignature = trainingMaskStore.signature(sensorId)
        val key = "$measuredRevision|${reference.key}|$weatherSignature|${sensorId ?: -1L}|$includeHistory|$trainingMaskSignature"
        if (key == cachedKey) return cached

        val sensors = db.sensors().filter { s ->
            (sensorId == null || s.id == sensorId) &&
                s.id >= 0L && !s.stableKey.startsWith("meteo-") && !s.stableKey.startsWith("http-get-")
        }
        val measuredBySensor = sensors.mapNotNull { sensor ->
            val pts = measuredHourly(sensor.id)
            if (pts.size >= 120) sensor to pts else null
        }
        val selected = measuredBySensor.maxByOrNull { it.second.size } ?: return null
        val sensor = selected.first
        val measured = selected.second
        val weatherBounds = referenceStore.historyBounds(reference.key) ?: return null
        val from = max(measured.first().timestamp, weatherBounds.first)
        val to = min(measured.last().timestamp, weatherBounds.last)
        if (to - from < 5L * 24L * INERTIA_HOUR_MS) return null

        val outside = outsideHourly(reference.key, from - 3L * INERTIA_HOUR_MS, to)
        if (outside.size < 120) return null
        val outMap = outside.associateBy { it.first }
        val indoor = measured.filter { it.timestamp in from..to }
        if (indoor.size < 120) return null
        val smooth = smoothAir(indoor.map { it.temperature })
        val hours = indoor.mapIndexedNotNull { index, p ->
            val outsideT = outsideAt(outMap, p.timestamp) ?: return@mapIndexedNotNull null
            InertiaHour(p.timestamp, p.temperature, p.humidity, outsideT, smooth[index])
        }
        if (hours.size < 120) return null

        // Le masque utilisateur ne supprime rien : il retire seulement ces heures du fit.
        // La propagation de l'état latent traverse toujours les périodes exclues.
        val manualExclusions = trainingMaskStore.query(sensor.id, from, to)
        val best = search(hours, manualExclusions) ?: fallback(hours, manualExclusions)
        val confidence = confidence(best)

        // Les paramètres (tau, couplages, poids extérieur) viennent EXCLUSIVEMENT
        // des heures MEASURED propres ci-dessus. Pour l'affichage historique, on
        // peut ensuite propager cet état lent sur la chronologie intérieure déjà
        // reconstruite : cela ne réentraîne jamais le modèle sur ses propres sorties.
        val outputHours: List<InertiaHour>
        val outputMass: DoubleArray
        if (includeHistory) {
            val fullIndoor = allHourly(sensor.id)
            val fullFrom = max(fullIndoor.firstOrNull()?.timestamp ?: from, weatherBounds.first)
            val fullTo = min(fullIndoor.lastOrNull()?.timestamp ?: to, weatherBounds.last)
            val fullOutside = outsideHourly(reference.key, fullFrom - 3L * INERTIA_HOUR_MS, fullTo)
            val fullOutMap = fullOutside.associateBy { it.first }
            val inRange = fullIndoor.filter { it.timestamp in fullFrom..fullTo }
            val fullSmooth = smoothAir(inRange.map { it.temperature })
            val built = inRange.mapIndexedNotNull { index, p ->
                val outsideT = outsideAt(fullOutMap, p.timestamp) ?: return@mapIndexedNotNull null
                InertiaHour(p.timestamp, p.temperature, p.humidity, outsideT, fullSmooth[index])
            }
            if (built.size >= 120) {
                outputHours = built
                outputMass = propagateDisplay(built, best.surfaceTauHours, best.deepTauHours, best.deepShare, best.outsideWeight)
            } else {
                outputHours = hours
                outputMass = best.mass
            }
        } else {
            outputHours = hours
            outputMass = best.mass
        }

        val points = outputHours.mapIndexed { index, h ->
            SamplePoint(
                sensorId = THERMAL_INERTIA_SENSOR_ID,
                timestamp = h.timestamp,
                // Keep full latent precision: rounding the state itself can visually erase a small
                // but physically real tangent change. Labels/diagnostics may still be rounded.
                temperature = outputMass[index],
                humidity = h.humidity,
                source = PointSource.RECONSTRUCTED,
                confidence = confidence
            )
        }
        if (points.isEmpty()) return null

        val trend = trendPerDay(outputHours, outputMass)
        val currentAir = outputHours.last().smoothAir
        val currentFlux = best.kMass * (outputMass.last() - currentAir)
        val diagnostics = ThermalInertiaDiagnostics(
            sourceSensorId = sensor.id,
            sourceRoom = sensor.room,
            currentC = round2(best.mass.last()),
            trendCPerDay = trend,
            tauHours = best.tauHours,
            couplingPerHour = best.kMass,
            outsideWeight = best.outsideWeight,
            confidence = confidence,
            cleanHours = best.cleanHours,
            plateauHours = best.plateauHours,
            fitRmse = best.rmse,
            currentFluxCPerHour = currentFlux,
            tangentPenalty = best.tangentPenalty,
            regimeHours = best.regimeHours,
            surfaceTauHours = best.surfaceTauHours,
            deepTauHours = best.deepTauHours,
            deepShare = best.deepShare
        )
        return ThermalInertiaEstimate(points, diagnostics).also {
            cachedKey = key
            cached = it
        }
    }


    private fun allHourly(sensorId: Long): List<SamplePoint> {
        PointSourceStore.ensure(db.readableDatabase)
        val raw = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity, ps.source
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source<>'forecast')
            ORDER BY p.timestamp
            """.trimIndent(),
            arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val source = PointSource.fromDb(if (c.isNull(3)) null else c.getString(3))
                raw += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2), source, 1.0)
            }
        }
        return raw.groupBy { bucket(it.timestamp) }.map { (ts, values) ->
            val priority = values.maxOf { it.source.priority }
            val best = values.filter { it.source.priority == priority }
            SamplePoint(
                sensorId, ts, best.map { it.temperature }.average(), best.map { it.humidity }.average(),
                best.first().source, best.mapNotNull { it.confidence }.averageOr(1.0)
            )
        }.sortedBy { it.timestamp }
    }


    private fun measuredHourly(sensorId: Long): List<SamplePoint> {
        PointSourceStore.ensure(db.readableDatabase)
        val out = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT (p.timestamp / 3600000) * 3600000 AS bucket,
                   AVG(p.temperature), AVG(p.humidity)
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source='measured')
            GROUP BY bucket
            ORDER BY bucket
            """.trimIndent(),
            arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2), PointSource.MEASURED, 1.0)
            }
        }
        return out
    }

    private fun outsideHourly(referenceKey: String, from: Long, to: Long): List<Pair<Long, Double>> =
        referenceStore.query(referenceKey, from, to)
            .filter { it.source != PointSource.FORECAST }
            .groupBy { bucket(it.timestamp) }
            .map { (ts, values) ->
                val priority = values.maxOf { it.source.priority }
                val best = values.filter { it.source.priority == priority }
                ts to best.map { it.temperature }.average()
            }
            .sortedBy { it.first }

    private fun outsideAt(map: Map<Long, Pair<Long, Double>>, timestamp: Long): Double? {
        val b = bucket(timestamp)
        map[b]?.let { return it.second }
        return listOfNotNull(map[b - INERTIA_HOUR_MS], map[b + INERTIA_HOUR_MS])
            .minByOrNull { abs(it.first - timestamp) }?.second
    }

    private fun smoothAir(values: List<Double>): List<Double> = values.indices.map { i ->
        val from = max(0, i - 2)
        val to = min(values.lastIndex, i + 2)
        val window = (from..to).map { values[it] }.sorted()
        if (window.size % 2 == 1) window[window.size / 2]
        else (window[window.size / 2 - 1] + window[window.size / 2]) / 2.0
    }

    private fun masks(
        hours: List<InertiaHour>,
        manualExclusions: List<ThermalTrainingExclusion> = emptyList()
    ): Pair<BooleanArray, BooleanArray> {
        val clean = BooleanArray(hours.size)
        val plateau = BooleanArray(hours.size)
        fun excluded(timestamp: Long): Boolean = manualExclusions.any { it.contains(timestamp) }

        for (i in 2 until hours.size) {
            // Ne jamais calculer une dérivée d'apprentissage à travers une frontière exclue.
            // On garde néanmoins ces heures dans la chronologie de propagation physique.
            if (excluded(hours[i].timestamp) || excluded(hours[i - 1].timestamp) || excluded(hours[i - 2].timestamp)) {
                continue
            }
            val dt = (hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
            val prevDt = (hours[i - 1].timestamp - hours[i - 2].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
            if (dt !in 0.75..2.5 || prevDt !in 0.75..2.5) continue
            val slope = (hours[i].smoothAir - hours[i - 1].smoothAir) / dt
            val previousSlope = (hours[i - 1].smoothAir - hours[i - 2].smoothAir) / prevDt
            val accelDt = ((dt + prevDt) * 0.5).coerceAtLeast(0.5)
            val accel = (slope - previousSlope) / accelDt
            val humidityJump = abs(hours[i].humidity - hours[i - 1].humidity) / dt
            val rawSlope = abs(hours[i].air - hours[i - 1].air) / dt
            val ok = rawSlope <= 0.90 && abs(slope) <= 0.70 && abs(accel) <= 0.60 && humidityJump <= 15.0
            clean[i] = ok
            plateau[i] = ok && abs(slope) <= 0.08 && abs(hours[i].outside - hours[i].smoothAir) >= 1.8 &&
                abs(slope) <= abs(previousSlope) + 0.03
        }
        return clean to plateau
    }

    private fun search(
        hours: List<InertiaHour>,
        manualExclusions: List<ThermalTrainingExclusion>
    ): InertiaCandidate? {
        val (clean, plateau) = masks(hours, manualExclusions)
        // Deux réservoirs thermiques : surface (heures/jours) et profondeur (jours/semaines).
        // La grille reste volontairement compacte pour rester légère sur téléphone.
        val surfaceTaus = doubleArrayOf(18.0, 30.0, 48.0, 72.0)
        val deepTaus = doubleArrayOf(144.0, 240.0, 336.0, 504.0, 720.0)
        val deepShares = doubleArrayOf(0.55, 0.70, 0.82)
        val outsideWeights = doubleArrayOf(0.08, 0.15, 0.25, 0.35)
        var best: InertiaCandidate? = null

        for (surfaceTau in surfaceTaus) {
            for (deepTau in deepTaus) {
                if (deepTau < surfaceTau * 3.0) continue
                for (deepShare in deepShares) {
                    for (outsideWeight in outsideWeights) {
                        val mass = propagateTwoMass(
                            hours, surfaceTau, deepTau, deepShare, outsideWeight, plateau
                        )
                        val rows = mutableListOf<DoubleArray>()
                        for (i in 2 until hours.size) {
                            if (!clean[i]) continue
                            val dt = (hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
                            if (dt !in 0.75..2.5) continue
                            val y = (hours[i].smoothAir - hours[i - 1].smoothAir) / dt
                            rows += doubleArrayOf(
                                hours[i - 1].outside - hours[i - 1].smoothAir,
                                mass[i - 1] - hours[i - 1].smoothAir,
                                y
                            )
                        }
                        if (rows.size < 80) continue
                        val split = (rows.size * 0.75).toInt().coerceIn(60, rows.size - 20)
                        val coeff = fitTwo(rows.take(split)) ?: continue
                        val kOut = coeff.first
                        val kMass = coeff.second
                        if (kOut !in 0.0..0.25 || kMass !in 0.001..0.20) continue
                        val validation = rows.drop(split)
                        val rmse = sqrt(validation.map { r ->
                            val e = kOut * r[0] + kMass * r[1] - r[2]
                            e * e
                        }.average())
                        val plateauIndices = hours.indices.filter { plateau[it] }
                        val plateauError = plateauIndices.map { i -> abs(mass[i] - hours[i].smoothAir) }.averageOr(1.5)

                        val massSlopes = DoubleArray(mass.size)
                        for (i in 1 until mass.size) {
                            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())
                                .coerceAtLeast(0.25)
                            massSlopes[i] = (mass[i] - mass[i - 1]) / dt
                        }
                        val slopeActivity = (1 until mass.size)
                            .filter { clean[it] }
                            .map { abs(massSlopes[it]) }
                            .averageOr(0.0)
                        val tangentAcceleration = (2 until mass.size)
                            .filter { clean[it] && clean[it - 1] }
                            .map { i ->
                                val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())
                                    .coerceAtLeast(0.25)
                                abs(massSlopes[i] - massSlopes[i - 1]) / dt
                            }
                            .averageOr(0.0)
                        val tangent = tangentPenalty(hours, mass, clean, outsideWeight)
                        val effectiveTau = (surfaceTau * (1.0 - deepShare) + deepTau * deepShare)

                        val score = rmse +
                            0.06 * plateauError +
                            0.40 * max(0.0, slopeActivity - 0.070) +
                            0.16 * max(0.0, tangentAcceleration - 0.030) +
                            0.60 * tangent.first
                        val candidate = InertiaCandidate(
                            tauHours = effectiveTau,
                            surfaceTauHours = surfaceTau,
                            deepTauHours = deepTau,
                            deepShare = deepShare,
                            outsideWeight = outsideWeight,
                            mass = mass,
                            kOutside = kOut,
                            kMass = kMass,
                            rmse = rmse,
                            score = score,
                            cleanHours = clean.count { it },
                            plateauHours = plateau.count { it },
                            tangentPenalty = tangent.first,
                            regimeHours = tangent.second
                        )
                        if (best == null || candidate.score < best!!.score) best = candidate
                    }
                }
            }
        }
        return best
    }

    private fun fallback(
        hours: List<InertiaHour>,
        manualExclusions: List<ThermalTrainingExclusion>
    ): InertiaCandidate {
        val (clean, plateau) = masks(hours, manualExclusions)
        val surfaceTau = 48.0
        val deepTau = 336.0
        val deepShare = 0.72
        val outsideWeight = 0.15
        val mass = propagateTwoMass(hours, surfaceTau, deepTau, deepShare, outsideWeight, plateau)
        val tangent = tangentPenalty(hours, mass, clean, outsideWeight)
        return InertiaCandidate(
            tauHours = surfaceTau * (1.0 - deepShare) + deepTau * deepShare,
            surfaceTauHours = surfaceTau,
            deepTauHours = deepTau,
            deepShare = deepShare,
            outsideWeight = outsideWeight,
            mass = mass,
            kOutside = 0.02,
            kMass = 0.012,
            rmse = 0.80,
            score = 9.0,
            cleanHours = clean.count { it },
            plateauHours = plateau.count { it },
            tangentPenalty = tangent.first,
            regimeHours = tangent.second
        )
    }

    /**
     * RC bi-masse stable : la couche superficielle reçoit immédiatement le forçage
     * air + extérieur et échange avec la masse profonde. La masse profonde ne voit
     * que la couche de surface. Aucune valeur ne saute ; seule la dérivée change dès
     * que le gradient thermique change.
     */
    private fun propagateTwoMass(
        hours: List<InertiaHour>,
        surfaceTauHours: Double,
        deepTauHours: Double,
        deepShare: Double,
        outsideWeight: Double,
        plateau: BooleanArray? = null
    ): DoubleArray {
        val mass = DoubleArray(hours.size)
        if (hours.isEmpty()) return mass
        val share = deepShare.coerceIn(0.45, 0.90)
        val w = outsideWeight.coerceIn(0.02, 0.45)
        var surface = forcingValue(hours[0], w)
        var deep = hours[0].smoothAir * 0.88 + hours[0].outside * 0.12
        mass[0] = (1.0 - share) * surface + share * deep

        for (i in 1 until hours.size) {
            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())
                .coerceIn(0.5, 24.0)
            val forcing = forcingValue(hours[i - 1], w)

            // La surface est surtout tirée par le flux courant, mais garde un lien avec
            // le noyau profond. Ce couplage évite qu'elle ne devienne une simple copie filtrée.
            val surfaceTarget = 0.82 * forcing + 0.18 * deep
            val alphaSurface = 1.0 - exp(-dt / surfaceTauHours.coerceAtLeast(6.0))
            var nextSurface = surface + alphaSurface * (surfaceTarget - surface)

            if (plateau?.getOrNull(i) == true) {
                // Une vraie phase intérieure calme donne une faible observation de la surface,
                // jamais de la masse profonde.
                val observationGain = min(0.06, 0.015 * dt)
                nextSurface += observationGain * (hours[i].smoothAir - nextSurface)
            }

            val alphaDeep = 1.0 - exp(-dt / deepTauHours.coerceAtLeast(surfaceTauHours * 2.5))
            val nextDeep = deep + alphaDeep * (nextSurface - deep)

            surface = nextSurface.coerceIn(-5.0, 50.0)
            deep = nextDeep.coerceIn(-5.0, 50.0)
            mass[i] = ((1.0 - share) * surface + share * deep).coerceIn(-5.0, 50.0)
        }
        return mass
    }

    private fun propagateDisplay(
        hours: List<InertiaHour>,
        surfaceTauHours: Double,
        deepTauHours: Double,
        deepShare: Double,
        outsideWeight: Double
    ): DoubleArray = propagateTwoMass(
        hours = hours,
        surfaceTauHours = surfaceTauHours,
        deepTauHours = deepTauHours,
        deepShare = deepShare,
        outsideWeight = outsideWeight,
        plateau = null
    )

    /**
     * v0.19.4 : le changement de régime est lu dans le FORÇAGE thermique, pas seulement
     * dans la pente de l'air intérieur. La masse peut donc modifier immédiatement sa
     * dérivée lorsque l'extérieur bouge alors que l'intérieur est encore presque plat.
     *
     * Le terme instantané est volontairement faible : un pic extérieur ne doit pas faire
     * sauter la masse. La réponse forte n'arrive que si les pentes ≈3 h et ≈9 h du forçage
     * restent cohérentes. La valeur de masse reste toujours continue.
     */
    private fun regimeConfidence(hours: List<InertiaHour>, index: Int, outsideWeight: Double): Double {
        if (index < 1 || index !in hours.indices) return 0.0
        val instantFrom = max(0, index - 1)
        val shortFrom = max(0, index - 3)
        val mediumFrom = max(0, index - 9)
        val instantSlope = forcingSlopeBetween(hours, instantFrom, index, outsideWeight) ?: 0.0
        val shortSlope = forcingSlopeBetween(hours, shortFrom, index, outsideWeight) ?: instantSlope
        val mediumSlope = forcingSlopeBetween(hours, mediumFrom, index, outsideWeight) ?: shortSlope

        // Toute variation réelle du forçage produit un petit changement de tangente.
        // Elle ne peut cependant apporter que 18 % de confiance à elle seule.
        val instantStrength = (abs(instantSlope) / 0.12).coerceIn(0.0, 1.0)
        val instant = 0.18 * instantStrength

        val aligned = shortSlope * mediumSlope > 0.0
        val persistentStrength = if (aligned) {
            ((0.62 * abs(shortSlope) + 0.38 * abs(mediumSlope) - 0.004) / 0.10)
                .coerceIn(0.0, 1.0)
        } else 0.0
        val instantAgreement = when {
            abs(instantSlope) < 1e-6 -> 0.90
            instantSlope * shortSlope > 0.0 -> 1.0
            else -> 0.72
        }
        return (instant + 0.82 * persistentStrength * instantAgreement).coerceIn(0.0, 1.0)
    }

    private fun forcingValue(hour: InertiaHour, outsideWeight: Double): Double {
        val w = outsideWeight.coerceIn(0.02, 0.45)
        return hour.smoothAir * (1.0 - w) + hour.outside * w
    }

    private fun forcingSlopeBetween(
        hours: List<InertiaHour>,
        fromIndex: Int,
        toIndex: Int,
        outsideWeight: Double
    ): Double? {
        if (fromIndex !in hours.indices || toIndex !in hours.indices || toIndex <= fromIndex) return null
        val elapsed = (hours[toIndex].timestamp - hours[fromIndex].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
        if (elapsed <= 0.25) return null
        return (forcingValue(hours[toIndex], outsideWeight) - forcingValue(hours[fromIndex], outsideWeight)) / elapsed
    }

    private fun slopeBetween(
        hours: List<InertiaHour>,
        fromIndex: Int,
        toIndex: Int,
        outside: Boolean
    ): Double? {
        if (fromIndex !in hours.indices || toIndex !in hours.indices || toIndex <= fromIndex) return null
        val elapsed = (hours[toIndex].timestamp - hours[fromIndex].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
        if (elapsed <= 0.25) return null
        val fromValue = if (outside) hours[fromIndex].outside else hours[fromIndex].smoothAir
        val toValue = if (outside) hours[toIndex].outside else hours[toIndex].smoothAir
        return (toValue - fromValue) / elapsed
    }

    /**
     * Pénalité tangentielle volontairement faible : elle ne force pas T_mass à suivre
     * T_air. Elle pénalise seulement un état latent qui continue franchement dans le
     * mauvais sens ou reste artificiellement plat pendant un régime persistant.
     */
    private fun tangentPenalty(
        hours: List<InertiaHour>,
        mass: DoubleArray,
        clean: BooleanArray,
        outsideWeight: Double
    ): Pair<Double, Int> {
        if (hours.size != mass.size || clean.size != mass.size || mass.size < 5) return 0.0 to 0
        var weightedError = 0.0
        var weight = 0.0
        var regimeHours = 0
        for (i in 4 until mass.size) {
            if (!clean[i] || !clean[i - 1]) continue
            val confidence = regimeConfidence(hours, i, outsideWeight)
            if (confidence < 0.20) continue
            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())
                .coerceAtLeast(0.25)
            val massSlope = (mass[i] - mass[i - 1]) / dt
            val referenceSlope = forcingSlopeBetween(hours, max(0, i - 3), i, outsideWeight) ?: continue
            if (abs(referenceSlope) < 0.006) continue

            val minimumUsefulSlope = min(0.045, abs(referenceSlope) * 0.18) * confidence
            val wrongDirection = if (massSlope * referenceSlope < 0.0) {
                min(0.20, abs(massSlope) + minimumUsefulSlope)
            } else 0.0
            val stalled = if (massSlope * referenceSlope >= 0.0) {
                max(0.0, minimumUsefulSlope - abs(massSlope))
            } else 0.0

            weightedError += confidence * (wrongDirection + stalled)
            weight += confidence
            regimeHours++
        }
        return (if (weight <= 0.0) 0.0 else weightedError / weight) to regimeHours
    }

    private fun fitTwo(rows: List<DoubleArray>): Pair<Double, Double>? {
        var a11 = 0.02
        var a12 = 0.0
        var a22 = 0.02
        var b1 = 0.0
        var b2 = 0.0
        rows.forEach { r ->
            val x1 = r[0]
            val x2 = r[1]
            val y = r[2]
            a11 += x1 * x1
            a12 += x1 * x2
            a22 += x2 * x2
            b1 += x1 * y
            b2 += x2 * y
        }
        val det = a11 * a22 - a12 * a12
        if (abs(det) < 1e-9) return null
        val k1 = (b1 * a22 - b2 * a12) / det
        val k2 = (a11 * b2 - a12 * b1) / det
        if (!k1.isFinite() || !k2.isFinite()) return null
        return k1 to k2
    }

    private fun confidence(candidate: InertiaCandidate): Double {
        val dataFactor = (candidate.cleanHours / 720.0).coerceIn(0.0, 1.0)
        val plateauFactor = (candidate.plateauHours / 40.0).coerceIn(0.0, 1.0)
        val errorFactor = (1.0 - candidate.rmse / 0.55).coerceIn(0.0, 1.0)
        return (0.08 + 0.44 * errorFactor + 0.28 * dataFactor + 0.20 * plateauFactor).coerceIn(0.08, 0.95)
    }

    private fun trendPerDay(hours: List<InertiaHour>, mass: DoubleArray): Double {
        if (mass.size < 2) return 0.0
        val last = hours.last().timestamp
        val target = last - 24L * INERTIA_HOUR_MS
        val index = hours.indices.minByOrNull { abs(hours[it].timestamp - target) } ?: 0
        val elapsed = ((last - hours[index].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()).coerceAtLeast(1.0)
        return (mass.last() - mass[index]) * 24.0 / elapsed
    }

    private fun weatherSignature(referenceKey: String): String? {
        return db.readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp), MAX(updated_at)
            FROM weather_reference_samples
            WHERE reference_key=? AND source<>'forecast'
            """.trimIndent(),
            arrayOf(referenceKey)
        ).use { c ->
            if (!c.moveToFirst() || c.getLong(0) <= 0L || c.isNull(1) || c.isNull(2)) null
            else "${c.getLong(0)}:${c.getLong(1)}:${c.getLong(2)}:${if (c.isNull(3)) 0L else c.getLong(3)}"
        }
    }

    private fun bucket(ts: Long): Long = (ts / INERTIA_HOUR_MS) * INERTIA_HOUR_MS
    private fun round2(v: Double): Double = kotlin.math.round(v * 100.0) / 100.0
    private fun List<Double>.averageOr(fallback: Double): Double = if (isEmpty()) fallback else average()
}
