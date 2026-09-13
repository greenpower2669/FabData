from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one old occurrence, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Version + WorkManager dependency
# ---------------------------------------------------------------------------
build_path = "app/build.gradle.kts"
build = read(build_path)
build = once(
    build,
    'versionCode = 57\n        versionName = "0.23.0"',
    'versionCode = 58\n        versionName = "0.23.1"',
    "version bump",
)
build = once(
    build,
    '    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")\n',
    '    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")\n'
    '    implementation("androidx.work:work-runtime-ktx:2.10.1")\n',
    "workmanager dependency",
)
write(build_path, build)


# ---------------------------------------------------------------------------
# Forecast memory trigger: idempotent under concurrent callers.
# ---------------------------------------------------------------------------
overlay_path = "app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt"
overlay = read(overlay_path)
overlay = once(
    overlay,
    '''        sql.execSQL("DROP TRIGGER IF EXISTS $TRIGGER")
        sql.execSQL(
            """
            CREATE TRIGGER $TRIGGER
''',
    '''        // Normal reads may call ensure() concurrently (UI, adaptive layer, WorkManager).
        // Never DROP/CREATE here: CREATE IF NOT EXISTS is atomic/idempotent for this schema.
        // A future trigger definition change must use an explicit versioned migration.
        sql.execSQL(
            """
            CREATE TRIGGER IF NOT EXISTS $TRIGGER
''',
    "idempotent forecast trigger",
)
write(overlay_path, overlay)


# ---------------------------------------------------------------------------
# Collect provider forecasts to H+48 independently from what the user displays.
# ---------------------------------------------------------------------------
weather_path = "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt"
weather = read(weather_path)
weather = once(
    weather,
    '''    /** Rafraîchit seulement H+6 sans retélécharger l'historique. */
    fun refreshForecast(reference: WeatherReference): Int {
        val now = System.currentTimeMillis()
        val oldForecasts = store.query(reference.key, now - hourMs, now + 12L * hourMs)
''',
    '''    /**
     * Rafraîchit uniquement le futur météo sans retélécharger l'historique.
     * La collecte reste volontairement plus large que l'affichage : H+48 est archivé
     * même si l'utilisateur regarde seulement H+3/H+6. Ainsi H+24 existe réellement
     * avant d'être remplacé par une émission plus récente.
     */
    fun refreshForecast(reference: WeatherReference): Int {
        val now = System.currentTimeMillis()
        val oldForecasts = store.query(reference.key, now - hourMs, now + 50L * hourMs)
''',
    "forecast refresh horizon",
)
weather = once(
    weather,
    '            "&hourly=temperature_2m,relative_humidity_2m&forecast_days=2&timezone=Europe%2FParis"',
    '            "&hourly=temperature_2m,relative_humidity_2m&forecast_days=3&timezone=Europe%2FParis"',
    "forecast provider days",
)
weather = once(
    weather,
    '        val end = now + 6L * hourMs + 70L * 60L * 1000L',
    '        val end = now + 48L * hourMs + 70L * 60L * 1000L',
    "forecast keep H48",
)
write(weather_path, weather)


# ---------------------------------------------------------------------------
# Durable UI preferences: every user orientation choice survives data growth.
# ---------------------------------------------------------------------------
ui_path = "app/src/main/java/com/fabdata/app/UiPreferenceStore.kt"
ui = read(ui_path)
ui = once(
    ui,
    '''    fun wideCenter(): Long? = if (prefs.contains("wide_center")) prefs.getLong("wide_center", 0L) else null
    fun saveWideCenter(value: Long) { prefs.edit().putLong("wide_center", value).apply() }
}
''',
    '''    fun wideCenter(): Long? = if (prefs.contains("wide_center")) prefs.getLong("wide_center", 0L) else null
    fun saveWideCenter(value: Long) { prefs.edit().putLong("wide_center", value).apply() }

    fun selectedTimestamp(): Long? = nullableLong("selected_timestamp")
    fun saveSelectedTimestamp(value: Long?) = saveNullableLong("selected_timestamp", value)

    fun wideOverviewRange(): LongRange? = loadRange("wide_overview_range")
    fun saveWideOverviewRange(value: LongRange?) = saveRange("wide_overview_range", value)

    fun explorationOverviewRange(): LongRange? = loadRange("exploration_overview_range")
    fun saveExplorationOverviewRange(value: LongRange?) = saveRange("exploration_overview_range", value)

    private fun nullableLong(key: String): Long? =
        if (prefs.contains(key)) prefs.getLong(key, 0L) else null

    private fun saveNullableLong(key: String, value: Long?) {
        prefs.edit().apply {
            if (value == null) remove(key) else putLong(key, value)
        }.apply()
    }

    private fun loadRange(key: String): LongRange? {
        val startKey = "$key:start"
        val endKey = "$key:end"
        if (!prefs.contains(startKey) || !prefs.contains(endKey)) return null
        val start = prefs.getLong(startKey, 0L)
        val end = prefs.getLong(endKey, 0L)
        return if (end > start) start..end else null
    }

    private fun saveRange(key: String, value: LongRange?) {
        prefs.edit().apply {
            val startKey = "$key:start"
            val endKey = "$key:end"
            if (value == null) {
                remove(startKey)
                remove(endKey)
            } else {
                putLong(startKey, value.first)
                putLong(endKey, value.last)
            }
        }.apply()
    }
}
''',
    "extended durable UI prefs",
)
write(ui_path, ui)


# ---------------------------------------------------------------------------
# Adaptive UI: keep useful last values, but clearly mark them stale and avoid SQL wall.
# ---------------------------------------------------------------------------
adaptive_ui_path = "app/src/main/java/com/fabdata/app/ForecastAdaptiveUi.kt"
adaptive_ui = read(adaptive_ui_path)
adaptive_ui = once(
    adaptive_ui,
    '''            error?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
''',
    '''            error?.let { raw ->
                val short = raw.replace('\\n', ' ').replace(Regex("\\s+"), " ").trim().take(220)
                val prefix = if (summary != null) "Dernières valeurs connues · actualisation impossible : " else "Actualisation impossible : "
                Text(prefix + short, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
''',
    "adaptive stale error label",
)
write(adaptive_ui_path, adaptive_ui)


# ---------------------------------------------------------------------------
# Main UI: future navigation + synchronous preference restore + range persistence.
# ---------------------------------------------------------------------------
main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)

main = once(
    main,
    '''        val db = FabDataDb(applicationContext)
        val initialUri = intent?.data
''',
    '''        val db = FabDataDb(applicationContext)
        // Scientific memory must not depend on how many future hours are currently visible.
        ForecastArchiveWorker.schedule(applicationContext)
        val initialUri = intent?.data
''',
    "schedule background forecast capture",
)

main = once(
    main,
    '''private const val OVERVIEW_LOD_MONTH_MS = 30L * 24L * 60L * 60L * 1000L
private const val LYON_DETAIL_GAP_MS = 90L * 60L * 1000L
''',
    '''private const val OVERVIEW_LOD_MONTH_MS = 30L * 24L * 60L * 60L * 1000L
private const val FORECAST_DISPLAY_FUTURE_MS = 48L * 60L * 60L * 1000L
private const val LYON_DETAIL_GAP_MS = 90L * 60L * 1000L
''',
    "future display constant",
)

main = once(
    main,
    '''    var wideOverviewRange by remember { mutableStateOf<LongRange?>(null) }
    var explorationOverviewRange by remember { mutableStateOf<LongRange?>(null) }
''',
    '''    var wideOverviewRange by remember { mutableStateOf(uiPrefs.wideOverviewRange()) }
    var explorationOverviewRange by remember { mutableStateOf(uiPrefs.explorationOverviewRange()) }
''',
    "restore cascade ranges",
)
main = once(
    main,
    '    var selectedTimestamp by remember { mutableStateOf<Long?>(null) }',
    '    var selectedTimestamp by remember { mutableStateOf(uiPrefs.selectedTimestamp()) }',
    "restore selected timestamp",
)

main = once(
    main,
    '''    // v0.22.0 : les choix utilisateur survivent aux recréations d'Activity et aux redémarrages.
    // Les écritures de navigation sont légèrement temporisées pour éviter de marteler les prefs pendant un glisser.
    LaunchedEffect(preset) { uiPrefs.saveTimePresetName(preset.name) }
    LaunchedEffect(showAllAnnotations) { uiPrefs.saveShowAllAnnotations(showAllAnnotations) }
    LaunchedEffect(windowCenterTimestamp, customViewSpanMs) {
        delay(250L)
        uiPrefs.saveWindowCenter(windowCenterTimestamp)
        uiPrefs.saveCustomViewSpan(customViewSpanMs)
    }
''',
    '''    // v0.23.1 : les choix utilisateur sont écrits dès leur validation. Les états de
    // navigation ne sont plus perdus si une nouvelle mesure étend les bornes pendant l'usage.
    LaunchedEffect(preset) { uiPrefs.saveTimePresetName(preset.name) }
    LaunchedEffect(showAllAnnotations) { uiPrefs.saveShowAllAnnotations(showAllAnnotations) }
    LaunchedEffect(windowCenterTimestamp, customViewSpanMs) {
        uiPrefs.saveWindowCenter(windowCenterTimestamp)
        uiPrefs.saveCustomViewSpan(customViewSpanMs)
    }
    LaunchedEffect(wideOverviewRange, explorationOverviewRange) {
        uiPrefs.saveWideOverviewRange(wideOverviewRange)
        uiPrefs.saveExplorationOverviewRange(explorationOverviewRange)
    }
    LaunchedEffect(selectedTimestamp) { uiPrefs.saveSelectedTimestamp(selectedTimestamp) }
''',
    "durable main UI effects",
)

main = once(
    main,
    '''            val all = when {
                physicalBounds == null -> weatherBounds
                weatherBounds == null -> physicalBounds
                else -> minOf(physicalBounds.first, weatherBounds.first)..maxOf(physicalBounds.last, weatherBounds.last)
            }
            val chosen = all?.let { bounds ->
''',
    '''            val historicalBounds = when {
                physicalBounds == null -> weatherBounds
                weatherBounds == null -> physicalBounds
                else -> minOf(physicalBounds.first, weatherBounds.first)..maxOf(physicalBounds.last, weatherBounds.last)
            }
            // Display bounds and acquisition bounds are deliberately independent. The user
            // may show only 1 h while the app still captures H+48. A 48 h detail view centered
            // on now naturally shows roughly the previous day + the next day.
            val nowForDisplay = System.currentTimeMillis()
            val all = historicalBounds?.let { bounds ->
                bounds.first..maxOf(bounds.last, nowForDisplay + FORECAST_DISPLAY_FUTURE_MS)
            }
            val chosen = all?.let { bounds ->
''',
    "future-aware global bounds",
)
main = once(
    main,
    '''                    val defaultCenter = bounds.last - requested / 2L
                    val center = (windowCenterTimestamp ?: defaultCenter).coerceIn(bounds.first, bounds.last)
''',
    '''                    val defaultCenter = nowForDisplay.coerceIn(bounds.first, bounds.last)
                    val center = (windowCenterTimestamp ?: defaultCenter).coerceIn(bounds.first, bounds.last)
''',
    "detail default center now",
)

# Restore curve visibility before first frame instead of default-then-async-restored flicker.
main = once(
    main,
    '''        sensors.forEach { sensor ->
            if (!showTemp.containsKey(sensor.id)) {
                showTemp[sensor.id] = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                    loaded.lyonReconstructedSamples.isEmpty()
                } else true
            }
            if (!showHumidity.containsKey(sensor.id)) showHumidity[sensor.id] = false
        }
''',
    '''        sensors.forEach { sensor ->
            if (!showTemp.containsKey(sensor.id)) {
                val defaultVisible = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                    loaded.lyonReconstructedSamples.isEmpty()
                } else true
                showTemp[sensor.id] = uiPrefs.curveTemperature(sensor.stableKey) ?: defaultVisible
            }
            if (!showHumidity.containsKey(sensor.id)) {
                showHumidity[sensor.id] = uiPrefs.curveHumidity(sensor.stableKey) ?: false
            }
        }
''',
    "physical curve prefs synchronous restore",
)
main = once(
    main,
    '        if (!showTemp.containsKey(WEATHER_OFFICIAL_SENSOR_ID)) showTemp[WEATHER_OFFICIAL_SENSOR_ID] = true',
    '        if (!showTemp.containsKey(WEATHER_OFFICIAL_SENSOR_ID)) showTemp[WEATHER_OFFICIAL_SENSOR_ID] = uiPrefs.curveTemperature(WEATHER_OFFICIAL_STABLE_KEY) ?: true',
    "official curve pref",
)
main = once(
    main,
    '''        if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            // Always checked: if data arrives later the curve appears without another user action.
            showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = true
        }
''',
    '''        if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = uiPrefs.curveTemperature(LYON_RECONSTRUCTED_STABLE_KEY) ?: true
        }
''',
    "terrain curve pref",
)
main = once(
    main,
    '        if (!showTemp.containsKey(FORECAST_RECONSTRUCTED_SENSOR_ID)) showTemp[FORECAST_RECONSTRUCTED_SENSOR_ID] = true',
    '        if (!showTemp.containsKey(FORECAST_RECONSTRUCTED_SENSOR_ID)) showTemp[FORECAST_RECONSTRUCTED_SENSOR_ID] = uiPrefs.curveTemperature(FORECAST_RECONSTRUCTED_STABLE_KEY) ?: true',
    "h24 weather curve pref",
)
main = once(
    main,
    '        if (!showTemp.containsKey(FORECAST_FAB_SENSOR_ID)) showTemp[FORECAST_FAB_SENSOR_ID] = true',
    '        if (!showTemp.containsKey(FORECAST_FAB_SENSOR_ID)) showTemp[FORECAST_FAB_SENSOR_ID] = uiPrefs.curveTemperature(FORECAST_FAB_STABLE_KEY) ?: true',
    "h24 fab curve pref",
)
main = once(
    main,
    '        if (!showTemp.containsKey(FORECAST_ACTIVE_SENSOR_ID)) showTemp[FORECAST_ACTIVE_SENSOR_ID] = true',
    '        if (!showTemp.containsKey(FORECAST_ACTIVE_SENSOR_ID)) showTemp[FORECAST_ACTIVE_SENSOR_ID] = uiPrefs.curveTemperature(FORECAST_ACTIVE_STABLE_KEY) ?: true',
    "active forecast curve pref",
)
main = once(
    main,
    '''        FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
            val id = forecastHorizonSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = false
            showHumidity[id] = false
        }
''',
    '''        FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
            val id = forecastHorizonSensorId(lead)
            val stableKey = "forecast-weather-h$lead"
            if (!showTemp.containsKey(id)) showTemp[id] = uiPrefs.curveTemperature(stableKey) ?: false
            showHumidity[id] = false
        }
''',
    "archive curve prefs",
)
main = once(
    main,
    '''        FORECAST_ADAPTIVE_HORIZONS.forEach { lead ->
            val id = forecastAdaptiveSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = false
            showHumidity[id] = false
        }
''',
    '''        FORECAST_ADAPTIVE_HORIZONS.forEach { lead ->
            val id = forecastAdaptiveSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = uiPrefs.curveTemperature(forecastAdaptiveStableKey(lead)) ?: false
            showHumidity[id] = false
        }
''',
    "adaptive curve prefs",
)
main = once(
    main,
    '        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true',
    '        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = uiPrefs.curveTemperature(THERMAL_INERTIA_STABLE_KEY) ?: true',
    "inertia curve pref",
)

# Global navigation uses terrain when available, then active forecast in the future.
main = once(
    main,
    '''private fun navigationWeatherPoints(sampleMap: Map<Long, List<SamplePoint>>): List<SamplePoint> =
    (sampleMap[WEATHER_OFFICIAL_SENSOR_ID].orEmpty() +
        sampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty())
''',
    '''private fun navigationWeatherPoints(sampleMap: Map<Long, List<SamplePoint>>): List<SamplePoint> =
    (sampleMap[WEATHER_OFFICIAL_SENSOR_ID].orEmpty() +
        sampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty() +
        sampleMap[FORECAST_ACTIVE_SENSOR_ID].orEmpty())
''',
    "overview future weather fallback",
)
main = main.replace(
    '"Navigation giga · météo extérieure · historique complet"',
    '"Navigation giga · météo extérieure · historique + futur capturé"',
)

# Do not recreate overview centres just because new measurements move the outer bounds.
main = once(
    main,
    '''                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        historyUiPrefs.previewCenter()?.coerceIn(bounds.first, bounds.last)
                            ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
''',
    '''                var previewCenter by remember {
                    mutableStateOf(
                        historyUiPrefs.previewCenter()?.coerceIn(bounds.first, bounds.last)
                            ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
''',
    "stable preview center state",
)
main = once(
    main,
    '''                var wideCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        historyUiPrefs.wideCenter()?.coerceIn(bounds.first, bounds.last)
                            ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                LaunchedEffect(previewPreset, previewZoom, previewCenter, wideCenter) {
                    delay(300L)
                    historyUiPrefs.savePreviewPresetName(previewPreset.name)
                    historyUiPrefs.savePreviewZoom(previewZoom)
                    historyUiPrefs.savePreviewCenter(previewCenter)
                    historyUiPrefs.saveWideCenter(wideCenter)
                }
''',
    '''                var wideCenter by remember {
                    mutableStateOf(
                        historyUiPrefs.wideCenter()?.coerceIn(bounds.first, bounds.last)
                            ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                LaunchedEffect(bounds.first, bounds.last) {
                    previewCenter = previewCenter.coerceIn(bounds.first, bounds.last)
                    wideCenter = wideCenter.coerceIn(bounds.first, bounds.last)
                }
                LaunchedEffect(previewPreset, previewZoom, previewCenter, wideCenter) {
                    historyUiPrefs.savePreviewPresetName(previewPreset.name)
                    historyUiPrefs.savePreviewZoom(previewZoom)
                    historyUiPrefs.savePreviewCenter(previewCenter)
                    historyUiPrefs.saveWideCenter(wideCenter)
                }
''',
    "stable overview persistence",
)

# Band choices are stored by stable key, with migration from old numeric IDs.
old_band = '''                val availableBandSensorIds = remember(sensors, gigaSampleMap, navigatorSampleMap, sampleMap) {
                    sensors.filter { sensor ->
                        forecastHorizonLeadForSensorId(sensor.id) == null &&
                            forecastAdaptiveLeadForSensorId(sensor.id) == null && (
                            gigaSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                                navigatorSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                                sampleMap[sensor.id].orEmpty().isNotEmpty()
                        )
                    }.map { it.id }.toSet()
                }
                val bandSignature = remember(availableBandSensorIds) { availableBandSensorIds.sorted().joinToString(",") }
                var bandSensorIds by remember(bandSignature, preferredIndoorSensorId) {
                    val configured = bandPrefs.getBoolean("configured", false)
                    val stored = bandPrefs.getStringSet("sensor_ids", emptySet()).orEmpty()
                        .mapNotNull { it.toLongOrNull() }
                        .filter { it in availableBandSensorIds }
                        .toSet()
                    val defaults = linkedSetOf<Long>().apply {
                        preferredIndoorSensorId?.takeIf { it in availableBandSensorIds }?.let { add(it) }
                        THERMAL_INERTIA_SENSOR_ID.takeIf { it in availableBandSensorIds }?.let { add(it) }
                        if (isEmpty()) availableBandSensorIds.firstOrNull()?.let { add(it) }
                    }
                    mutableStateOf(if (configured) stored else defaults)
                }
                var bandChooserOpen by rememberSaveable { mutableStateOf(historyUiPrefs.bandChooserOpen()) }
                LaunchedEffect(bandChooserOpen) { historyUiPrefs.saveBandChooserOpen(bandChooserOpen) }
                fun saveBandSensors(next: Set<Long>) {
                    bandSensorIds = next
                    bandPrefs.edit()
                        .putBoolean("configured", true)
                        .putStringSet("sensor_ids", next.map { it.toString() }.toSet())
                        .apply()
                }
'''
new_band = '''                val availableBandSensors = remember(sensors, gigaSampleMap, navigatorSampleMap, sampleMap) {
                    sensors.filter { sensor ->
                        forecastHorizonLeadForSensorId(sensor.id) == null &&
                            forecastAdaptiveLeadForSensorId(sensor.id) == null && (
                            gigaSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                                navigatorSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                                sampleMap[sensor.id].orEmpty().isNotEmpty()
                        )
                    }
                }
                val availableBandSensorIds = availableBandSensors.map { it.id }.toSet()
                val bandKeyById = availableBandSensors.associate { it.id to it.stableKey }
                val bandIdByKey = availableBandSensors.associate { it.stableKey to it.id }
                val bandSignature = remember(availableBandSensors) {
                    availableBandSensors.map { it.stableKey }.sorted().joinToString(",")
                }
                var bandSensorIds by remember(bandSignature, preferredIndoorSensorId) {
                    val configured = bandPrefs.getBoolean("configured", false)
                    val stableStored = bandPrefs.getStringSet("sensor_keys", emptySet()).orEmpty()
                        .mapNotNull { bandIdByKey[it] }
                        .toSet()
                    val legacyStored = bandPrefs.getStringSet("sensor_ids", emptySet()).orEmpty()
                        .mapNotNull { it.toLongOrNull() }
                        .filter { it in availableBandSensorIds }
                        .toSet()
                    val stored = if (stableStored.isNotEmpty() || bandPrefs.contains("sensor_keys")) stableStored else legacyStored
                    val defaults = linkedSetOf<Long>().apply {
                        preferredIndoorSensorId?.takeIf { it in availableBandSensorIds }?.let { add(it) }
                        THERMAL_INERTIA_SENSOR_ID.takeIf { it in availableBandSensorIds }?.let { add(it) }
                        if (isEmpty()) availableBandSensorIds.firstOrNull()?.let { add(it) }
                    }
                    mutableStateOf(if (configured) stored else defaults)
                }
                var bandChooserOpen by rememberSaveable { mutableStateOf(historyUiPrefs.bandChooserOpen()) }
                LaunchedEffect(bandChooserOpen) { historyUiPrefs.saveBandChooserOpen(bandChooserOpen) }
                fun saveBandSensors(next: Set<Long>) {
                    bandSensorIds = next
                    bandPrefs.edit()
                        .putBoolean("configured", true)
                        .putStringSet("sensor_ids", next.map { it.toString() }.toSet())
                        .putStringSet("sensor_keys", next.mapNotNull { bandKeyById[it] }.toSet())
                        .apply()
                }
'''
main = once(main, old_band, new_band, "stable band selection")

write(main_path, main)

print("Applied FabData v0.23.1: H+48 capture, future view, trigger race fix, durable UI state")
