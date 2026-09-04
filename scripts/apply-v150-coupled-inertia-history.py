#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str, label: str):
    p = ROOT / path
    text = p.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable dans {path}")
    p.write_text(text.replace(old, new, 1))


def require(path: str, needle: str, label: str):
    text = (ROOT / path).read_text()
    if needle not in text:
        raise SystemExit(f"{label}: invariant absent dans {path}")

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
replace_once(
    "app/build.gradle.kts",
    'versionCode = 29\n        versionName = "0.14.0"',
    'versionCode = 30\n        versionName = "0.15.0"',
    "version"
)

# Nouvelle provenance explicite : RC + inertie apprise.
replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    'const val MODEL_VERSION = "thermal-rc-mass-3"',
    'const val MODEL_VERSION = "thermal-rc-inertia-4"',
    "model version"
)

# ---------------------------------------------------------------------------
# Inertie : apprentissage toujours MEASURED ; affichage peut couvrir aussi le
# passé reconstruit, sans jamais utiliser ce passé pour apprendre les paramètres.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '''    val tauHours: Double,\n    val couplingPerHour: Double,\n    val confidence: Double,''',
    '''    val tauHours: Double,\n    val couplingPerHour: Double,\n    val outsideWeight: Double,\n    val confidence: Double,''',
    "inertia diagnostics outsideWeight"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '    fun estimate(reference: WeatherReference): ThermalInertiaEstimate? {',
    '    fun estimate(reference: WeatherReference, sensorId: Long? = null, includeHistory: Boolean = true): ThermalInertiaEstimate? {',
    "inertia estimate signature"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '        val key = "$measuredRevision|${reference.key}|$weatherSignature"',
    '        val key = "$measuredRevision|${reference.key}|$weatherSignature|${sensorId ?: -1L}|$includeHistory"',
    "inertia cache key"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '''        val sensors = db.sensors().filter { s ->\n            s.id >= 0L && !s.stableKey.startsWith("meteo-") && !s.stableKey.startsWith("http-get-")\n        }''',
    '''        val sensors = db.sensors().filter { s ->\n            (sensorId == null || s.id == sensorId) &&\n                s.id >= 0L && !s.stableKey.startsWith("meteo-") && !s.stableKey.startsWith("http-get-")\n        }''',
    "inertia selected sensor"
)

old_points = '''        val best = search(hours) ?: fallback(hours)\n        val confidence = confidence(best)\n        val points = hours.mapIndexed { index, h ->\n            SamplePoint(\n                sensorId = THERMAL_INERTIA_SENSOR_ID,\n                timestamp = h.timestamp,\n                temperature = round2(best.mass[index]),\n                humidity = h.humidity,\n                source = PointSource.RECONSTRUCTED,\n                confidence = confidence\n            )\n        }\n        if (points.isEmpty()) return null\n\n        val trend = trendPerDay(hours, best.mass)\n        val currentAir = hours.last().smoothAir\n        val currentFlux = best.kMass * (best.mass.last() - currentAir)'''

new_points = '''        val best = search(hours) ?: fallback(hours)\n        val confidence = confidence(best)\n\n        // Les paramètres (tau, couplages, poids extérieur) viennent EXCLUSIVEMENT\n        // des heures MEASURED propres ci-dessus. Pour l'affichage historique, on\n        // peut ensuite propager cet état lent sur la chronologie intérieure déjà\n        // reconstruite : cela ne réentraîne jamais le modèle sur ses propres sorties.\n        val outputHours: List<InertiaHour>\n        val outputMass: DoubleArray\n        if (includeHistory) {\n            val fullIndoor = allHourly(sensor.id)\n            val fullFrom = max(fullIndoor.firstOrNull()?.timestamp ?: from, weatherBounds.first)\n            val fullTo = min(fullIndoor.lastOrNull()?.timestamp ?: to, weatherBounds.last)\n            val fullOutside = outsideHourly(reference.key, fullFrom - 3L * INERTIA_HOUR_MS, fullTo)\n            val fullOutMap = fullOutside.associateBy { it.first }\n            val inRange = fullIndoor.filter { it.timestamp in fullFrom..fullTo }\n            val fullSmooth = smoothAir(inRange.map { it.temperature })\n            val built = inRange.mapIndexedNotNull { index, p ->\n                val outsideT = outsideAt(fullOutMap, p.timestamp) ?: return@mapIndexedNotNull null\n                InertiaHour(p.timestamp, p.temperature, p.humidity, outsideT, fullSmooth[index])\n            }\n            if (built.size >= 120) {\n                outputHours = built\n                outputMass = propagateDisplay(built, best.tauHours, best.outsideWeight)\n            } else {\n                outputHours = hours\n                outputMass = best.mass\n            }\n        } else {\n            outputHours = hours\n            outputMass = best.mass\n        }\n\n        val points = outputHours.mapIndexed { index, h ->\n            SamplePoint(\n                sensorId = THERMAL_INERTIA_SENSOR_ID,\n                timestamp = h.timestamp,\n                temperature = round2(outputMass[index]),\n                humidity = h.humidity,\n                source = PointSource.RECONSTRUCTED,\n                confidence = confidence\n            )\n        }\n        if (points.isEmpty()) return null\n\n        val trend = trendPerDay(outputHours, outputMass)\n        val currentAir = outputHours.last().smoothAir\n        val currentFlux = best.kMass * (outputMass.last() - currentAir)'''
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    old_points,
    new_points,
    "inertia display history"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '''            tauHours = best.tauHours,\n            couplingPerHour = best.kMass,\n            confidence = confidence,''',
    '''            tauHours = best.tauHours,\n            couplingPerHour = best.kMass,\n            outsideWeight = best.outsideWeight,\n            confidence = confidence,''',
    "inertia diagnostics constructor"
)

all_hourly = '''\n    private fun allHourly(sensorId: Long): List<SamplePoint> {\n        PointSourceStore.ensure(db.readableDatabase)\n        val raw = mutableListOf<SamplePoint>()\n        db.readableDatabase.rawQuery(\n            """\n            SELECT p.timestamp, p.temperature, p.humidity, ps.source\n            FROM samples p\n            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp\n            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source<>'forecast')\n            ORDER BY p.timestamp\n            """.trimIndent(),\n            arrayOf(sensorId.toString())\n        ).use { c ->\n            while (c.moveToNext()) {\n                val source = PointSource.fromDb(if (c.isNull(3)) null else c.getString(3))\n                raw += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2), source, 1.0)\n            }\n        }\n        return raw.groupBy { bucket(it.timestamp) }.map { (ts, values) ->\n            val priority = values.maxOf { it.source.priority }\n            val best = values.filter { it.source.priority == priority }\n            SamplePoint(\n                sensorId, ts, best.map { it.temperature }.average(), best.map { it.humidity }.average(),\n                best.first().source, best.map { it.confidence }.average()\n            )\n        }.sortedBy { it.timestamp }\n    }\n'''
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '    private fun measuredHourly(sensorId: Long): List<SamplePoint> {',
    all_hourly + '\n    private fun measuredHourly(sensorId: Long): List<SamplePoint> {',
    "inertia all hourly"
)

propagate_display = '''\n    private fun propagateDisplay(\n        hours: List<InertiaHour>,\n        tauHours: Double,\n        outsideWeight: Double\n    ): DoubleArray {\n        val mass = DoubleArray(hours.size)\n        mass[0] = hours[0].smoothAir * 0.78 + hours[0].outside * 0.22\n        for (i in 1 until hours.size) {\n            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())\n                .coerceIn(0.5, 24.0)\n            val target = hours[i - 1].smoothAir * (1.0 - outsideWeight) +\n                hours[i - 1].outside * outsideWeight\n            val alpha = 1.0 - exp(-dt / tauHours.coerceAtLeast(24.0))\n            mass[i] = (mass[i - 1] + alpha * (target - mass[i - 1])).coerceIn(-5.0, 50.0)\n        }\n        return mass\n    }\n'''
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '    private fun fitTwo(rows: List<DoubleArray>): Pair<Double, Double>? {',
    propagate_display + '\n    private fun fitTwo(rows: List<DoubleArray>): Pair<Double, Double>? {',
    "inertia display propagation"
)

# ---------------------------------------------------------------------------
# ThermalEngine : apprentissage à 6 variables avec T_mass - T_air.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''private data class TrainingRow(\n    val timestamp: Long,\n    val tin: Double,\n    val nextTin: Double,\n    val tout: Double,\n    val toutAvg6: Double,\n    val hourOfDay: Int,''',
    '''private data class TrainingRow(\n    val timestamp: Long,\n    val tin: Double,\n    val nextTin: Double,\n    val tout: Double,\n    val toutAvg6: Double,\n    val mass: Double,\n    val hourOfDay: Int,''',
    "training row mass"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''class ThermalEngine(\n    private val db: FabDataDb,\n    private val referenceStore: WeatherReferenceStore\n) {\n    private val zone = ZoneId.of("Europe/Paris")''',
    '''class ThermalEngine(\n    private val db: FabDataDb,\n    private val referenceStore: WeatherReferenceStore\n) {\n    private val zone = ZoneId.of("Europe/Paris")\n    private val inertiaEstimator = ThermalInertiaEstimator(db, referenceStore)''',
    "engine inertia estimator"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        val outMap = outside.associateBy { hourBucket(it.timestamp) }\n        val medianDeltas = buildingMedianDeltaByHour(measured.first().timestamp, measured.last().timestamp)\n\n        var best: ThermalModel? = null\n        for (lag in 0..12) {\n            val rows = buildTrainingRows(measured, outMap, medianDeltas, lag)''',
    '''        val outMap = outside.associateBy { hourBucket(it.timestamp) }\n        val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n            ?: error("Température inertielle estimée indisponible pour ${sensor.room}")\n        val inertiaMap = inertia.points.associateBy { hourBucket(it.timestamp) }\n        val medianDeltas = buildingMedianDeltaByHour(measured.first().timestamp, measured.last().timestamp)\n\n        var best: ThermalModel? = null\n        for (lag in 0..12) {\n            val rows = buildTrainingRows(measured, outMap, inertiaMap, medianDeltas, lag)''',
    "calibrate inertia input"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '            val driftRmse = validateLongHorizon(coeff, valid, profile)',
    '            val driftRmse = validateLongHorizon(coeff, valid, profile, inertia.diagnostics)',
    "long horizon inertia"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            val exchange = coeff[0] + coeff[1]\n            if (!exchange.isFinite() || exchange <= 0.002 || exchange >= 0.65) continue\n            val tau = (1.0 / exchange).coerceIn(1.0, 500.0)''',
    '''            val exchange = coeff[0] + coeff[1]\n            val massCoupling = coeff.getOrNull(2) ?: Double.NaN\n            if (!exchange.isFinite() || exchange <= 0.002 || exchange >= 0.65) continue\n            if (!massCoupling.isFinite() || massCoupling !in 0.001..0.25) continue\n            val tau = (1.0 / exchange).coerceIn(1.0, 500.0)''',
    "mass coupling guard"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''    private fun buildTrainingRows(\n        indoor: List<HourPoint>,\n        outside: Map<Long, HourPoint>,\n        medianDeltas: Map<Long, Double>,\n        lagHours: Int\n    ): List<TrainingRow> {''',
    '''    private fun buildTrainingRows(\n        indoor: List<HourPoint>,\n        outside: Map<Long, HourPoint>,\n        inertia: Map<Long, SamplePoint>,\n        medianDeltas: Map<Long, Double>,\n        lagHours: Int\n    ): List<TrainingRow> {''',
    "training rows signature"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            val avg6 = outsideAverage(outside, extTs, 6) ?: return@forEach\n            val hour = Instant.ofEpochMilli(a.timestamp).atZone(zone).hour\n            val features = doubleArrayOf(\n                tout - a.temperature,\n                avg6 - a.temperature,\n                sin(2.0 * PI * hour / 24.0),\n                cos(2.0 * PI * hour / 24.0),\n                1.0\n            )\n            rows += TrainingRow(a.timestamp, a.temperature, b.temperature, tout, avg6, hour, features, dTin)''',
    '''            val avg6 = outsideAverage(outside, extTs, 6) ?: return@forEach\n            val mass = inertia[hourBucket(a.timestamp)]?.temperature ?: return@forEach\n            val hour = Instant.ofEpochMilli(a.timestamp).atZone(zone).hour\n            val features = doubleArrayOf(\n                tout - a.temperature,\n                avg6 - a.temperature,\n                mass - a.temperature,\n                sin(2.0 * PI * hour / 24.0),\n                cos(2.0 * PI * hour / 24.0),\n                1.0\n            )\n            rows += TrainingRow(a.timestamp, a.temperature, b.temperature, tout, avg6, mass, hour, features, dTin)''',
    "training mass feature"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '        val n = 5',
    '        val n = rows.firstOrNull()?.features?.size ?: return null',
    "dynamic ridge dimension"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''    private fun predictDelta(coeff: DoubleArray, tin: Double, tout: Double, toutAvg6: Double, hour: Int): Double {\n        val f = doubleArrayOf(\n            tout - tin,\n            toutAvg6 - tin,\n            sin(2.0 * PI * hour / 24.0),\n            cos(2.0 * PI * hour / 24.0),\n            1.0\n        )\n        return dot(coeff, f)\n    }''',
    '''    private fun predictDelta(\n        coeff: DoubleArray,\n        tin: Double,\n        mass: Double,\n        tout: Double,\n        toutAvg6: Double,\n        hour: Int\n    ): Double {\n        val f = if (coeff.size >= 6) {\n            doubleArrayOf(\n                tout - tin,\n                toutAvg6 - tin,\n                mass - tin,\n                sin(2.0 * PI * hour / 24.0),\n                cos(2.0 * PI * hour / 24.0),\n                1.0\n            )\n        } else {\n            doubleArrayOf(\n                tout - tin,\n                toutAvg6 - tin,\n                sin(2.0 * PI * hour / 24.0),\n                cos(2.0 * PI * hour / 24.0),\n                1.0\n            )\n        }\n        return dot(coeff, f)\n    }''',
    "predict delta inertia"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        val learned = predictDelta(coeff, indoor, outside, outsideAvg6, hour)\n        val slowMemory = profile.massCoupling() * (mass - indoor)\n        return learned + slowMemory''',
    '''        val learned = predictDelta(coeff, indoor, mass, outside, outsideAvg6, hour)\n        if (coeff.size >= 6) return learned\n        val slowMemory = profile.massCoupling() * (mass - indoor)\n        return learned + slowMemory''',
    "mass aware learned inertia"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {\n        val exchange = coeff[0] + coeff[1]\n        if (!exchange.isFinite() || abs(exchange) < 0.002) return null\n        val seasonal = coeff[2] * sin(2.0 * PI * hour / 24.0) +\n            coeff[3] * cos(2.0 * PI * hour / 24.0) + coeff[4]\n        val value = (coeff[0] * tout + coeff[1] * avg6 + seasonal) / exchange\n        return value.takeIf { it.isFinite() }\n    }''',
    '''    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {\n        val exchange = coeff[0] + coeff[1]\n        if (!exchange.isFinite() || abs(exchange) < 0.002) return null\n        val sinIndex = if (coeff.size >= 6) 3 else 2\n        val cosIndex = if (coeff.size >= 6) 4 else 3\n        val biasIndex = if (coeff.size >= 6) 5 else 4\n        // À l'équilibre air≈masse : le terme appris (T_mass-T_air) s'annule.\n        val seasonal = coeff[sinIndex] * sin(2.0 * PI * hour / 24.0) +\n            coeff[cosIndex] * cos(2.0 * PI * hour / 24.0) + coeff[biasIndex]\n        val value = (coeff[0] * tout + coeff[1] * avg6 + seasonal) / exchange\n        return value.takeIf { it.isFinite() }\n    }''',
    "equilibrium inertia indices"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''    private fun validateLongHorizon(\n        coeff: DoubleArray,\n        rows: List<TrainingRow>,\n        profile: ThermalBuildingProfile\n    ): Double {''',
    '''    private fun validateLongHorizon(\n        coeff: DoubleArray,\n        rows: List<TrainingRow>,\n        profile: ThermalBuildingProfile,\n        inertia: ThermalInertiaDiagnostics\n    ): Double {''',
    "validate horizon signature"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        var current = selected.first().tin\n        var mass = current''',
    '''        var current = selected.first().tin\n        var mass = selected.first().mass''',
    "validate initial mass"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            if (!contiguous) {\n                current = row.tin\n                mass = row.tin\n            }''',
    '''            if (!contiguous) {\n                current = row.tin\n                mass = row.mass\n            }''',
    "validate reset mass"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '            val nextMass = advanceMass(profile, current, mass, row.toutAvg6)',
    '            val nextMass = advanceInertiaMass(inertia, current, mass, row.toutAvg6)',
    "validate learned mass advance"
)

advance_inertia = '''\n    private fun advanceInertiaMass(\n        diagnostics: ThermalInertiaDiagnostics,\n        indoor: Double,\n        mass: Double,\n        outsideAvg: Double\n    ): Double {\n        val w = diagnostics.outsideWeight.coerceIn(0.02, 0.45)\n        val tau = diagnostics.tauHours.coerceIn(24.0, 1440.0)\n        val target = indoor * (1.0 - w) + outsideAvg * w\n        return mass + (target - mass) / tau\n    }\n'''
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '    private fun massAwareDelta(',
    advance_inertia + '\n    private fun massAwareDelta(',
    "engine learned mass advance helper"
)

# Reconstruction historique : aucune reconstruction sans modèle inertiel appris.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            if (model == null || !model.acceptableForHistory) {\n                skipped++\n                if (diagnostic == null) diagnostic = "Modèle de ${sensor.room} non validé pour la reconstruction."\n                return@forEach\n            }\n            val measured = measuredHourly(sensor.id)''',
    '''            if (model == null || !model.acceptableForHistory) {\n                skipped++\n                if (diagnostic == null) diagnostic = "Modèle de ${sensor.room} non validé pour la reconstruction."\n                return@forEach\n            }\n            val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n            if (inertia == null) {\n                skipped++\n                if (diagnostic == null) diagnostic = "Température inertielle de ${sensor.room} indisponible : reconstruction refusée."\n                return@forEach\n            }\n            val measured = measuredHourly(sensor.id)''',
    "mandatory inertia reconstruction"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap, profile, progress)',
    '            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap, profile, inertia, progress)',
    "reconstruct before inertia call"
)
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '            val gaps = fillInteriorGapsForward(sensor, model, reference, profile, progress)',
    '            val gaps = fillInteriorGapsForward(sensor, model, reference, profile, inertia, progress)',
    "gap inertia call"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        profile: ThermalBuildingProfile,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {\n        val start = hourBucket(startAt)''',
    '''        profile: ThermalBuildingProfile,\n        inertia: ThermalInertiaEstimate,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {\n        val start = hourBucket(startAt)''',
    "reconstruct before signature"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '        val initial = estimateInitialStateForward(model, first, start, firstHour, outside, profile)',
    '        val initial = estimateInitialStateForward(model, first, start, firstHour, outside, profile, inertia)',
    "initial state inertia call"
)

# This exact text occurs in reconstructBeforeFirst after validate replacement already changed another occurrence.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '            val nextMass = advanceMass(profile, current, currentMass, extAvg6)',
    '            val nextMass = advanceInertiaMass(inertia.diagnostics, current, currentMass, extAvg6)',
    "history learned mass advance"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            "État masse initiale ${round2(initial.third)} °C · ${profile.summary()}"''',
    '''            "État inertiel initial ${round2(initial.third)} °C · τ ${round2(inertia.diagnostics.tauHours)} h · couplage appris"''',
    "history diagnostic inertia"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        outside: Map<Long, HourPoint>,\n        profile: ThermalBuildingProfile\n    ): Triple<Double, Double, Double>? {''',
    '''        outside: Map<Long, HourPoint>,\n        profile: ThermalBuildingProfile,\n        inertia: ThermalInertiaEstimate\n    ): Triple<Double, Double, Double>? {''',
    "initial state signature"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        val initialMass = initialMassTemperature(profile, start, firstHour, outside) ?: return null\n        val low = (initialMass - 7.0).coerceAtLeast(5.0)''',
    '''        val initialMass = initialMassTemperature(profile, start, firstHour, outside) ?: return null\n        val targetMassAtFirst = inertia.points.minByOrNull { abs(it.timestamp - firstHour) }?.temperature\n        val low = (initialMass - 7.0).coerceAtLeast(5.0)''',
    "target learned mass"
)

# second advanceMass in initial-state search
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '                val nextMass = advanceMass(profile, current, mass, avg6)',
    '                val nextMass = advanceInertiaMass(inertia.diagnostics, current, mass, avg6)',
    "initial state learned mass advance"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''                val error = abs(current - first.temperature) + 0.035 * abs(candidate - initialMass)''',
    '''                val massError = targetMassAtFirst?.let { abs(mass - it) } ?: 0.0\n                val error = abs(current - first.temperature) +\n                    0.20 * massError + 0.035 * abs(candidate - initialMass)''',
    "initial state two-wolf raccord"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        reference: WeatherReference,\n        profile: ThermalBuildingProfile,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {\n        val measured = measuredHourly(sensor.id)''',
    '''        reference: WeatherReference,\n        profile: ThermalBuildingProfile,\n        inertia: ThermalInertiaEstimate,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {\n        val measured = measuredHourly(sensor.id)''',
    "gap signature inertia"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            var current = left.temperature\n            var currentH = left.humidity\n            var currentMass = left.temperature''',
    '''            var current = left.temperature\n            var currentH = left.humidity\n            var currentMass = inertia.points\n                .minByOrNull { abs(it.timestamp - left.timestamp) }\n                ?.takeIf { abs(it.timestamp - left.timestamp) <= 3L * THERMAL_HOUR_MS }\n                ?.temperature ?: left.temperature''',
    "gap initial inertia"
)

# second history/gap advanceMass occurrence
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '                val nextMass = advanceMass(profile, current, currentMass, avg6)',
    '                val nextMass = advanceInertiaMass(inertia.diagnostics, current, currentMass, avg6)',
    "gap learned mass advance"
)

# refreshExistingReconstructions gap-only path
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''                val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()\n                if (model == null || !model.acceptableForHistory) { skipped++; return@forEach }\n                val r = fillInteriorGapsForward(sensor, model, reference, profile)''',
    '''                val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()\n                if (model == null || !model.acceptableForHistory) { skipped++; return@forEach }\n                val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n                    ?: run { skipped++; return@forEach }\n                val r = fillInteriorGapsForward(sensor, model, reference, profile, inertia)''',
    "refresh gaps inertia"
)

# Forecast must use the same learned latent state once the model has 6 coefficients.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            val model = runCatching { calibrate(sensor, reference, profile, preferLongHorizon = true) }.getOrNull()\n            if (model == null || !model.acceptableForForecast) { skipped++; return@forEach }\n            val measured = measuredHourly(sensor.id)''',
    '''            val model = runCatching { calibrate(sensor, reference, profile, preferLongHorizon = true) }.getOrNull()\n            if (model == null || !model.acceptableForForecast) { skipped++; return@forEach }\n            val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n                ?: run { skipped++; return@forEach }\n            val measured = measuredHourly(sensor.id)''',
    "forecast inertia requirement"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '            var currentMass = estimateCurrentMass(profile, measured, outMap)',
    '''            var currentMass = inertia.points.minByOrNull { abs(it.timestamp - latest.timestamp) }\n                ?.temperature ?: inertia.diagnostics.currentC''',
    "forecast current inertia"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '                val nextMass = advanceMass(profile, currentT, currentMass, avg6)',
    '                val nextMass = advanceInertiaMass(inertia.diagnostics, currentT, currentMass, avg6)',
    "forecast learned mass advance"
)

# ---------------------------------------------------------------------------
# UI : le choix de sonde du modèle est persistant et pilote aussi la courbe inertielle.
# L'extension météo déclenche automatiquement le bâtiment pour la même profondeur.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''    val profileStore = remember { ThermalProfileStore(context) }\n    var profile by remember { mutableStateOf(profileStore.load()) }''',
    '''    val profileStore = remember { ThermalProfileStore(context) }\n    val modelSensorPrefs = remember {\n        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)\n    }\n    var profile by remember { mutableStateOf(profileStore.load()) }''',
    "thermal sensor prefs"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '    var selectedSensorId by remember { mutableStateOf<Long?>(null) }',
    '''    var selectedSensorId by remember {\n        mutableStateOf(modelSensorPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L })\n    }''',
    "load selected model sensor"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                    selectedSensorId = thermalStatus.preferred?.sensor?.id\n                }''',
    '''                    selectedSensorId = thermalStatus.preferred?.sensor?.id\n                    selectedSensorId?.let { modelSensorPrefs.edit().putLong("selected_sensor_id", it).apply() }\n                }''',
    "persist automatic sensor"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                                    selectedSensorId = selectable[next].sensor.id\n                                }''',
    '''                                    selectedSensorId = selectable[next].sensor.id\n                                    modelSensorPrefs.edit().putLong("selected_sensor_id", selectable[next].sensor.id).apply()\n                                }''',
    "persist previous sensor"
)
# same block occurs a second time for ▶
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                                    selectedSensorId = selectable[next].sensor.id\n                                }''',
    '''                                    selectedSensorId = selectable[next].sensor.id\n                                    modelSensorPrefs.edit().putLong("selected_sensor_id", selectable[next].sensor.id).apply()\n                                }''',
    "persist next sensor"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    ') { Text("Étendre historique météo") }',
    ') { Text("Étendre historique météo + bâtiment") }',
    "combined history button"
)
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '            title = { Text("Étendre la référence météo ?") },',
    '            title = { Text("Étendre l’historique complet ?") },',
    "combined history dialog title"
)
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '                    Text("FabData va préparer ${reference.label} avant le modèle thermique. La courbe affichée sera exactement la série donnée au moteur RC.")',
    '                    Text("FabData prépare automatiquement les deux petits loups : météo extérieure + inertie bâtiment, puis reconstruit l’air intérieur sur la même profondeur. Pas de courbe historique intérieure sans inertie.")',
    "combined history explanation"
)

old_weather_action = '''                        val result = withContext(Dispatchers.IO) {\n                            runCatching { manager.prepareHistory(reference, weatherHistoryDays) }\n                        }\n                        busy = false\n                        result.fold(\n                            onSuccess = { prepared ->\n                                val c = prepared.coverage\n                                info = "${prepared.sync.label} · historique ${prepared.days} j · couverture ${(c.coverage * 100).toInt()} % · trou max ${c.maxGapHours} h · ${c.measuredHours} h réelles · ${c.reconstructedHours} h reconstruites"\n                                suppressNextAuto = true\n                                onDataChanged()\n                            },\n                            onFailure = { info = it.message ?: "Extension météo impossible" }\n                        )'''
new_weather_action = '''                        val result = withContext(Dispatchers.IO) {\n                            runCatching {\n                                val prepared = manager.prepareHistory(reference, weatherHistoryDays)\n                                if (!prepared.coverage.ready) {\n                                    error("${reference.city} incomplet : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")\n                                }\n                                val checked = engine.status(reference, selectedSensorId, profile)\n                                if (!checked.canReconstruct) error(checked.message)\n                                val activeId = selectedSensorId ?: checked.preferred?.sensor?.id\n                                val activeModel = checked.preferred?.model?.takeIf { it.sensorId == activeId }\n                                val summary = engine.reconstructHistory(\n                                    reference = reference,\n                                    requestedDays = weatherHistoryDays,\n                                    sensorId = activeId,\n                                    profile = profile,\n                                    precalibratedModel = activeModel\n                                ) { p ->\n                                    scope.launch {\n                                        info = if (p.total > 0) {\n                                            val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)\n                                            "${p.stage} · $percent % · ${p.changed} point(s) écrit(s)"\n                                        } else p.stage\n                                        if (p.total > 0 && p.processed > 0) {\n                                            suppressNextAuto = true\n                                            onDataChanged()\n                                        }\n                                    }\n                                }\n                                prepared to summary\n                            }\n                        }\n                        busy = false\n                        result.fold(\n                            onSuccess = { (prepared, summary) ->\n                                val c = prepared.coverage\n                                val detail = summary.diagnostic?.let { d -> " · $d" }.orEmpty()\n                                info = "Deux petits loups prêts · météo ${prepared.days} j ${(c.coverage * 100).toInt()} % · bâtiment ${summary.reconstructed} point(s) · ${summary.raccords} raccord(s)$detail"\n                                suppressNextAuto = true\n                                onDataChanged()\n                            },\n                            onFailure = { info = it.message ?: "Extension météo + bâtiment impossible" }\n                        )'''
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    old_weather_action,
    new_weather_action,
    "combined weather+building action"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                "Garde-fou : moins de 16 jours réels = aucune reconstruction historique. Au-delà, toutes les données réelles propres disponibles sont utilisées.",''',
    '''                "Garde-fou : apprentissage uniquement sur MEASURED propres. Clim probable, fenêtre, saut brutal ou donnée douteuse restent visibles mais sont exclues de l’apprentissage. Météo + inertie sont obligatoires pour prolonger le passé.",''',
    "training guard text"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '                    Text("Des données antérieures semblent manquer. FabData peut estimer l\'historique thermique du bâtiment avec le modèle validé.")',
    '                    Text("FabData prolonge ensemble la météo, l’état inertiel du bâtiment puis l’air intérieur. Les paramètres sont appris uniquement sur les mesures réelles propres.")',
    "history dialog two wolves"
)

# Main graph inertia uses the persisted model sensor selected by the tourniquet.
replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '                val inertia = runCatching { inertiaEstimator.estimate(selectedWeatherReference) }.getOrNull()',
    '''                val modelSensorId = context\n                    .getSharedPreferences("fabdata_thermal_model", Context.MODE_PRIVATE)\n                    .getLong("selected_sensor_id", -1L)\n                    .takeIf { it >= 0L }\n                val inertia = runCatching {\n                    inertiaEstimator.estimate(selectedWeatherReference, modelSensorId, includeHistory = true)\n                }.getOrNull()''',
    "main graph selected inertia sensor"
)

# Inertial UI no longer claims read-only observation: learning remains measured-only,
# but the validated latent state is now one of the two mandatory history drivers.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalExperimentUi.kt",
    '''                "Observation uniquement : mesures intérieures réelles + météo explicative. Cette courbe ne participe ni à la reconstruction ni à la prévision.",''',
    '''                "Apprise uniquement sur les points MEASURED propres. Clim, fenêtres probables et données douteuses restent visibles mais ne forment pas le modèle. Cette inertie accompagne désormais la météo pour prolonger l’historique.",''',
    "inertia UI role"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalExperimentUi.kt",
    '''                    "τ ≈ ${formatTau(d.tauHours)} · couplage air ↔ masse ${d.couplingLabel} · confiance ${d.confidenceLabel} ${(d.confidence * 100).toInt()} %",''',
    '''                    "τ ≈ ${formatTau(d.tauHours)} · extérieur inertiel ${(d.outsideWeight * 100).toInt()} % · couplage air ↔ masse ${d.couplingLabel} · confiance ${d.confidenceLabel} ${(d.confidence * 100).toInt()} %",''',
    "inertia outside weight UI"
)

# ---------------------------------------------------------------------------
# Safety checks: source priority and measured data core are intentionally untouched.
# ---------------------------------------------------------------------------
require("app/src/main/java/com/fabdata/app/ThermalEngine.kt", "mass - a.temperature", "mass feature")
require("app/src/main/java/com/fabdata/app/ThermalEngine.kt", "includeHistory = false", "measured-only inertia training")
require("app/src/main/java/com/fabdata/app/ThermalEngine.kt", "Température inertielle de ${sensor.room} indisponible : reconstruction refusée.", "mandatory inertia")
require("app/src/main/java/com/fabdata/app/ThermalUi.kt", "Étendre historique météo + bâtiment", "combined history UI")
require("app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt", "private fun allHourly", "inertia history display")
require("app/src/main/java/com/fabdata/app/PointSourceLayer.kt", 'MODEL_VERSION = "thermal-rc-inertia-4"', "provenance model")

print("FabData v0.15.0 coupled inertia/history patch applied")
