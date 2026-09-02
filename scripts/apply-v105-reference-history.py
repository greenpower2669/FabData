from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# 1) Measured-only physical bounds: reconstructed indoor history must never move
#    the anchor used to request the next weather-history extension.
# -----------------------------------------------------------------------------
data_path = "app/src/main/java/com/fabdata/app/DataLayer.kt"
data = read(data_path)
if "fun physicalMeasuredBounds()" not in data:
    marker = '''    fun existingSampleTimestamps(sensorId: Long, from: Long, to: Long): Set<Long> {\n'''
    method = '''    /** Bornes des seules vraies mesures intérieures (pas reconstruit/forecast). */\n    fun physicalMeasuredBounds(): LongRange? {\n        PointSourceStore.ensure(readableDatabase)\n        readableDatabase.rawQuery(\n            """\n            SELECT MIN(p.timestamp), MAX(p.timestamp)\n            FROM samples p\n            JOIN sensors s ON s.id = p.sensor_id\n            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp\n            WHERE s.stable_key NOT LIKE 'meteo-%'\n              AND s.stable_key NOT LIKE 'http-get-%'\n              AND (ps.source IS NULL OR ps.source='measured')\n            """.trimIndent(), null\n        ).use { c ->\n            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null\n            return c.getLong(0)..c.getLong(1)\n        }\n    }\n\n'''
    data = replace_once(data, marker, method + marker, "DataLayer physicalMeasuredBounds")
    write(data_path, data)
    print("DataLayer: bornes measured-only ajoutées")
else:
    print("DataLayer: physicalMeasuredBounds déjà présent")


# -----------------------------------------------------------------------------
# 2) Weather reference becomes the single visible/RC source of truth.
#    Official observations win; Open-Meteo historical is a reconstructed fallback.
# -----------------------------------------------------------------------------
weather_path = "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt"
weather = read(weather_path)

if "fun historyBounds(referenceKey: String)" not in weather:
    old = '''    fun clear(referenceKey: String) {\n        db.writableDatabase.delete("weather_reference_samples", "reference_key=?", arrayOf(referenceKey))\n    }\n'''
    new = '''    fun historyBounds(referenceKey: String): LongRange? {\n        db.readableDatabase.rawQuery(\n            "SELECT MIN(timestamp), MAX(timestamp) FROM weather_reference_samples WHERE reference_key=? AND source<>'forecast'",\n            arrayOf(referenceKey)\n        ).use { c ->\n            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null\n            return c.getLong(0)..c.getLong(1)\n        }\n    }\n\n    fun clear(referenceKey: String) {\n        db.writableDatabase.delete("weather_reference_samples", "reference_key=?", arrayOf(referenceKey))\n    }\n'''
    weather = replace_once(weather, old, new, "WeatherReferenceStore historyBounds")

if "data class WeatherReferenceCoverage" not in weather:
    marker = '''data class WeatherReferenceSyncResult(\n    val measured: Int,\n    val reconstructed: Int,\n    val forecast: Int,\n    val label: String\n)\n'''
    addition = marker + '''\ndata class WeatherReferenceCoverage(\n    val from: Long,\n    val to: Long,\n    val expectedHours: Int,\n    val presentHours: Int,\n    val measuredHours: Int,\n    val reconstructedHours: Int,\n    val coverage: Double,\n    val maxGapHours: Int\n) {\n    val ready: Boolean get() = coverage >= 0.90 && maxGapHours <= 3\n}\n\ndata class WeatherReferencePreparation(\n    val sync: WeatherReferenceSyncResult,\n    val coverage: WeatherReferenceCoverage,\n    val days: Int\n)\n'''
    weather = replace_once(weather, marker, addition, "WeatherReference data classes")

new_refresh = r'''    /**
     * Recharge uniquement la station sélectionnée.
     * v0.10.3 : weather_reference_samples EST la série de référence visible ET celle du RC.
     * Les observations officielles gardent la priorité ; Open-Meteo historique sert
     * seulement de reconstruction de secours pour obtenir une entrée longue/continue.
     */
    fun refreshSelected(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {
        store.keepOnly(reference.key)

        // Filet de sécurité historique public/modelisé. Ne peut jamais écraser measured.
        runCatching { fetchOpenMeteoHistory(reference, from, to) }
            .getOrDefault(emptyList())
            .forEach { store.upsert(reference.key, it) }

        if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
            val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
            db.querySamples(sensor.id, from, to, maxPoints = 30_000).forEach { p ->
                val source = PointSourceStore.sourceFor(db, sensor.id, p.timestamp)
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, source))
            }

            // Si un token existe, l'horaire officiel étend Lyon au-delà du seed embarqué.
            if (credentials.hasCredential()) {
                runCatching { fetchOfficialHourly(reference, from, to) }
                    .getOrDefault(emptyList())
                    .forEach { store.upsert(reference.key, it) }
            }

            lyonLab.queryOfficial(LyonSeriesKind.HOURLY, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
            }
            lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
            }
            lyonLab.reconstruct(from, to).points.forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.RECONSTRUCTED, 0.72))
            }
        } else {
            if (credentials.hasCredential()) {
                runCatching { fetchOfficialHourly(reference, from, to) }
                    .getOrDefault(emptyList())
                    .forEach { store.upsert(reference.key, it) }
            }
            reconstructShortGaps(reference.key, from, to)
        }

        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)
        val actual = store.query(reference.key, from, minOf(to, System.currentTimeMillis()))
        return WeatherReferenceSyncResult(
            measured = actual.count { it.source == PointSource.MEASURED },
            reconstructed = actual.count { it.source == PointSource.RECONSTRUCTED },
            forecast = forecast,
            label = reference.label
        )
    }

    /**
     * Prépare explicitement 30/60/90 jours AVANT la première vraie mesure intérieure.
     * 18 h supplémentaires sont chargées en amont : retard RC max 12 h + moyenne 6 h.
     */
    fun prepareHistory(reference: WeatherReference, requestedDays: Int): WeatherReferencePreparation {
        val days = requestedDays.coerceIn(1, 90)
        val indoor = db.physicalMeasuredBounds() ?: db.physicalSensorBounds() ?: db.globalTimeBounds()
            ?: error("Aucune donnée intérieure")
        val coreFrom = indoor.first - days.toLong() * 24L * hourMs
        val loadFrom = coreFrom - 18L * hourMs
        val loadTo = maxOf(indoor.last, System.currentTimeMillis() + 7L * hourMs)
        val sync = refreshSelected(reference, loadFrom, loadTo)
        val coverage = coverage(reference.key, loadFrom, indoor.first)
        return WeatherReferencePreparation(sync, coverage, days)
    }

    fun coverage(referenceKey: String, from: Long, to: Long): WeatherReferenceCoverage {
        val start = roundHour(from)
        val end = roundHour(to)
        if (end < start) return WeatherReferenceCoverage(from, to, 0, 0, 0, 0, 0.0, Int.MAX_VALUE)
        val points = store.query(referenceKey, from, to).filter { it.source != PointSource.FORECAST }
        val byHour = points.groupBy { roundHour(it.timestamp) }
            .filterKeys { it in start..end }
        val expected = (((end - start) / hourMs) + 1L).toInt().coerceAtLeast(1)
        val buckets = byHour.keys.sorted()
        val measured = byHour.values.count { values -> values.any { it.source == PointSource.MEASURED } }
        val reconstructed = byHour.values.count { values -> values.none { it.source == PointSource.MEASURED } }
        val coverage = byHour.size.toDouble() / expected.toDouble()
        val leading = buckets.firstOrNull()?.let { ((it - start) / hourMs).toInt().coerceAtLeast(0) } ?: expected
        val trailing = buckets.lastOrNull()?.let { ((end - it) / hourMs).toInt().coerceAtLeast(0) } ?: expected
        val internal = buckets.zipWithNext().maxOfOrNull { (a, b) ->
            (((b - a) / hourMs).toInt() - 1).coerceAtLeast(0)
        } ?: 0
        return WeatherReferenceCoverage(
            from = start,
            to = end,
            expectedHours = expected,
            presentHours = byHour.size,
            measuredHours = measured,
            reconstructedHours = reconstructed,
            coverage = coverage,
            maxGapHours = maxOf(leading, trailing, internal)
        )
    }

'''
pattern = re.compile(
    r'''    /\*\*\n     \* Recharge uniquement la station sélectionnée\..*?\n    /\*\* Rafraîchit seulement H\+6 sans retélécharger l'historique\. \*/''',
    re.S,
)
match = pattern.search(weather)
if not match:
    raise SystemExit("WeatherReferenceLayer: refreshSelected introuvable")
weather = weather[:match.start()] + new_refresh + "    /** Rafraîchit seulement H+6 sans retélécharger l'historique. */" + weather[match.end():]

if "private fun fetchOpenMeteoHistory" not in weather:
    marker = '''    private fun fetchOfficialHourly(reference: WeatherReference, from: Long, to: Long): List<WeatherReferencePoint> {\n'''
    method = r'''    private fun fetchOpenMeteoHistory(
        reference: WeatherReference,
        from: Long,
        to: Long
    ): List<WeatherReferencePoint> {
        val historyTo = minOf(to, System.currentTimeMillis() - hourMs)
        if (historyTo <= from) return emptyList()
        val startDate = Instant.ofEpochMilli(from).atZone(zone).toLocalDate()
        val endDate = Instant.ofEpochMilli(historyTo).atZone(zone).toLocalDate()
        if (startDate.isAfter(endDate)) return emptyList()
        val url = "https://archive-api.open-meteo.com/v1/archive" +
            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
            "&start_date=$startDate&end_date=$endDate" +
            "&hourly=temperature_2m%2Crelative_humidity_2m&timezone=Europe%2FParis"
        val raw = httpGetAnonymous(url)
        val hourly = JSONObject(raw).getJSONObject("hourly")
        val times = hourly.getJSONArray("time")
        val temps = hourly.getJSONArray("temperature_2m")
        val hums = hourly.getJSONArray("relative_humidity_2m")
        val out = mutableListOf<WeatherReferencePoint>()
        for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {
            val time = times.optString(i)
            val temp = temps.optDouble(i, Double.NaN)
            val hum = hums.optDouble(i, Double.NaN)
            if (!temp.isFinite() || !hum.isFinite()) continue
            val ts = runCatching {
                LocalDateTime.parse(time).atZone(zone).toInstant().toEpochMilli()
            }.getOrNull() ?: continue
            if (ts !in from..historyTo || temp !in -60.0..65.0 || hum !in 0.0..100.0) continue
            out += WeatherReferencePoint(ts, temp, hum, PointSource.RECONSTRUCTED, 0.68)
        }
        return out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }

    private fun httpGetAnonymous(url: String): String {
        val c = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 20_000
            readTimeout = 30_000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "FabData/0.10.3 Android")
            setRequestProperty("Accept", "application/json")
        }
        return try {
            val code = c.responseCode
            if (code !in 200..299) error("Historique météo HTTP $code")
            c.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

'''
    weather = replace_once(weather, marker, method + marker, "WeatherReference OpenMeteo history")

write(weather_path, weather)
print("WeatherReference: série unique + extension historique ajoutées")


# -----------------------------------------------------------------------------
# 3) Reconstruction RC: coverage check includes lag + 6h-average margin.
#    Model equation/calibration stays untouched.
# -----------------------------------------------------------------------------
engine_path = "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
engine = read(engine_path)
old = '''            if (!referenceCoverageReady(outside, startAt, first.timestamp)) {\n                skipped++\n                if (diagnostic == null) diagnostic = "Référence ${reference.city} encore trop trouée avant la première mesure intérieure."\n                return@forEach\n            }\n'''
new = '''            // v0.10.3 : la première heure du RC consomme déjà Tout(t-lag) et sa moyenne 6 h.\n            // La couverture doit donc être valide AVANT startAt, pas seulement à partir de startAt.\n            val requiredReferenceStart = startAt - (model.lagHours + 5L) * THERMAL_HOUR_MS\n            if (!referenceCoverageReady(outside, requiredReferenceStart, first.timestamp)) {\n                skipped++\n                if (diagnostic == null) diagnostic = "Référence ${reference.city} encore trop trouée avec la marge de retard du modèle."\n                return@forEach\n            }\n'''
if "requiredReferenceStart" not in engine:
    engine = replace_once(engine, old, new, "ThermalEngine lag coverage")
    write(engine_path, engine)
    print("ThermalEngine: marge lag+6h vérifiée")
else:
    print("ThermalEngine: marge lag déjà appliquée")


# -----------------------------------------------------------------------------
# 4) Thermal UI: explicit weather-history button and automatic preparation before
#    indoor reconstruction. What the user sees is what the RC consumes.
# -----------------------------------------------------------------------------
ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)

if "weatherHistoryDialog" not in ui:
    old = '''    var historyDialog by remember { mutableStateOf(false) }\n    var historyDays by remember { mutableIntStateOf(30) }\n'''
    new = '''    var weatherHistoryDialog by remember { mutableStateOf(false) }\n    var weatherHistoryDays by remember { mutableIntStateOf(30) }\n    var historyDialog by remember { mutableStateOf(false) }\n    var historyDays by remember { mutableIntStateOf(30) }\n'''
    ui = replace_once(ui, old, new, "ThermalUi weather states")

# Reload chart whenever the selected reference has actually been refreshed.
old = '''                if (triggerChartReload && forecast.forecast > 0) {\n                    suppressNextAuto = true\n                    onDataChanged()\n                }\n'''
new = '''                if (triggerChartReload) {\n                    suppressNextAuto = true\n                    onDataChanged()\n                }\n'''
if old in ui:
    ui = ui.replace(old, new, 1)

if "Étendre historique météo" not in ui:
    marker = '''            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {\n                OutlinedButton(\n                    onClick = { scope.launch { refresh(allHistory = true, triggerChartReload = true) } },\n'''
    addition = '''            OutlinedButton(\n                onClick = { weatherHistoryDialog = true },\n                enabled = !busy,\n                modifier = Modifier.fillMaxWidth()\n            ) { Text("Étendre historique météo") }\n\n'''
    ui = replace_once(ui, marker, addition + marker, "ThermalUi extend button")

# Estimer historique always prepares the chosen station first.
old_block = '''                                // Ordre strict : construire d'abord la référence extérieure complète,\n                                // puis seulement lancer le modèle intérieur dans le sens du temps.\n                                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()\n                                    ?: error("Aucune donnée intérieure")\n                                val from = bounds.first - historyDays.toLong() * 24L * 60L * 60L * 1000L - 18L * 60L * 60L * 1000L\n                                val to = maxOf(bounds.last, System.currentTimeMillis() + 7L * 60L * 60L * 1000L)\n                                manager.refreshSelected(reference, from, to)\n                                val checked = engine.status(reference, selectedSensorId)\n'''
new_block = '''                                // Ordre strict v0.10.3 : la référence visible/RC est préparée AVANT tout.\n                                val prepared = manager.prepareHistory(reference, historyDays)\n                                if (!prepared.coverage.ready) {\n                                    error("${reference.city} incomplet : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")\n                                }\n                                val checked = engine.status(reference, selectedSensorId)\n'''
if old_block in ui:
    ui = ui.replace(old_block, new_block, 1)

if "Étendre la référence météo ?" not in ui:
    marker = '''    if (historyDialog) {\n'''
    dialog = r'''    if (weatherHistoryDialog) {
        AlertDialog(
            onDismissRequest = { weatherHistoryDialog = false },
            title = { Text("Étendre la référence météo ?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("FabData va préparer ${reference.label} avant le modèle thermique. La courbe affichée sera exactement la série donnée au moteur RC.")
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(30, 60, 90).forEach { d ->
                            AssistChip(
                                onClick = { weatherHistoryDays = d },
                                label = { Text("$d jours") }
                            )
                        }
                    }
                    Text("Sélection : $weatherHistoryDays jours avant la première vraie mesure intérieure.", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                Button(onClick = {
                    weatherHistoryDialog = false
                    scope.launch {
                        busy = true
                        val result = withContext(Dispatchers.IO) {
                            runCatching { manager.prepareHistory(reference, weatherHistoryDays) }
                        }
                        busy = false
                        result.fold(
                            onSuccess = { prepared ->
                                val c = prepared.coverage
                                info = "${prepared.sync.label} · historique ${prepared.days} j · couverture ${(c.coverage * 100).toInt()} % · trou max ${c.maxGapHours} h · ${c.measuredHours} h réelles · ${c.reconstructedHours} h reconstruites"
                                suppressNextAuto = true
                                onDataChanged()
                            },
                            onFailure = { info = it.message ?: "Extension météo impossible" }
                        )
                    }
                }) { Text("Étendre") }
            },
            dismissButton = { TextButton(onClick = { weatherHistoryDialog = false }) { Text("Annuler") } }
        )
    }

'''
    ui = replace_once(ui, marker, dialog + marker, "ThermalUi weather history dialog")

write(ui_path, ui)
print("ThermalUi: extension météo + auto-préparation appliquées")


# -----------------------------------------------------------------------------
# 5) Main chart/overview reads weather_reference_samples directly.
#    This makes the visible long curve exactly identical to the RC input series.
# -----------------------------------------------------------------------------
main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)

if "weatherReferenceStore.historyBounds" not in main:
    old = '''            val all = db.physicalSensorBounds() ?: db.globalTimeBounds()\n'''
    new = '''            val physicalBounds = db.physicalSensorBounds() ?: db.globalTimeBounds()\n            val selectedWeatherReference = WeatherReferenceCatalog.byKey(WeatherReferencePrefs(context).selectedKey())\n            val weatherReferenceStore = WeatherReferenceStore(db)\n            val weatherBounds = weatherReferenceStore.historyBounds(selectedWeatherReference.key)\n            val all = when {\n                physicalBounds == null -> weatherBounds\n                weatherBounds == null -> physicalBounds\n                else -> minOf(physicalBounds.first, weatherBounds.first)..maxOf(physicalBounds.last, weatherBounds.last)\n            }\n'''
    main = replace_once(main, old, new, "MainActivity global weather bounds")

old = '''                val lyonReconstructed = lyonLab.reconstruct(chosen.first, chosen.last).points.map {\n                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, PointSource.RECONSTRUCTED, 0.72)\n                }\n'''
new = '''                // v0.10.3 : cette couche EST la série météo effectivement consommée par le RC.\n                val lyonReconstructed = weatherReferenceStore.query(\n                    selectedWeatherReference.key, chosen.first, chosen.last\n                ).filter { it.source != PointSource.FORECAST }.map {\n                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, it.source, it.confidence)\n                }\n'''
if old in main:
    main = main.replace(old, new, 1)

if "overviewWithReference" not in main:
    pattern = re.compile(r'''                val overview = s\.associate \{ sensor ->.*?\n                \}\n                val stat =''', re.S)
    m = pattern.search(main)
    if not m:
        raise SystemExit("MainActivity overview block introuvable")
    block = m.group(0)
    replacement = block[:-len("                val stat =")] + '''                val overviewReference = weatherReferenceStore.query(\n                    selectedWeatherReference.key, all.first, all.last\n                ).filter { it.source != PointSource.FORECAST }.map {\n                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, it.source, it.confidence)\n                }\n                val overviewWithReference = overview + (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference)\n                val stat ='''
    main = main[:m.start()] + replacement + main[m.end():]

main = main.replace(
    '''                    s, all, chosen, samples, overview, stat,\n''',
    '''                    s, all, chosen, samples, overviewWithReference, stat,\n''',
    1,
)

if "val visualReference = WeatherReferenceCatalog.byKey" not in main:
    old = '''    val lyonReconstructedSensor = Sensor(\n        id = LYON_RECONSTRUCTED_SENSOR_ID,\n        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,\n        name = "Lyon reconstruit",\n        room = "Lyon reconstruit",\n'''
    new = '''    val visualReference = WeatherReferenceCatalog.byKey(WeatherReferencePrefs(context).selectedKey())\n    val lyonReconstructedSensor = Sensor(\n        id = LYON_RECONSTRUCTED_SENSOR_ID,\n        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,\n        name = "${visualReference.city} reconstruit",\n        room = "${visualReference.city} reconstruit",\n'''
    main = replace_once(main, old, new, "MainActivity dynamic reference label")

main = main.replace(
    '''                    HistoryOverviewCard(\n                        sensors = sensors,\n                        sampleMap = overviewSampleMap,\n''',
    '''                    HistoryOverviewCard(\n                        sensors = chartSensors,\n                        sampleMap = overviewSampleMap,\n''',
    1,
)

write(main_path, main)
print("MainActivity: courbe visible = entrée RC")


# -----------------------------------------------------------------------------
# 6) Version bump.
# -----------------------------------------------------------------------------
gradle_path = "app/build.gradle.kts"
gradle = read(gradle_path)
gradle = gradle.replace('versionCode = 21', 'versionCode = 22')
gradle = gradle.replace('versionName = "0.10.2"', 'versionName = "0.10.3"')
write(gradle_path, gradle)
print("Version: 0.10.3 / code 22")
