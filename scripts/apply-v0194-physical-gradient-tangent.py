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

# --- Inertial curve: preserve value continuity, make the tangent react to physical forcing. ---
text = INERTIA.read_text()

text = replace_once(
    text,
    'temperature = round2(outputMass[index]),',
    '''// Keep full latent precision: rounding the state itself can visually erase a small\n                // but physically real tangent change. Labels/diagnostics may still be rounded.\n                temperature = outputMass[index],''',
    'full precision inertial output'
)

text = text.replace('val regime = regimeConfidence(hours, i - 1)\n            val effectiveTau = tauHours / (1.0 + 0.55 * regime)',
                    'val regime = regimeConfidence(hours, i - 1, outsideWeight)\n            val effectiveTau = tauHours / (1.0 + 1.10 * regime)')
text = text.replace('val regime = regimeConfidence(hours, i - 1)\n            val effectiveTau = tauHours.coerceAtLeast(24.0) / (1.0 + 0.55 * regime)',
                    'val regime = regimeConfidence(hours, i - 1, outsideWeight)\n            val effectiveTau = tauHours.coerceAtLeast(24.0) / (1.0 + 1.10 * regime)')

text = text.replace('val tangent = tangentPenalty(hours, mass, clean)',
                    'val tangent = tangentPenalty(hours, mass, clean, outsideWeight)', 1)
text = text.replace('val tangent = tangentPenalty(hours, mass, clean)',
                    'val tangent = tangentPenalty(hours, mass, clean, 0.15)', 1)
text = text.replace('0.42 * tangent.first', '0.55 * tangent.first', 1)

old_regime = '''    /**
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
'''
new_regime = '''    /**
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
'''
text = replace_once(text, old_regime, new_regime, 'forcing based regime confidence')

old_tangent_sig = '''    private fun tangentPenalty(
        hours: List<InertiaHour>,
        mass: DoubleArray,
        clean: BooleanArray
    ): Pair<Double, Int> {'''
new_tangent_sig = '''    private fun tangentPenalty(
        hours: List<InertiaHour>,
        mass: DoubleArray,
        clean: BooleanArray,
        outsideWeight: Double
    ): Pair<Double, Int> {'''
text = replace_once(text, old_tangent_sig, new_tangent_sig, 'tangent signature')
text = text.replace('val confidence = regimeConfidence(hours, i)',
                    'val confidence = regimeConfidence(hours, i, outsideWeight)', 1)
text = text.replace('val referenceSlope = slopeBetween(hours, max(0, i - 3), i, outside = false) ?: continue\n            if (abs(referenceSlope) < 0.035) continue\n\n            val minimumUsefulSlope = min(0.055, abs(referenceSlope) * 0.22) * confidence',
                    '''val referenceSlope = forcingSlopeBetween(hours, max(0, i - 3), i, outsideWeight) ?: continue
            if (abs(referenceSlope) < 0.006) continue

            val minimumUsefulSlope = min(0.045, abs(referenceSlope) * 0.18) * confidence''', 1)

INERTIA.write_text(text)

# --- Calculated indoor curve: daily terms become a tiny residual, never an autonomous motor. ---
text = ENGINE.read_text()

old_coeff = '''            val coeff = ridgeRegression(train) ?: continue
            val metrics = validate(coeff, valid)
            val driftRmse = validateLongHorizon(coeff, valid, profile, inertia.diagnostics)
            val exchange = coeff[0] + coeff[1]
            val massCoupling = coeff.getOrNull(2) ?: Double.NaN
'''
new_coeff = '''            val coeff = ridgeRegression(train)?.clone() ?: continue
            // Les deux gradients extérieurs représentent des conductances : ils ne peuvent
            // pas devenir des moteurs de signe arbitraire à cause de la colinéarité du fit.
            coeff[0] = coeff[0].coerceIn(0.0, 0.35)
            coeff[1] = coeff[1].coerceIn(0.0, 0.35)
            val metrics = validate(coeff, valid)
            val driftRmse = validateLongHorizon(coeff, valid, profile, inertia.diagnostics)
            val exchange = coeff[0] + coeff[1]
            val massCoupling = coeff.getOrNull(2) ?: Double.NaN
'''
text = replace_once(text, old_coeff, new_coeff, 'physical conductance clamps')

old_ridge = '''        val ridge = 0.015
        for (i in 0 until n) a[i][i] += ridge
        return solve(a, b)
'''
new_ridge = '''        // Les gradients physiques restent libres ; l'heure de la journée et le biais
        // sont fortement régularisés pour ne jamais fabriquer une oscillation autonome.
        for (i in 0 until n) {
            val ridge = when (i) {
                3, 4 -> 0.30   // sin/cos 24 h : correction résiduelle seulement
                5 -> 0.08      // biais
                else -> 0.015  // gradients Tout/Tin et masse/Tin
            }
            a[i][i] += ridge
        }
        return solve(a, b)
'''
text = replace_once(text, old_ridge, new_ridge, 'feature specific ridge')

old_validate = '''    private fun validate(coeff: DoubleArray, rows: List<TrainingRow>): ThermalMetrics {
        val errors = rows.map { row ->
            val predicted = row.tin + dot(coeff, row.features)
            predicted - row.nextTin
        }
'''
new_validate = '''    private fun validate(coeff: DoubleArray, rows: List<TrainingRow>): ThermalMetrics {
        val errors = rows.map { row ->
            // Validation identique au moteur réellement utilisé : le résidu horaire est borné.
            val predicted = row.tin + predictDelta(
                coeff, row.tin, row.mass, row.tout, row.toutAvg6, row.hourOfDay
            )
            predicted - row.nextTin
        }
'''
text = replace_once(text, old_validate, new_validate, 'constrained validation')

old_predict = '''    private fun predictDelta(
        coeff: DoubleArray,
        tin: Double,
        mass: Double,
        tout: Double,
        toutAvg6: Double,
        hour: Int
    ): Double {
        val f = if (coeff.size >= 6) {
            doubleArrayOf(
                tout - tin,
                toutAvg6 - tin,
                mass - tin,
                sin(2.0 * PI * hour / 24.0),
                cos(2.0 * PI * hour / 24.0),
                1.0
            )
        } else {
            doubleArrayOf(
                tout - tin,
                toutAvg6 - tin,
                sin(2.0 * PI * hour / 24.0),
                cos(2.0 * PI * hour / 24.0),
                1.0
            )
        }
        return dot(coeff, f)
    }
'''
new_predict = '''    private fun predictDelta(
        coeff: DoubleArray,
        tin: Double,
        mass: Double,
        tout: Double,
        toutAvg6: Double,
        hour: Int
    ): Double {
        if (coeff.size >= 6) {
            // Cœur physique : l'air calculé est tendu par les gradients extérieur/air
            // et masse/air. L'heure ne peut plus devenir un moteur indépendant.
            val physical =
                coeff[0].coerceAtLeast(0.0) * (tout - tin) +
                coeff[1].coerceAtLeast(0.0) * (toutAvg6 - tin) +
                coeff[2] * (mass - tin)
            val dailyRaw =
                coeff[3] * sin(2.0 * PI * hour / 24.0) +
                coeff[4] * cos(2.0 * PI * hour / 24.0) + coeff[5]

            // Résidu max ~0,025 °C/h, et surtout proportionnel au flux physique.
            // Si le flux physique est quasi nul, le résidu tombe à quelques millièmes.
            val residualLimit = min(0.025, 0.18 * abs(physical) + 0.0025)
            val residual = dailyRaw.coerceIn(-residualLimit, residualLimit)
            val combined = physical + residual

            // Une correction horaire n'a jamais le droit d'inverser un flux physique net.
            return if (abs(physical) >= 0.005 && combined * physical < 0.0) {
                0.25 * physical
            } else combined
        }

        val f = doubleArrayOf(
            tout - tin,
            toutAvg6 - tin,
            sin(2.0 * PI * hour / 24.0),
            cos(2.0 * PI * hour / 24.0),
            1.0
        )
        return dot(coeff, f)
    }
'''
text = replace_once(text, old_predict, new_predict, 'physical predictor')

old_equilibrium = '''    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {
        val exchange = coeff[0] + coeff[1]
        if (!exchange.isFinite() || abs(exchange) < 0.002) return null
        val sinIndex = if (coeff.size >= 6) 3 else 2
        val cosIndex = if (coeff.size >= 6) 4 else 3
        val biasIndex = if (coeff.size >= 6) 5 else 4
        // À l'équilibre air≈masse : le terme appris (T_mass-T_air) s'annule.
        val seasonal = coeff[sinIndex] * sin(2.0 * PI * hour / 24.0) +
            coeff[cosIndex] * cos(2.0 * PI * hour / 24.0) + coeff[biasIndex]
        val value = (coeff[0] * tout + coeff[1] * avg6 + seasonal) / exchange
        return value.takeIf { it.isFinite() }
    }
'''
new_equilibrium = '''    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {
        val kNow = coeff.getOrNull(0)?.coerceAtLeast(0.0) ?: return null
        val kSlow = coeff.getOrNull(1)?.coerceAtLeast(0.0) ?: return null
        val exchange = kNow + kSlow
        if (!exchange.isFinite() || exchange < 0.002) return null
        // À l'équilibre air≈masse. La correction horaire n'est volontairement PAS une
        // température d'équilibre : elle reste un petit résidu autour du flux physique.
        val value = (kNow * tout + kSlow * avg6) / exchange
        return value.takeIf { it.isFinite() }
    }
'''
text = replace_once(text, old_equilibrium, new_equilibrium, 'physical equilibrium')

ENGINE.write_text(text)

# Force calculated-curve coherence to see this as a new physical model.
text = POINTS.read_text()
text = replace_once(text, 'const val MODEL_VERSION = "thermal-rc-inertia-4"',
                    'const val MODEL_VERSION = "thermal-rc-inertia-5"', 'model version')
POINTS.write_text(text)

# Package version for a testable APK/AAB.
text = GRADLE.read_text()
text = replace_once(text, 'versionCode = 39', 'versionCode = 40', 'version code')
text = replace_once(text, 'versionName = "0.19.3"', 'versionName = "0.19.4"', 'version name')
GRADLE.write_text(text)

print('v0.19.4 applied: physical indoor gradient + forcing-driven inertia tangent')
