package com.fabdata.app

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FileOpen
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
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

private enum class TimePreset(val label: String, val spanMs: Long) {
    HOUR("Heure", 60L * 60L * 1000L),
    DAY("Jour", 24L * 60L * 60L * 1000L),
    WEEK("Semaine", 7L * 24L * 60L * 60L * 1000L),
    MONTH("Mois", 31L * 24L * 60L * 60L * 1000L),
    YEAR("Année", 366L * 24L * 60L * 60L * 1000L)
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
    Color(0xFF1769AA),
    Color(0xFFD1495B),
    Color(0xFF2A9D8F),
    Color(0xFFE08E0B),
    Color(0xFF6A4C93),
    Color(0xFF0081A7),
    Color(0xFFB56576),
    Color(0xFF588157)
)

private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FabDataApp(db: FabDataDb, initialImport: android.net.Uri?) {
    val context = LocalContext.current
    val importer = remember { CsvImporter(context, db) }
    val backup = remember { FabDataBackup(context, db) }
    val draftStore = remember { AnnotationDraftStore(context) }
    val prefsStore = remember { FabPrefs(context) }
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    var sensors by remember { mutableStateOf<List<Sensor>>(emptyList()) }
    var sampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var statsMap by remember { mutableStateOf<Map<Long, SensorStats>>(emptyMap()) }
    var annotations by remember { mutableStateOf<List<AnnotationItem>>(emptyList()) }
    var globalBounds by remember { mutableStateOf<LongRange?>(null) }
    var viewBounds by remember { mutableStateOf<LongRange?>(null) }
    var preset by rememberSaveable { mutableStateOf(TimePreset.WEEK) }
    var reloadToken by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var selectedTimestamp by remember { mutableStateOf<Long?>(null) }
    var selectedAnnotation by remember { mutableStateOf<AnnotationItem?>(null) }
    var detailAnnotation by remember { mutableStateOf<AnnotationItem?>(null) }
    var settingsOpen by remember { mutableStateOf(false) }
    var annotationTimestamp by remember { mutableStateOf<Long?>(null) }
    var editingAnnotation by remember { mutableStateOf<AnnotationItem?>(null) }
    var editSensor by remember { mutableStateOf<Sensor?>(null) }
    var prefs by remember { mutableStateOf(prefsStore.load()) }
    val showTemp = remember { mutableStateMapOf<Long, Boolean>() }
    val showHumidity = remember { mutableStateMapOf<Long, Boolean>() }
    var initialHandled by remember { mutableStateOf(false) }

    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        if (uri != null) {
            scope.launch {
                busy = true
                val result = withContext(Dispatchers.IO) { runCatching { backup.export(uri) } }
                busy = false
                snackbar.showSnackbar(
                    result.fold(
                        onSuccess = {
                            "Sauvegarde créée : ${it.measurements} mesures · ${it.events} événement(s) · ${it.sensors} capteur(s)"
                        },
                        onFailure = { "Sauvegarde impossible : ${it.message ?: "erreur inconnue"}" }
                    )
                )
            }
        }
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            scope.launch {
                busy = true
                val results = withContext(Dispatchers.IO) {
                    uris.map { uri ->
                        runCatching {
                            backup.importIfBackup(uri) ?: importer.import(uri).toFabDataImportSummary()
                        }
                    }
                }
                val ok = results.mapNotNull { it.getOrNull() }
                val errors = results.count { it.isFailure }
                val measuresAdded = ok.sumOf { it.measurementsAdded }
                val measuresDuplicates = ok.sumOf { it.measurementsDuplicates }
                val eventsAdded = ok.sumOf { it.eventsAdded }
                val eventsDuplicates = ok.sumOf { it.eventsDuplicates }
                val invalid = ok.sumOf { it.invalid }
                busy = false
                reloadToken++
                snackbar.showSnackbar(
                    "Import : $measuresAdded mesure(s) ajoutée(s) · $measuresDuplicates déjà présente(s) · " +
                        "$eventsAdded événement(s) restauré(s) · $eventsDuplicates événement(s) déjà présent(s) · " +
                        "$invalid invalide(s)" + if (errors > 0) " · $errors fichier(s) en erreur" else ""
                )
            }
        }
    }

    LaunchedEffect(initialImport, initialHandled) {
        if (!initialHandled && initialImport != null) {
            initialHandled = true
            busy = true
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    backup.importIfBackup(initialImport) ?: importer.import(initialImport).toFabDataImportSummary()
                }
            }
            busy = false
            reloadToken++
            snackbar.showSnackbar(
                result.fold(
                    onSuccess = {
                        "Import : ${it.measurementsAdded} mesure(s) ajoutée(s) · ${it.measurementsDuplicates} déjà présente(s) · " +
                            "${it.eventsAdded} événement(s) restauré(s) · ${it.eventsDuplicates} déjà présent(s)"
                    },
                    onFailure = { "Import impossible : ${it.message ?: "format inconnu"}" }
                )
            )
        }
    }

    LaunchedEffect(reloadToken, preset) {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            val s = db.sensors()
            val all = db.globalTimeBounds()
            val chosen = all?.let {
                val end = it.last
                max(it.first, end - preset.spanMs)..end
            }
            if (chosen == null) {
                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyList())
            } else {
                val samples = s.associate { sensor ->
                    sensor.id to db.querySamples(sensor.id, chosen.first, chosen.last)
                }
                val stat = s.mapNotNull { sensor ->
                    db.stats(sensor.id, chosen.first, chosen.last)?.let { value -> sensor.id to value }
                }.toMap()
                LoadedData(s, all, chosen, samples, stat, db.annotations(chosen.first, chosen.last))
            }
        }
        sensors = loaded.sensors
        globalBounds = loaded.globalBounds
        viewBounds = loaded.viewBounds
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
                            if (busy) "Mise à jour…" else "Courbes & événements",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    IconButton(onClick = {
                        picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel"))
                    }) { Icon(Icons.Default.FileOpen, contentDescription = "Importer des CSV") }
                    IconButton(onClick = {
                        exportLauncher.launch("FabData_sauvegarde.csv")
                    }) {
                        Icon(Icons.Default.FileDownload, contentDescription = "Exporter / sauvegarder FabData")
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
            FloatingActionButton(
                onClick = {
                    editingAnnotation = null
                    annotationTimestamp = selectedTimestamp ?: viewBounds?.last ?: System.currentTimeMillis()
                },
                containerColor = MaterialTheme.colorScheme.primaryContainer
            ) {
                Icon(Icons.Default.Add, contentDescription = "Ajouter une annotation")
            }
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                TimeTabs(preset = preset, onSelect = {
                    preset = it
                    selectedTimestamp = null
                    selectedAnnotation = null
                })
            }

            if (sensors.isEmpty()) {
                item {
                    EmptyState {
                        picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel"))
                    }
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
                        bounds = viewBounds,
                        prefs = prefs,
                        selectedTimestamp = selectedTimestamp,
                        onSelectTimestamp = {
                            selectedTimestamp = it
                            selectedAnnotation = null
                        },
                        onAnnotationClick = {
                            selectedAnnotation = it
                            selectedTimestamp = it.timestamp
                        },
                        onAnnotationDoubleClick = {
                            detailAnnotation = it
                            selectedAnnotation = it
                        },
                        onRequestAnnotation = { ts ->
                            editingAnnotation = null
                            annotationTimestamp = ts
                            selectedTimestamp = ts
                        }
                    )
                }

                selectedAnnotation?.let { note ->
                    item {
                        AnnotationPreviewCard(
                            annotation = note,
                            sensors = sensors,
                            sampleMap = sampleMap,
                            onOpen = { detailAnnotation = note },
                            onClose = { selectedAnnotation = null }
                        )
                    }
                }

                selectedTimestamp?.let { ts ->
                    item {
                        InspectorCard(ts, sensors, sampleMap, showTemp, showHumidity)
                    }
                }

                item {
                    PeriodSummaryCard(
                        preset = preset,
                        statsMap = statsMap,
                        sensors = sensors,
                        viewBounds = viewBounds,
                        globalBounds = globalBounds
                    )
                }

                item {
                    Text(
                        "Résumé par pièce",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                }

                items(sensors, key = { it.id }) { sensor ->
                    SensorStatsCard(sensor, statsMap[sensor.id], prefs)
                }

                item {
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

                item { Spacer(Modifier.height(72.dp)) }
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
                    showTemp.clear()
                    showHumidity.clear()
                    selectedTimestamp = null
                    selectedAnnotation = null
                    detailAnnotation = null
                    reloadToken++
                    settingsOpen = false
                    snackbar.showSnackbar("Base FabData vidée")
                }
            }
        )
    }

    annotationTimestamp?.let { ts ->
        AnnotationDialog(
            initialTimestamp = ts,
            initial = editingAnnotation,
            sensors = sensors,
            draftStore = draftStore,
            onDismiss = {
                annotationTimestamp = null
                editingAnnotation = null
            },
            onSave = { id, timestamp, title, note, sensorId, roomName, type ->
                scope.launch {
                    withContext(Dispatchers.IO) {
                        if (id == null) {
                            db.addAnnotation(timestamp, title, note, sensorId, roomName, type)
                        } else {
                            db.updateAnnotation(id, timestamp, title, note, sensorId, roomName, type)
                        }
                    }
                    annotationTimestamp = null
                    editingAnnotation = null
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
                    showTemp.remove(sensor.id)
                    showHumidity.remove(sensor.id)
                    editSensor = null
                    reloadToken++
                }
            }
        )
    }

    detailAnnotation?.let { note ->
        AnnotationDetailSheet(
            annotation = note,
            sensors = sensors,
            sampleMap = sampleMap,
            onDismiss = { detailAnnotation = null },
            onEdit = {
                editingAnnotation = note
                annotationTimestamp = note.timestamp
                detailAnnotation = null
            },
            onDelete = {
                scope.launch {
                    withContext(Dispatchers.IO) { db.deleteAnnotation(note.id) }
                    selectedAnnotation = null
                    detailAnnotation = null
                    reloadToken++
                }
            }
        )
    }
}

@Composable
private fun TimeTabs(preset: TimePreset, onSelect: (TimePreset) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            TimePreset.entries.forEach { item ->
                Surface(
                    onClick = { onSelect(item) },
                    color = if (item == preset) MaterialTheme.colorScheme.primaryContainer else Color.Transparent,
                    shape = RoundedCornerShape(16.dp)
                ) {
                    Column(
                        Modifier.padding(horizontal = 14.dp, vertical = 9.dp),
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            item.label,
                            fontWeight = if (item == preset) FontWeight.Bold else FontWeight.Normal,
                            color = if (item == preset) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        if (item == preset) {
                            Spacer(Modifier.height(4.dp))
                            Box(
                                Modifier.width(34.dp).height(3.dp)
                                    .background(MaterialTheme.colorScheme.primary, RoundedCornerShape(2.dp))
                            )
                        }
                    }
                }
            }
        }
        Text(
            "Pince = zoom temps · glisse = déplacer · double tap fond = reset · appui long = événement",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
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
            Text("Importe tes exports CSV. Un réimport chevauchant complète la base sans dupliquer les dates.")
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
            Text("Superposition", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "Chaque pièce peut afficher T°, humidité, les deux ou aucune.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            sensors.forEach { sensor ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(12.dp)
                            .background(palette[sensor.colorIndex % palette.size], RoundedCornerShape(6.dp))
                    )
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        Text(sensor.room, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (sensor.name != sensor.room) {
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
                        onCheckedChange = { showTemp[sensor.id] = it }
                    )
                    Text("%", style = MaterialTheme.typography.labelMedium)
                    Checkbox(
                        checked = showHumidity[sensor.id] == true,
                        onCheckedChange = { showHumidity[sensor.id] = it }
                    )
                    IconButton(onClick = { onEdit(sensor) }) {
                        Icon(Icons.Default.Edit, contentDescription = "Modifier la pièce")
                    }
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
    onSelectTimestamp: (Long) -> Unit,
    onAnnotationClick: (AnnotationItem) -> Unit,
    onAnnotationDoubleClick: (AnnotationItem) -> Unit,
    onRequestAnnotation: (Long) -> Unit
) {
    var resetKey by remember { mutableIntStateOf(0) }

    Card(
        shape = RoundedCornerShape(22.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Courbes interactives", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(
                        "Point épais = événement · 1 clic = aperçu · double clic = fiche",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                OutlinedButton(onClick = { resetKey++ }) { Text("Reset") }
            }

            if (bounds == null) {
                Box(Modifier.fillMaxWidth().height(340.dp), contentAlignment = Alignment.Center) {
                    Text("Pas de données")
                }
            } else {
                InteractiveChart(
                    modifier = Modifier.fillMaxWidth().height(390.dp),
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
                    onSelectTimestamp = onSelectTimestamp,
                    onAnnotationClick = onAnnotationClick,
                    onAnnotationDoubleClick = onAnnotationDoubleClick,
                    onRequestAnnotation = onRequestAnnotation
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
    onSelectTimestamp: (Long) -> Unit,
    onAnnotationClick: (AnnotationItem) -> Unit,
    onAnnotationDoubleClick: (AnnotationItem) -> Unit,
    onRequestAnnotation: (Long) -> Unit
) {
    var zoom by remember(resetKey, from, to) { mutableFloatStateOf(1f) }
    var center by remember(resetKey, from, to) { mutableFloatStateOf(0.5f) }

    val axisColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.60f)
    val gridColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.55f)
    val textColor = MaterialTheme.colorScheme.onSurfaceVariant
    val annotationColor = MaterialTheme.colorScheme.tertiary
    val selectColor = MaterialTheme.colorScheme.primary
    val surfaceColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.20f)

    fun visibleWindow(): LongRange {
        val fullSpan = (to - from).coerceAtLeast(1L)
        val visibleFraction = 1f / zoom
        val startFraction = (center - visibleFraction / 2f).coerceIn(0f, 1f - visibleFraction)
        val endFraction = startFraction + visibleFraction
        return (from + (fullSpan * startFraction).toLong())..
            (from + (fullSpan * endFraction).toLong())
    }

    Canvas(
        modifier = modifier
            .background(surfaceColor, RoundedCornerShape(16.dp))
            .pointerInput(from, to, resetKey) {
                detectTransformGestures { _, pan, zoomChange, _ ->
                    val oldVisible = 1f / zoom
                    val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)
                    zoom = newZoom
                    val visible = 1f / zoom
                    center = (center - (pan.x / size.width.toFloat()) * oldVisible)
                        .coerceIn(visible / 2f, 1f - visible / 2f)
                }
            }
            .pointerInput(from, to, resetKey, zoom, center, annotations) {
                detectTapGestures(
                    onLongPress = { p ->
                        val left = 52.dp.toPx()
                        val right = size.width - 44.dp.toPx()
                        if (p.x in left..right) {
                            val window = visibleWindow()
                            val span = (window.last - window.first).coerceAtLeast(1L)
                            val frac = ((p.x - left) / (right - left)).coerceIn(0f, 1f)
                            onRequestAnnotation(window.first + (span * frac).toLong())
                        }
                    },
                    onDoubleTap = { p ->
                        val left = 52.dp.toPx()
                        val right = size.width - 44.dp.toPx()
                        val window = visibleWindow()
                        val span = (window.last - window.first).coerceAtLeast(1L)
                        val hitPx = 20.dp.toPx()
                        val hit = annotations
                            .filter { it.timestamp in window }
                            .minByOrNull { note ->
                                val x = left + ((note.timestamp - window.first).toDouble() / span.toDouble()).toFloat() * (right - left)
                                abs(x - p.x)
                            }
                            ?.takeIf { note ->
                                val x = left + ((note.timestamp - window.first).toDouble() / span.toDouble()).toFloat() * (right - left)
                                abs(x - p.x) <= hitPx
                            }
                        if (hit != null) {
                            onAnnotationDoubleClick(hit)
                        } else {
                            zoom = 1f
                            center = 0.5f
                        }
                    },
                    onTap = { p ->
                        val left = 52.dp.toPx()
                        val right = size.width - 44.dp.toPx()
                        if (p.x in left..right) {
                            val window = visibleWindow()
                            val span = (window.last - window.first).coerceAtLeast(1L)
                            val hitPx = 18.dp.toPx()
                            val hit = annotations
                                .filter { it.timestamp in window }
                                .minByOrNull { note ->
                                    val x = left + ((note.timestamp - window.first).toDouble() / span.toDouble()).toFloat() * (right - left)
                                    abs(x - p.x)
                                }
                                ?.takeIf { note ->
                                    val x = left + ((note.timestamp - window.first).toDouble() / span.toDouble()).toFloat() * (right - left)
                                    abs(x - p.x) <= hitPx
                                }
                            if (hit != null) {
                                onAnnotationClick(hit)
                            } else {
                                val frac = ((p.x - left) / (right - left)).coerceIn(0f, 1f)
                                onSelectTimestamp(window.first + (span * frac).toLong())
                            }
                        }
                    }
                )
            }
    ) {
        val left = 52.dp.toPx()
        val right = size.width - 44.dp.toPx()
        val top = 22.dp.toPx()
        val bottom = size.height - 38.dp.toPx()
        val plotW = (right - left).coerceAtLeast(1f)
        val plotH = (bottom - top).coerceAtLeast(1f)
        val fullSpan = (to - from).coerceAtLeast(1L)
        val visibleFraction = 1f / zoom
        val startFraction = (center - visibleFraction / 2f).coerceIn(0f, 1f - visibleFraction)
        val endFraction = startFraction + visibleFraction
        val visibleFrom = from + (fullSpan * startFraction).toLong()
        val visibleTo = from + (fullSpan * endFraction).toLong()
        val visibleSpan = (visibleTo - visibleFrom).coerceAtLeast(1L)

        val tempValues = sensors
            .filter { showTemp[it.id] == true }
            .flatMap { sampleMap[it.id].orEmpty() }
            .filter { it.timestamp in visibleFrom..visibleTo }
            .map { it.temperature }

        val humidityValues = sensors
            .filter { showHumidity[it.id] == true }
            .flatMap { sampleMap[it.id].orEmpty() }
            .filter { it.timestamp in visibleFrom..visibleTo }
            .map { it.humidity }

        val tempRange = paddedRange(tempValues, 15.0, 35.0, -50.0, 80.0)
        val humRange = paddedRange(humidityValues, 30.0, 70.0, 0.0, 100.0)

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

        if (tempValues.isNotEmpty()) {
            for (i in 0..4) {
                val v = tempRange.second - (tempRange.second - tempRange.first) * i / 4.0
                val y = top + plotH * i / 4f
                drawContext.canvas.nativeCanvas.drawText(
                    String.format(Locale.FRANCE, "%.1f°", v),
                    4.dp.toPx(),
                    y + 4.dp.toPx(),
                    paint
                )
            }
        }

        if (humidityValues.isNotEmpty()) {
            for (i in 0..4) {
                val v = humRange.second - (humRange.second - humRange.first) * i / 4.0
                val y = top + plotH * i / 4f
                drawContext.canvas.nativeCanvas.drawText(
                    String.format(Locale.FRANCE, "%.0f%%", v),
                    size.width - 3.dp.toPx(),
                    y + 4.dp.toPx(),
                    rightPaint
                )
            }
        }

        for (i in 0..4) {
            val ts = visibleFrom + visibleSpan * i / 4L
            val x = left + plotW * i / 4f
            drawContext.canvas.nativeCanvas.drawText(
                formatAxisTime(ts, visibleSpan),
                x,
                size.height - 10.dp.toPx(),
                centerPaint
            )
        }

        fun mapX(ts: Long): Float =
            left + ((ts - visibleFrom).toDouble() / visibleSpan.toDouble()).toFloat() * plotW

        fun mapTemp(v: Double): Float =
            bottom - (((v - tempRange.first) / (tempRange.second - tempRange.first)).toFloat() * plotH)

        fun mapHum(v: Double): Float =
            bottom - (((v - humRange.first) / (humRange.second - humRange.first)).toFloat() * plotH)

        sensors.forEach { sensor ->
            val color = palette[sensor.colorIndex % palette.size]
            val points = sampleMap[sensor.id].orEmpty().filter { it.timestamp in visibleFrom..visibleTo }

            if (showTemp[sensor.id] == true && points.size >= 2) {
                val path = Path()
                points.forEachIndexed { index, p ->
                    val x = mapX(p.timestamp)
                    val y = mapTemp(p.temperature)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, color, style = Stroke(width = prefs.lineWidth.dp.toPx()))
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        drawCircle(color, 2.2.dp.toPx(), Offset(mapX(p.timestamp), mapTemp(p.temperature)))
                    }
                }
            }

            if (showHumidity[sensor.id] == true && points.size >= 2) {
                val path = Path()
                points.forEachIndexed { index, p ->
                    val x = mapX(p.timestamp)
                    val y = mapHum(p.humidity)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(
                    path,
                    color.copy(alpha = 0.82f),
                    style = Stroke(
                        width = max(1.2f, prefs.lineWidth - 0.5f).dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 7f))
                    )
                )
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        drawCircle(color.copy(alpha = 0.82f), 2.dp.toPx(), Offset(mapX(p.timestamp), mapHum(p.humidity)))
                    }
                }
            }
        }

        annotations.filter { it.timestamp in visibleFrom..visibleTo }.forEach { note ->
            val x = mapX(note.timestamp)
            val sensor = note.sensorId?.let { id -> sensors.firstOrNull { it.id == id } }
            val point = sensor?.let { nearest(sampleMap[it.id].orEmpty(), note.timestamp) }

            val markerY = when {
                sensor != null && point != null && showTemp[sensor.id] == true -> mapTemp(point.temperature)
                sensor != null && point != null && showHumidity[sensor.id] == true -> mapHum(point.humidity)
                else -> top + 14.dp.toPx()
            }

            if (sensor == null || point == null) {
                drawLine(
                    annotationColor.copy(alpha = 0.55f),
                    Offset(x, top),
                    Offset(x, bottom),
                    1.3f,
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(7f, 7f))
                )
            }

            val markerColor = sensor?.let { palette[it.colorIndex % palette.size] } ?: annotationColor
            drawCircle(Color.White, 8.dp.toPx(), Offset(x, markerY))
            drawCircle(markerColor, 6.dp.toPx(), Offset(x, markerY))
            drawCircle(Color.White.copy(alpha = 0.92f), 2.dp.toPx(), Offset(x, markerY))

            if (zoom > 2.4f) {
                val notePaint = android.graphics.Paint(paint).apply {
                    color = markerColor.toArgbCompat()
                    textSize = 9.dp.toPx()
                }
                drawContext.canvas.nativeCanvas.drawText(
                    note.title.take(16),
                    x + 7.dp.toPx(),
                    (markerY - 7.dp.toPx()).coerceAtLeast(top + 9.dp.toPx()),
                    notePaint
                )
            }
        }

        selectedTimestamp?.takeIf { it in visibleFrom..visibleTo }?.let { ts ->
            val x = mapX(ts)
            drawLine(selectColor, Offset(x, top), Offset(x, bottom), strokeWidth = 2f)
        }
    }
}

@Composable
private fun AnnotationPreviewCard(
    annotation: AnnotationItem,
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    onOpen: () -> Unit,
    onClose: () -> Unit
) {
    val sensor = annotation.sensorId?.let { id -> sensors.firstOrNull { it.id == id } }
    val point = sensor?.let { nearest(sampleMap[it.id].orEmpty(), annotation.timestamp) }

    Card(
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.55f))
    ) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(annotation.title, fontWeight = FontWeight.Bold)
                    Text(
                        "${formatDateTime(annotation.timestamp)} · ${annotation.roomName ?: sensor?.room ?: "Toutes les pièces"}",
                        style = MaterialTheme.typography.labelSmall
                    )
                }
                IconButton(onClick = onClose) { Icon(Icons.Default.Close, contentDescription = "Fermer") }
            }
            if (annotation.note.isNotBlank()) {
                Text(annotation.note, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            if (point != null) {
                Text(
                    String.format(Locale.FRANCE, "Au point : %.1f °C · %.1f %%", point.temperature, point.humidity),
                    style = MaterialTheme.typography.bodySmall
                )
            }
            TextButton(onClick = onOpen) { Text("Ouvrir la fiche") }
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
    Card(
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.45f))
    ) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text("Curseur · ${formatDateTime(timestamp)}", fontWeight = FontWeight.Bold)
            sensors.filter { showTemp[it.id] == true || showHumidity[it.id] == true }.forEach { sensor ->
                nearest(sampleMap[sensor.id].orEmpty(), timestamp)?.let { point ->
                    Row(Modifier.fillMaxWidth()) {
                        Text(sensor.room, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                        if (showTemp[sensor.id] == true) {
                            Text(String.format(Locale.FRANCE, "%.1f °C", point.temperature), Modifier.width(78.dp))
                        }
                        if (showHumidity[sensor.id] == true) {
                            Text(String.format(Locale.FRANCE, "%.1f %%", point.humidity), Modifier.width(72.dp))
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PeriodSummaryCard(
    preset: TimePreset,
    statsMap: Map<Long, SensorStats>,
    sensors: List<Sensor>,
    viewBounds: LongRange?,
    globalBounds: LongRange?
) {
    val points = statsMap.values.sumOf { it.count }
    Card(
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.42f))
    ) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Text("${preset.label} · synthèse", fontWeight = FontWeight.Bold)
            Text("${sensors.size} capteur(s) · $points mesure(s)", style = MaterialTheme.typography.bodySmall)
            viewBounds?.let {
                Text("${formatDateTime(it.first)} → ${formatDateTime(it.last)}", style = MaterialTheme.typography.bodySmall)
            }
            globalBounds?.let {
                Text(
                    "Historique total : ${compactDuration(it.last - it.first)}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun SensorStatsCard(sensor: Sensor, stats: SensorStats?, prefs: ChartPrefs) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(11.dp)
                        .background(palette[sensor.colorIndex % palette.size], RoundedCornerShape(6.dp))
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    sensor.room,
                    Modifier.weight(1f),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    stats?.count?.let { "$it pts" } ?: "—",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (stats == null) {
                Text("Aucune mesure sur cette période")
            } else {
                val latest = stats.latest
                Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                    StatBlock(
                        "Dernière T°",
                        latest?.let { String.format(Locale.FRANCE, "%.1f °C", it.temperature) } ?: "—",
                        latest?.temperature?.let { it >= prefs.highTemp } == true
                    )
                    StatBlock(
                        "Dernière HR",
                        latest?.let { String.format(Locale.FRANCE, "%.1f %%", it.humidity) } ?: "—",
                        latest?.humidity?.let { it < prefs.lowHumidity || it > prefs.highHumidity } == true
                    )
                }
                Text(
                    String.format(
                        Locale.FRANCE,
                        "T° min %.1f · moy %.1f · max %.1f °C",
                        stats.tempMin,
                        stats.tempAvg,
                        stats.tempMax
                    ),
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    String.format(
                        Locale.FRANCE,
                        "HR min %.1f · moy %.1f · max %.1f %%",
                        stats.humidityMin,
                        stats.humidityAvg,
                        stats.humidityMax
                    ),
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }
    }
}

@Composable
private fun StatBlock(label: String, value: String, alert: Boolean) {
    Column {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            value,
            fontWeight = FontWeight.Bold,
            color = if (alert) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface
        )
    }
}

@Composable
private fun AnnotationSection(
    annotations: List<AnnotationItem>,
    sensors: List<Sensor>,
    onOpen: (AnnotationItem) -> Unit,
    onDelete: (Long) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Événements", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        if (annotations.isEmpty()) {
            Text(
                "Aucun événement sur cette période.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        } else {
            annotations.reversed().forEach { note ->
                val sensor = note.sensorId?.let { id -> sensors.firstOrNull { it.id == id } }
                Card(shape = RoundedCornerShape(14.dp), onClick = { onOpen(note) }) {
                    Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(note.title, fontWeight = FontWeight.SemiBold)
                            Text(
                                "${formatDateTime(note.timestamp)} · ${note.roomName ?: sensor?.room ?: "Global"}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            note.type?.takeIf { it.isNotBlank() }?.let {
                                Text(it, style = MaterialTheme.typography.labelSmall)
                            }
                            if (note.note.isNotBlank()) {
                                Text(note.note, style = MaterialTheme.typography.bodySmall, maxLines = 2)
                            }
                        }
                        IconButton(onClick = { onDelete(note.id) }) {
                            Icon(Icons.Default.Delete, contentDescription = "Supprimer l'événement")
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AnnotationDetailSheet(
    annotation: AnnotationItem,
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    onDismiss: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    val sensor = annotation.sensorId?.let { id -> sensors.firstOrNull { it.id == id } }
    val point = sensor?.let { nearest(sampleMap[it.id].orEmpty(), annotation.timestamp) }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    annotation.title,
                    Modifier.weight(1f),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold
                )
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Default.Close, contentDescription = "Fermer")
                }
            }
            Text(formatDateTime(annotation.timestamp), fontWeight = FontWeight.SemiBold)
            Text("Pièce : ${annotation.roomName ?: sensor?.room ?: "Toutes les pièces"}")
            sensor?.let { Text("Capteur : ${it.name}") }
            annotation.type?.takeIf { it.isNotBlank() }?.let { Text("Type : $it") }

            if (point != null) {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.5f)
                    )
                ) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Mesure la plus proche", fontWeight = FontWeight.Bold)
                        Text(String.format(Locale.FRANCE, "%.1f °C", point.temperature))
                        Text(String.format(Locale.FRANCE, "%.1f %% HR", point.humidity))
                        Text(formatDateTime(point.timestamp), style = MaterialTheme.typography.labelSmall)
                    }
                }
            }

            if (annotation.note.isBlank()) {
                Text("Aucune note détaillée.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                Text(annotation.note, style = MaterialTheme.typography.bodyLarge)
            }

            HorizontalDivider()
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = onEdit) { Text("Modifier") }
                OutlinedButton(onClick = onDelete) { Text("Supprimer") }
            }
            Spacer(Modifier.height(28.dp))
        }
    }
}

@Composable
private fun SettingsDialog(
    initial: ChartPrefs,
    onDismiss: () -> Unit,
    onSave: (ChartPrefs) -> Unit,
    onClear: () -> Unit
) {
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
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                SettingSwitch("Grille du graphique", grid) { grid = it }
                SettingSwitch("Afficher les points", points) { points = it }
                Text("Épaisseur des courbes : ${String.format(Locale.FRANCE, "%.1f", width)}")
                Slider(value = width, onValueChange = { width = it }, valueRange = 1f..6f)
                OutlinedTextField(
                    highTemp,
                    { highTemp = it },
                    label = { Text("Alerte température haute (°C)") },
                    singleLine = true
                )
                OutlinedTextField(
                    lowHum,
                    { lowHum = it },
                    label = { Text("Humidité basse (%)") },
                    singleLine = true
                )
                OutlinedTextField(
                    highHum,
                    { highHum = it },
                    label = { Text("Humidité haute (%)") },
                    singleLine = true
                )
                HorizontalDivider()
                Text("Politique de confidentialité · FabData v0.7", fontWeight = FontWeight.Bold)
                Text(
                    "Les mesures, noms de pièces et événements sont traités localement sur cet appareil. " +
                        "FabData n'envoie aucune donnée utilisateur à un serveur, n'intègre ni publicité ni analytique " +
                        "et ne crée aucun compte utilisateur.",
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    "Les imports et sauvegardes CSV sont déclenchés explicitement par l'utilisateur via le sélecteur " +
                        "de fichiers Android. Contact confidentialité : dépôt GitHub greenpower2669/FabData.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                HorizontalDivider()
                TextButton(onClick = onClear) {
                    Text("Vider toute la base locale", color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            Button(onClick = {
                onSave(
                    ChartPrefs(
                        grid,
                        points,
                        width,
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
private fun SensorEditDialog(
    sensor: Sensor,
    onDismiss: () -> Unit,
    onSave: (String, String, Int) -> Unit,
    onDelete: () -> Unit
) {
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
                Row(
                    Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    palette.forEachIndexed { index, color ->
                        Surface(
                            onClick = { colorIndex = index },
                            shape = RoundedCornerShape(50),
                            color = color,
                            border = if (index == colorIndex) {
                                BorderStroke(3.dp, MaterialTheme.colorScheme.onSurface)
                            } else null,
                            modifier = Modifier.size(34.dp)
                        ) {}
                    }
                }
                TextButton(onClick = onDelete) {
                    Text("Supprimer ce capteur et ses mesures", color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            Button(onClick = { onSave(name, room, colorIndex) }) { Text("Enregistrer") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
}

@Composable
private fun AnnotationDialog(
    initialTimestamp: Long,
    initial: AnnotationItem?,
    sensors: List<Sensor>,
    draftStore: AnnotationDraftStore,
    onDismiss: () -> Unit,
    onSave: (Long?, Long, String, String, Long?, String?, String?) -> Unit
) {
    val formatter = remember { DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm") }
    val draftKey = remember(initial?.id) { initial?.id?.let { "edit_$it" } ?: "new" }
    val savedDraft = remember(draftKey, initialTimestamp) { draftStore.load(draftKey) }
    val baseTimestamp = savedDraft?.timestamp ?: initial?.timestamp ?: initialTimestamp
    var dateText by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.dateText?.takeIf { it.isNotBlank() } ?: formatEpoch(baseTimestamp, formatter))
    }
    var title by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.title ?: initial?.title.orEmpty())
    }
    var note by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.note ?: initial?.note.orEmpty())
    }
    var sensorId by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.sensorId ?: initial?.sensorId)
    }
    var roomName by remember(initial?.id, initialTimestamp) {
        mutableStateOf(
            savedDraft?.roomName
                ?: initial?.roomName
                ?: initial?.sensorId?.let { id -> sensors.firstOrNull { it.id == id }?.room }
                .orEmpty()
        )
    }
    var type by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.type ?: initial?.type.orEmpty())
    }
    var sensorMenu by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf(false) }

    LaunchedEffect(dateText, title, note, sensorId, roomName, type, draftKey) {
        val ts = parseLocalDate(dateText, formatter) ?: baseTimestamp
        draftStore.save(
            draftKey,
            AnnotationDraft(
                timestamp = ts,
                dateText = dateText,
                title = title,
                note = note,
                sensorId = sensorId,
                roomName = roomName,
                type = type
            )
        )
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "Nouvel événement" else "Modifier l’événement") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    "Brouillon sauvegardé automatiquement",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary
                )
                OutlinedTextField(
                    dateText,
                    { dateText = it; error = false },
                    label = { Text("Date / heure") },
                    supportingText = { if (error) Text("Format : jj/MM/aaaa HH:mm") },
                    isError = error,
                    singleLine = true
                )
                OutlinedTextField(title, { title = it }, label = { Text("Titre") }, singleLine = true)
                OutlinedTextField(note, { note = it }, label = { Text("Note") }, minLines = 3)
                OutlinedTextField(
                    roomName,
                    { roomName = it },
                    label = { Text("Pièce / lieu") },
                    supportingText = { Text("ex. SDB, chambre, chambre principale, salon") },
                    singleLine = true
                )
                OutlinedTextField(
                    type,
                    { type = it },
                    label = { Text("Type d’événement (facultatif)") },
                    singleLine = true
                )

                Box {
                    OutlinedButton(onClick = { sensorMenu = true }) {
                        Text(sensorId?.let { id -> sensors.firstOrNull { it.id == id }?.room } ?: "Aucun capteur précis")
                    }
                    DropdownMenu(expanded = sensorMenu, onDismissRequest = { sensorMenu = false }) {
                        DropdownMenuItem(
                            text = { Text("Aucun capteur précis") },
                            onClick = {
                                sensorId = null
                                sensorMenu = false
                            }
                        )
                        sensors.forEach { sensor ->
                            DropdownMenuItem(
                                text = { Text(sensor.room) },
                                onClick = {
                                    sensorId = sensor.id
                                    if (roomName.isBlank()) roomName = sensor.room
                                    sensorMenu = false
                                }
                            )
                        }
                    }
                }

                Text("Pièces rapides", style = MaterialTheme.typography.labelMedium)
                Row(
                    Modifier.horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    listOf("SDB", "Chambre", "Chambre principale", "Salon").forEach { room ->
                        AssistChip(onClick = { roomName = room }, label = { Text(room) })
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = {
                val ts = parseLocalDate(dateText, formatter)
                if (ts == null) {
                    error = true
                } else {
                    draftStore.clear(draftKey)
                    onSave(
                        initial?.id,
                        ts,
                        title,
                        note,
                        sensorId,
                        roomName.trim().ifBlank { null },
                        type.trim().ifBlank { null }
                    )
                }
            }) {
                Text(if (initial == null) "Ajouter" else "Enregistrer")
            }
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

private fun paddedRange(
    values: List<Double>,
    fallbackMin: Double,
    fallbackMax: Double,
    clampMin: Double,
    clampMax: Double
): Pair<Double, Double> {
    if (values.isEmpty()) return fallbackMin to fallbackMax
    var low = values.minOrNull() ?: fallbackMin
    var high = values.maxOrNull() ?: fallbackMax
    val span = (high - low).coerceAtLeast(0.5)
    low = max(clampMin, low - span * 0.12)
    high = min(clampMax, high + span * 0.12)
    if (high - low < 0.5) high = min(clampMax, low + 0.5)
    return low to high
}

private fun formatDateTime(epoch: Long): String =
    formatEpoch(epoch, DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm"))

private fun formatEpoch(epoch: Long, formatter: DateTimeFormatter): String =
    Instant.ofEpochMilli(epoch).atZone(ZoneId.systemDefault()).format(formatter)

private fun parseLocalDate(value: String, formatter: DateTimeFormatter): Long? = try {
    LocalDateTime.parse(value.trim(), formatter)
        .atZone(ZoneId.systemDefault())
        .toInstant()
        .toEpochMilli()
} catch (_: Exception) {
    null
}

private fun formatAxisTime(epoch: Long, span: Long): String {
    val formatter = when {
        span <= 2L * 60L * 60L * 1000L -> DateTimeFormatter.ofPattern("HH:mm")
        span <= 2L * 24L * 60L * 60L * 1000L -> DateTimeFormatter.ofPattern("HH:mm")
        span <= 14L * 24L * 60L * 60L * 1000L -> DateTimeFormatter.ofPattern("EEE HH'h'", Locale.FRANCE)
        span <= 70L * 24L * 60L * 60L * 1000L -> DateTimeFormatter.ofPattern("dd/MM")
        else -> DateTimeFormatter.ofPattern("MMM yy", Locale.FRANCE)
    }
    return formatEpoch(epoch, formatter)
}

private fun compactDuration(ms: Long): String {
    val hours = ms / 3_600_000L
    return when {
        hours < 48 -> "${hours} h"
        hours < 24L * 90L -> "${hours / 24} j"
        else -> "${hours / (24L * 30L)} mois"
    }
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
        tertiaryContainer = Color(0xFFF4D9EC),
        background = Color(0xFFF7F8FA),
        surface = Color(0xFFFFFFFF),
        surfaceVariant = Color(0xFFE9EEF3)
    )
    MaterialTheme(colorScheme = colors, content = content)
}
