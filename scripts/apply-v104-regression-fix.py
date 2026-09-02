from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


# -----------------------------------------------------------------------------
# 1) Restore Lyon reconstruit as a VISUAL overlay only.
#    Internal weather reference still remains one reference/time series.
# -----------------------------------------------------------------------------
main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)
marker = "v0.10.2 : Lyon reconstruit redevient une couche visuelle comparative"
if marker not in main:
    old = '''    // v0.10 : measured / reconstructed / forecast restent sur la même sonde.\n    // Le capteur virtuel Lyon reconstruit est conservé en mémoire pour compatibilité\n    // du détail historique, mais n'est plus présenté comme une seconde sonde.\n    val chartSensors = sensors\n    val chartSampleMap = sampleMap\n'''
    new = '''    // v0.10.2 : Lyon reconstruit redevient une couche visuelle comparative.\n    // Il ne crée PAS une deuxième référence météo ni une deuxième série persistée :\n    // le pseudo-capteur n'existe que pour Superposition / graphique / inspecteur.\n    val chartSensors = sensors + lyonReconstructedSensor\n    val chartSampleMap = sampleMap + (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples)\n'''
    if old not in main:
        raise SystemExit("MainActivity: bloc chartSensors v0.10 introuvable")
    main = main.replace(old, new, 1)
    write(main_path, main)
    print("MainActivity: couche Lyon reconstruit restaurée")
else:
    print("MainActivity: v0.10.2 déjà appliqué")


# -----------------------------------------------------------------------------
# 2) Historical reconstruction diagnostics + stable forward-only initialization.
#    RC equation/calibration are intentionally untouched.
# -----------------------------------------------------------------------------
engine_path = "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
engine = read(engine_path)

if "val diagnostic: String? = null" not in engine:
    engine = engine.replace(
        '''data class ThermalWriteSummary(\n    val reconstructed: Int,\n    val forecast: Int,\n    val skippedSensors: Int,\n    val raccords: Int = 0,\n    val maxRaccordDrift: Double = 0.0\n)''',
        '''data class ThermalWriteSummary(\n    val reconstructed: Int,\n    val forecast: Int,\n    val skippedSensors: Int,\n    val raccords: Int = 0,\n    val maxRaccordDrift: Double = 0.0,\n    val diagnostic: String? = null\n)''',
        1,
    )
    engine = engine.replace(
        '''private data class ForwardFillSummary(\n    val created: Int = 0,\n    val raccords: Int = 0,\n    val maxDrift: Double = 0.0\n)''',
        '''private data class ForwardFillSummary(\n    val created: Int = 0,\n    val raccords: Int = 0,\n    val maxDrift: Double = 0.0,\n    val diagnostic: String? = null\n)''',
        1,
    )

new_reconstruct = r'''    fun reconstructHistory(
        reference: WeatherReference,
        requestedDays: Int,
        sensorId: Long? = null
    ): ThermalWriteSummary {
        val days = requestedDays.coerceIn(1, MAX_HISTORY_DAYS)
        var total = 0
        var skipped = 0
        var raccords = 0
        var maxDrift = 0.0
        var diagnostic: String? = null
        val targets = physicalSensors().filter { sensorId == null || it.id == sensorId }
        targets.forEach { sensor ->
            val model = runCatching { calibrate(sensor, reference) }.getOrNull()
            if (model == null || !model.acceptable) {
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
            if (!referenceCoverageReady(outside, startAt, first.timestamp)) {
                skipped++
                if (diagnostic == null) diagnostic = "Référence ${reference.city} encore trop trouée avant la première mesure intérieure."
                return@forEach
            }
            val outMap = outside.associateBy { hourBucket(it.timestamp) }

            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap)
            total += before.created
            raccords += before.raccords
            maxDrift = max(maxDrift, before.maxDrift)
            if (diagnostic == null && before.diagnostic != null) diagnostic = before.diagnostic

            val gaps = fillInteriorGapsForward(sensor, model, reference)
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
'''
pattern = re.compile(
    r'''    fun reconstructHistory\(\n        reference: WeatherReference,.*?\n    \}\n\n    /\*\* Prévision courte automatique H\+6''',
    re.S,
)
match = pattern.search(engine)
if not match:
    raise SystemExit("ThermalEngine: reconstructHistory introuvable")
engine = engine[:match.start()] + new_reconstruct + "\n    /** Prévision courte automatique H+6" + engine[match.end():]

new_before = r'''    private fun reconstructBeforeFirst(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        first: HourPoint,
        startAt: Long,
        outside: Map<Long, HourPoint>
    ): ForwardFillSummary {
        val start = hourBucket(startAt)
        val firstHour = hourBucket(first.timestamp)
        if (start >= firstHour) return ForwardFillSummary(diagnostic = "Période historique vide.")

        // v0.10.2 : on ne change PAS le modèle RC. On cherche seulement l'état intérieur
        // initial plausible qui, en faisant tourner CE MÊME modèle vers l'avant avec Lyon,
        // rejoint au mieux la première vraie mesure. Cela remplace l'équilibre algébrique
        // fragile qui pouvait refuser silencieusement toute reconstruction.
        val initial = estimateInitialStateForward(model, first, start, firstHour, outside)
            ?: return ForwardFillSummary(diagnostic = "Impossible d'initialiser un état thermique plausible avec ${reference.city}.")

        var current = initial.first
        var currentH = initial.second
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
            val next = current + predictDelta(model.coefficients, current, ext, extAvg6, stepHour)
            if (!plausibleIndoor(next)) {
                return ForwardFillSummary(created, 0, 0.0, "Propagation arrêtée avant dérive physique abusive (${round2(next)} °C).")
            }
            val outHum = outside[hourBucket(ts)]?.humidity ?: currentH
            currentH += 0.08 * (outHum - currentH)
            current = next
            ts += THERMAL_HOUR_MS
        }

        // Aucun raccord caché : l'écart à la première vraie mesure reste un diagnostic.
        val drift = abs(current - first.temperature)
        return ForwardFillSummary(created, 1, drift)
    }

    private fun estimateInitialStateForward(
        model: ThermalModel,
        first: HourPoint,
        start: Long,
        firstHour: Long,
        outside: Map<Long, HourPoint>
    ): Pair<Double, Double>? {
        val low = (first.temperature - 14.0).coerceAtLeast(5.0)
        val high = (first.temperature + 14.0).coerceAtMost(45.0)
        var candidate = low
        var bestStart: Double? = null
        var bestError = Double.POSITIVE_INFINITY

        while (candidate <= high + 1e-9) {
            var current = candidate
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
                val next = current + predictDelta(model.coefficients, current, ext, avg6, hour)
                if (!plausibleIndoor(next)) {
                    valid = false
                    break
                }
                current = next
                ts += THERMAL_HOUR_MS
            }
            if (valid && ts >= firstHour) {
                val error = abs(current - first.temperature)
                if (error < bestError) {
                    bestError = error
                    bestStart = candidate
                }
            }
            candidate += 0.25
        }

        val startTemp = bestStart ?: return null
        val startHumidity = outside[hourBucket(start)]?.humidity ?: first.humidity
        return startTemp to startHumidity
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

write(engine_path, engine)
print("ThermalEngine: initialisation forward + diagnostic appliqués")


# -----------------------------------------------------------------------------
# 3) Keep reconstruction result visible after chart reload.
# -----------------------------------------------------------------------------
ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)
ui_marker = "v0.10.2 : préserver le diagnostic de reconstruction"
if ui_marker not in ui:
    old = '''                            onSuccess = {\n                                info = "Historique : ${it.reconstructed} point(s) · ${it.raccords} raccord(s) · dérive max ${fmt(it.maxRaccordDrift)} °C · ${it.skippedSensors} refus"\n                                onDataChanged()\n                            },'''
    new = '''                            onSuccess = {\n                                // v0.10.2 : préserver le diagnostic de reconstruction pendant\n                                // le rechargement du graphique au lieu de le remplacer aussitôt.\n                                val detail = it.diagnostic?.let { d -> " · $d" }.orEmpty()\n                                info = "Historique : ${it.reconstructed} point(s) · ${it.raccords} raccord(s) · dérive max ${fmt(it.maxRaccordDrift)} °C · ${it.skippedSensors} refus$detail"\n                                suppressNextAuto = true\n                                onDataChanged()\n                            },'''
    if old not in ui:
        raise SystemExit("ThermalUi: bloc résultat historique introuvable")
    ui = ui.replace(old, new, 1)
    write(ui_path, ui)
    print("ThermalUi: diagnostic persistant appliqué")
else:
    print("ThermalUi: v0.10.2 déjà appliqué")


# -----------------------------------------------------------------------------
# 4) Version bump is generated by this patch as well, so CI compiles the right APK.
# -----------------------------------------------------------------------------
gradle_path = "app/build.gradle.kts"
gradle = read(gradle_path)
gradle = gradle.replace('versionCode = 20', 'versionCode = 21')
gradle = gradle.replace('versionName = "0.10.1"', 'versionName = "0.10.2"')
write(gradle_path, gradle)
print("Version: 0.10.2 / code 21")
