from pathlib import Path

MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
LAB = Path('app/src/main/java/com/fabdata/app/LyonLabLayer.kt')

text = MAIN.read_text(encoding='utf-8')

if 'LYON_RECONSTRUCTED_SENSOR_ID' not in text:
    text = text.replace(
        'private const val LYON_NEAREST_TOLERANCE_MS = 75L * 60L * 1000L\n',
        'private const val LYON_NEAREST_TOLERANCE_MS = 75L * 60L * 1000L\n'
        'private const val LYON_RECONSTRUCTED_SENSOR_ID = -6902900103L\n'
        'private const val LYON_RECONSTRUCTED_STABLE_KEY = "lyon-reconstructed"\n',
        1
    )

old_loaded = '''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val overviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>
)'''
new_loaded = '''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val overviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>,
    val lyonReconstructedSamples: List<SamplePoint>
)'''
if old_loaded in text:
    text = text.replace(old_loaded, new_loaded, 1)

if 'var lyonReconstructedSamples by remember' not in text:
    text = text.replace(
        '    var sampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }\n',
        '    var sampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }\n'
        '    var lyonReconstructedSamples by remember { mutableStateOf<List<SamplePoint>>(emptyList()) }\n',
        1
    )

old_styles = '''    val activeCurveStyles = remember(sensors, styleVersion) {
        sensors.associate { sensor -> sensor.id to curveStyleStore.load("sensor:${sensor.stableKey}") }
    }
'''
new_styles = '''    val activeCurveStyles = remember(sensors, styleVersion) {
        buildMap {
            sensors.forEach { sensor -> put(sensor.id, curveStyleStore.load("sensor:${sensor.stableKey}")) }
            put(LYON_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("lyon:reconstructed"))
        }
    }
'''
if old_styles in text:
    text = text.replace(old_styles, new_styles, 1)

# Remove the duplicate unconditional official sync. The guarded automatic sync above is enough.
duplicate_sync = '''    // Synchronise silencieusement les observations mesurées du jour à Lyon-Bron.
    // Une absence de réseau ne bloque jamais l'ouverture ni les imports CSV.
    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) { runCatching { meteoOfficial.syncSixMinute24h() } }
        // Reload even on failure: Lyon has already been created and must remain
        // visible so the user can distinguish "no data" from "no sensor".
        reloadToken++
        result.exceptionOrNull()?.let { error ->
            snackbar.showSnackbar("Lyon non actualisé : ${error.message ?: "réseau ou source indisponible"}")
        }
    }

'''
text = text.replace(duplicate_sync, '', 1)

text = text.replace(
    '                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes)\n',
    '                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList())\n',
    1
)

old_samples = '''                val samples = s.associate { sensor ->
                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        val reconstructed = lyonLab.reconstruct(chosen.first, chosen.last).points.map {
                            SamplePoint(sensor.id, it.timestamp, it.temperature, it.humidity)
                        }
                        // Tant que la clé officielle n'est pas configurée, l'ancien Lyon reste
                        // visible comme secours, sans être réécrit ni mélangé aux tables officielles.
                        reconstructed.ifEmpty { db.querySamples(sensor.id, chosen.first, chosen.last) }
                    } else {
                        db.querySamples(sensor.id, chosen.first, chosen.last)
                    }
                    sensor.id to value
                }
'''
new_samples = '''                val samples = s.associate { sensor ->
                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        // La ligne Lyon reste la donnée officielle brute 6 min.
                        val officialSix = lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, chosen.first, chosen.last).map {
                            SamplePoint(sensor.id, it.timestamp, it.temperature, it.humidity)
                        }
                        // Secours lecture seule pour les anciennes bases avant l'API officielle.
                        officialSix.ifEmpty { db.querySamples(sensor.id, chosen.first, chosen.last) }
                    } else {
                        db.querySamples(sensor.id, chosen.first, chosen.last)
                    }
                    sensor.id to value
                }
                val lyonReconstructed = if (s.any { it.stableKey == LyonWeatherSync.STABLE_KEY }) {
                    lyonLab.reconstruct(chosen.first, chosen.last).points.map {
                        SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity)
                    }
                } else emptyList()
'''
if old_samples not in text and 'val lyonReconstructed = if' not in text:
    raise SystemExit('v0.9.1: main samples anchor not found')
text = text.replace(old_samples, new_samples, 1)

old_ctor = '''                LoadedData(
                    s, all, chosen, samples, overview, stat,
                    db.annotations(chosen.first, chosen.last), allNotes
                )'''
new_ctor = '''                LoadedData(
                    s, all, chosen, samples, overview, stat,
                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed
                )'''
if old_ctor in text:
    text = text.replace(old_ctor, new_ctor, 1)

if 'lyonReconstructedSamples = loaded.lyonReconstructedSamples' not in text:
    text = text.replace(
        '        sampleMap = loaded.samples\n',
        '        sampleMap = loaded.samples\n        lyonReconstructedSamples = loaded.lyonReconstructedSamples\n',
        1
    )

old_toggle_init = '''        sensors.forEach { sensor ->
            if (!showTemp.containsKey(sensor.id)) showTemp[sensor.id] = true
            if (!showHumidity.containsKey(sensor.id)) showHumidity[sensor.id] = false
        }
        busy = false
'''
new_toggle_init = '''        sensors.forEach { sensor ->
            if (!showTemp.containsKey(sensor.id)) {
                showTemp[sensor.id] = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                    loaded.lyonReconstructedSamples.isEmpty()
                } else true
            }
            if (!showHumidity.containsKey(sensor.id)) showHumidity[sensor.id] = false
        }
        if (sensors.any { it.stableKey == LyonWeatherSync.STABLE_KEY }) {
            if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
                showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = loaded.lyonReconstructedSamples.isNotEmpty()
            }
            if (!showHumidity.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
                showHumidity[LYON_RECONSTRUCTED_SENSOR_ID] = false
            }
        }
        busy = false
'''
if old_toggle_init in text:
    text = text.replace(old_toggle_init, new_toggle_init, 1)

# Build a virtual, display-only sensor. It is never inserted into SQLite.
if 'val chartSensors = if (sensors.any' not in text:
    anchor = '    Scaffold(\n'
    virtual = '''    val lyonReconstructedSensor = Sensor(
        id = LYON_RECONSTRUCTED_SENSOR_ID,
        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,
        name = "Lyon reconstruit",
        room = "Lyon reconstruit",
        colorIndex = 3,
        latestTimestamp = lyonReconstructedSamples.lastOrNull()?.timestamp
    )
    val chartSensors = if (sensors.any { it.stableKey == LyonWeatherSync.STABLE_KEY }) {
        sensors + lyonReconstructedSensor
    } else sensors
    val chartSampleMap = if (chartSensors.any { it.id == LYON_RECONSTRUCTED_SENSOR_ID }) {
        sampleMap + (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples)
    } else sampleMap

'''
    if anchor not in text:
        raise SystemExit('v0.9.1: Scaffold anchor not found')
    text = text.replace(anchor, virtual + anchor, 1)

# Selector + personalization + main graph + inspector use the virtual series.
text = text.replace(
    '''                    SeriesSelector(
                        sensors = sensors,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        onEdit = { editSensor = it }
                    )''',
    '''                    SeriesSelector(
                        sensors = chartSensors,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        onEdit = { if (it.id != LYON_RECONSTRUCTED_SENSOR_ID) editSensor = it }
                    )''',
    1
)
text = text.replace(
    '''                    CurvePersonalizationCard(
                        sensors = sensors,
                        onEdit = { key, label -> styleEditKey = key to label }
                    )''',
    '''                    CurvePersonalizationCard(
                        sensors = chartSensors,
                        onEdit = { key, label -> styleEditKey = key to label }
                    )''',
    1
)
text = text.replace('                        sensors = sensors,\n                        sampleMap = sampleMap,\n                        showTemp = showTemp,',
                    '                        sensors = chartSensors,\n                        sampleMap = chartSampleMap,\n                        showTemp = showTemp,', 1)
text = text.replace('                            InspectorCard(ts, sensors, sampleMap, showTemp, showHumidity)',
                    '                            InspectorCard(ts, chartSensors, chartSampleMap, showTemp, showHumidity)', 1)

# Do not expose an edit/delete action for the virtual curve, and make labels explicit.
old_series_label = '''                    Column(Modifier.weight(1f)) {
                        Text(sensor.room, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (sensor.name != sensor.room) {
                            Text(
                                sensor.name,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
'''
new_series_label = '''                    Column(Modifier.weight(1f)) {
                        val displayRoom = when {
                            sensor.id == LYON_RECONSTRUCTED_SENSOR_ID -> "Lyon reconstruit"
                            sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon officiel · 6 min"
                            else -> sensor.room
                        }
                        Text(displayRoom, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (sensor.name != sensor.room && sensor.id != LYON_RECONSTRUCTED_SENSOR_ID) {
                            Text(
                                sensor.name,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
'''
if old_series_label in text:
    text = text.replace(old_series_label, new_series_label, 1)

text = text.replace(
    '''                    IconButton(onClick = { onEdit(sensor) }) {
                        Icon(Icons.Default.Edit, contentDescription = "Modifier la pièce")
                    }
''',
    '''                    if (sensor.id != LYON_RECONSTRUCTED_SENSOR_ID) {
                        IconButton(onClick = { onEdit(sensor) }) {
                            Icon(Icons.Default.Edit, contentDescription = "Modifier la pièce")
                        }
                    } else {
                        Spacer(Modifier.size(48.dp))
                    }
''',
    1
)

# Break visible paths across real gaps for both Lyon official and reconstructed series.
text = text.replace(
    'val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&\n',
    'val breakHere = (sensor.stableKey == LyonWeatherSync.STABLE_KEY || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) &&\n'
)

MAIN.write_text(text, encoding='utf-8')

lab = LAB.read_text(encoding='utf-8')
old_personal = '''            sensors.forEach { sensor ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(sensor.room, Modifier.weight(1f))
                    TextButton(onClick = { onEdit("sensor:${sensor.stableKey}", sensor.room) }) { Text("Personnaliser") }
                }
            }
'''
new_personal = '''            sensors.forEach { sensor ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    val isRecon = sensor.stableKey == "lyon-reconstructed"
                    val label = when {
                        isRecon -> "Lyon reconstruit"
                        sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon officiel · 6 min"
                        else -> sensor.room
                    }
                    val key = if (isRecon) "lyon:reconstructed" else "sensor:${sensor.stableKey}"
                    Text(label, Modifier.weight(1f))
                    TextButton(onClick = { onEdit(key, label) }) { Text("Personnaliser") }
                }
            }
'''
if old_personal in lab:
    lab = lab.replace(old_personal, new_personal, 1)
LAB.write_text(lab, encoding='utf-8')

print('FabData v0.9.1 Lyon reconstructed toggle patch applied')
