from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main_path = ROOT / "app/src/main/java/com/fabdata/app/MainActivity.kt"
gradle_path = ROOT / "app/build.gradle.kts"

main = main_path.read_text()
gradle = gradle_path.read_text()

MARKER = "Archives météo H+1 → H+23"
if MARKER in main and 'versionName = "0.22.0"' in gradle:
    print("v0.22.0 UI persistence patch already applied")
    raise SystemExit(0)


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)

# Version bump.
gradle = once(
    gradle,
    'versionCode = 55\n        versionName = "0.21.9"',
    'versionCode = 56\n        versionName = "0.22.0"',
    "version bump",
)

# Durable UI preference store available to the main screen.
main = once(
    main,
    '    val prefsStore = remember { FabPrefs(context) }\n    val scope = rememberCoroutineScope()',
    '    val prefsStore = remember { FabPrefs(context) }\n    val uiPrefs = remember { UiPreferenceStore(context) }\n    val scope = rememberCoroutineScope()',
    "ui preference store",
)

# Restore main navigation/presentation choices instead of resetting them on Activity recreation.
main = once(
    main,
    '''    var preset by rememberSaveable { mutableStateOf(TimePreset.TWO_DAYS) }
    var windowCenterTimestamp by remember { mutableStateOf<Long?>(null) }
    var customViewSpanMs by remember { mutableStateOf<Long?>(null) }
    var showAllAnnotations by rememberSaveable { mutableStateOf(true) }''',
    '''    var preset by remember {
        mutableStateOf(TimePreset.entries.firstOrNull { it.name == uiPrefs.timePresetName() } ?: TimePreset.TWO_DAYS)
    }
    var windowCenterTimestamp by remember { mutableStateOf(uiPrefs.windowCenter()) }
    var customViewSpanMs by remember { mutableStateOf(uiPrefs.customViewSpan()) }
    var showAllAnnotations by remember { mutableStateOf(uiPrefs.showAllAnnotations()) }''',
    "main persisted state",
)

main = once(
    main,
    '''    var initialHandled by remember { mutableStateOf(false) }

    // v0.17 : cet orchestrateur reste composé''',
    '''    var initialHandled by remember { mutableStateOf(false) }

    // v0.22.0 : les choix utilisateur survivent aux recréations d'Activity et aux redémarrages.
    // Les écritures de navigation sont légèrement temporisées pour éviter de marteler les prefs pendant un glisser.
    LaunchedEffect(preset) { uiPrefs.saveTimePresetName(preset.name) }
    LaunchedEffect(showAllAnnotations) { uiPrefs.saveShowAllAnnotations(showAllAnnotations) }
    LaunchedEffect(windowCenterTimestamp, customViewSpanMs) {
        delay(250L)
        uiPrefs.saveWindowCenter(windowCenterTimestamp)
        uiPrefs.saveCustomViewSpan(customViewSpanMs)
    }

    // v0.17 : cet orchestrateur reste composé''',
    "main persistence effects",
)

# Apply persisted curve visibility by stable key after every sensor-list reconstruction.
main = once(
    main,
    '''    val chartSensors = physicalChartSensors + lyonReconstructedSensor + forecastActiveSensor + forecastHorizonSensors + forecastReconstructedSensor + forecastFabSensor + inertiaSensor
    val chartSampleMap = sampleMap.filterKeys''',
    '''    val chartSensors = physicalChartSensors + lyonReconstructedSensor + forecastActiveSensor + forecastHorizonSensors + forecastReconstructedSensor + forecastFabSensor + inertiaSensor
    LaunchedEffect(chartSensors.map { it.stableKey }) {
        chartSensors.forEach { sensor ->
            uiPrefs.curveTemperature(sensor.stableKey)?.let { showTemp[sensor.id] = it }
            uiPrefs.curveHumidity(sensor.stableKey)?.let { showHumidity[sensor.id] = it }
        }
    }
    val chartSampleMap = sampleMap.filterKeys''',
    "restore curve visibility",
)

# H+1..H+23 remain available for the detailed graph but never pollute the overview-band chooser.
main = once(
    main,
    '''                    sensors.filter { sensor ->
                        gigaSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                            navigatorSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                            sampleMap[sensor.id].orEmpty().isNotEmpty()
                    }.map { it.id }.toSet()''',
    '''                    sensors.filter { sensor ->
                        forecastHorizonLeadForSensorId(sensor.id) == null && (
                            gigaSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                                navigatorSampleMap[sensor.id].orEmpty().isNotEmpty() ||
                                sampleMap[sensor.id].orEmpty().isNotEmpty()
                        )
                    }.map { it.id }.toSet()''',
    "exclude H1-H23 from band chooser",
)

# Persist the global overview preset/zoom/centres and chooser expansion.
main = once(
    main,
    '''                var previewPreset by rememberSaveable { mutableStateOf(PreviewPreset.M6) }
                var previewZoom by rememberSaveable { mutableFloatStateOf(1f) }
                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }''',
    '''                val historyContext = LocalContext.current
                val historyUiPrefs = remember(historyContext) { UiPreferenceStore(historyContext) }
                var previewPreset by rememberSaveable {
                    mutableStateOf(
                        PreviewPreset.entries.firstOrNull { it.name == historyUiPrefs.previewPresetName() }
                            ?: PreviewPreset.M6
                    )
                }
                var previewZoom by rememberSaveable { mutableFloatStateOf(historyUiPrefs.previewZoom()) }
                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        historyUiPrefs.previewCenter()?.coerceIn(bounds.first, bounds.last)
                            ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }''',
    "overview preset restore",
)

main = once(
    main,
    '''                var wideCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }''',
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
                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }''',
    "overview center persistence",
)

main = once(
    main,
    '                var bandChooserOpen by rememberSaveable { mutableStateOf(false) }',
    '''                var bandChooserOpen by rememberSaveable { mutableStateOf(historyUiPrefs.bandChooserOpen()) }
                LaunchedEffect(bandChooserOpen) { historyUiPrefs.saveBandChooserOpen(bandChooserOpen) }''',
    "band chooser persistence",
)

# Replace the flat selector with a compact H+1..H+23 archive drawer and durable visibility choices.
start = main.index('@Composable\nprivate fun SeriesSelector(')
end = main.index('\nprivate fun mergeTerrainReference(', start)
series_selector = r'''@Composable
private fun SeriesSelector(
    sensors: List<Sensor>,
    showTemp: MutableMap<Long, Boolean>,
    showHumidity: MutableMap<Long, Boolean>,
    onEditSensor: (Sensor) -> Unit,
    onStyleEdit: (Sensor) -> Unit
) {
    val context = LocalContext.current
    val uiPrefs = remember(context) { UiPreferenceStore(context) }
    var archiveExpanded by rememberSaveable { mutableStateOf(uiPrefs.forecastArchiveExpanded()) }
    val archiveSensors = sensors
        .filter { sensor -> forecastHorizonLeadForSensorId(sensor.id)?.let { it in 1..23 } == true }
        .sortedBy { forecastHorizonLeadForSensorId(it.id) ?: Int.MAX_VALUE }
    val archiveIds = archiveSensors.map { it.id }.toSet()
    val mainSensors = sensors.filterNot { it.id in archiveIds }

    LaunchedEffect(archiveExpanded) { uiPrefs.saveForecastArchiveExpanded(archiveExpanded) }

    Card(shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Superposition", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "Chaque courbe est indépendante. Les horizons H+1 à H+23 restent rangés dans Archives météo.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            @Composable
            fun SensorRow(sensor: Sensor) {
                val lead = forecastHorizonLeadForSensorId(sensor.id)
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(12.dp)
                            .background(palette[sensor.colorIndex % palette.size], RoundedCornerShape(6.dp))
                    )
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        val displayRoom = when (sensor.id) {
                            WEATHER_OFFICIAL_SENSOR_ID -> "Station météo officielle"
                            LYON_RECONSTRUCTED_SENSOR_ID -> "Référence terrain · réel > reconstruit"
                            FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision météo H+24 fixe"
                            FORECAST_FAB_SENSOR_ID -> "Prévision Fab H+24"
                            FORECAST_ACTIVE_SENSOR_ID -> "Prévision météo active · dernière disponible"
                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"
                            else -> lead?.let { "Prévision météo H+$it" } ?: sensor.room
                        }
                        Text(displayRoom, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) {
                            Text(sensor.room, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else if (lead != null) {
                            Text(
                                "Archive locale fixe H+$lead · conservée avant remplacement",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        } else if (sensor.name != sensor.room && sensor.id != THERMAL_INERTIA_SENSOR_ID) {
                            Text(
                                sensor.name,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    Text("T°", style = MaterialTheme.typography.labelMedium)
                    Checkbox(
                        checked = showTemp[sensor.id] == true,
                        onCheckedChange = { checked ->
                            showTemp[sensor.id] = checked
                            uiPrefs.saveCurveTemperature(sensor.stableKey, checked)
                        }
                    )
                    if (sensor.id != THERMAL_INERTIA_SENSOR_ID &&
                        sensor.id != FORECAST_RECONSTRUCTED_SENSOR_ID &&
                        sensor.id != FORECAST_FAB_SENSOR_ID &&
                        !isForecastArchiveSensorId(sensor.id)
                    ) {
                        Text("%", style = MaterialTheme.typography.labelMedium)
                        Checkbox(
                            checked = showHumidity[sensor.id] == true,
                            onCheckedChange = { checked ->
                                showHumidity[sensor.id] = checked
                                uiPrefs.saveCurveHumidity(sensor.stableKey, checked)
                            }
                        )
                    } else {
                        Spacer(Modifier.size(48.dp))
                    }
                    IconButton(onClick = { onStyleEdit(sensor) }) {
                        Icon(Icons.Default.Settings, contentDescription = "Personnaliser la courbe")
                    }
                    if (sensor.id >= 0L) {
                        IconButton(onClick = { onEditSensor(sensor) }) {
                            Icon(Icons.Default.Edit, contentDescription = "Modifier la sonde")
                        }
                    }
                }
            }

            mainSensors.forEach { sensor -> SensorRow(sensor) }

            if (archiveSensors.isNotEmpty()) {
                HorizontalDivider()
                val visibleCount = archiveSensors.count { showTemp[it.id] == true }
                OutlinedButton(
                    onClick = { archiveExpanded = !archiveExpanded },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        "Archives météo H+1 → H+23 · $visibleCount/${archiveSensors.size} " +
                            if (archiveExpanded) "▴" else "▾"
                    )
                }
                if (archiveExpanded) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End
                    ) {
                        TextButton(onClick = {
                            archiveSensors.forEach { sensor ->
                                showTemp[sensor.id] = true
                                uiPrefs.saveCurveTemperature(sensor.stableKey, true)
                            }
                        }) { Text("Tout afficher") }
                        TextButton(onClick = {
                            archiveSensors.forEach { sensor ->
                                showTemp[sensor.id] = false
                                uiPrefs.saveCurveTemperature(sensor.stableKey, false)
                            }
                        }) { Text("Tout masquer") }
                    }
                    archiveSensors.forEach { sensor -> SensorRow(sensor) }
                }
            }
        }
    }
}
'''
main = main[:start] + series_selector + main[end:]

main_path.write_text(main)
gradle_path.write_text(gradle)
print("Applied v0.22.0 persistent UI + compact forecast archive selector")
