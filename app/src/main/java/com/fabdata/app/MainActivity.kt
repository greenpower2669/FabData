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
import androidx.compose.foundation.gestures.detectDragGestures
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
import androidx.compose.runtime.rememberUpdatedState
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
import kotlinx.coroutines.delay
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
    HOUR("1 h", 60L * 60L * 1000L),
    DAY("24 h", 24L * 60L * 60L * 1000L),
    TWO_DAYS("48 h", 48L * 60L * 60L * 1000L),
    WEEK("1 sem.", 7L * 24L * 60L * 60L * 1000L),
    MONTH("1 mois", 31L * 24L * 60L * 60L * 1000L)
}

private enum class PreviewPreset(val label: String, val spanMs: Long) {
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}

private const val LYON_DETAIL_GAP_MS = 90L * 60L * 1000L
private const val LYON_NEAREST_TOLERANCE_MS = 75L * 60L * 1000L
private const val WEATHER_OFFICIAL_SENSOR_ID = -6902900102L
private const val WEATHER_OFFICIAL_STABLE_KEY = "weather-reference-official"
private const val LYON_RECONSTRUCTED_SENSOR_ID = -6902900103L
private const val LYON_RECONSTRUCTED_STABLE_KEY = "lyon-reconstructed"

private data class LyonHybridSyncResult(
    val received: Int,
    val stored: Int,
    val label: String
)

private suspend fun syncLyonHybrid(
    db: FabDataDb,
    legacy: LyonWeatherSync,
    official: MeteoFranceOfficialClient,
    credentials: MeteoFranceCredentialStore
): LyonHybridSyncResult = withContext(Dispatchers.IO) {
    // System invariant: Lyon exists before any network call.
    db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)

    if (credentials.hasCredential()) {
        runCatching { official.syncSixMinute24h() }
            .fold(
                onSuccess = { LyonHybridSyncResult(it.received, it.stored, "Lyon officiel · 6 min") },
                onFailure = {
                    val fallback = legacy.syncToday()
                    LyonHybridSyncResult(
                        fallback.parsed,
                        fallback.added + fallback.corrected,
                        "Lyon secours auto · officiel indisponible"
                    )
                }
            )
    } else {
        val fallback = legacy.syncToday()
        LyonHybridSyncResult(
            fallback.parsed,
            fallback.added + fallback.corrected,
            "Lyon secours auto · sans token"
        )
    }
}

private suspend fun completeLyonHybrid(
    db: FabDataDb,
    legacy: LyonWeatherSync,
    official: MeteoFranceOfficialClient,
    credentials: MeteoFranceCredentialStore
): LyonHybridSyncResult = withContext(Dispatchers.IO) {
    db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
    if (credentials.hasCredential()) {
        val bounds = db.physicalSensorBounds() ?: error("Aucune période physique")
        runCatching { official.syncHourly(bounds.first, bounds.last) }
            .fold(
                onSuccess = { LyonHybridSyncResult(it.received, it.stored, "Lyon horaire officiel") },
                onFailure = {
                    val fallback = legacy.completePhysicalPeriod()
                    LyonHybridSyncResult(
                        fallback.daysDownloaded,
                        fallback.added + fallback.corrected,
                        "Lyon secours historique · officiel indisponible"
                    )
                }
            )
    } else {
        val fallback = legacy.completePhysicalPeriod()
        LyonHybridSyncResult(
            fallback.daysDownloaded,
            fallback.added + fallback.corrected,
            "Lyon secours historique · sans token"
        )
    }
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
    val overviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>,
    val lyonReconstructedSamples: List<SamplePoint>,
    val inertiaEstimate: ThermalInertiaEstimate?
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FabDataApp(db: FabDataDb, initialImport: android.net.Uri?) {
    val context = LocalContext.current
    val importer = remember { CsvImporter(context, db) }
    val backup = remember { FabDataBackup(context, db) }
    val lyonWeather = remember { LyonWeatherSync(db) } // legacy read-only fallback
    val lyonLab = remember { LyonLabStore(db) }
    val meteoCredentials = remember { MeteoFranceCredentialStore(context) }
    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, meteoCredentials) }
    val curveStyleStore = remember { CurveStyleStore(context) }
    val weatherReferenceStore = remember { WeatherReferenceStore(db) }
    val weatherReferenceManager = remember { WeatherReferenceManager(context, db, lyonLab, meteoCredentials) }
    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }
    val remoteSensorStore = remember { RemoteSensorStore(context) }
    val remoteSensorSync = remember { RemoteSensorHttpSync(db) }
    val draftStore = remember { AnnotationDraftStore(context) }
    val prefsStore = remember { FabPrefs(context) }
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    var sensors by remember { mutableStateOf<List<Sensor>>(emptyList()) }
    var sampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var lyonReconstructedSamples by remember { mutableStateOf<List<SamplePoint>>(emptyList()) }
    var inertiaEstimate by remember { mutableStateOf<ThermalInertiaEstimate?>(null) }
    var statsMap by remember { mutableStateOf<Map<Long, SensorStats>>(emptyMap()) }
    var annotations by remember { mutableStateOf<List<AnnotationItem>>(emptyList()) }
    var allAnnotations by remember { mutableStateOf<List<AnnotationItem>>(emptyList()) }
    var overviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var globalBounds by remember { mutableStateOf<LongRange?>(null) }
    var viewBounds by remember { mutableStateOf<LongRange?>(null) }
    var preset by rememberSaveable { mutableStateOf(TimePreset.TWO_DAYS) }
    var windowCenterTimestamp by remember { mutableStateOf<Long?>(null) }
    var customViewSpanMs by remember { mutableStateOf<Long?>(null) }
    var showAllAnnotations by rememberSaveable { mutableStateOf(true) }
    var reloadToken by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var thermalBusy by remember { mutableStateOf(false) }
    var thermalProgressText by remember { mutableStateOf<String?>(null) }
    var selectedTimestamp by remember { mutableStateOf<Long?>(null) }
    var selectedAnnotation by remember { mutableStateOf<AnnotationItem?>(null) }
    var detailAnnotation by remember { mutableStateOf<AnnotationItem?>(null) }
    var settingsOpen by remember { mutableStateOf(false) }
    var remoteSensorDialogOpen by remember { mutableStateOf(false) }
    var remoteConfigs by remember { mutableStateOf(remoteSensorStore.load()) }
    var annotationTimestamp by remember { mutableStateOf<Long?>(null) }
    var editingAnnotation by remember { mutableStateOf<AnnotationItem?>(null) }
    var editSensor by remember { mutableStateOf<Sensor?>(null) }
    var lyonDetailOpen by remember { mutableStateOf(false) }
    var styleEditKey by remember { mutableStateOf<Pair<String, String>?>(null) }
    var styleVersion by remember { mutableIntStateOf(0) }
    var styleTick by remember { mutableStateOf(System.currentTimeMillis()) }
    var prefs by remember { mutableStateOf(prefsStore.load()) }
    val showTemp = remember { mutableStateMapOf<Long, Boolean>() }
    val showHumidity = remember { mutableStateMapOf<Long, Boolean>() }
    var initialHandled by remember { mutableStateOf(false) }

    // v0.17 : cet orchestrateur reste composé même quand les réglages thermiques
    // sont loin sous le viewport du LazyColumn.
    FabLiveUpdateCoordinator(
        db = db,
        lyonLab = lyonLab,
        credentials = meteoCredentials,
        dataVersion = reloadToken,
        onDataChanged = { reloadToken++ }
    )

    val activeCurveStyles = remember(sensors, styleVersion) {
        buildMap {
            sensors.forEach { sensor -> put(sensor.id, curveStyleStore.load("sensor:${sensor.stableKey}")) }
            put(WEATHER_OFFICIAL_SENSOR_ID, curveStyleStore.load("weather:official"))
            put(LYON_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("lyon:reconstructed"))
            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))
        }
    }

    LaunchedEffect(Unit) {
        while (true) {
            if (!thermalBusy) styleTick = System.currentTimeMillis()
            delay(if (thermalBusy) 900L else 180L)
        }
    }

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

    // v0.17 : la météo live est désormais pilotée par FabLiveUpdateCoordinator
    // à l'ouverture, au retour au focus et ensuite toutes les 5 minutes au premier plan.

    // Les sondes HTTP ajoutées une fois restent automatiques ensuite.
    LaunchedEffect(Unit) {
        val configs = remoteSensorStore.load()
        if (configs.isNotEmpty()) {
            withContext(Dispatchers.IO) {
                configs.forEach { config -> runCatching { remoteSensorSync.sync(config) } }
            }
            reloadToken++
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

    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs) {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            val s = db.sensors()

            // Les thermomètres physiques/importés définissent la période de navigation.
            // Lyon et les sondes HTTP complètent cette période sans pousser l'ancien hors écran.
            val physicalBounds = db.physicalSensorBounds() ?: db.globalTimeBounds()
            val selectedWeatherReference = WeatherReferencePrefs(context).selectedReference()
            val weatherBounds = weatherReferenceStore.historyBounds(selectedWeatherReference.key)
            val all = when {
                physicalBounds == null -> weatherBounds
                weatherBounds == null -> physicalBounds
                else -> minOf(physicalBounds.first, weatherBounds.first)..maxOf(physicalBounds.last, weatherBounds.last)
            }
            val chosen = all?.let { bounds ->
                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)
                val requested = minOf(customViewSpanMs ?: preset.spanMs, fullSpan)
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
                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null)
            } else {
                val samples = s.associate { sensor ->
                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        // v0.10 : une seule chronologie Lyon. Reconstruction d'abord, puis
                        // données stockées, puis officiel 6 min qui garde la priorité absolue.
                        val merged = linkedMapOf<Long, SamplePoint>()
                        lyonLab.reconstruct(chosen.first, chosen.last).points.forEach {
                            merged[it.timestamp] = SamplePoint(
                                sensor.id, it.timestamp, it.temperature, it.humidity,
                                PointSource.RECONSTRUCTED, 0.72
                            )
                        }
                        db.querySamples(sensor.id, chosen.first, chosen.last).forEach { merged[it.timestamp] = it }
                        lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, chosen.first, chosen.last).forEach {
                            merged[it.timestamp] = SamplePoint(sensor.id, it.timestamp, it.temperature, it.humidity, PointSource.MEASURED, 1.0)
                        }
                        merged.values.sortedBy { it.timestamp }
                    } else {
                        db.querySamples(sensor.id, chosen.first, chosen.last)
                    }
                    sensor.id to value
                }
                // v0.10.3 : cette couche EST la série météo effectivement consommée par le RC.
                val lyonReconstructed = weatherReferenceStore.query(
                    selectedWeatherReference.key, chosen.first, chosen.last
                ).filter { it.source != PointSource.FORECAST }.map {
                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, it.source, it.confidence)
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
                val overviewReference = weatherReferenceStore.query(
                    selectedWeatherReference.key, all.first, all.last
                ).filter { it.source != PointSource.FORECAST }.map {
                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, it.source, it.confidence)
                }
                val overviewWithReference = overview + (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference)
                val stat = s.mapNotNull { sensor ->
                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        sensorStatsFromSamples(sensor.id, samples[sensor.id].orEmpty())
                    } else {
                        db.stats(sensor.id, chosen.first, chosen.last)
                    }
                    value?.let { sensor.id to it }
                }.toMap()
                val modelSensorId = context
                    .getSharedPreferences("fabdata_thermal_model", Context.MODE_PRIVATE)
                    .getLong("selected_sensor_id", -1L)
                    .takeIf { it >= 0L }
                val inertia = runCatching {
                    inertiaEstimator.estimate(selectedWeatherReference, modelSensorId, includeHistory = true)
                }.getOrNull()
                LoadedData(
                    s, all, chosen, samples, overviewWithReference, stat,
                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed, inertia
                )
            }
        }
        sensors = loaded.sensors
        globalBounds = loaded.globalBounds
        viewBounds = loaded.viewBounds
        sampleMap = loaded.samples
        lyonReconstructedSamples = loaded.lyonReconstructedSamples
        inertiaEstimate = loaded.inertiaEstimate
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
            if (!showTemp.containsKey(sensor.id)) {
                showTemp[sensor.id] = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                    loaded.lyonReconstructedSamples.isEmpty()
                } else true
            }
            if (!showHumidity.containsKey(sensor.id)) showHumidity[sensor.id] = false
        }
        if (!showTemp.containsKey(WEATHER_OFFICIAL_SENSOR_ID)) showTemp[WEATHER_OFFICIAL_SENSOR_ID] = true
        if (!showHumidity.containsKey(WEATHER_OFFICIAL_SENSOR_ID)) showHumidity[WEATHER_OFFICIAL_SENSOR_ID] = false
        if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            // Always checked: if data arrives later the curve appears without another user action.
            showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = true
        }
        if (!showHumidity.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            showHumidity[LYON_RECONSTRUCTED_SENSOR_ID] = false
        }
        // v0.19.7: on montre la surface/sol inertiel sur la période MEASURED uniquement.
        // La masse énergétique profonde reste cachée et n'est jamais branchée au graphe.
        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true
        showHumidity[THERMAL_INERTIA_SENSOR_ID] = false
        busy = false
    }

    val visualReference = WeatherReferencePrefs(context).selectedReference()
    val weatherOfficialSamples = lyonReconstructedSamples
        .filter { it.source == PointSource.MEASURED }
        .map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }
    val weatherReconstructedSamples = lyonReconstructedSamples
        .filter { it.source == PointSource.RECONSTRUCTED }
        .map { it.copy(sensorId = LYON_RECONSTRUCTED_SENSOR_ID) }
    val weatherOfficialSensor = Sensor(
        id = WEATHER_OFFICIAL_SENSOR_ID,
        stableKey = WEATHER_OFFICIAL_STABLE_KEY,
        name = "Station météo officielle",
        room = visualReference.label,
        colorIndex = 2,
        latestTimestamp = weatherOfficialSamples.lastOrNull()?.timestamp
    )
    val lyonReconstructedSensor = Sensor(
        id = LYON_RECONSTRUCTED_SENSOR_ID,
        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,
        name = "Station météo reconstruite",
        room = visualReference.label,
        colorIndex = 3,
        latestTimestamp = weatherReconstructedSamples.lastOrNull()?.timestamp
    )
    // Les deux pseudo-capteurs météo sont uniquement des vues de la référence sélectionnée.
    // Aucun doublon n'est persisté et les anciennes clés internes restent compatibles.
    // v0.19.7 : seule la couche superficielle/sol issue des heures MEASURED est visible.
    // inertiaEstimate.points reste la masse bâtiment cachée et n'entre jamais ici.
    val inertiaVisible = viewBounds?.let { b ->
        inertiaEstimate?.surfacePoints?.filter { it.timestamp in b }.orEmpty()
    }.orEmpty()
    val inertiaOverview = globalBounds?.let { b ->
        inertiaEstimate?.surfacePoints?.filter { it.timestamp in b }.orEmpty().let { selected ->
            if (selected.size <= 1200) selected else {
                val step = ((selected.size + 1199) / 1200).coerceAtLeast(1)
                selected.filterIndexed { index, _ -> index % step == 0 }
            }
        }
    }.orEmpty()
    val inertiaSensor = Sensor(
        id = THERMAL_INERTIA_SENSOR_ID,
        stableKey = THERMAL_INERTIA_STABLE_KEY,
        name = "Sol inertiel estimé",
        room = "Surface / sol équivalent · réel",
        colorIndex = 4,
        latestTimestamp = inertiaEstimate?.surfacePoints?.lastOrNull()?.timestamp
    )
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + inertiaSensor
    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +
        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)
    val overviewReference = overviewSampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()
    val chartOverviewSampleMap = overviewSampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to overviewReference.filter { it.source == PointSource.MEASURED }.map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +
        (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference.filter { it.source == PointSource.RECONSTRUCTED }) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaOverview)

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
                    IconButton(onClick = {
                        scope.launch {
                            busy = true
                            val selected = WeatherReferencePrefs(context).selectedReference()
                            val result = withContext(Dispatchers.IO) {
                                runCatching {
                                    if (selected.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                                        syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials)
                                    }
                                    weatherReferenceManager.refreshRecent(selected)
                                }
                            }
                            busy = false
                            reloadToken++
                            snackbar.showSnackbar(
                                result.fold(
                                    onSuccess = { "${it.label} · ${it.measured} réel(s) · ${it.reconstructed} reconstruit(s)" },
                                    onFailure = { "Station météo non actualisée : ${it.message ?: "réseau ou source indisponible"}" }
                                )
                            )
                        }
                    }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Actualiser Lyon et les courbes")
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
        Box(Modifier.fillMaxSize().padding(padding)) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(
                    start = 14.dp,
                    top = 14.dp,
                    end = 14.dp,
                    bottom = if (thermalBusy) 176.dp else 14.dp
                ),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
            if (sensors.isEmpty()) {
                item {
                    EmptyState {
                        picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel"))
                    }
                }
            } else {
                item {
                    HistoryOverviewCard(
                        sensors = chartSensors,
                        sampleMap = chartOverviewSampleMap,
                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        selectedTimestamp = selectedTimestamp,
                        onSelectTimestamp = { ts ->
                            // v0.17 : une sélection depuis le bandeau place la visée
                            // au centre de la fenêtre détaillée tout en gardant son zoom.
                            selectedTimestamp = ts
                            windowCenterTimestamp = ts
                            selectedAnnotation = null
                        },
                        onNavigate = { ts ->
                            // Le double-tap recentre le graphe principal autour du point
                            // en conservant le preset/zoom temporel actuellement choisi.
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        },
                        onUseForInertia = { range ->
                            val sensorId = inertiaEstimate?.diagnostics?.sourceSensorId
                            if (sensorId == null) {
                                scope.launch { snackbar.showSnackbar("Modèle d'inertie indisponible : aucune sonde physique active") }
                            } else {
                                scope.launch {
                                    busy = true
                                    val changed = withContext(Dispatchers.IO) {
                                        // ThermalTrainingMaskStore initialise SQLite dans son constructeur.
                                        // Le créer ici empêche tout accès DB synchrone pendant la composition UI.
                                        ThermalTrainingMaskStore(db).includeRange(sensorId, range.first, range.last)
                                    }
                                    reloadToken++
                                    busy = false
                                    snackbar.showSnackbar(
                                        if (changed > 0) "Zone réintégrée à l'entraînement inertiel"
                                        else "Zone déjà utilisée pour l'entraînement inertiel"
                                    )
                                }
                            }
                        },
                        onExcludeFromInertia = { range ->
                            val sensorId = inertiaEstimate?.diagnostics?.sourceSensorId
                            if (sensorId == null) {
                                scope.launch { snackbar.showSnackbar("Modèle d'inertie indisponible : aucune sonde physique active") }
                            } else {
                                scope.launch {
                                    busy = true
                                    withContext(Dispatchers.IO) {
                                        // Même garde-fou pour l'exclusion : création du store + écriture hors UI.
                                        ThermalTrainingMaskStore(db).addMerged(
                                            sensorId,
                                            range.first,
                                            range.last,
                                            "Sélection bandeau global"
                                        )
                                    }
                                    reloadToken++
                                    busy = false
                                    snackbar.showSnackbar("Zone exclue de l'entraînement inertiel · RAW conservées")
                                }
                            }
                        },
                        onZoomRange = { range ->
                            val span = (range.last - range.first).coerceAtLeast(60L * 60L * 1000L)
                            val center = range.first + span / 2L
                            customViewSpanMs = span
                            windowCenterTimestamp = center
                            selectedTimestamp = center
                            selectedAnnotation = null
                        }
                    )
                }

                item {
                    TimeTabs(preset = preset, onSelect = {
                        customViewSpanMs = null
                        preset = it
                        windowCenterTimestamp = selectedTimestamp
                            ?: viewBounds?.let { b -> b.first + (b.last - b.first) / 2L }
                        selectedAnnotation = null
                    })
                }

                item {
                    ChartCard(
                        sensors = chartSensors,
                        sampleMap = chartSampleMap,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        annotations = annotations,
                        bounds = viewBounds,
                        prefs = prefs,
                        curveStyles = activeCurveStyles,
                        styleTick = styleTick,
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
                        },
                        onRequestZoom = { ts ->
                            customViewSpanMs = null
                            preset = TimePreset.TWO_DAYS
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        }
                    )
                }

                item {
                    SensorSourcesCard(
                        sensors = sensors,
                        remoteConfigs = remoteConfigs,
                        showLyonSpecificTools = visualReference.key == WeatherReferenceCatalog.DEFAULT_KEY,
                        onOpenLyon = { lyonDetailOpen = true },
                        onSyncLyon = {
                            scope.launch {
                                busy = true
                                val selected = WeatherReferencePrefs(context).selectedReference()
                                val result = withContext(Dispatchers.IO) {
                                    runCatching {
                                        if (selected.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                                            syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials)
                                        }
                                        weatherReferenceManager.refreshRecent(selected)
                                    }
                                }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "${it.label} · ${it.measured} réel(s) · ${it.reconstructed} reconstruit(s)" },
                                        onFailure = { "Station météo : ${it.message ?: "source indisponible"}" }
                                    )
                                )
                            }
                        },
                        onCompleteLyon = {
                            scope.launch {
                                busy = true
                                val result = runCatching { completeLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "${it.label} : ${it.received} lot(s) · ${it.stored} valeur(s) stockée(s)" },
                                        onFailure = { "Compléter Lyon : ${it.message ?: "archives indisponibles"}" }
                                    )
                                )
                            }
                        },
                        onAddRemote = { remoteSensorDialogOpen = true },
                        onSyncRemote = { config ->
                            scope.launch {
                                busy = true
                                val result = withContext(Dispatchers.IO) { runCatching { remoteSensorSync.sync(config) } }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "${config.name} : ${if (it.added) "mesure ajoutée" else "déjà à jour"}" },
                                        onFailure = { "${config.name} : ${it.message ?: "GET impossible"}" }
                                    )
                                )
                            }
                        },
                        onDeleteRemote = { config ->
                            remoteSensorStore.delete(config.id)
                            remoteConfigs = remoteSensorStore.load()
                        }
                    )
                }

                item {
                    SeriesSelector(
                        sensors = chartSensors,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        onEditSensor = { sensor -> if (sensor.id >= 0L) editSensor = sensor },
                        onStyleEdit = { sensor ->
                            val key = when (sensor.id) {
                                WEATHER_OFFICIAL_SENSOR_ID -> "weather:official"
                                LYON_RECONSTRUCTED_SENSOR_ID -> "lyon:reconstructed"
                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"
                                else -> "sensor:${sensor.stableKey}"
                            }
                            styleEditKey = key to sensor.name
                        }
                    )
                }

                item {
                    ThermalReferenceCard(
                        db = db,
                        lyonLab = lyonLab,
                        credentials = meteoCredentials,
                        dataVersion = reloadToken,
                        onDataChanged = { reloadToken++ },
                        onBusyChanged = { thermalBusy = it },
                        onProgressChanged = { thermalProgressText = it }
                    )
                }

                item {
                    ThermalInertiaExperimentCard(inertiaEstimate)
                }

                item {
                    SourceAwareExportCard(db)
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
                        if (viewBounds?.let { ts in it } == true) {
                            InspectorCard(ts, chartSensors, chartSampleMap, showTemp, showHumidity)
                        } else {
                            Card(shape = RoundedCornerShape(18.dp)) {
                                Column(
                                    Modifier.fillMaxWidth().padding(14.dp),
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
                                    Text("Sélection prévisu · ${formatDateTime(ts)}", fontWeight = FontWeight.Bold)
                                    Text(
                                        "Hors de la fenêtre détaillée · double-tape sur le bandeau pour ouvrir cette période.",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
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

                item { Spacer(Modifier.height(72.dp)) }
            }
            }

            if (thermalBusy) {
                ThermalBusyOverlay(
                    progressText = thermalProgressText,
                    sensors = chartSensors,
                    sampleMap = chartSampleMap,
                    showTemp = showTemp,
                    bounds = viewBounds,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(horizontal = 14.dp, vertical = 82.dp)
                )
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

    if (lyonDetailOpen) {
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

    if (remoteSensorDialogOpen) {
        RemoteSensorDialog(
            onDismiss = { remoteSensorDialogOpen = false },
            onSave = { name, url, tempKey, humidityKey, timestampKey ->
                val config = remoteSensorStore.add(name, url, tempKey, humidityKey, timestampKey)
                remoteConfigs = remoteSensorStore.load()
                remoteSensorDialogOpen = false
                scope.launch {
                    busy = true
                    val result = withContext(Dispatchers.IO) { runCatching { remoteSensorSync.sync(config) } }
                    busy = false
                    reloadToken++
                    snackbar.showSnackbar(
                        result.fold(
                            onSuccess = { "${config.name} initialisée · synchro automatique activée" },
                            onFailure = { "${config.name} enregistrée · GET initial : ${it.message ?: "échec"}" }
                        )
                    )
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
private fun SensorSourcesCard(
    sensors: List<Sensor>,
    remoteConfigs: List<RemoteSensorConfig>,
    showLyonSpecificTools: Boolean,
    onOpenLyon: () -> Unit,
    onSyncLyon: () -> Unit,
    onCompleteLyon: () -> Unit,
    onAddRemote: () -> Unit,
    onSyncRemote: (RemoteSensorConfig) -> Unit,
    onDeleteRemote: (RemoteSensorConfig) -> Unit
) {
    val lyon = sensors.firstOrNull { it.stableKey == LyonWeatherSync.STABLE_KEY }
    Card(shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Sources & synchronisation", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "La station météo active est choisie dans Référence météo & moteur thermique. Ici on synchronise les sources sans dupliquer les noms des courbes.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Source météo", fontWeight = FontWeight.SemiBold)
                    Text(
                        if (lyon?.latestTimestamp != null) "Synchronisation disponible" else "En attente de données",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (showLyonSpecificTools) {
                    TextButton(onClick = onOpenLyon) { Text("Détail") }
                    TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }
                }
                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
            }

            remoteConfigs.forEach { config ->
                HorizontalDivider()
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(config.name, fontWeight = FontWeight.SemiBold)
                        Text(
                            "HTTP GET · automatique",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    TextButton(onClick = { onSyncRemote(config) }) { Text("Actualiser") }
                    IconButton(onClick = { onDeleteRemote(config) }) {
                        Icon(Icons.Default.Delete, contentDescription = "Supprimer la sonde HTTP")
                    }
                }
            }

            OutlinedButton(onClick = onAddRemote, modifier = Modifier.fillMaxWidth()) {
                Text("+ Ajouter une sonde HTTP GET")
            }
        }
    }
}

@Composable
private fun RemoteSensorDialog(
    onDismiss: () -> Unit,
    onSave: (String, String, String, String, String) -> Unit
) {
    var name by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var temperatureKey by remember { mutableStateOf("temperature") }
    var humidityKey by remember { mutableStateOf("humidity") }
    var timestampKey by remember { mutableStateOf("timestamp") }
    var error by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Ajouter une sonde HTTP GET") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text("À faire une seule fois : ensuite FabData synchronise cette sonde automatiquement.")
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Nom de la sonde") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it; error = false },
                    label = { Text("URL GET (http:// ou https://)") },
                    isError = error,
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Text("Réponse JSON ou texte : temperature=23.4&humidity=51", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(
                    value = temperatureKey,
                    onValueChange = { temperatureKey = it },
                    label = { Text("Champ température") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = humidityKey,
                    onValueChange = { humidityKey = it },
                    label = { Text("Champ humidité") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = timestampKey,
                    onValueChange = { timestampKey = it },
                    label = { Text("Champ date/heure (optionnel)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(onClick = {
                if (!url.trim().startsWith("http://") && !url.trim().startsWith("https://")) {
                    error = true
                } else {
                    onSave(name, url, temperatureKey, humidityKey, timestampKey)
                }
            }) { Text("Initialiser") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
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
            "Tap = curseur · double tap = événement · appui long = zoom 48 h · pince/glisse = ajuster",
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
    onEditSensor: (Sensor) -> Unit,
    onStyleEdit: (Sensor) -> Unit
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
                        val displayRoom = when (sensor.id) {
                            WEATHER_OFFICIAL_SENSOR_ID -> "Station météo officielle"
                            LYON_RECONSTRUCTED_SENSOR_ID -> "Station météo reconstruite"
                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"
                            else -> sensor.room
                        }
                        Text(displayRoom, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) {
                            Text(sensor.room, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
                        onCheckedChange = { showTemp[sensor.id] = it }
                    )
                    if (sensor.id != THERMAL_INERTIA_SENSOR_ID) {
                        Text("%", style = MaterialTheme.typography.labelMedium)
                        Checkbox(
                            checked = showHumidity[sensor.id] == true,
                            onCheckedChange = { showHumidity[sensor.id] = it }
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
        }
    }
}

@Composable
private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,
    viewBounds: LongRange?,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit,
    onNavigate: (Long) -> Unit,
    onUseForInertia: (LongRange) -> Unit,
    onExcludeFromInertia: (LongRange) -> Unit,
    onZoomRange: (LongRange) -> Unit
) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp)
        ) {
            Text("Vue globale", fontWeight = FontWeight.Bold)
            Text(
                "Tap = viser · double tap = ouvrir · Sélection = choisir une période · pince/glisse = prévisu",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            val bounds = historyBounds
            if (bounds == null) {
                Text("Historique global indisponible", style = MaterialTheme.typography.bodySmall)
            } else {
                var previewPreset by rememberSaveable { mutableStateOf(PreviewPreset.M6) }
                var previewZoom by rememberSaveable { mutableFloatStateOf(1f) }
                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }
                var rangeStart by remember { mutableStateOf<Long?>(null) }
                var rangeEnd by remember { mutableStateOf<Long?>(null) }
                var rangeMenuOpen by remember { mutableStateOf(false) }
                val helpContext = LocalContext.current
                val helpPrefs = remember {
                    helpContext.getSharedPreferences("fabdata_context_help", Context.MODE_PRIVATE)
                }
                var helpOpen by rememberSaveable { mutableStateOf(false) }
                var tipOpen by rememberSaveable {
                    mutableStateOf(
                        !helpPrefs.getBoolean("range_tip_dismissed", false) &&
                            !helpPrefs.getBoolean("range_selection_used", false)
                    )
                }
                var demoOpen by rememberSaveable { mutableStateOf(false) }
                var demoStep by rememberSaveable { mutableIntStateOf(0) }
                var demoReplayToken by rememberSaveable { mutableIntStateOf(0) }

                LaunchedEffect(demoOpen, demoReplayToken) {
                    if (demoOpen) {
                        demoStep = 0
                        delay(850L)
                        demoStep = 1
                        delay(850L)
                        demoStep = 2
                        delay(850L)
                        demoStep = 3
                    }
                }

                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    PreviewPreset.entries.forEach { item ->
                        Surface(
                            onClick = {
                                previewPreset = item
                                previewZoom = 1f
                                previewCenter = (selectedTimestamp
                                    ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                                    ?: previewCenter).coerceIn(bounds.first, bounds.last)
                            },
                            color = if (item == previewPreset) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent,
                            shape = RoundedCornerShape(14.dp)
                        ) {
                            Text(
                                item.label,
                                Modifier.padding(horizontal = 10.dp, vertical = 7.dp),
                                fontWeight = if (item == previewPreset) FontWeight.Bold else FontWeight.Normal
                            )
                        }
                    }
                }

                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    AssistChip(
                        onClick = {
                            rangeSelectionMode = !rangeSelectionMode
                            rangeMenuOpen = false
                            rangeStart = null
                            rangeEnd = null
                            if (rangeSelectionMode) {
                                helpOpen = false
                                demoOpen = false
                            }
                        },
                        label = {
                            Text(if (rangeSelectionMode) "✓ Sélection active" else "Sélectionner une période")
                        }
                    )
                    OutlinedButton(
                        onClick = {
                            helpOpen = !helpOpen
                            tipOpen = false
                            if (!helpOpen) demoOpen = false
                        }
                    ) { Text("? Aide") }
                    OutlinedButton(
                        onClick = {
                            tipOpen = !tipOpen
                            helpOpen = false
                            demoOpen = false
                        }
                    ) { Text("! Astuce") }
                }
                if (rangeSelectionMode) {
                    Text(
                        "↔ Glisse horizontalement dans le bandeau puis choisis l'action. Tu peux recommencer pour plusieurs zones.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }

                if (helpOpen) {
                    Card(
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.38f)
                        )
                    ) {
                        Column(
                            Modifier.fillMaxWidth().padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            Text("? Sélection des périodes", fontWeight = FontWeight.Bold)
                            Text(
                                "Active Sélectionner une période, puis glisse directement dans le bandeau du haut. " +
                                    "La zone reste visible et une petite liste d'actions s'ouvre à droite.",
                                style = MaterialTheme.typography.bodySmall
                            )
                            Text(
                                "Le graphe principal ne change pas : son appui long reste réservé au zoom 48 h.",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Row(
                                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                TextButton(onClick = {
                                    demoOpen = true
                                    demoReplayToken++
                                }) { Text("▶ Voir la démonstration") }
                                TextButton(onClick = {
                                    helpOpen = false
                                    demoOpen = false
                                }) { Text("Fermer") }
                            }
                            if (demoOpen) {
                                RangeSelectionHelpDemo(
                                    step = demoStep,
                                    onReplay = { demoReplayToken++ },
                                    onNext = { demoStep = (demoStep + 1).coerceAtMost(3) }
                                )
                            }
                        }
                    }
                }

                if (tipOpen) {
                    Card(
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.34f)
                        )
                    ) {
                        Column(
                            Modifier.fillMaxWidth().padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            Text("! Astuce du jour", fontWeight = FontWeight.Bold)
                            Text(
                                "Si tu connais une période avec climatisation, fenêtre ouverte, chauffage inhabituel ou autre événement extérieur, " +
                                    "sélectionne-la ici puis choisis Exclure du modèle d'inertie. Les RAW restent intactes.",
                                style = MaterialTheme.typography.bodySmall
                            )
                            Row(
                                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                TextButton(onClick = {
                                    rangeSelectionMode = true
                                    tipOpen = false
                                    helpOpen = false
                                }) { Text("Essayer maintenant") }
                                TextButton(onClick = {
                                    tipOpen = false
                                    helpPrefs.edit().putBoolean("range_tip_dismissed", true).apply()
                                }) { Text("Ne plus afficher") }
                            }
                        }
                    }
                }

                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)
                val maxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)
                val mainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }
                    ?: (24L * 60L * 60L * 1000L)
                val minSpan = minOf(maxSpan, maxOf(24L * 60L * 60L * 1000L, mainSpan))
                val maxZoom = (maxSpan.toDouble() / minSpan.toDouble()).toFloat().coerceAtLeast(1f)
                val effectiveZoom = previewZoom.coerceIn(1f, maxZoom)
                val previewSpan = (maxSpan.toDouble() / effectiveZoom.toDouble()).toLong()
                    .coerceIn(minSpan, maxSpan)

                fun clampCenter(value: Long, span: Long): Long {
                    if (span >= fullSpan) return bounds.first + fullSpan / 2L
                    val half = span / 2L
                    return value.coerceIn(bounds.first + half, bounds.last - (span - half))
                }

                val effectiveCenter = clampCenter(previewCenter, previewSpan)
                val previewFrom = if (previewSpan >= fullSpan) bounds.first else effectiveCenter - previewSpan / 2L
                val previewTo = if (previewSpan >= fullSpan) bounds.last else previewFrom + previewSpan
                val previewWindow = previewFrom..previewTo
                val visiblePoints = sensors.flatMap { sensor ->
                    sampleMap[sensor.id].orEmpty().filter { it.timestamp in previewWindow }
                }
                val minTemp = visiblePoints.minOfOrNull { it.temperature } ?: 0.0
                val maxTemp = visiblePoints.maxOfOrNull { it.temperature } ?: 1.0
                val tempRange = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0
                val highlight = MaterialTheme.colorScheme.primary
                val selectionColor = MaterialTheme.colorScheme.tertiary
                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)

                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(92.dp)
                        .background(surface, RoundedCornerShape(12.dp))
                        .pointerInput(bounds, previewPreset, rangeSelectionMode) {
                            if (!rangeSelectionMode) detectTransformGestures { centroid, pan, zoomChange, _ ->
                                val oldMaxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)
                                val oldMainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }
                                    ?: (24L * 60L * 60L * 1000L)
                                val oldMinSpan = minOf(
                                    oldMaxSpan,
                                    maxOf(24L * 60L * 60L * 1000L, oldMainSpan)
                                )
                                val oldMaxZoom = (oldMaxSpan.toDouble() / oldMinSpan.toDouble())
                                    .toFloat().coerceAtLeast(1f)
                                val oldZoom = previewZoom.coerceIn(1f, oldMaxZoom)
                                val oldSpan = (oldMaxSpan.toDouble() / oldZoom.toDouble()).toLong()
                                    .coerceIn(oldMinSpan, oldMaxSpan)
                                val oldCenter = clampCenter(previewCenter, oldSpan)
                                val oldFrom = if (oldSpan >= fullSpan) bounds.first else oldCenter - oldSpan / 2L
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val fraction = (centroid.x / width).coerceIn(0f, 1f)
                                val anchorTs = oldFrom + (oldSpan * fraction).toLong()

                                val newZoom = (oldZoom * zoomChange).coerceIn(1f, oldMaxZoom)
                                val newSpan = (oldMaxSpan.toDouble() / newZoom.toDouble()).toLong()
                                    .coerceIn(oldMinSpan, oldMaxSpan)
                                val zoomAnchoredCenter = anchorTs - (newSpan * fraction).toLong() + newSpan / 2L
                                val panShift = (-(pan.x / width) * newSpan.toDouble()).toLong()

                                previewZoom = newZoom
                                previewCenter = clampCenter(zoomAnchoredCenter + panShift, newSpan)
                            }
                        }
                        .pointerInput(previewFrom, previewTo, rangeSelectionMode) {
                            if (!rangeSelectionMode) {
                                detectTapGestures(
                                    onDoubleTap = { p ->
                                        val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        val ts = previewFrom + (previewSpan * frac).toLong()
                                        onSelectTimestamp(ts)
                                        onNavigate(ts)
                                    },
                                    onTap = { p ->
                                        val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        onSelectTimestamp(previewFrom + (previewSpan * frac).toLong())
                                    }
                                )
                            }
                        }
                        .pointerInput(previewFrom, previewTo, rangeSelectionMode) {
                            if (rangeSelectionMode) {
                                detectDragGestures(
                                    onDragStart = { p ->
                                        val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        val ts = previewFrom + (previewSpan * frac).toLong()
                                        rangeStart = ts
                                        rangeEnd = ts
                                        rangeMenuOpen = false
                                    },
                                    onDrag = { change, _ ->
                                        val frac = (change.position.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        rangeEnd = previewFrom + (previewSpan * frac).toLong()
                                        change.consume()
                                    },
                                    onDragEnd = {
                                        val a = rangeStart
                                        val b = rangeEnd
                                        if (a != null && b != null && kotlin.math.abs(b - a) >= 60L * 60L * 1000L) {
                                            rangeMenuOpen = true
                                            tipOpen = false
                                            helpPrefs.edit().putBoolean("range_selection_used", true).apply()
                                        } else {
                                            rangeStart = null
                                            rangeEnd = null
                                        }
                                    },
                                    onDragCancel = {
                                        rangeStart = null
                                        rangeEnd = null
                                        rangeMenuOpen = false
                                    }
                                )
                            }
                        }
                ) {
                    if (visiblePoints.isNotEmpty()) {
                        sensors.forEach { sensor ->
                            val points = sampleMap[sensor.id].orEmpty()
                                .filter { it.timestamp in previewWindow }
                                .sortedBy { it.timestamp }
                            if (points.size >= 2) {
                                val path = Path()
                                var previous: SamplePoint? = null
                                // La prévisu est sous-échantillonnée ; son seuil de coupure
                                // s'adapte à sa largeur temporelle pour ne pas casser chaque bucket.
                                val previewGapLimit = maxOf(
                                    6L * 60L * 60L * 1000L,
                                    previewSpan / 150L
                                )
                                points.forEach { point ->
                                    val x = ((point.timestamp - previewFrom).toDouble() / previewSpan.toDouble())
                                        .toFloat() * size.width
                                    val y = size.height - (((point.temperature - minTemp) / tempRange)
                                        .toFloat() * size.height)
                                    val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                                        previous?.let { point.timestamp - it.timestamp > previewGapLimit } == true
                                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                                    previous = point
                                }
                                drawPath(
                                    path,
                                    palette[sensor.colorIndex % palette.size].copy(alpha = 0.72f),
                                    style = Stroke(width = 1.5.dp.toPx())
                                )
                            }
                        }
                    }

                    // Fenêtre détaillée actuelle : fond grisé + deux limites.
                    viewBounds?.let { visible ->
                        val clippedStart = maxOf(visible.first, previewFrom)
                        val clippedEnd = minOf(visible.last, previewTo)
                        if (clippedEnd > clippedStart) {
                            val left = (((clippedStart - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            val right = (((clippedEnd - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            drawRect(
                                highlight.copy(alpha = 0.16f),
                                topLeft = Offset(left, 0f),
                                size = androidx.compose.ui.geometry.Size(right - left, size.height)
                            )
                            drawLine(highlight.copy(alpha = 0.85f), Offset(left, 0f), Offset(left, size.height), 2f)
                            drawLine(highlight.copy(alpha = 0.85f), Offset(right, 0f), Offset(right, size.height), 2f)
                        }
                    }

                    if (rangeSelectionMode) {
                        val a = rangeStart
                        val b = rangeEnd
                        if (a != null && b != null) {
                            val start = maxOf(minOf(a, b), previewFrom)
                            val end = minOf(maxOf(a, b), previewTo)
                            if (end > start) {
                                val left = (((start - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                    .coerceIn(0f, size.width)
                                val right = (((end - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                    .coerceIn(0f, size.width)
                                drawRect(
                                    selectionColor.copy(alpha = 0.24f),
                                    topLeft = Offset(left, 0f),
                                    size = androidx.compose.ui.geometry.Size(right - left, size.height)
                                )
                                drawLine(selectionColor, Offset(left, 0f), Offset(left, size.height), 2.dp.toPx())
                                drawLine(selectionColor, Offset(right, 0f), Offset(right, size.height), 2.dp.toPx())
                                drawCircle(selectionColor, 5.dp.toPx(), Offset(left, size.height / 2f))
                                drawCircle(selectionColor, 5.dp.toPx(), Offset(right, size.height / 2f))
                            }
                        }
                    }

                    selectedTimestamp?.takeIf { it in previewWindow }?.let { selected ->
                        val x = (((selected - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        drawLine(
                            selectionColor.copy(alpha = 0.95f),
                            Offset(x, 0f),
                            Offset(x, size.height),
                            2.dp.toPx()
                        )
                        drawCircle(selectionColor, 4.dp.toPx(), Offset(x, size.height / 2f))
                    }
                }

                val pendingRange = rangeStart?.let { a ->
                    rangeEnd?.let { b -> minOf(a, b)..maxOf(a, b) }
                }
                Box(Modifier.fillMaxWidth()) {
                    Box(Modifier.align(Alignment.TopEnd)) {
                        DropdownMenu(
                            expanded = rangeMenuOpen && pendingRange != null,
                            onDismissRequest = {
                                rangeMenuOpen = false
                                rangeStart = null
                                rangeEnd = null
                            }
                        ) {
                            pendingRange?.let { selectedRange ->
                                DropdownMenuItem(
                                    text = { Text("Utiliser cette zone pour entraîner l'inertie") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onUseForInertia(selectedRange)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Exclure cette zone du modèle d'inertie") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onExcludeFromInertia(selectedRange)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Utiliser cette zone comme nouveau zoom") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        rangeSelectionMode = false
                                        onZoomRange(selectedRange)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Annuler") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                            }
                        }
                    }
                }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDateTime(previewFrom), style = MaterialTheme.typography.labelSmall)
                    Text(
                        "max ${previewPreset.label}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(formatDateTime(previewTo), style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}

@Composable
private fun RangeSelectionHelpDemo(
    step: Int,
    onReplay: () -> Unit,
    onNext: () -> Unit
) {
    val accent = MaterialTheme.colorScheme.primary
    val secondary = MaterialTheme.colorScheme.tertiary
    val track = MaterialTheme.colorScheme.outlineVariant
    val popup = MaterialTheme.colorScheme.surface
    val popupLine = MaterialTheme.colorScheme.onSurfaceVariant

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Canvas(
            Modifier.fillMaxWidth().height(92.dp)
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.30f), RoundedCornerShape(12.dp))
        ) {
            val y = size.height * 0.55f
            drawLine(track, Offset(size.width * 0.08f, y), Offset(size.width * 0.92f, y), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.12f, y - 15f), Offset(size.width * 0.30f, y + 8f), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.30f, y + 8f), Offset(size.width * 0.48f, y - 12f), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.48f, y - 12f), Offset(size.width * 0.67f, y + 5f), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.67f, y + 5f), Offset(size.width * 0.88f, y - 8f), 2.dp.toPx())

            val startX = size.width * 0.20f
            val finalX = size.width * 0.68f
            val cursorX = when (step.coerceIn(0, 3)) {
                0 -> startX
                1 -> startX + (finalX - startX) * 0.48f
                else -> finalX
            }
            if (step >= 1) {
                drawRect(
                    secondary.copy(alpha = 0.22f),
                    topLeft = Offset(startX, 8f),
                    size = androidx.compose.ui.geometry.Size((cursorX - startX).coerceAtLeast(2f), size.height - 16f)
                )
                drawLine(secondary, Offset(startX, 8f), Offset(startX, size.height - 8f), 2.dp.toPx())
                drawLine(secondary, Offset(cursorX, 8f), Offset(cursorX, size.height - 8f), 2.dp.toPx())
            }
            drawCircle(accent, 6.dp.toPx(), Offset(cursorX, y))

            if (step >= 3) {
                val left = size.width * 0.66f
                val top = 7f
                val width = size.width * 0.30f
                val height = size.height * 0.68f
                drawRect(
                    popup,
                    topLeft = Offset(left, top),
                    size = androidx.compose.ui.geometry.Size(width, height)
                )
                repeat(3) { index ->
                    val lineY = top + 16f + index * 16f
                    drawLine(
                        popupLine,
                        Offset(left + 10f, lineY),
                        Offset(left + width - 10f, lineY),
                        1.5.dp.toPx()
                    )
                }
            }
        }

        Text(
            when (step.coerceIn(0, 3)) {
                0 -> "1 · Active la sélection et pose le doigt / la souris au début de la période."
                1 -> "2 · Glisse horizontalement : le rectangle suit exactement l'intervalle choisi."
                2 -> "3 · Relâche : la période reste surlignée."
                else -> "4 · La popup propose Entraîner, Exclure, Nouveau zoom ou Annuler."
            },
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            TextButton(onClick = onReplay) { Text("↻ Rejouer") }
            TextButton(onClick = onNext, enabled = step < 3) { Text("Étape suivante") }
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
    curveStyles: Map<Long, CurveVisualPrefs>,
    styleTick: Long,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit,
    onAnnotationClick: (AnnotationItem) -> Unit,
    onAnnotationDoubleClick: (AnnotationItem) -> Unit,
    onRequestAnnotation: (Long) -> Unit,
    onRequestZoom: (Long) -> Unit
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
                        "Plein = réel · tirets = reconstruit · pointillés = prévision · point épais = événement",
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
                    curveStyles = curveStyles,
                    styleTick = styleTick,
                    selectedTimestamp = selectedTimestamp,
                    resetKey = resetKey,
                    onSelectTimestamp = onSelectTimestamp,
                    onAnnotationClick = onAnnotationClick,
                    onAnnotationDoubleClick = onAnnotationDoubleClick,
                    onRequestAnnotation = onRequestAnnotation,
                    onRequestZoom = onRequestZoom
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
    curveStyles: Map<Long, CurveVisualPrefs>,
    styleTick: Long,
    selectedTimestamp: Long?,
    resetKey: Int,
    onSelectTimestamp: (Long) -> Unit,
    onAnnotationClick: (AnnotationItem) -> Unit,
    onAnnotationDoubleClick: (AnnotationItem) -> Unit,
    onRequestAnnotation: (Long) -> Unit,
    onRequestZoom: (Long) -> Unit
) {
    var zoom by remember(resetKey, from, to) { mutableFloatStateOf(1f) }
    var center by remember(resetKey, from, to) { mutableFloatStateOf(0.5f) }
    var sightTemperature by remember(resetKey, from, to) { mutableStateOf<Double?>(null) }
    val currentSelectedTimestamp by rememberUpdatedState(selectedTimestamp)

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

    fun visibleTemperatureRange(window: LongRange): Pair<Double, Double> {
        val values = sensors
            .filter { showTemp[it.id] == true }
            .flatMap { sampleMap[it.id].orEmpty() }
            .filter { it.timestamp in window }
            .flatMap { p ->
                if (p.source == PointSource.FORECAST && p.uncertaintyC != null) {
                    listOf(p.temperature, p.temperature + p.uncertaintyC, p.temperature - p.uncertaintyC)
                } else listOf(p.temperature)
            }
        return paddedRange(values, 15.0, 35.0, -50.0, 80.0)
    }

    Canvas(
        modifier = modifier
            .background(surfaceColor, RoundedCornerShape(16.dp))
            .pointerInput(from, to, resetKey) {
                detectTransformGestures { centroid, pan, zoomChange, _ ->
                    val window = visibleWindow()
                    val span = (window.last - window.first).coerceAtLeast(1L)
                    val leftPx = 52.dp.toPx()
                    val rightPx = size.width - 44.dp.toPx()
                    val topPx = 22.dp.toPx()
                    val bottomPx = size.height - 38.dp.toPx()
                    val plotHeight = (bottomPx - topPx).coerceAtLeast(1f)
                    val range = visibleTemperatureRange(window)
                    val selectedX = currentSelectedTimestamp
                        ?.takeIf { it in window }
                        ?.let { leftPx + ((it - window.first).toDouble() / span.toDouble()).toFloat() * (rightPx - leftPx) }
                    val selectedY = sightTemperature?.let { temp ->
                        bottomPx - (((temp - range.first) / (range.second - range.first)).toFloat() * plotHeight)
                    }
                    val grabsSight = selectedX != null &&
                        (kotlin.math.abs(centroid.x - selectedX) <= 30.dp.toPx() ||
                            (selectedY != null && kotlin.math.abs(centroid.y - selectedY) <= 24.dp.toPx())) &&
                        zoomChange in 0.97f..1.03f

                    if (grabsSight && centroid.x in leftPx..rightPx && centroid.y in topPx..bottomPx) {
                        val fracX = ((centroid.x - leftPx) / (rightPx - leftPx)).coerceIn(0f, 1f)
                        onSelectTimestamp(window.first + (span * fracX).toLong())
                        val fracY = ((bottomPx - centroid.y) / plotHeight).coerceIn(0f, 1f)
                        sightTemperature = range.first + (range.second - range.first) * fracY.toDouble()
                    } else {
                        val oldVisible = 1f / zoom
                        val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)
                        zoom = newZoom
                        val visible = 1f / zoom
                        center = (center - (pan.x / size.width.toFloat()) * oldVisible)
                            .coerceIn(visible / 2f, 1f - visible / 2f)
                    }
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
                            onRequestZoom(window.first + (span * frac).toLong())
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
                        } else if (p.x in left..right) {
                            val frac = ((p.x - left) / (right - left)).coerceIn(0f, 1f)
                            onRequestAnnotation(window.first + (span * frac).toLong())
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
                                val top = 22.dp.toPx()
                                val bottom = size.height - 38.dp.toPx()
                                if (p.y in top..bottom) {
                                    val range = visibleTemperatureRange(window)
                                    val fracY = ((bottom - p.y) / (bottom - top).coerceAtLeast(1f)).coerceIn(0f, 1f)
                                    sightTemperature = range.first + (range.second - range.first) * fracY.toDouble()
                                }
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
            .flatMap { p ->
                if (p.source == PointSource.FORECAST && p.uncertaintyC != null) {
                    listOf(p.temperature, p.temperature + p.uncertaintyC, p.temperature - p.uncertaintyC)
                } else listOf(p.temperature)
            }

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
            val baseColor = palette[sensor.colorIndex % palette.size]
            val visual = curveStyles[sensor.id] ?: CurveVisualPrefs()
            val color = resolveCurveColor(baseColor, visual, styleTick) ?: Color.Transparent
            val auraColor = resolveAuraColor(visual, styleTick)
            val points = sampleMap[sensor.id].orEmpty().filter { it.timestamp in visibleFrom..visibleTo }

            if (showTemp[sensor.id] == true && points.size >= 2) {
                val sourcePaths = PointSource.entries.associateWith { Path() }
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val prev = previous
                    if (prev != null) {
                        val breakHere = (
                            sensor.stableKey == LyonWeatherSync.STABLE_KEY ||
                            sensor.id == LYON_RECONSTRUCTED_SENSOR_ID || sensor.id == THERMAL_INERTIA_SENSOR_ID
                        ) && p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS
                        if (!breakHere) {
                            val path = sourcePaths[p.source]!!
                            path.moveTo(mapX(prev.timestamp), mapTemp(prev.temperature))
                            path.lineTo(mapX(p.timestamp), mapTemp(p.temperature))
                        }
                    }
                    previous = p
                }
                sourcePaths.forEach { (source, path) ->
                    val alpha = when (source) {
                        PointSource.MEASURED -> 1.0f
                        PointSource.RECONSTRUCTED -> 0.78f
                        PointSource.FORECAST -> 0.62f
                    }
                    val effect = when (source) {
                        PointSource.MEASURED -> null
                        PointSource.RECONSTRUCTED -> PathEffect.dashPathEffect(floatArrayOf(13f, 7f))
                        PointSource.FORECAST -> PathEffect.dashPathEffect(floatArrayOf(3f, 7f))
                    }
                    auraColor?.let { aura ->
                        drawPath(path, aura.copy(alpha = aura.alpha * alpha), style = Stroke(width = (prefs.lineWidth + 7f).dp.toPx(), pathEffect = effect))
                    }
                    drawPath(path, color.copy(alpha = color.alpha * alpha), style = Stroke(width = prefs.lineWidth.dp.toPx(), pathEffect = effect))
                }
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        val alpha = when (p.source) { PointSource.MEASURED -> 1f; PointSource.RECONSTRUCTED -> 0.78f; PointSource.FORECAST -> 0.60f }
                        drawCircle(color.copy(alpha = color.alpha * alpha), 2.2.dp.toPx(), Offset(mapX(p.timestamp), mapTemp(p.temperature)))
                    }
                }

                // Nuage d'incertitude : +σ, -σ, +σ... Les marqueurs deviennent
                // volontairement plus rares quand l'horizon s'éloigne.
                val forecastCloud = points.filter { it.source == PointSource.FORECAST && it.uncertaintyC != null }
                forecastCloud.forEachIndexed { index, p ->
                    val horizon = index + 1
                    val stride = when {
                        horizon <= 6 -> 1
                        horizon <= 12 -> 2
                        else -> 3
                    }
                    if ((horizon - 1) % stride == 0) {
                        val sigma = p.uncertaintyC!!.coerceIn(0.0, 8.0)
                        val cloudValue = p.temperature + if (index % 2 == 0) sigma else -sigma
                        val confidenceAlpha = ((p.confidence ?: 0.35) * 0.72).toFloat().coerceIn(0.16f, 0.58f)
                        drawCircle(
                            color.copy(alpha = color.alpha * confidenceAlpha),
                            (2.1f + min(1.8, sigma).toFloat()).dp.toPx(),
                            Offset(mapX(p.timestamp), mapTemp(cloudValue))
                        )
                    }
                }
            }

            if (showHumidity[sensor.id] == true && points.size >= 2) {
                val sourcePaths = PointSource.entries.associateWith { Path() }
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val prev = previous
                    if (prev != null) {
                        val breakHere = (sensor.stableKey == LyonWeatherSync.STABLE_KEY || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) &&
                            p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS
                        if (!breakHere) {
                            val path = sourcePaths[p.source]!!
                            path.moveTo(mapX(prev.timestamp), mapHum(prev.humidity))
                            path.lineTo(mapX(p.timestamp), mapHum(p.humidity))
                        }
                    }
                    previous = p
                }
                sourcePaths.forEach { (source, path) ->
                    val alpha = when (source) { PointSource.MEASURED -> 0.82f; PointSource.RECONSTRUCTED -> 0.68f; PointSource.FORECAST -> 0.54f }
                    val effect = when (source) {
                        PointSource.MEASURED -> PathEffect.dashPathEffect(floatArrayOf(10f, 7f))
                        PointSource.RECONSTRUCTED -> PathEffect.dashPathEffect(floatArrayOf(16f, 9f))
                        PointSource.FORECAST -> PathEffect.dashPathEffect(floatArrayOf(3f, 7f))
                    }
                    drawPath(path, color.copy(alpha = color.alpha * alpha), style = Stroke(width = max(1.2f, prefs.lineWidth - 0.5f).dp.toPx(), pathEffect = effect))
                }
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        drawCircle(color.copy(alpha = if (p.source == PointSource.MEASURED) 0.82f else 0.58f), 2.dp.toPx(), Offset(mapX(p.timestamp), mapHum(p.humidity)))
                    }
                }
            }
        }

        annotations.filter { it.timestamp in visibleFrom..visibleTo }.forEach { note ->
            val x = mapX(note.timestamp)
            val sensor = note.sensorId?.let { id -> sensors.firstOrNull { it.id == id } }
            val point = sensor?.let { nearestForSensor(it, sampleMap[it.id].orEmpty(), note.timestamp) }

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
            drawLine(selectColor, Offset(x, top), Offset(x, bottom), strokeWidth = 2.dp.toPx())

            val fallbackTemperature = sensors
                .firstOrNull { showTemp[it.id] == true }
                ?.let { sensor -> nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), ts)?.temperature }
            val crossTemperature = (sightTemperature ?: fallbackTemperature)
                ?.coerceIn(tempRange.first, tempRange.second)
            val crossY = crossTemperature?.let { mapTemp(it) }

            // Vrai crosshair : température horizontale sur toute la zone utile.
            if (crossY != null && crossY in top..bottom) {
                drawLine(
                    selectColor.copy(alpha = 0.88f),
                    Offset(left, crossY),
                    Offset(right, crossY),
                    strokeWidth = 1.8.dp.toPx()
                )
                drawCircle(Color.White, 5.dp.toPx(), Offset(x, crossY))
                drawCircle(selectColor, 3.2.dp.toPx(), Offset(x, crossY))
            }

            val sightPaint = android.graphics.Paint(centerPaint).apply {
                color = selectColor.toArgbCompat()
                textSize = 9.dp.toPx()
                isFakeBoldText = true
            }
            val timeLabel = formatDateTime(ts)
            val timeHalf = sightPaint.measureText(timeLabel) / 2f + 4.dp.toPx()
            val timeX = x.coerceIn(left + timeHalf, right - timeHalf)

            // Date/heure répétée en haut ET en bas du graphe.
            drawContext.canvas.nativeCanvas.drawText(timeLabel, timeX, top + 10.dp.toPx(), sightPaint)
            drawContext.canvas.nativeCanvas.drawText(timeLabel, timeX, bottom - 5.dp.toPx(), sightPaint)

            // Température du crosshair répétée à gauche ET à droite.
            if (crossTemperature != null && crossY != null) {
                val tempLabel = String.format(Locale.FRANCE, "%.1f°", crossTemperature)
                val leftSightPaint = android.graphics.Paint(paint).apply {
                    color = selectColor.toArgbCompat()
                    textSize = 9.dp.toPx()
                    isFakeBoldText = true
                    textAlign = android.graphics.Paint.Align.LEFT
                }
                val rightSightPaint = android.graphics.Paint(leftSightPaint).apply {
                    textAlign = android.graphics.Paint.Align.RIGHT
                }
                val baseline = (crossY - 4.dp.toPx()).coerceIn(top + 9.dp.toPx(), bottom - 3.dp.toPx())
                drawContext.canvas.nativeCanvas.drawText(tempLabel, left + 4.dp.toPx(), baseline, leftSightPaint)
                drawContext.canvas.nativeCanvas.drawText(tempLabel, right - 4.dp.toPx(), baseline, rightSightPaint)
            }

            // Les températures réelles de chaque sonde restent indiquées à leur propre niveau.
            sensors.filter { showTemp[it.id] == true }.forEach { sensor ->
                val point = nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), ts) ?: return@forEach
                val y = mapTemp(point.temperature)
                if (y !in top..bottom) return@forEach
                val markerColor = palette[sensor.colorIndex % palette.size]
                drawLine(markerColor, Offset(x - 13.dp.toPx(), y), Offset(x + 13.dp.toPx(), y), strokeWidth = 2.2.dp.toPx())
                drawCircle(markerColor, 3.2.dp.toPx(), Offset(x, y))
                val valuePaint = android.graphics.Paint(paint).apply {
                    color = markerColor.toArgbCompat()
                    textSize = 9.dp.toPx()
                    isFakeBoldText = true
                }
                val label = String.format(Locale.FRANCE, "%.1f°", point.temperature)
                val width = valuePaint.measureText(label)
                val tx = if (x + 18.dp.toPx() + width <= right) x + 18.dp.toPx() else x - 18.dp.toPx() - width
                drawContext.canvas.nativeCanvas.drawText(label, tx, y - 4.dp.toPx(), valuePaint)
            }
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
    val point = sensor?.let { nearestForSensor(it, sampleMap[it.id].orEmpty(), annotation.timestamp) }

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
                val point = nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), timestamp)
                Row(Modifier.fillMaxWidth()) {
                    Text(sensor.room, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                    if (showTemp[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f °C", it.temperature) } ?: "—",
                            Modifier.width(78.dp)
                        )
                    }
                    if (showHumidity[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f %%", it.humidity) } ?: "—",
                            Modifier.width(72.dp)
                        )
                    }
                }
                if (point?.source == PointSource.FORECAST) {
                    val sigmaText = point.uncertaintyC?.let { "σ ${String.format(Locale.FRANCE, "%.2f", it)} °C" } ?: "σ —"
                    val confidenceText = point.confidence?.let { "confiance ${(it * 100).toInt()} %" } ?: "confiance —"
                    val analogText = point.analogCount?.let { "$it analogues historiques" } ?: "analogues insuffisants"
                    Text(
                        "Prévision · $sigmaText · $confidenceText · $analogText",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
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
    val point = sensor?.let { nearestForSensor(it, sampleMap[it.id].orEmpty(), annotation.timestamp) }

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
                Text("Politique de confidentialité · FabData v0.8", fontWeight = FontWeight.Bold)
                Text(
                    "Les mesures, noms de pièces et événements sont traités localement sur cet appareil. " +
                        "FabData n'envoie aucune donnée utilisateur à un serveur, n'intègre ni publicité ni analytique " +
                        "et ne crée aucun compte utilisateur. La sonde Lyon consulte uniquement une page publique " +
                        "d'observations météo Lyon-Bron afin d'importer température et humidité.",
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

private fun nearestForSensor(
    sensor: Sensor,
    points: List<SamplePoint>,
    timestamp: Long
): SamplePoint? {
    val point = nearest(points, timestamp) ?: return null
    if (sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
        abs(point.timestamp - timestamp) > LYON_NEAREST_TOLERANCE_MS
    ) return null
    return point
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
