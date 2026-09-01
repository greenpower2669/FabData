from pathlib import Path

DATA = Path('app/src/main/java/com/fabdata/app/DataLayer.kt')
MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
LAB = Path('app/src/main/java/com/fabdata/app/LyonLabLayer.kt')

# -----------------------------------------------------------------------------
# SQLite v3: additive only. Existing samples/annotations remain untouched.
# -----------------------------------------------------------------------------
text = DATA.read_text(encoding='utf-8')
text = text.replace('SQLiteOpenHelper(context, "fabdata.db", null, 2)', 'SQLiteOpenHelper(context, "fabdata.db", null, 3)')
if 'ensureLyonLabSchema(db)' not in text:
    anchor = '        db.execSQL("CREATE INDEX idx_annotations_time ON annotations(timestamp)")\n'
    if anchor not in text:
        raise SystemExit('v0.9: DataLayer onCreate anchor not found')
    text = text.replace(anchor, anchor + '        ensureLyonLabSchema(db)\n', 1)

upgrade_anchor = '''        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE annotations ADD COLUMN room_name TEXT")
            db.execSQL("ALTER TABLE annotations ADD COLUMN type TEXT")
            db.execSQL("ALTER TABLE annotations ADD COLUMN updated_at INTEGER NOT NULL DEFAULT 0")
            db.execSQL("UPDATE annotations SET updated_at = created_at WHERE updated_at = 0")
        }
'''
if 'if (oldVersion < 3)' not in text:
    if upgrade_anchor not in text:
        raise SystemExit('v0.9: DataLayer upgrade anchor not found')
    text = text.replace(upgrade_anchor, upgrade_anchor + '''        if (oldVersion < 3) {
            // Migration strictement additive : aucune table historique n'est réécrite.
            ensureLyonLabSchema(db)
        }
''', 1)
DATA.write_text(text, encoding='utf-8')

# -----------------------------------------------------------------------------
# LyonLab small compile/support additions and detailed style application.
# -----------------------------------------------------------------------------
text = LAB.read_text(encoding='utf-8')
if 'import androidx.compose.foundation.layout.weight' not in text:
    text = text.replace('import androidx.compose.foundation.layout.width\n', 'import androidx.compose.foundation.layout.width\nimport androidx.compose.foundation.layout.weight\n', 1)

# Animated style tick in Lyon detail.
if 'var lyonStyleTick by remember' not in text:
    anchor = '    var decisions by remember { mutableStateOf<List<LyonDecision>>(emptyList()) }\n\n'
    if anchor not in text:
        raise SystemExit('v0.9: Lyon detail state anchor not found')
    text = text.replace(anchor, anchor + '''    var lyonStyleTick by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            lyonStyleTick = System.currentTimeMillis()
            delay(180L)
        }
    }

''', 1)

old_chart_call = '''            LyonMiniChart(
                points = points,
                selectedTimestamp = selected,
                onTap = { selected = it },
                onDoubleTap = {
                    selected = it
                    if (kind == LyonSeriesKind.RECONSTRUCTED) editTimestamp = it
                }
            )
'''
new_chart_call = '''            LyonMiniChart(
                points = points,
                selectedTimestamp = selected,
                visualPrefs = styleStore.load("lyon:${kind.dbKey}"),
                styleTick = lyonStyleTick,
                onTap = { selected = it },
                onDoubleTap = {
                    selected = it
                    if (kind == LyonSeriesKind.RECONSTRUCTED) editTimestamp = it
                }
            )
'''
if 'visualPrefs = styleStore.load("lyon:${kind.dbKey}")' not in text:
    if old_chart_call not in text:
        raise SystemExit('v0.9: LyonMiniChart call anchor not found')
    text = text.replace(old_chart_call, new_chart_call, 1)

old_sig = '''private fun LyonMiniChart(
    points: List<LyonLabPoint>,
    selectedTimestamp: Long?,
    onTap: (Long) -> Unit,
    onDoubleTap: (Long) -> Unit
) {
    val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f)
    val line = MaterialTheme.colorScheme.primary
    val select = MaterialTheme.colorScheme.tertiary
'''
new_sig = '''private fun LyonMiniChart(
    points: List<LyonLabPoint>,
    selectedTimestamp: Long?,
    visualPrefs: CurveVisualPrefs,
    styleTick: Long,
    onTap: (Long) -> Unit,
    onDoubleTap: (Long) -> Unit
) {
    val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f)
    val line = resolveCurveColor(MaterialTheme.colorScheme.primary, visualPrefs, styleTick)
        ?: Color.Transparent
    val aura = resolveAuraColor(visualPrefs, styleTick)
    val select = MaterialTheme.colorScheme.tertiary
'''
if 'visualPrefs: CurveVisualPrefs' not in text:
    if old_sig not in text:
        raise SystemExit('v0.9: LyonMiniChart signature anchor not found')
    text = text.replace(old_sig, new_sig, 1)

old_draw = '        drawPath(path, line, style = Stroke(width = 2.5.dp.toPx()))\n'
if 'aura?.let { drawPath(path, it' not in text:
    if old_draw not in text:
        raise SystemExit('v0.9: Lyon chart draw anchor not found')
    text = text.replace(old_draw, '''        aura?.let { drawPath(path, it, style = Stroke(width = 10.dp.toPx())) }
        drawPath(path, line, style = Stroke(width = 2.5.dp.toPx()))
''', 1)

# Helper for main chart statistics when Lyon is reconstructed instead of legacy samples.
if 'fun sensorStatsFromSamples(' not in text:
    text += '''

fun sensorStatsFromSamples(sensorId: Long, points: List<SamplePoint>): SensorStats? {
    if (points.isEmpty()) return null
    val latest = points.maxByOrNull { it.timestamp }
    return SensorStats(
        sensorId = sensorId,
        count = points.size,
        tempMin = points.minOf { it.temperature },
        tempMax = points.maxOf { it.temperature },
        tempAvg = points.map { it.temperature }.average(),
        humidityMin = points.minOf { it.humidity },
        humidityMax = points.maxOf { it.humidity },
        humidityAvg = points.map { it.humidity }.average(),
        latest = latest
    )
}
'''
LAB.write_text(text, encoding='utf-8')

# -----------------------------------------------------------------------------
# MainActivity: official Lyon source, reconstructed main curve, detail UI,
# per-curve personalization, animated style rendering.
# -----------------------------------------------------------------------------
text = MAIN.read_text(encoding='utf-8')
if 'import kotlinx.coroutines.delay' not in text:
    text = text.replace('import kotlinx.coroutines.Dispatchers\n', 'import kotlinx.coroutines.Dispatchers\nimport kotlinx.coroutines.delay\n', 1)

stores_anchor = '''    val lyonWeather = remember { LyonWeatherSync(db) }
    val remoteSensorStore = remember { RemoteSensorStore(context) }
'''
if 'val lyonLab = remember { LyonLabStore(db) }' not in text:
    if stores_anchor not in text:
        raise SystemExit('v0.9: stores anchor not found')
    text = text.replace(stores_anchor, '''    val lyonWeather = remember { LyonWeatherSync(db) } // legacy read-only fallback
    val lyonLab = remember { LyonLabStore(db) }
    val meteoCredentials = remember { MeteoFranceCredentialStore(context) }
    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, meteoCredentials) }
    val curveStyleStore = remember { CurveStyleStore(context) }
    val remoteSensorStore = remember { RemoteSensorStore(context) }
''', 1)

state_anchor = '''    var editSensor by remember { mutableStateOf<Sensor?>(null) }
    var prefs by remember { mutableStateOf(prefsStore.load()) }
'''
if 'var lyonDetailOpen by remember' not in text:
    if state_anchor not in text:
        raise SystemExit('v0.9: state anchor not found')
    text = text.replace(state_anchor, '''    var editSensor by remember { mutableStateOf<Sensor?>(null) }
    var lyonDetailOpen by remember { mutableStateOf(false) }
    var styleEditKey by remember { mutableStateOf<Pair<String, String>?>(null) }
    var styleVersion by remember { mutableIntStateOf(0) }
    var styleTick by remember { mutableStateOf(System.currentTimeMillis()) }
    var prefs by remember { mutableStateOf(prefsStore.load()) }
''', 1)

active_anchor = '    var initialHandled by remember { mutableStateOf(false) }\n\n'
if 'val activeCurveStyles = remember(sensors, styleVersion)' not in text:
    if active_anchor not in text:
        raise SystemExit('v0.9: active styles anchor not found')
    text = text.replace(active_anchor, active_anchor + '''    val activeCurveStyles = remember(sensors, styleVersion) {
        sensors.associate { sensor -> sensor.id to curveStyleStore.load("sensor:${sensor.stableKey}") }
    }

    LaunchedEffect(Unit) {
        while (true) {
            styleTick = System.currentTimeMillis()
            delay(180L)
        }
    }

''', 1)

old_startup = '''    // Synchronise silencieusement les observations mesurées du jour à Lyon-Bron.
    // Une absence de réseau ne bloque jamais l'ouverture ni les imports CSV.
    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
        // Reload even on failure: Lyon has already been created and must remain
        // visible so the user can distinguish "no data" from "no sensor".
        reloadToken++
        result.exceptionOrNull()?.let { error ->
            snackbar.showSnackbar("Lyon non actualisé : ${error.message ?: "réseau ou source indisponible"}")
        }
    }
'''
new_startup = '''    // v0.9 : la source principale devient l'API officielle Météo-France.
    // Sans clé configurée, on n'écrit rien et l'application démarre normalement.
    LaunchedEffect(Unit) {
        if (meteoCredentials.hasCredential()) {
            val result = withContext(Dispatchers.IO) { runCatching { meteoOfficial.syncSixMinute24h() } }
            reloadToken++
            result.exceptionOrNull()?.let { error ->
                snackbar.showSnackbar("Lyon officiel non actualisé : ${error.message ?: "source indisponible"}")
            }
        }
    }
'''
if 'la source principale devient l\'API officielle' not in text:
    if old_startup not in text:
        raise SystemExit('v0.9: startup Lyon block not found')
    text = text.replace(old_startup, new_startup, 1)

old_samples = '''                val samples = s.associate { sensor ->
                    sensor.id to db.querySamples(sensor.id, chosen.first, chosen.last)
                }
                val overview = s.associate { sensor ->
                    sensor.id to db.querySamples(sensor.id, all.first, all.last, maxPoints = 600)
                }
                val stat = s.mapNotNull { sensor ->
                    db.stats(sensor.id, chosen.first, chosen.last)?.let { value -> sensor.id to value }
                }.toMap()
'''
new_samples = '''                val samples = s.associate { sensor ->
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
                val overview = s.associate { sensor ->
                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        val hourly = lyonLab.queryOfficial(LyonSeriesKind.HOURLY, all.first, all.last)
                            .map { SamplePoint(sensor.id, it.timestamp, it.temperature, it.humidity) }
                        hourly.ifEmpty { db.querySamples(sensor.id, all.first, all.last, maxPoints = 600) }
                    } else {
                        db.querySamples(sensor.id, all.first, all.last, maxPoints = 600)
                    }
                    sensor.id to value
                }
                val stat = s.mapNotNull { sensor ->
                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        sensorStatsFromSamples(sensor.id, samples[sensor.id].orEmpty())
                    } else {
                        db.stats(sensor.id, chosen.first, chosen.last)
                    }
                    value?.let { sensor.id to it }
                }.toMap()
'''
if 'val reconstructed = lyonLab.reconstruct' not in text:
    if old_samples not in text:
        raise SystemExit('v0.9: samples load anchor not found')
    text = text.replace(old_samples, new_samples, 1)

# Toolbar refresh: official 6-minute source.
text = text.replace('runCatching { lyonWeather.syncToday() }', 'runCatching { meteoOfficial.syncSixMinute24h() }')
text = text.replace('"Lyon : ${it.added} ajoutée(s) · ${it.corrected} corrigée(s) · ${it.duplicates} inchangée(s)"', '"Lyon 6 min officiel : ${it.received} reçue(s) · ${it.stored} stockée(s)"')
text = text.replace('"Lyon : ${it.added} ajoutée(s) · ${it.corrected} corrigée(s)"', '"Lyon 6 min officiel : ${it.received} reçue(s) · ${it.stored} stockée(s)"')

# SensorSourcesCard call: detail + official hourly completion.
call_anchor = '''                        onSyncLyon = {
'''
if 'onOpenLyon = { lyonDetailOpen = true }' not in text:
    idx = text.find(call_anchor)
    if idx < 0:
        raise SystemExit('v0.9: SensorSources call anchor not found')
    # Insert immediately before onSyncLyon in the first SensorSourcesCard call.
    text = text[:idx] + '                        onOpenLyon = { lyonDetailOpen = true },\n' + text[idx:]

# Replace completePhysicalPeriod call with official hourly for the physical period.
text = text.replace(
    'runCatching { lyonWeather.completePhysicalPeriod() }',
    'runCatching {\n                                    val b = db.physicalSensorBounds() ?: error("Aucune période physique")\n                                    meteoOfficial.syncHourly(b.first, b.last)\n                                }'
)
text = text.replace(
    '"Lyon : ${it.added} ajoutée(s) · ${it.corrected} corrigée(s) · ${it.daysDownloaded} jour(s) vérifié(s)"',
    '"Lyon horaire officiel : ${it.received} reçue(s) · ${it.stored} stockée(s)"'
)

# Add personalization card after existing series selector.
series_block = '''                item {
                    SeriesSelector(
                        sensors = sensors,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        onEdit = { editSensor = it }
                    )
                }
'''
if 'CurvePersonalizationCard(' not in text:
    if series_block not in text:
        raise SystemExit('v0.9: SeriesSelector block not found')
    text = text.replace(series_block, series_block + '''
                item {
                    CurvePersonalizationCard(
                        sensors = sensors,
                        onEdit = { key, label -> styleEditKey = key to label }
                    )
                }
''', 1)

# Main ChartCard receives visual prefs and animation tick.
main_chart_anchor = '''                        prefs = prefs,
                        selectedTimestamp = selectedTimestamp,
'''
if 'curveStyles = activeCurveStyles' not in text:
    if main_chart_anchor not in text:
        raise SystemExit('v0.9: ChartCard call prefs anchor not found')
    text = text.replace(main_chart_anchor, '''                        prefs = prefs,
                        curveStyles = activeCurveStyles,
                        styleTick = styleTick,
                        selectedTimestamp = selectedTimestamp,
''', 1)

# SensorSourcesCard signature.
sig_anchor = '''    sensors: List<Sensor>,
    remoteConfigs: List<RemoteSensorConfig>,
    onSyncLyon: () -> Unit,
'''
if 'onOpenLyon: () -> Unit' not in text:
    if sig_anchor not in text:
        raise SystemExit('v0.9: SensorSources signature anchor not found')
    text = text.replace(sig_anchor, '''    sensors: List<Sensor>,
    remoteConfigs: List<RemoteSensorConfig>,
    onOpenLyon: () -> Unit,
    onSyncLyon: () -> Unit,
''', 1)

text = text.replace(
    '"Lyon est préconfigurée par défaut. 《 Compléter 》 aligne ses archives sur la période réelle des thermomètres connectés."',
    '"Lyon-Bron officiel : 6 min sur 24 h + archive horaire. Détail = brut / horaire / reconstruit."'
)
row_buttons = '''                TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }
                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
'''
if 'TextButton(onClick = onOpenLyon) { Text("Détail") }' not in text:
    if row_buttons not in text:
        raise SystemExit('v0.9: Lyon source row buttons anchor not found')
    text = text.replace(row_buttons, '''                TextButton(onClick = onOpenLyon) { Text("Détail") }
                TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }
                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
''', 1)

# Chart signatures.
chart_sig = '''    bounds: LongRange?,
    prefs: ChartPrefs,
    selectedTimestamp: Long?,
'''
if 'curveStyles: Map<Long, CurveVisualPrefs>' not in text:
    if chart_sig not in text:
        raise SystemExit('v0.9: ChartCard signature anchor not found')
    text = text.replace(chart_sig, '''    bounds: LongRange?,
    prefs: ChartPrefs,
    curveStyles: Map<Long, CurveVisualPrefs>,
    styleTick: Long,
    selectedTimestamp: Long?,
''', 1)

interactive_call = '''                    prefs = prefs,
                    selectedTimestamp = selectedTimestamp,
'''
if 'curveStyles = curveStyles' not in text:
    if interactive_call not in text:
        raise SystemExit('v0.9: InteractiveChart call anchor not found')
    text = text.replace(interactive_call, '''                    prefs = prefs,
                    curveStyles = curveStyles,
                    styleTick = styleTick,
                    selectedTimestamp = selectedTimestamp,
''', 1)

# InteractiveChart signature is second occurrence of prefs signature.
interactive_sig = '''    to: Long,
    prefs: ChartPrefs,
    selectedTimestamp: Long?,
'''
if text.count('curveStyles: Map<Long, CurveVisualPrefs>') < 2:
    if interactive_sig not in text:
        raise SystemExit('v0.9: InteractiveChart signature anchor not found')
    text = text.replace(interactive_sig, '''    to: Long,
    prefs: ChartPrefs,
    curveStyles: Map<Long, CurveVisualPrefs>,
    styleTick: Long,
    selectedTimestamp: Long?,
''', 1)

# Apply styles/aura to main chart curves.
color_anchor = '''        sensors.forEach { sensor ->
            val color = palette[sensor.colorIndex % palette.size]
            val points = sampleMap[sensor.id].orEmpty().filter { it.timestamp in visibleFrom..visibleTo }
'''
if 'val visual = curveStyles[sensor.id]' not in text:
    if color_anchor not in text:
        raise SystemExit('v0.9: chart sensor color anchor not found')
    text = text.replace(color_anchor, '''        sensors.forEach { sensor ->
            val baseColor = palette[sensor.colorIndex % palette.size]
            val visual = curveStyles[sensor.id] ?: CurveVisualPrefs()
            val color = resolveCurveColor(baseColor, visual, styleTick) ?: Color.Transparent
            val auraColor = resolveAuraColor(visual, styleTick)
            val points = sampleMap[sensor.id].orEmpty().filter { it.timestamp in visibleFrom..visibleTo }
''', 1)

first_draw = '                drawPath(path, color, style = Stroke(width = prefs.lineWidth.dp.toPx()))\n'
if 'auraColor?.let { aura ->' not in text:
    if first_draw not in text:
        raise SystemExit('v0.9: temperature drawPath anchor not found')
    text = text.replace(first_draw, '''                auraColor?.let { aura ->
                    drawPath(path, aura, style = Stroke(width = (prefs.lineWidth + 7f).dp.toPx()))
                }
                drawPath(path, color, style = Stroke(width = prefs.lineWidth.dp.toPx()))
''', 1)

# Detail Lyon and curve style dialogs before annotation dialogs.
ui_anchor = '    if (remoteSensorDialogOpen) {\n'
if 'LyonDetailSheet(' not in text:
    if ui_anchor not in text:
        raise SystemExit('v0.9: dialog UI anchor not found')
    insert = '''    if (lyonDetailOpen) {
        LyonDetailSheet(
            store = lyonLab,
            client = meteoOfficial,
            credentialStore = meteoCredentials,
            styleStore = curveStyleStore,
            initialBounds = viewBounds,
            onDismiss = { lyonDetailOpen = false },
            onDataChanged = { reloadToken++ },
            onStyleEdit = { key, label -> styleEditKey = key to label }
        )
    }

    styleEditKey?.let { (key, label) ->
        CurveStyleDialog(
            curveLabel = label,
            initial = curveStyleStore.load(key),
            onDismiss = { styleEditKey = null },
            onSave = { value ->
                curveStyleStore.save(key, value)
                styleVersion++
                styleEditKey = null
            }
        )
    }

'''
    text = text.replace(ui_anchor, insert + ui_anchor, 1)

MAIN.write_text(text, encoding='utf-8')
print('FabData v0.9.0 Lyon lab integration patch applied')
