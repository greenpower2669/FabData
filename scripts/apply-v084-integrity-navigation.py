from pathlib import Path

DATA = Path("app/src/main/java/com/fabdata/app/DataLayer.kt")
MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")

# DataLayer: preserve every real CSV timestamp + expose all annotations.
text = DATA.read_text(encoding="utf-8")
original = text

start_marker = '                if (exactKnownFormat && rows.isNotEmpty()) {\n'
end_marker = '                } else {\n                    invalid += parseGenericRows(rows, delimiter, headers, parsed)\n                }\n'
if "Respecte le timestamp REEL de chaque ligne" not in text:
    start = text.find(start_marker)
    end_start = text.find(end_marker, start)
    if start < 0 or end_start < 0:
        raise SystemExit("v0.8.4: exact thermo import block not found")
    end = end_start + len(end_marker)
    replacement = '''                if (exactKnownFormat && rows.isNotEmpty()) {
                    // Respecte le timestamp REEL de chaque ligne.
                    // Ne reconstruit plus artificiellement la série à pas fixe de 60 s :
                    // les trous, coupures et blocs discontinus restent à leur vraie place.
                    rows.forEach { line ->
                        try {
                            val fields = splitCsv(line, delimiter)
                            val ts = parseExactThermoTime(fields.getOrNull(0).orEmpty())
                            val temp = parseNumber(fields.getOrNull(1).orEmpty())
                            val hum = parseNumber(fields.getOrNull(2).orEmpty())
                            if (ts == null || temp == null || hum == null ||
                                temp !in -100.0..150.0 || hum !in 0.0..100.0
                            ) {
                                invalid++
                            } else {
                                parsed += ParsedPoint(ts, temp, hum)
                            }
                        } catch (_: Exception) {
                            invalid++
                        }
                    }
                } else {
                    invalid += parseGenericRows(rows, delimiter, headers, parsed)
                }
'''
    text = text[:start] + replacement + text[end:]

if "fun annotationsAll()" not in text:
    anchor = '    fun deleteAnnotation(id: Long) {\n'
    insert = '''    /** Toutes les annotations réellement stockées, indépendamment du zoom courant. */
    fun annotationsAll(): List<AnnotationItem> {
        val out = mutableListOf<AnnotationItem>()
        readableDatabase.rawQuery(
            "SELECT id, timestamp, title, note, sensor_id, room_name, type, updated_at FROM annotations ORDER BY timestamp",
            null
        ).use { c ->
            while (c.moveToNext()) {
                out += AnnotationItem(
                    id = c.getLong(0), timestamp = c.getLong(1), title = c.getString(2), note = c.getString(3),
                    sensorId = if (c.isNull(4)) null else c.getLong(4),
                    roomName = if (c.isNull(5)) null else c.getString(5),
                    type = if (c.isNull(6)) null else c.getString(6),
                    updatedAt = if (c.isNull(7)) 0L else c.getLong(7)
                )
            }
        }
        return out
    }

'''
    if anchor not in text:
        raise SystemExit("v0.8.4: deleteAnnotation anchor not found")
    text = text.replace(anchor, insert + anchor, 1)

if text != original:
    DATA.write_text(text, encoding="utf-8")

# MainActivity: physical-history navigation, 48 h default, all annotations,
# centered selection, overview navigator and corrected gestures.
text = MAIN.read_text(encoding="utf-8")
original = text

old = '''private enum class TimePreset(val label: String, val spanMs: Long) {
    HOUR("Heure", 60L * 60L * 1000L),
    DAY("Jour", 24L * 60L * 60L * 1000L),
    WEEK("Semaine", 7L * 24L * 60L * 60L * 1000L),
    MONTH("Mois", 31L * 24L * 60L * 60L * 1000L),
    YEAR("Année", 366L * 24L * 60L * 60L * 1000L)
}
'''
new = '''private enum class TimePreset(val label: String, val spanMs: Long) {
    HOUR("1 h", 60L * 60L * 1000L),
    DAY("24 h", 24L * 60L * 60L * 1000L),
    TWO_DAYS("48 h", 48L * 60L * 60L * 1000L),
    WEEK("1 sem.", 7L * 24L * 60L * 60L * 1000L),
    MONTH("1 mois", 31L * 24L * 60L * 60L * 1000L)
}
'''
if 'TWO_DAYS("48 h"' not in text:
    if old not in text:
        raise SystemExit("v0.8.4: TimePreset block not found")
    text = text.replace(old, new, 1)

old = '''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>
)
'''
new = '''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val overviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>
)
'''
if "val overviewSamples: Map<Long, List<SamplePoint>>" not in text:
    if old not in text:
        raise SystemExit("v0.8.4: LoadedData block not found")
    text = text.replace(old, new, 1)

old = '''    var annotations by remember { mutableStateOf<List<AnnotationItem>>(emptyList()) }
    var globalBounds by remember { mutableStateOf<LongRange?>(null) }
    var viewBounds by remember { mutableStateOf<LongRange?>(null) }
    var preset by rememberSaveable { mutableStateOf(TimePreset.WEEK) }
    var reloadToken by remember { mutableIntStateOf(0) }
'''
new = '''    var annotations by remember { mutableStateOf<List<AnnotationItem>>(emptyList()) }
    var allAnnotations by remember { mutableStateOf<List<AnnotationItem>>(emptyList()) }
    var overviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var globalBounds by remember { mutableStateOf<LongRange?>(null) }
    var viewBounds by remember { mutableStateOf<LongRange?>(null) }
    var preset by rememberSaveable { mutableStateOf(TimePreset.TWO_DAYS) }
    var windowCenterTimestamp by remember { mutableStateOf<Long?>(null) }
    var showAllAnnotations by rememberSaveable { mutableStateOf(true) }
    var reloadToken by remember { mutableIntStateOf(0) }
'''
if "var overviewSampleMap by remember" not in text:
    if old not in text:
        raise SystemExit("v0.8.4: state block not found")
    text = text.replace(old, new, 1)

if "Les thermomètres physiques/importés définissent la période de navigation." not in text:
    start = text.find('    LaunchedEffect(reloadToken, preset) {\n')
    end = text.find('\n\n    Scaffold(', start)
    if start < 0 or end < 0:
        raise SystemExit("v0.8.4: data load block not found")
    replacement = '''    LaunchedEffect(reloadToken, preset, windowCenterTimestamp) {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            val s = db.sensors()

            // Les thermomètres physiques/importés définissent la période de navigation.
            // Lyon et les sondes HTTP complètent cette période sans pousser l'ancien hors écran.
            val all = db.physicalSensorBounds() ?: db.globalTimeBounds()
            val chosen = all?.let { bounds ->
                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)
                val requested = minOf(preset.spanMs, fullSpan)
                if (requested >= fullSpan) {
                    bounds
                } else {
                    val defaultCenter = bounds.last - requested / 2L
                    val center = (windowCenterTimestamp ?: defaultCenter).coerceIn(bounds.first, bounds.last)
                    var windowStart = center - requested / 2L
                    var windowEnd = windowStart + requested
                    if (windowStart < bounds.first) {
                        windowStart = bounds.first
                        windowEnd = windowStart + requested
                    }
                    if (windowEnd > bounds.last) {
                        windowEnd = bounds.last
                        windowStart = windowEnd - requested
                    }
                    windowStart..windowEnd
                }
            }

            val allNotes = db.annotationsAll()
            if (chosen == null || all == null) {
                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes)
            } else {
                val samples = s.associate { sensor ->
                    sensor.id to db.querySamples(sensor.id, chosen.first, chosen.last)
                }
                val overview = s.associate { sensor ->
                    sensor.id to db.querySamples(sensor.id, all.first, all.last, maxPoints = 600)
                }
                val stat = s.mapNotNull { sensor ->
                    db.stats(sensor.id, chosen.first, chosen.last)?.let { value -> sensor.id to value }
                }.toMap()
                LoadedData(
                    s, all, chosen, samples, overview, stat,
                    db.annotations(chosen.first, chosen.last), allNotes
                )
            }
        }
        sensors = loaded.sensors
        globalBounds = loaded.globalBounds
        viewBounds = loaded.viewBounds
        sampleMap = loaded.samples
        overviewSampleMap = loaded.overviewSamples
        statsMap = loaded.stats
        annotations = loaded.annotations
        allAnnotations = loaded.allAnnotations

        loaded.viewBounds?.let { bounds ->
            val current = selectedTimestamp
            if (current == null || current !in bounds) {
                selectedTimestamp = bounds.first + (bounds.last - bounds.first) / 2L
            }
        }

        sensors.forEach { sensor ->
            if (!showTemp.containsKey(sensor.id)) showTemp[sensor.id] = true
            if (!showHumidity.containsKey(sensor.id)) showHumidity[sensor.id] = false
        }
        busy = false
    }'''
    text = text[:start] + replacement + text[end:]

old = '''                TimeTabs(preset = preset, onSelect = {
                    preset = it
                    selectedTimestamp = null
                    selectedAnnotation = null
                })
'''
new = '''                TimeTabs(preset = preset, onSelect = {
                    preset = it
                    windowCenterTimestamp = selectedTimestamp
                        ?: viewBounds?.let { b -> b.first + (b.last - b.first) / 2L }
                    selectedAnnotation = null
                })
'''
if "windowCenterTimestamp = selectedTimestamp" not in text:
    if old not in text:
        raise SystemExit("v0.8.4: TimeTabs callback not found")
    text = text.replace(old, new, 1)

anchor = '''                item {
                    ChartCard(
'''
insert = '''                item {
                    HistoryOverviewCard(
                        sensors = sensors,
                        sampleMap = overviewSampleMap,
                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        onSelect = { ts ->
                            preset = TimePreset.TWO_DAYS
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        }
                    )
                }

'''
if "HistoryOverviewCard(" not in text:
    if anchor not in text:
        raise SystemExit("v0.8.4: ChartCard item anchor not found")
    text = text.replace(anchor, insert + anchor, 1)

old = '''                        onRequestAnnotation = { ts ->
                            editingAnnotation = null
                            annotationTimestamp = ts
                            selectedTimestamp = ts
                        }
                    )
'''
new = '''                        onRequestAnnotation = { ts ->
                            editingAnnotation = null
                            annotationTimestamp = ts
                            selectedTimestamp = ts
                        },
                        onRequestZoom = { ts ->
                            preset = TimePreset.TWO_DAYS
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        }
                    )
'''
if "onRequestZoom = { ts ->" not in text:
    if old not in text:
        raise SystemExit("v0.8.4: ChartCard callback tail not found")
    text = text.replace(old, new, 1)

old = '''                item {
                    AnnotationSection(
                        annotations = annotations,
                        sensors = sensors,
                        onOpen = { detailAnnotation = it },
                        onDelete = { id ->
                            scope.launch {
                                withContext(Dispatchers.IO) { db.deleteAnnotation(id) }
                                if (selectedAnnotation?.id == id) selectedAnnotation = null
                                if (detailAnnotation?.id == id) detailAnnotation = null
                                reloadToken++
                            }
                        }
                    )
                }
'''
new = '''                item {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            if (showAllAnnotations) "Toutes les annotations" else "Annotations de la période",
                            Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold
                        )
                        Switch(checked = showAllAnnotations, onCheckedChange = { showAllAnnotations = it })
                    }
                    AnnotationSection(
                        annotations = if (showAllAnnotations) allAnnotations else annotations,
                        sensors = sensors,
                        onOpen = { detailAnnotation = it },
                        onDelete = { id ->
                            scope.launch {
                                withContext(Dispatchers.IO) { db.deleteAnnotation(id) }
                                if (selectedAnnotation?.id == id) selectedAnnotation = null
                                if (detailAnnotation?.id == id) detailAnnotation = null
                                reloadToken++
                            }
                        }
                    )
                }
'''
if 'if (showAllAnnotations) "Toutes les annotations" else "Annotations de la période"' not in text:
    if old not in text:
        raise SystemExit("v0.8.4: AnnotationSection item block not found")
    text = text.replace(old, new, 1)

old = '            "Pince = zoom temps · glisse = déplacer · double tap fond = reset · appui long = événement",\n'
new = '            "Tap = curseur · double tap = événement · appui long = zoom 48 h · pince/glisse = ajuster",\n'
if new.strip() not in text:
    if old not in text:
        raise SystemExit("v0.8.4: TimeTabs help text not found")
    text = text.replace(old, new, 1)

sig_old = '''    onAnnotationDoubleClick: (AnnotationItem) -> Unit,
    onRequestAnnotation: (Long) -> Unit
) {
'''
sig_new = '''    onAnnotationDoubleClick: (AnnotationItem) -> Unit,
    onRequestAnnotation: (Long) -> Unit,
    onRequestZoom: (Long) -> Unit
) {
'''
if "onRequestZoom: (Long) -> Unit" not in text:
    if text.count(sig_old) < 2:
        raise SystemExit("v0.8.4: chart signature anchors not found twice")
    text = text.replace(sig_old, sig_new, 2)

old = '''                    onAnnotationDoubleClick = onAnnotationDoubleClick,
                    onRequestAnnotation = onRequestAnnotation
                )
'''
new = '''                    onAnnotationDoubleClick = onAnnotationDoubleClick,
                    onRequestAnnotation = onRequestAnnotation,
                    onRequestZoom = onRequestZoom
                )
'''
if "onRequestZoom = onRequestZoom" not in text:
    if old not in text:
        raise SystemExit("v0.8.4: InteractiveChart call tail not found")
    text = text.replace(old, new, 1)

old = '                            onRequestAnnotation(window.first + (span * frac).toLong())\n'
new = '                            onRequestZoom(window.first + (span * frac).toLong())\n'
if new not in text:
    if old not in text:
        raise SystemExit("v0.8.4: long-press action not found")
    text = text.replace(old, new, 1)

old = '''                        if (hit != null) {
                            onAnnotationDoubleClick(hit)
                        } else {
                            zoom = 1f
                            center = 0.5f
                        }
'''
new = '''                        if (hit != null) {
                            onAnnotationDoubleClick(hit)
                        } else if (p.x in left..right) {
                            val frac = ((p.x - left) / (right - left)).coerceIn(0f, 1f)
                            onRequestAnnotation(window.first + (span * frac).toLong())
                        }
'''
if "onRequestAnnotation(window.first + (span * frac).toLong())" not in text:
    if old not in text:
        raise SystemExit("v0.8.4: double-tap fallback block not found")
    text = text.replace(old, new, 1)

anchor = '''@Composable
private fun ChartCard(
'''
overview = '''@Composable
private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,
    viewBounds: LongRange?,
    onSelect: (Long) -> Unit
) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Text("Vue globale", fontWeight = FontWeight.Bold)
            Text(
                "Tap sur l’historique = afficher 48 h autour de ce point",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            val bounds = historyBounds
            val allPoints = sensors.flatMap { sensor -> sampleMap[sensor.id].orEmpty() }
            if (bounds == null || allPoints.isEmpty()) {
                Text("Historique global indisponible", style = MaterialTheme.typography.bodySmall)
            } else {
                val minTemp = allPoints.minOf { it.temperature }
                val maxTemp = allPoints.maxOf { it.temperature }
                val range = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0
                val span = (bounds.last - bounds.first).coerceAtLeast(1L)
                val highlight = MaterialTheme.colorScheme.primary
                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)

                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(86.dp)
                        .background(surface, RoundedCornerShape(12.dp))
                        .pointerInput(bounds, viewBounds) {
                            detectTapGestures { p ->
                                val frac = (p.x / size.width.toFloat()).coerceIn(0f, 1f)
                                onSelect(bounds.first + (span * frac).toLong())
                            }
                        }
                ) {
                    sensors.forEach { sensor ->
                        val points = sampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in bounds }
                            .sortedBy { it.timestamp }
                        if (points.size >= 2) {
                            val path = Path()
                            points.forEachIndexed { index, point ->
                                val x = ((point.timestamp - bounds.first).toDouble() / span.toDouble()).toFloat() * size.width
                                val y = size.height - (((point.temperature - minTemp) / range).toFloat() * size.height)
                                if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                            }
                            drawPath(
                                path,
                                palette[sensor.colorIndex % palette.size].copy(alpha = 0.72f),
                                style = Stroke(width = 1.5.dp.toPx())
                            )
                        }
                    }
                    viewBounds?.let { visible ->
                        val left = (((visible.first - bounds.first).toDouble() / span.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        val right = (((visible.last - bounds.first).toDouble() / span.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        if (right > left) {
                            drawRect(
                                highlight.copy(alpha = 0.14f),
                                topLeft = Offset(left, 0f),
                                size = androidx.compose.ui.geometry.Size(right - left, size.height)
                            )
                            drawLine(highlight.copy(alpha = 0.8f), Offset(left, 0f), Offset(left, size.height), 2f)
                            drawLine(highlight.copy(alpha = 0.8f), Offset(right, 0f), Offset(right, size.height), 2f)
                        }
                    }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDateTime(bounds.first), style = MaterialTheme.typography.labelSmall)
                    Text(formatDateTime(bounds.last), style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}

'''
if "private fun HistoryOverviewCard(" not in text:
    if anchor not in text:
        raise SystemExit("v0.8.4: ChartCard composable anchor not found")
    text = text.replace(anchor, overview + anchor, 1)

if text != original:
    MAIN.write_text(text, encoding="utf-8")

print("FabData v0.8.4 integrity/navigation patch applied")
