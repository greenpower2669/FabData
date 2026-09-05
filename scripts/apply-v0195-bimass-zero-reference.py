from pathlib import Path

INERTIA = Path('app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt')
ENGINE = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt')
POINTS = Path('app/src/main/java/com/fabdata/app/PointSourceLayer.kt')
GRADLE = Path('app/build.gradle.kts')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, got {count}')
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    i = text.find(start)
    if i < 0:
        raise SystemExit(f'{label}: start marker not found')
    j = text.find(end, i)
    if j < 0:
        raise SystemExit(f'{label}: end marker not found')
    return text[:i] + replacement + text[j:]


# -----------------------------------------------------------------------------
# 1) Inertie thermique v0.19.5 : deux masses cachées couplées.
# -----------------------------------------------------------------------------
text = INERTIA.read_text()

old_diag_tail = '''    val currentFluxCPerHour: Double,
    val tangentPenalty: Double = 0.0,
    val regimeHours: Int = 0
) {'''
new_diag_tail = '''    val currentFluxCPerHour: Double,
    val tangentPenalty: Double = 0.0,
    val regimeHours: Int = 0,
    val surfaceTauHours: Double = 48.0,
    val deepTauHours: Double = 336.0,
    val deepShare: Double = 0.72
) {'''
text = replace_once(text, old_diag_tail, new_diag_tail, 'inertia diagnostics bi-mass fields')

old_candidate = '''private data class InertiaCandidate(
    val tauHours: Double,
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
)'''
new_candidate = '''private data class InertiaCandidate(
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
)'''
text = replace_once(text, old_candidate, new_candidate, 'inertia candidate bi-mass fields')

text = text.replace(' * Estimateur inertiel couplé v0.19.\n', ' * Estimateur inertiel couplé bi-masse v0.19.5.\n', 1)
text = text.replace(
    ' * T_mass est un état latent lent. Plusieurs constantes de temps et couplages extérieurs\n * sont testés sur les seules mesures propres, puis ces paramètres peuvent être propagés\n * sur l\'historique sans réentraîner le modèle sur ses propres sorties.\n',
    ''' * T_mass affichée est la moyenne énergétique de deux états latents : une couche\n * superficielle réactive (murs/mobilier/cloisons) et une masse profonde lente.\n * Un changement extérieur modifie donc immédiatement la dérivée de la couche de surface\n * sans faire sauter aucune température ; si le forçage persiste, il se transmet ensuite\n * à la masse profonde. Les paramètres sont appris uniquement sur les vraies mesures.\n''',
    1
)

text = replace_once(
    text,
    'outputMass = propagateDisplay(built, best.tauHours, best.outsideWeight)',
    'outputMass = propagateDisplay(built, best.surfaceTauHours, best.deepTauHours, best.deepShare, best.outsideWeight)',
    'history bi-mass propagation'
)

old_diag_end = '''            currentFluxCPerHour = currentFlux,
            tangentPenalty = best.tangentPenalty,
            regimeHours = best.regimeHours
        )'''
new_diag_end = '''            currentFluxCPerHour = currentFlux,
            tangentPenalty = best.tangentPenalty,
            regimeHours = best.regimeHours,
            surfaceTauHours = best.surfaceTauHours,
            deepTauHours = best.deepTauHours,
            deepShare = best.deepShare
        )'''
text = replace_once(text, old_diag_end, new_diag_end, 'diagnostics expose bi-mass')

search_start = '    private fun search(\n'
fallback_start = '    private fun fallback(\n'
new_search = '''    private fun search(
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

'''
text = replace_between(text, search_start, fallback_start, new_search, 'replace inertia search')

propagate_start = '    private fun fallback(\n'
propagate_marker = '    /**\n     * v0.19.4'
new_fallback_and_propagation = '''    private fun fallback(
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

'''
text = replace_between(text, propagate_start, propagate_marker, new_fallback_and_propagation, 'replace inertia fallback/propagation')

INERTIA.write_text(text)


# -----------------------------------------------------------------------------
# 2) Sonde reconstruite v0.19.5 : Tm est le zéro, on apprend seulement k et Δt.
# -----------------------------------------------------------------------------
text = ENGINE.read_text()

text = text.replace(
    '''/**
 * Modèle thermique grey-box RC discret :
 * ΔTin = a(Tout_lag-Tin) + b(Tout_moy6h-Tin) + c.sin(h) + d.cos(h) + e
 *
 * Les termes a/b représentent échange + accumulation thermique. Les termes jour/nuit
 * ne forcent aucune sinusoïde sur la courbe : ils corrigent seulement le résidu horaire
 * appris sur les vraies mesures. Les reconstructions/prévisions passent toujours par
 * PointSourceStore et sa priorité stricte.
 */''',
    '''/**
 * Modèle de sonde reconstruite v0.19.5, exprimé autour de l'inertie thermique :
 *
 *     x(t) = Tout(t-Δ) - Tm(t)
 *     y(t) = Tin(t) - Tm(t)
 *     y(t) ≈ k · x(t)
 *
 * donc Tin_recon(t) = Tm(t) + k [Tout(t-Δ) - Tm(t)].
 * Le changement de signe est naturel puisque Tm est le zéro du repère. Le facteur k
 * est ajusté globalement par moindres carrés robustes, jamais par un ratio point-à-point,
 * donc aucun problème lorsque x≈0. Les RAW restent prioritaires et inchangées.
 */''',
    1
)

calib_start = '        var best: ThermalModel? = null\n        for (lag in 0..12) {'
calib_end = '        return best ?: error("Aucun modèle RC stable n\'a passé la calibration")'
new_calib = '''        var best: ThermalModel? = null
        for (lag in 0..12) {
            val rows = buildTrainingRows(measured, outMap, inertiaMap, medianDeltas, lag)
            if (rows.size < 120) continue
            val split = (rows.size * 0.80).toInt().coerceIn(80, rows.size - 24)
            val train = rows.take(split)
            val valid = rows.drop(split)
            val k = fitProjectionFactor(train) ?: continue
            if (k !in 0.01..0.85) continue
            val coeff = doubleArrayOf(k)
            val metrics = validate(coeff, valid)
            val driftRmse = validateLongHorizon(coeff, valid, profile, inertia.diagnostics)
            val dataFactor = min(1.0, realDays / 35.0) * min(1.0, rows.size / 500.0)
            val errorFactor = (1.0 - metrics.rmse / 2.8).coerceIn(0.0, 1.0)
            val biasFactor = (1.0 - abs(metrics.bias) / 1.3).coerceIn(0.0, 1.0)
            val driftFactor = (1.0 - driftRmse / 3.2).coerceIn(0.0, 1.0)
            val confidence = (0.12 + 0.40 * errorFactor + 0.16 * biasFactor + 0.17 * dataFactor + 0.15 * driftFactor).coerceIn(0.0, 1.0)
            val model = ThermalModel(
                sensor.id, sensor.name, sensor.room, reference.key, reference.stationId, reference.city,
                lag, coeff, train.first().timestamp, train.last().timestamp, rows.size, realDays,
                metrics, driftRmse, confidence, inertia.diagnostics.tauHours
            )
            val better = if (best == null) {
                true
            } else if (preferLongHorizon) {
                (model.metrics.rmse + 0.35 * model.longHorizonRmse) <
                    (best!!.metrics.rmse + 0.35 * best!!.longHorizonRmse)
            } else {
                model.metrics.rmse < best!!.metrics.rmse
            }
            if (better) best = model
        }
'''
text = replace_between(text, calib_start, calib_end, new_calib, 'projection calibration')
text = text.replace('return best ?: error("Aucun modèle RC stable n\'a passé la calibration")',
                    'return best ?: error("Aucun facteur de projection inertielle stable n\'a passé la calibration")', 1)

training_start = '    private fun buildTrainingRows(\n'
ridge_start = '    private fun ridgeRegression(\n'
new_training = '''    private fun buildTrainingRows(
        indoor: List<HourPoint>,
        outside: Map<Long, HourPoint>,
        inertia: Map<Long, SamplePoint>,
        medianDeltas: Map<Long, Double>,
        lagHours: Int
    ): List<TrainingRow> {
        val rows = mutableListOf<TrainingRow>()
        indoor.zipWithNext().forEach { (a, b) ->
            val dt = b.timestamp - a.timestamp
            if (dt !in (45L * 60L * 1000L)..(90L * 60L * 1000L)) return@forEach
            val dTin = b.temperature - a.temperature
            // On garde les mêmes garde-fous d'événements atypiques qu'avant.
            if (abs(dTin) > 1.35) return@forEach
            if (abs(b.humidity - a.humidity) > 18.0) return@forEach
            val buildingDelta = medianDeltas[hourBucket(a.timestamp)]
            if (buildingDelta != null && abs(dTin - buildingDelta) > 1.25) return@forEach

            val ts = hourBucket(a.timestamp)
            val extTs = ts - lagHours * THERMAL_HOUR_MS
            val tout = outsideAt(outside, extTs) ?: return@forEach
            val avg6 = outsideAverage(outside, extTs, 6) ?: tout
            val mass = inertia[ts]?.temperature ?: return@forEach
            val hour = Instant.ofEpochMilli(a.timestamp).atZone(zone).hour

            // Repère centré sur l'inertie : x = Tout-Tm, y = Tin-Tm.
            val x = tout - mass
            val y = a.temperature - mass
            rows += TrainingRow(
                timestamp = a.timestamp,
                tin = a.temperature,
                nextTin = a.temperature,
                tout = tout,
                toutAvg6 = avg6,
                mass = mass,
                hourOfDay = hour,
                features = doubleArrayOf(x),
                delta = y
            )
        }
        return rows
    }

    /**
     * Ajustement à l'origine y≈k·x. On n'utilise jamais k=y/x point par point :
     * le passage x=0 ne crée donc aucune singularité. Une seconde passe robuste retire
     * seulement les gros résidus encore présents après les garde-fous physiques.
     */
    private fun fitProjectionFactor(rows: List<TrainingRow>): Double? {
        fun fit(source: List<TrainingRow>): Double? {
            var xx = 0.0
            var xy = 0.0
            source.forEach { row ->
                val x = row.features.firstOrNull() ?: return@forEach
                val y = row.delta
                if (!x.isFinite() || !y.isFinite()) return@forEach
                xx += x * x
                xy += x * y
            }
            if (xx < 4.0) return null
            return (xy / xx).takeIf { it.isFinite() }
        }

        val first = fit(rows) ?: return null
        val residuals = rows.mapNotNull { row ->
            val x = row.features.firstOrNull() ?: return@mapNotNull null
            val r = abs(row.delta - first * x)
            r.takeIf { it.isFinite() }
        }.sorted()
        val medianResidual = residuals.getOrNull(residuals.size / 2) ?: 0.20
        val limit = max(0.20, 3.0 * medianResidual)
        val robust = rows.filter { row ->
            val x = row.features.firstOrNull() ?: return@filter false
            abs(row.delta - first * x) <= limit
        }
        return (fit(robust.ifEmpty { rows }) ?: first).coerceIn(0.0, 0.85)
    }

'''
text = replace_between(text, training_start, ridge_start, new_training, 'zero-reference training rows')

predict_marker = '''    private fun predictDelta(
        coeff: DoubleArray,
        tin: Double,
        mass: Double,
        tout: Double,
        toutAvg6: Double,
        hour: Int
    ): Double {
'''
predict_insert = predict_marker + '''        if (coeff.size == 1) {
            val k = coeff[0].coerceIn(0.0, 0.85)
            val target = mass + k * (tout - mass)
            return target - tin
        }
'''
text = replace_once(text, predict_marker, predict_insert, 'projection predictor')

old_mass_delta = '''        val learned = predictDelta(coeff, indoor, mass, outside, outsideAvg6, hour)
        if (coeff.size >= 6) return learned
        val slowMemory = profile.massCoupling() * (mass - indoor)
        return learned + slowMemory
'''
new_mass_delta = '''        val learned = predictDelta(coeff, indoor, mass, outside, outsideAvg6, hour)
        if (coeff.size == 1 || coeff.size >= 6) return learned
        val slowMemory = profile.massCoupling() * (mass - indoor)
        return learned + slowMemory
'''
text = replace_once(text, old_mass_delta, new_mass_delta, 'projection massAwareDelta')

old_advance = '''        val w = diagnostics.outsideWeight.coerceIn(0.02, 0.45)
        val tau = diagnostics.tauHours.coerceIn(24.0, 1440.0)
        val target = indoor * (1.0 - w) + outsideAvg * w
        return mass + (target - mass) / tau
'''
new_advance = '''        val w = diagnostics.outsideWeight.coerceIn(0.02, 0.45)
        val target = indoor * (1.0 - w) + outsideAvg * w
        // Pendant une reconstruction, on ne transporte qu'une température de masse.
        // On utilise donc l'équivalent énergétique des deux pôles appris ; l'affichage
        // inertiel complet est recalculé ensuite par ThermalInertiaEstimator.
        val share = diagnostics.deepShare.coerceIn(0.45, 0.90)
        val alphaSurface = 1.0 - exp(-1.0 / diagnostics.surfaceTauHours.coerceAtLeast(6.0))
        val alphaDeep = 1.0 - exp(-1.0 / diagnostics.deepTauHours.coerceAtLeast(24.0))
        val alpha = ((1.0 - share) * alphaSurface + share * alphaDeep).coerceIn(0.0001, 0.25)
        return mass + alpha * (target - mass)
'''
text = replace_once(text, old_advance, new_advance, 'bi-mass equivalent reconstruction state')

old_equilibrium_head = '''    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {
        val kNow = coeff.getOrNull(0)?.coerceAtLeast(0.0) ?: return null
'''
new_equilibrium_head = '''    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {
        if (coeff.size == 1) return tout.takeIf { it.isFinite() }
        val kNow = coeff.getOrNull(0)?.coerceAtLeast(0.0) ?: return null
'''
text = replace_once(text, old_equilibrium_head, new_equilibrium_head, 'projection equilibrium compatibility')

text = text.replace('"Modèle thermique RC validé. FabData utilise toutes les données réelles propres disponibles au-delà du minimum de 16 jours."',
                    '"Projection inertielle validée. FabData apprend l’atténuation et le retard uniquement sur les données réelles propres."', 1)

ENGINE.write_text(text)


# -----------------------------------------------------------------------------
# 3) Version / invalidation des anciennes courbes calculées.
# -----------------------------------------------------------------------------
text = POINTS.read_text()
text = replace_once(text, 'const val MODEL_VERSION = "thermal-rc-inertia-5"',
                    'const val MODEL_VERSION = "thermal-zero-bimass-6"', 'model version')
POINTS.write_text(text)

text = GRADLE.read_text()
text = replace_once(text, 'versionCode = 40', 'versionCode = 41', 'version code')
text = replace_once(text, 'versionName = "0.19.4"', 'versionName = "0.19.5"', 'version name')
GRADLE.write_text(text)

print('FabData v0.19.5 bi-mass inertia + zero-reference reconstruction patch applied')
