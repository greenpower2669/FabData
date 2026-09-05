from pathlib import Path

TARGET = Path("app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt")
text = TARGET.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
'''    val plateauHours: Int,
    val fitRmse: Double,
    val currentFluxCPerHour: Double
) {''',
'''    val plateauHours: Int,
    val fitRmse: Double,
    val currentFluxCPerHour: Double,
    val tangentPenalty: Double = 0.0,
    val regimeHours: Int = 0
) {''',
"diagnostics fields",
)

replace_once(
'''    val rmse: Double,
    val score: Double,
    val cleanHours: Int,
    val plateauHours: Int
)''',
'''    val rmse: Double,
    val score: Double,
    val cleanHours: Int,
    val plateauHours: Int,
    val tangentPenalty: Double,
    val regimeHours: Int
)''',
"candidate fields",
)

replace_once(
''' * Estimateur inertiel couplé v0.15.''',
''' * Estimateur inertiel couplé v0.19.
 *
 * v0.19 ajoute une lecture tangentielle explicitement normalisée par Δt :
 * la valeur reste inertielle et continue, mais un changement de régime persistant
 * peut faire pivoter plus tôt la pente sans suivre les oscillations rapides.''',
"version comment",
)

replace_once(
'''        val measuredRevision = db.physicalMeasuredRevision() ?: return null
        val weatherSignature = weatherSignature(reference.key) ?: return null
        val key = "$measuredRevision|${reference.key}|$weatherSignature|${sensorId ?: -1L}|$includeHistory"
        if (key == cachedKey) return cached
''',
'''        val measuredRevision = db.physicalMeasuredRevision() ?: return null
        val weatherSignature = weatherSignature(reference.key) ?: return null
        val trainingMaskStore = ThermalTrainingMaskStore(db)
        // Une modification d'une zone utilisateur invalide immédiatement le cache,
        // même si aucune donnée RAW n'a changé.
        val trainingMaskSignature = trainingMaskStore.signature(sensorId)
        val key = "$measuredRevision|${reference.key}|$weatherSignature|${sensorId ?: -1L}|$includeHistory|$trainingMaskSignature"
        if (key == cachedKey) return cached
''',
"cache key",
)

replace_once(
'''        if (hours.size < 120) return null

        val best = search(hours) ?: fallback(hours)
        val confidence = confidence(best)
''',
'''        if (hours.size < 120) return null

        // Le masque utilisateur ne supprime rien : il retire seulement ces heures du fit.
        // La propagation de l'état latent traverse toujours les périodes exclues.
        val manualExclusions = trainingMaskStore.query(sensor.id, from, to)
        val best = search(hours, manualExclusions) ?: fallback(hours, manualExclusions)
        val confidence = confidence(best)
''',
"manual exclusions",
)

replace_once(
'''            fitRmse = best.rmse,
            currentFluxCPerHour = currentFlux
        )''',
'''            fitRmse = best.rmse,
            currentFluxCPerHour = currentFlux,
            tangentPenalty = best.tangentPenalty,
            regimeHours = best.regimeHours
        )''',
"diagnostics assignment",
)

old_masks = '''    private fun masks(hours: List<InertiaHour>): Pair<BooleanArray, BooleanArray> {
        val clean = BooleanArray(hours.size)
        val plateau = BooleanArray(hours.size)
        for (i in 2 until hours.size) {
            val dt = (hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
            val prevDt = (hours[i - 1].timestamp - hours[i - 2].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
            if (dt !in 0.75..2.5 || prevDt !in 0.75..2.5) continue
            val slope = (hours[i].smoothAir - hours[i - 1].smoothAir) / dt
            val previousSlope = (hours[i - 1].smoothAir - hours[i - 2].smoothAir) / prevDt
            val accel = slope - previousSlope
            val humidityJump = abs(hours[i].humidity - hours[i - 1].humidity) / dt
            val rawSlope = abs(hours[i].air - hours[i - 1].air) / dt
            val ok = rawSlope <= 0.90 && abs(slope) <= 0.70 && abs(accel) <= 0.60 && humidityJump <= 15.0
            clean[i] = ok
            plateau[i] = ok && abs(slope) <= 0.08 && abs(hours[i].outside - hours[i].smoothAir) >= 1.8 &&
                abs(slope) <= abs(previousSlope) + 0.03
        }
        return clean to plateau
    }
'''
new_masks = '''    private fun masks(
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
'''
replace_once(old_masks, new_masks, "masks")

replace_once(
'''    private fun search(hours: List<InertiaHour>): InertiaCandidate? {
        val (clean, plateau) = masks(hours)''',
'''    private fun search(
        hours: List<InertiaHour>,
        manualExclusions: List<ThermalTrainingExclusion>
    ): InertiaCandidate? {
        val (clean, plateau) = masks(hours, manualExclusions)''',
"search signature",
)

replace_once(
'''                val plateauIndices = hours.indices.filter { plateau[it] }
                val plateauError = plateauIndices.map { i -> abs(mass[i] - hours[i].smoothAir) }.averageOr(1.5)
                val jitter = (1 until mass.size).map { i -> abs(mass[i] - mass[i - 1]) }.averageOr(0.0)
                val score = rmse + 0.06 * plateauError + 0.45 * max(0.0, jitter - 0.065)
                val candidate = InertiaCandidate(
                    tau, outsideWeight, mass, kOut, kMass, rmse, score,
                    clean.count { it }, plateau.count { it }
                )''',
'''                val plateauIndices = hours.indices.filter { plateau[it] }
                val plateauError = plateauIndices.map { i -> abs(mass[i] - hours[i].smoothAir) }.averageOr(1.5)

                // v_mass = ΔT_mass / Δt : contrairement à l'ancien jitter en simple ΔT,
                // cette grandeur reste cohérente si des trous temporels apparaissent.
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
                val tangent = tangentPenalty(hours, mass, clean)

                val score = rmse +
                    0.06 * plateauError +
                    0.45 * max(0.0, slopeActivity - 0.065) +
                    0.18 * max(0.0, tangentAcceleration - 0.025) +
                    0.42 * tangent.first
                val candidate = InertiaCandidate(
                    tau, outsideWeight, mass, kOut, kMass, rmse, score,
                    clean.count { it }, plateau.count { it }, tangent.first, tangent.second
                )''',
"candidate scoring",
)

replace_once(
'''    private fun fallback(hours: List<InertiaHour>): InertiaCandidate {
        val (clean, plateau) = masks(hours)
        val tau = 168.0
        val mass = propagate(hours, tau, 0.15, plateau)
        return InertiaCandidate(
            tauHours = tau,
            outsideWeight = 0.15,
            mass = mass,
            kOutside = 0.02,
            kMass = 0.012,
            rmse = 0.80,
            score = 9.0,
            cleanHours = clean.count { it },
            plateauHours = plateau.count { it }
        )
    }''',
'''    private fun fallback(
        hours: List<InertiaHour>,
        manualExclusions: List<ThermalTrainingExclusion>
    ): InertiaCandidate {
        val (clean, plateau) = masks(hours, manualExclusions)
        val tau = 168.0
        val mass = propagate(hours, tau, 0.15, plateau)
        val tangent = tangentPenalty(hours, mass, clean)
        return InertiaCandidate(
            tauHours = tau,
            outsideWeight = 0.15,
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
    }''',
"fallback",
)

replace_once(
'''            val target = hours[i - 1].smoothAir * (1.0 - outsideWeight) + hours[i - 1].outside * outsideWeight
            val alpha = 1.0 - exp(-dt / tauHours)
            var next = mass[i - 1] + alpha * (target - mass[i - 1])''',
'''            val target = hours[i - 1].smoothAir * (1.0 - outsideWeight) + hours[i - 1].outside * outsideWeight
            // La valeur ne saute jamais. Seule la vitesse de convergence augmente légèrement
            // lorsqu'un même changement de direction persiste sur plusieurs échelles de temps.
            val regime = regimeConfidence(hours, i - 1)
            val effectiveTau = tauHours / (1.0 + 0.55 * regime)
            val alpha = 1.0 - exp(-dt / effectiveTau)
            var next = mass[i - 1] + alpha * (target - mass[i - 1])''',
"training propagation",
)

replace_once(
'''            val target = hours[i - 1].smoothAir * (1.0 - outsideWeight) +
                hours[i - 1].outside * outsideWeight
            val alpha = 1.0 - exp(-dt / tauHours.coerceAtLeast(24.0))
            mass[i] = (mass[i - 1] + alpha * (target - mass[i - 1])).coerceIn(-5.0, 50.0)''',
'''            val target = hours[i - 1].smoothAir * (1.0 - outsideWeight) +
                hours[i - 1].outside * outsideWeight
            val regime = regimeConfidence(hours, i - 1)
            val effectiveTau = tauHours.coerceAtLeast(24.0) / (1.0 + 0.55 * regime)
            val alpha = 1.0 - exp(-dt / effectiveTau)
            mass[i] = (mass[i - 1] + alpha * (target - mass[i - 1])).coerceIn(-5.0, 50.0)''',
"display propagation",
)

helpers = '''
    /**
     * Confiance 0..1 qu'un changement de pente est un vrai changement de régime.
     * Les pentes courte (≈3 h) et moyenne (≈9 h) doivent être de même signe.
     * La météo extérieure n'impose jamais le signe : elle ne fait que renforcer ou
     * atténuer légèrement la confiance. Tous les calculs sont normalisés par Δt réel.
     */
    private fun regimeConfidence(hours: List<InertiaHour>, index: Int): Double {
        if (index < 3 || index !in hours.indices) return 0.0
        val shortFrom = max(0, index - 3)
        val mediumFrom = max(0, index - 9)
        val shortSlope = slopeBetween(hours, shortFrom, index, outside = false) ?: return 0.0
        val mediumSlope = slopeBetween(hours, mediumFrom, index, outside = false) ?: return 0.0
        if (shortSlope * mediumSlope <= 0.0) return 0.0
        if (abs(shortSlope) < 0.035 || abs(mediumSlope) < 0.020) return 0.0

        val outsideSlope = slopeBetween(hours, mediumFrom, index, outside = true) ?: 0.0
        val strength = ((0.65 * abs(shortSlope) + 0.35 * abs(mediumSlope) - 0.025) / 0.14)
            .coerceIn(0.0, 1.0)
        val outsideSupport = when {
            abs(outsideSlope) < 0.015 -> 0.85
            outsideSlope * mediumSlope > 0.0 -> 1.0
            else -> 0.70
        }
        return (strength * outsideSupport).coerceIn(0.0, 1.0)
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
        clean: BooleanArray
    ): Pair<Double, Int> {
        if (hours.size != mass.size || clean.size != mass.size || mass.size < 5) return 0.0 to 0
        var weightedError = 0.0
        var weight = 0.0
        var regimeHours = 0
        for (i in 4 until mass.size) {
            if (!clean[i] || !clean[i - 1]) continue
            val confidence = regimeConfidence(hours, i)
            if (confidence < 0.20) continue
            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())
                .coerceAtLeast(0.25)
            val massSlope = (mass[i] - mass[i - 1]) / dt
            val referenceSlope = slopeBetween(hours, max(0, i - 3), i, outside = false) ?: continue
            if (abs(referenceSlope) < 0.035) continue

            val minimumUsefulSlope = min(0.055, abs(referenceSlope) * 0.22) * confidence
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

'''
replace_once(
'''    private fun fitTwo(rows: List<DoubleArray>): Pair<Double, Double>? {''',
helpers + '''    private fun fitTwo(rows: List<DoubleArray>): Pair<Double, Double>? {''',
"tangent helpers",
)

TARGET.write_text(text, encoding="utf-8")
print("FabData v0.19 tangent core applied")
