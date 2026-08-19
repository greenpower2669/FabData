package com.fabdata.app

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FileOpen
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val db = FabDataDb(applicationContext)
        val initialUri = intent?.data
        setContent {
            FabDataTheme {
                FabDataApp(db = db, initialImport = initialUri)
            }
        }
    }
}

private enum class RangePreset(val label: String, val hours: Int?) {
    H1("1 h", 1), H6("6 h", 6), H12("12 h", 12), H24("24 h", 24), ALL("Tout", null)
}

private data class ChartPrefs(
    val showGrid: Boolean,
    val showPoints: Boolean,
    val lineWidth: Float,
    val highTemp: Double,
    val lowHumidity: Double,
    val highHumidity: Double
)

private class FabPrefs(context: Context) {
    private val p = context.getSharedPreferences("fabdata_prefs", Context.MODE_PRIVATE)
    fun load() = ChartPrefs(
        showGrid = p.getBoolean("show_grid", true),
        showPoints = p.getBoolean("show_points", false),
        lineWidth = p.getFloat("line_width", 2.5f),
        highTemp = p.getString("high_temp", "30")?.toDoubleOrNull() ?: 30.0,
        lowHumidity = p.getString("low_humidity", "30")?.toDoubleOrNull() ?: 30.0,
        highHumidity = p.getString("high_humidity", "70")?.toDoubleOrNull() ?: 70.0
    )
    fun save(v: ChartPrefs) {
        p.edit()
            .putBoolean("show_grid", v.showGrid)
            .putBoolean("show_points", v.showPoints)
            .putFloat("line_width", v.lineWidth)
            .putString("high_temp", v.highTemp.toString())
            .putString("low_humidity", v.lowHumidity.toString())
            .putString("high_humidity", v.highHumidity.toString())
            .apply()
    }
}

private val palette = listOf(
    Color(0xFF1769AA), Color(0xFFD1495B), Color(0xFF2A9D8F), Color(0xFFE08E0B),
    Color(0xFF6A4C93), Color(0xFF0081A7), Color(0xFFB56576), Color(0xFF588157)
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FabDataApp(db: FabDataDb, initialImport: android.net.Uri?) {
    val context = LocalContext.current
    val importer = remember { CsvImporter(context, db) }
    val prefsStore = remember { FabPrefs(context) }
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    var sensors by remember { mutableStateOf<List<Sensor>>(emptyList()) }
    var sampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var statsMap by remember { mutableStateOf<Map<Long, SensorStats>>(emptyMap()) }
    var annotations by remember { mutableStateOf<List<AnnotationItem>>(emptyList()) }
    var bounds by remember { mutableStateOf<LongRange?>(null) }
    var preset by rememberSaveable { mutableStateOf(RangePreset.ALL) }
    var reloadToken by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var selectedTimestamp by remember { mutableStateOf<Long?>(null) }
    var settingsOpen by remember { mutableStateOf(false) }
    var annotationOpen by remember { mutableStateOf(false) }
    var editSensor by remember { mutableStateOf<Sensor?>(null) }
    var prefs by remember { mutableStateOf(prefsStore.load()) }
    val showTemp = remember { mutableStateMapOf<Long, Boolean>() }
    val showHumidity = remember { mutableStateMapOf<Long, Boolean>() }
    var initialHandled by remember { mutableStateOf(false) }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            scope.launch {
                busy = true
                val results = withContext(Dispatchers.IO) {
                    uris.map { uri -> runCatching { importer.import(uri) } }
                }
                val ok = results.mapNotNull { it.getOrNull() }
                val errors = results.count { it.isFailure }
                val added = ok.sumOf { it.added }
                val duplicates = ok.sumOf { it.duplicates }
                val invalid = ok.sumOf { it.invalid }
                busy = false
                reloadToken++
                snackbar.showSnackbar("Import : $added ajoutées · $duplicates déjà présentes · $invalid invalides${if (errors > 0) " · $errors fichier(s) en erreur" else ""}")
            }
        }
    }

    LaunchedEffect(initialImport, initialHandled) {
        if (!initialHandled && initialImport != null) {
            initialHandled = true
            busy = true
            val result = withContext(Dispatchers.IO) { runCatching { importer.import(initialImport) } }
            busy = false
            reloadToken++
            snackbar.showSnackbar(result.fold(
                onSuccess = { "${it.added} mesure(s) ajoutée(s), ${it.duplicates} déjà présentes" },
                onFailure = { "Import impossible : ${it.message ?: "format inconnu"}" }
            ))
        }
    }

    LaunchedEffect(reloadToken, preset) {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            val s = db.sensors()
            val allBounds = db.globalTimeBounds()
            val chosenBounds = if (allBounds == null) null else {
                val end = allBounds.last
                val start = preset.hours?.let { max(allBounds.first, end - it * 60L * 60L * 1000L) } ?: allBounds.first
                start..end
            }
            if (chosenBounds == null) {
                LoadedData(s, null, emptyMap(), emptyMap(), emptyList())
            } else {
                val samples = s.associate { sensor -> sensor.id to db.querySamples(sensor.id, chosenBounds.first, chosenBounds.last) }
                val stat = s.mapNotNull { sensor -> db.stats(sensor.id, chosenBounds.first, chosenBounds.last)?.let { sensor.id to it } }.toMap()
                val notes = db.annotations(chosenBounds.first, chosenBounds.last)
                LoadedData(s, chosenBounds, samples, stat, notes)
            }
        }
        sensors = loaded.sensors
        bounds = loaded.bounds
        sampleMap = loaded.samples
        statsMap = loaded.stats
        annotations = loaded.annotations
        sensors.forEach { sensor ->
            if (!showTemp.containsKey(sensor.id)) showTemp[sensor.id] = true
            if (!showHumidity.containsKey(sensor.id)) showHumidity[sensor.id] = false
        }
        busy = false
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("FabData", fontWeight = FontWeight.Bold)
                        Text(
                            if (busy) "Mise à jour…" else "Analyse thermo-hygrométrique",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel")) }) {
                        Icon(Icons.Default.FileOpen, contentDescription = "Importer des CSV")
                    }
                    IconButton(onClick = { reloadToken++ }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Actualiser")
                    }
                    IconButton(onClick = { settingsOpen = true }) {
                        Icon(Icons.Default.Settings, contentDescription = "Réglages")
                    }
                }
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { annotationOpen = true }, containerColor = MaterialTheme.colorScheme.primaryContainer) {
                Icon(Icons.Default.Add, contentDescription = "Ajouter une annotation")
            }
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                DashboardSummary(sensors, statsMap, bounds)
            }
            item {
                RangeSelector(preset = preset, onSelect = { preset = it })
            }
            if (sensors.isEmpty()) {
                item {
                    EmptyState(onImport = { picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel")) })
                }
            } else {
                item {
                    SeriesSelector(
                        sensors = sensors,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        onEdit = { editSensor = it }
                    )
                }
                item {
                    ChartCard(
                        sensors = sensors,
                        sampleMap = sampleMap,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        annotations = annotations,
                        bounds = bounds,
                        prefs = prefs,
                        selectedTimestamp = selectedTimestamp,
                        onSelectTimestamp = { selectedTimestamp = it }
                    )
                }
                selectedTimestamp?.let { ts ->
                    item {
                        InspectorCard(ts, sensors, sampleMap, showTemp, showHumidity)
                    }
                }
                item {
                    Text("Résumé par pièce", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                }
                items(sensors, key = { it.id }) { sensor ->
                    SensorStatsCard(sensor, statsMap[sensor.id], prefs)
                }
                item {
                    AnnotationSection(
                        annotations = annotations,
                        sensors = sensors,
                        onDelete = { id ->
                            scope.launch {
                                withContext(Dispatchers.IO) { db.deleteAnnotation(id) }
                                reloadToken++
                            }
                        }
                    )
                }
                item { Spacer(Modifier.height(70.dp)) }
            }
        }
    }

    if (settingsOpen) {
        SettingsDialog(
            initial = prefs,
            onDismiss = { settingsOpen = false },
            onSave = {
                prefs = it
                prefsStore.save(it)
                settingsOpen = false
            },
            onClear = {
                scope.launch {
                    withContext(Dispatchers.IO) { db.clearAll() }
                    showTemp.clear(); showHumidity.clear(); selectedTimestamp = null
                    reloadToken++
                    settingsOpen = false
                    snackbar.showSnackbar("Base FabData vidée")
                }
            }
        )
    }

    if (annotationOpen) {
        AnnotationDialog(
            initialTimestamp = selectedTimestamp ?: bounds?.last ?: System.currentTimeMillis(),
            sensors = sensors,
            onDismiss = { annotationOpen = false },
            onSave = { timestamp, title, note, sensorId ->
                scope.launch {
                    withContext(Dispatchers.IO) { db.addAnnotation(timestamp, title, note, sensorId) }
                    annotationOpen = false
                    reloadToken++
                }
            }
        )
    }

    editSensor?.let { sensor ->
        SensorEditDialog(
            sensor = sensor,
            onDismiss = { editSensor = null },
            onSave = { name, room, colorIndex ->
                scope.launch {
                    withContext(Dispatchers.IO) { db.updateSensor(sensor.id, name, room, colorIndex) }
                    editSensor = null
                    reloadToken++
                }
            },
            onDelete = {
                scope.launch {
                    withContext(Dispatchers.IO) { db.deleteSensor(sensor.id) }
                    showTemp.remove(sensor.id); showHumidity.remove(sensor.id)
                    editSensor = null
                    reloadToken++
                }
            }
        )
    }
}

private data class LoadedData(
    val sensors: List<Sensor>,
    val bounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>
)

@Composable
private fun DashboardSummary(sensors: List<Sensor>, stats: Map<Long, SensorStats>, bounds: LongRange?) {
    val points = stats.values.sumOf { it.count }
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.55f)),
        shape = RoundedCornerShape(22.dp)
    ) {
        Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Vue d’ensemble", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(22.dp)) {
                Metric("Capteurs", sensors.size.toString())
                Metric("Points", points.toString())
                Metric("Fenêtre", bounds?.let { compactDuration(it.last - it.first) } ?: "—")
            }
            if (bounds != null) {
                Text(
                    "${formatDateTime(bounds.first)} → ${formatDateTime(bounds.last)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun Metric(label: String, value: String) {
    Column {
        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun RangeSelector(preset: RangePreset, onSelect: (RangePreset) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("Période", style = MaterialTheme.typography.labelLarge)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            RangePreset.entries.forEach { item ->
                AssistChip(
                    onClick = { onSelect(item) },
                    label = { Text(item.label) },
                    leadingIcon = if (item == preset) ({ Text("✓") }) else null
                )
            }
        }
    }
}

@Composable
private fun EmptyState(onImport: () -> Unit) {
    Card(shape = RoundedCornerShape(22.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Icon(Icons.Default.FileOpen, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.primary)
            Text("Aucune donnée", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("Importe un ou plusieurs exports CSV. Les réimports chevauchants complètent automatiquement la base sans dupliquer les dates.")
            Button(onClick = onImport) { Text("Importer des CSV") }
        }
    }
}

@Composable
private fun SeriesSelector(
    sensors: List<Sensor>,
    showTemp: MutableMap<Long, Boolean>,
    showHumidity: MutableMap<Long, Boolean>,
    onEdit: (Sensor) -> Unit
) {
    Card(shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Superposition des courbes", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text("Coche les séries à comparer. T° = température, % = humidité.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            sensors.forEach { sensor ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(11.dp).background(palette[sensor.colorIndex % palette.size], RoundedCornerShape(6.dp)))
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        Text(sensor.room, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (sensor.name != sensor.room) Text(sensor.name, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text("T°", style = MaterialTheme.typography.labelMedium)
                    Checkbox(checked = showTemp[sensor.id] == true, onCheckedChange = { showTemp[sensor.id] = it })
                    Text("%", style = MaterialTheme.typography.labelMedium)
                    Checkbox(checked = showHumidity[sensor.id] == true, onCheckedChange = { showHumidity[sensor.id] = it })
                    IconButton(onClick = { onEdit(sensor) }) { Icon(Icons.Default.Edit, contentDescription = "Modifier le capteur") }
                }
            }
        }
    }
}

@Composable
private fun ChartCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    showTemp: Map<Long, Boolean>,
    showHumidity: Map<Long, Boolean>,
    annotations: List<AnnotationItem>,
    bounds: LongRange?,
    prefs: ChartPrefs,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit
) {
    var resetKey by remember { mutableIntStateOf(0) }
    Card(shape = RoundedCornerShape(22.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Courbes", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("Pince pour zoomer · glisse pour parcourir · touche pour inspecter", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                OutlinedButton(onClick = { resetKey++ }) { Text("Reset zoom") }
            }
            if (bounds == null) {
                Box(Modifier.fillMaxWidth().height(300.dp), contentAlignment = Alignment.Center) { Text("Pas de données") }
            } else {
                InteractiveChart(
                    modifier = Modifier.fillMaxWidth().height(360.dp),
                    sensors = sensors,
                    sampleMap = sampleMap,
                    showTemp = showTemp,
                    showHumidity = showHumidity,
                    annotations = annotations,
                    from = bounds.first,
                    to = bounds.last,
                    prefs = prefs,
                    selectedTimestamp = selectedTimestamp,
                    resetKey = resetKey,
                    onSelectTimestamp = onSelectTimestamp
                )
            }
        }
    }
}

@Composable
private fun InteractiveChart(
    modifier: Modifier,
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    showTemp: Map<Long, Boolean>,
    showHumidity: Map<Long, Boolean>,
    annotations: List<AnnotationItem>,
    from: Long,
    to: Long,
    prefs: ChartPrefs,
    selectedTimestamp: Long?,
    resetKey: Int,
    onSelectTimestamp: (Long) -> Unit
) {
    var zoom by remember(resetKey, from, to) { mutableFloatStateOf(1f) }
    var center by remember(resetKey, from, to) { mutableFloatStateOf(0.5f) }
    val axisColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.55f)
    val gridColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f)
    val textColor = MaterialTheme.colorScheme.onSurfaceVariant
    val annotationColor = MaterialTheme.colorScheme.tertiary
    val selectColor = MaterialTheme.colorScheme.primary

    Canvas(
        modifier = modifier
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.22f), RoundedCornerShape(16.dp))
            .pointerInput(from, to, resetKey) {
                detectTransformGestures { _, pan, zoomChange, _ ->
                    val newZoom = (zoom * zoomChange).coerceIn(1f, 180f)
                    val oldVisible = 1f / zoom
                    zoom = newZoom
                    val visible = 1f / zoom
                    center = (center - (pan.x / size.width.toFloat()) * oldVisible)
                        .coerceIn(visible / 2f, 1f - visible / 2f)
                }
            }
            .pointerInput(from, to, resetKey, zoom, center) {
                detectTapGestures { p ->
                    val visibleFraction = 1f / zoom
                    val startFraction = (center - visibleFraction / 2f).coerceIn(0f, 1f - visibleFraction)
                    val left = 52.dp.toPx()
                    val right = size.width - 44.dp.toPx()
                    if (p.x in left..right) {
                        val xFraction = ((p.x - left) / (right - left)).coerceIn(0f, 1f)
                        val fraction = startFraction + xFraction * visibleFraction
                        onSelectTimestamp(from + ((to - from) * fraction).toLong())
                    }
                }
            }
    ) {
        val left = 52.dp.toPx()
        val right = size.width - 44.dp.toPx()
        val top = 18.dp.toPx()
        val bottom = size.height - 36.dp.toPx()
        val plotW = (right - left).coerceAtLeast(1f)
        val plotH = (bottom - top).coerceAtLeast(1f)
        val fullSpan = (to - from).coerceAtLeast(1L)
        val visibleFraction = 1f / zoom
        val startFraction = (center - visibleFraction / 2f).coerceIn(0f, 1f - visibleFraction)
        val endFraction = startFraction + visibleFraction
        val visibleFrom = from + (fullSpan * startFraction).toLong()
        val visibleTo = from + (fullSpan * endFraction).toLong()
        val visibleSpan = (visibleTo - visibleFrom).coerceAtLeast(1L)

        val activeTemp = sensors.filter { showTemp[it.id] == true }
            .flatMap { sampleMap[it.id].orEmpty() }
            .filter { it.timestamp in visibleFrom..visibleTo }
            .map { it.temperature }
        val activeHum = sensors.filter { showHumidity[it.id] == true }
            .flatMap { sampleMap[it.id].orEmpty() }
            .filter { it.timestamp in visibleFrom..visibleTo }
            .map { it.humidity }

        val tempRange = paddedRange(activeTemp, fallbackMin = 15.0, fallbackMax = 35.0, clampMin = -50.0, clampMax = 80.0)
        val humRange = paddedRange(activeHum, fallbackMin = 30.0, fallbackMax = 70.0, clampMin = 0.0, clampMax = 100.0)

        if (prefs.showGrid) {
            for (i in 0..4) {
                val y = top + plotH * i / 4f
                drawLine(gridColor, Offset(left, y), Offset(right, y), strokeWidth = 1f)
            }
            for (i in 0..4) {
                val x = left + plotW * i / 4f
                drawLine(gridColor, Offset(x, top), Offset(x, bottom), strokeWidth = 1f)
            }
        }
        drawLine(axisColor, Offset(left, top), Offset(left, bottom), 1.5f)
        drawLine(axisColor, Offset(right, top), Offset(right, bottom), 1.5f)
        drawLine(axisColor, Offset(left, bottom), Offset(right, bottom), 1.5f)

        val paint = android.graphics.Paint().apply {
            isAntiAlias = true
            textSize = 10.dp.toPx()
            color = textColor.toArgbCompat()
        }
        val rightPaint = android.graphics.Paint(paint).apply { textAlign = android.graphics.Paint.Align.RIGHT }
        val centerPaint = android.graphics.Paint(paint).apply { textAlign = android.graphics.Paint.Align.CENTER }

        if (activeTemp.isNotEmpty()) {
            for (i in 0..4) {
                val v = tempRange.second - (tempRange.second - tempRange.first) * i / 4.0
                val y = top + plotH * i / 4f
                drawContext.canvas.nativeCanvas.drawText(String.format(Locale.FRANCE, "%.1f°", v), 4.dp.toPx(), y + 4.dp.toPx(), paint)
            }
        }
        if (activeHum.isNotEmpty()) {
            for (i in 0..4) {
                val v = humRange.second - (humRange.second - humRange.first) * i / 4.0
                val y = top + plotH * i / 4f
                drawContext.canvas.nativeCanvas.drawText(String.format(Locale.FRANCE, "%.0f%%", v), size.width - 3.dp.toPx(), y + 4.dp.toPx(), rightPaint)
            }
        }
        for (i in 0..4) {
            val ts = visibleFrom + visibleSpan * i / 4L
            val x = left + plotW * i / 4f
            drawContext.canvas.nativeCanvas.drawText(formatAxisTime(ts, visibleSpan), x, size.height - 9.dp.toPx(), centerPaint)
        }

        fun mapX(ts: Long): Float = left + ((ts - visibleFrom).toDouble() / visibleSpan.toDouble()).toFloat() * plotW
        fun mapTemp(v: Double): Float = bottom - (((v - tempRange.first) / (tempRange.second - tempRange.first)).toFloat() * plotH)
        fun mapHum(v: Double): Float = bottom - (((v - humRange.first) / (humRange.second - humRange.first)).toFloat() * plotH)

        annotations.filter { it.timestamp in visibleFrom..visibleTo }.forEach { note ->
            val x = mapX(note.timestamp)
            drawLine(annotationColor.copy(alpha = 0.8f), Offset(x, top), Offset(x, bottom), 1.5f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 7f)))
            val notePaint = android.graphics.Paint(paint).apply { color = annotationColor.toArgbCompat(); textSize = 9.dp.toPx() }
            drawContext.canvas.nativeCanvas.drawText(note.title.take(18), x + 3.dp.toPx(), top + 12.dp.toPx(), notePaint)
        }

        sensors.forEach { sensor ->
            val color = palette[sensor.colorIndex % palette.size]
            val points = sampleMap[sensor.id].orEmpty().filter { it.timestamp in visibleFrom..visibleTo }
            if (showTemp[sensor.id] == true && points.size >= 2) {
                val path = Path()
                points.forEachIndexed { index, p ->
                    val x = mapX(p.timestamp); val y = mapTemp(p.temperature)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, color, style = Stroke(width = prefs.lineWidth.dp.toPx()))
                if (prefs.showPoints || zoom > 20f) {
                    points.forEach { p -> drawCircle(color, radius = 2.2.dp.toPx(), center = Offset(mapX(p.timestamp), mapTemp(p.temperature))) }
                }
            }
            if (showHumidity[sensor.id] == true && points.size >= 2) {
                val path = Path()
                points.forEachIndexed { index, p ->
                    val x = mapX(p.timestamp); val y = mapHum(p.humidity)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, color.copy(alpha = 0.8f), style = Stroke(width = max(1.2f, prefs.lineWidth - 0.5f).dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 7f))))
                if (prefs.showPoints || zoom > 20f) {
                    points.forEach { p -> drawCircle(color.copy(alpha = 0.8f), radius = 2.dp.toPx(), center = Offset(mapX(p.timestamp), mapHum(p.humidity))) }
                }
            }
        }

        selectedTimestamp?.takeIf { it in visibleFrom..visibleTo }?.let { ts ->
            val x = mapX(ts)
            drawLine(selectColor, Offset(x, top), Offset(x, bottom), strokeWidth = 2f)
        }
    }
}

@Composable
private fun InspectorCard(
    timestamp: Long,
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    showTemp: Map<Long, Boolean>,
    showHumidity: Map<Long, Boolean>
) {
    Card(shape = RoundedCornerShape(18.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.45f))) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text("Curseur · ${formatDateTime(timestamp)}", fontWeight = FontWeight.Bold)
            sensors.filter { showTemp[it.id] == true || showHumidity[it.id] == true }.forEach { sensor ->
                nearest(sampleMap[sensor.id].orEmpty(), timestamp)?.let { point ->
                    Row(Modifier.fillMaxWidth()) {
                        Text(sensor.room, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                        if (showTemp[sensor.id] == true) Text(String.format(Locale.FRANCE, "%.1f °C", point.temperature), Modifier.width(78.dp))
                        if (showHumidity[sensor.id] == true) Text(String.format(Locale.FRANCE, "%.1f %%", point.humidity), Modifier.width(72.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun SensorStatsCard(sensor: Sensor, stats: SensorStats?, prefs: ChartPrefs) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(11.dp).background(palette[sensor.colorIndex % palette.size], RoundedCornerShape(6.dp)))
                Spacer(Modifier.width(8.dp))
                Text(sensor.room, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(stats?.count?.let { "$it pts" } ?: "—", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (stats == null) {
                Text("Aucune mesure sur cette période")
            } else {
                val latest = stats.latest
                Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                    StatBlock("Dernière T°", latest?.let { String.format(Locale.FRANCE, "%.1f °C", it.temperature) } ?: "—", latest?.temperature?.let { it >= prefs.highTemp } == true)
                    StatBlock("Dernière HR", latest?.let { String.format(Locale.FRANCE, "%.1f %%", it.humidity) } ?: "—", latest?.humidity?.let { it < prefs.lowHumidity || it > prefs.highHumidity } == true)
                }
                Text(String.format(Locale.FRANCE, "T°  min %.1f · moy %.1f · max %.1f °C", stats.tempMin, stats.tempAvg, stats.tempMax), style = MaterialTheme.typography.bodySmall)
                Text(String.format(Locale.FRANCE, "HR  min %.1f · moy %.1f · max %.1f %%", stats.humidityMin, stats.humidityAvg, stats.humidityMax), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun StatBlock(label: String, value: String, alert: Boolean) {
    Column {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, fontWeight = FontWeight.Bold, color = if (alert) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
    }
}

@Composable
private fun AnnotationSection(annotations: List<AnnotationItem>, sensors: List<Sensor>, onDelete: (Long) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Annotations", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        if (annotations.isEmpty()) {
            Text("Aucune annotation sur cette période.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            annotations.forEach { note ->
                Card(shape = RoundedCornerShape(14.dp)) {
                    Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(note.title, fontWeight = FontWeight.SemiBold)
                            Text(formatDateTime(note.timestamp), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            note.sensorId?.let { id -> sensors.firstOrNull { it.id == id }?.let { Text(it.room, style = MaterialTheme.typography.labelSmall) } }
                            if (note.note.isNotBlank()) Text(note.note, style = MaterialTheme.typography.bodySmall)
                        }
                        IconButton(onClick = { onDelete(note.id) }) { Icon(Icons.Default.Delete, contentDescription = "Supprimer l'annotation") }
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsDialog(initial: ChartPrefs, onDismiss: () -> Unit, onSave: (ChartPrefs) -> Unit, onClear: () -> Unit) {
    var grid by remember { mutableStateOf(initial.showGrid) }
    var points by remember { mutableStateOf(initial.showPoints) }
    var width by remember { mutableFloatStateOf(initial.lineWidth) }
    var highTemp by remember { mutableStateOf(initial.highTemp.toString()) }
    var lowHum by remember { mutableStateOf(initial.lowHumidity.toString()) }
    var highHum by remember { mutableStateOf(initial.highHumidity.toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Réglages FabData") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                SettingSwitch("Grille du graphique", grid) { grid = it }
                SettingSwitch("Afficher les points", points) { points = it }
                Text("Épaisseur des courbes : ${String.format(Locale.FRANCE, "%.1f", width)}")
                Slider(value = width, onValueChange = { width = it }, valueRange = 1f..6f)
                OutlinedTextField(highTemp, { highTemp = it }, label = { Text("Alerte température haute (°C)") }, singleLine = true)
                OutlinedTextField(lowHum, { lowHum = it }, label = { Text("Humidité basse (%)") }, singleLine = true)
                OutlinedTextField(highHum, { highHum = it }, label = { Text("Humidité haute (%)") }, singleLine = true)
                HorizontalDivider()
                TextButton(onClick = onClear) { Text("Vider toute la base locale", color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            Button(onClick = {
                onSave(
                    ChartPrefs(
                        grid, points, width,
                        highTemp.replace(',', '.').toDoubleOrNull() ?: initial.highTemp,
                        lowHum.replace(',', '.').toDoubleOrNull() ?: initial.lowHumidity,
                        highHum.replace(',', '.').toDoubleOrNull() ?: initial.highHumidity
                    )
                )
            }) { Text("Enregistrer") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
}

@Composable
private fun SettingSwitch(label: String, checked: Boolean, onChecked: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChecked)
    }
}

@Composable
private fun SensorEditDialog(sensor: Sensor, onDismiss: () -> Unit, onSave: (String, String, Int) -> Unit, onDelete: () -> Unit) {
    var name by remember { mutableStateOf(sensor.name) }
    var room by remember { mutableStateOf(sensor.room) }
    var colorIndex by remember { mutableIntStateOf(sensor.colorIndex) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Capteur / pièce") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("Nom du capteur") }, singleLine = true)
                OutlinedTextField(room, { room = it }, label = { Text("Nom de la pièce") }, singleLine = true)
                Text("Couleur")
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    palette.forEachIndexed { index, color ->
                        Surface(
                            onClick = { colorIndex = index },
                            shape = RoundedCornerShape(50),
                            color = color,
                            border = if (index == colorIndex) androidx.compose.foundation.BorderStroke(3.dp, MaterialTheme.colorScheme.onSurface) else null,
                            modifier = Modifier.size(34.dp)
                        ) {}
                    }
                }
                TextButton(onClick = onDelete) { Text("Supprimer ce capteur et ses mesures", color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { Button(onClick = { onSave(name, room, colorIndex) }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
}

@Composable
private fun AnnotationDialog(
    initialTimestamp: Long,
    sensors: List<Sensor>,
    onDismiss: () -> Unit,
    onSave: (Long, String, String, Long?) -> Unit
) {
    val formatter = remember { DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm") }
    var dateText by remember { mutableStateOf(formatEpoch(initialTimestamp, formatter)) }
    var title by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var sensorId by remember { mutableStateOf<Long?>(null) }
    var sensorMenu by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Nouvelle annotation") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(dateText, { dateText = it; error = false }, label = { Text("Date / heure") }, supportingText = { if (error) Text("Format attendu : jj/MM/aaaa HH:mm") }, isError = error, singleLine = true)
                OutlinedTextField(title, { title = it }, label = { Text("Titre") }, singleLine = true)
                OutlinedTextField(note, { note = it }, label = { Text("Note") }, minLines = 2)
                Box {
                    OutlinedButton(onClick = { sensorMenu = true }) { Text(sensorId?.let { id -> sensors.firstOrNull { it.id == id }?.room } ?: "Toutes les pièces") }
                    androidx.compose.material3.DropdownMenu(expanded = sensorMenu, onDismissRequest = { sensorMenu = false }) {
                        androidx.compose.material3.DropdownMenuItem(text = { Text("Toutes les pièces") }, onClick = { sensorId = null; sensorMenu = false })
                        sensors.forEach { sensor ->
                            androidx.compose.material3.DropdownMenuItem(text = { Text(sensor.room) }, onClick = { sensorId = sensor.id; sensorMenu = false })
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = {
                val ts = parseLocalDate(dateText, formatter)
                if (ts == null) error = true else onSave(ts, title, note, sensorId)
            }) { Text("Ajouter") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
}

private fun nearest(points: List<SamplePoint>, timestamp: Long): SamplePoint? {
    if (points.isEmpty()) return null
    var lo = 0
    var hi = points.lastIndex
    while (lo <= hi) {
        val mid = (lo + hi) ushr 1
        val v = points[mid].timestamp
        if (v < timestamp) lo = mid + 1 else if (v > timestamp) hi = mid - 1 else return points[mid]
    }
    val a = points.getOrNull(lo)
    val b = points.getOrNull(lo - 1)
    return when {
        a == null -> b
        b == null -> a
        abs(a.timestamp - timestamp) < abs(b.timestamp - timestamp) -> a
        else -> b
    }
}

private fun paddedRange(values: List<Double>, fallbackMin: Double, fallbackMax: Double, clampMin: Double, clampMax: Double): Pair<Double, Double> {
    if (values.isEmpty()) return fallbackMin to fallbackMax
    var low = values.minOrNull() ?: fallbackMin
    var high = values.maxOrNull() ?: fallbackMax
    val span = (high - low).coerceAtLeast(0.5)
    low = max(clampMin, low - span * 0.12)
    high = min(clampMax, high + span * 0.12)
    if (high - low < 0.5) high = min(clampMax, low + 0.5)
    return low to high
}

private fun formatDateTime(epoch: Long): String = formatEpoch(epoch, DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm"))
private fun formatEpoch(epoch: Long, formatter: DateTimeFormatter): String = Instant.ofEpochMilli(epoch).atZone(ZoneId.systemDefault()).format(formatter)
private fun parseLocalDate(value: String, formatter: DateTimeFormatter): Long? = try {
    LocalDateTime.parse(value.trim(), formatter).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
} catch (_: Exception) { null }

private fun formatAxisTime(epoch: Long, span: Long): String {
    val formatter = if (span > 36L * 60L * 60L * 1000L) DateTimeFormatter.ofPattern("dd/MM HH'h'") else DateTimeFormatter.ofPattern("HH:mm")
    return formatEpoch(epoch, formatter)
}

private fun compactDuration(ms: Long): String {
    val hours = ms / 3_600_000L
    return if (hours < 48) "${hours} h" else "${hours / 24} j"
}

private fun Color.toArgbCompat(): Int = android.graphics.Color.argb(
    (alpha * 255).toInt().coerceIn(0, 255),
    (red * 255).toInt().coerceIn(0, 255),
    (green * 255).toInt().coerceIn(0, 255),
    (blue * 255).toInt().coerceIn(0, 255)
)

@Composable
private fun FabDataTheme(content: @Composable () -> Unit) {
    val colors = lightColorScheme(
        primary = Color(0xFF1565C0),
        onPrimary = Color.White,
        primaryContainer = Color(0xFFD7E9FF),
        onPrimaryContainer = Color(0xFF001D36),
        secondary = Color(0xFF3A6073),
        secondaryContainer = Color(0xFFD6E5EE),
        tertiary = Color(0xFF8A4F7D),
        background = Color(0xFFF7F8FA),
        surface = Color(0xFFFFFFFF),
        surfaceVariant = Color(0xFFE9EEF3)
    )
    MaterialTheme(colorScheme = colors, content = content)
}
