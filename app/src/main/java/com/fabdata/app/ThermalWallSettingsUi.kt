package com.fabdata.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

private data class ThermalWallUiRuntime(
    val config: ThermalWallConfigStore,
    val solar: ThermalWallSolarService
)

@Composable
fun ThermalWallSettingsCard(
    db: FabDataDb,
    reference: WeatherReference,
    enabled: Boolean = true,
    onChanged: () -> Unit = {}
) {
    val scope = rememberCoroutineScope()
    var runtime by remember(db) { mutableStateOf<ThermalWallUiRuntime?>(null) }
    var open by remember { mutableStateOf(false) }
    var version by remember { mutableIntStateOf(0) }
    var info by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(db) {
        runtime = withContext(Dispatchers.IO) {
            ThermalWallUiRuntime(
                ThermalWallConfigStore(db),
                ThermalWallSolarService(db, WeatherReferenceStore(db))
            )
        }
    }

    val rt = runtime
    Card(shape = RoundedCornerShape(14.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp)
        ) {
            Text("Sondes & pans extérieurs", fontWeight = FontWeight.SemiBold)
            Text(
                if (rt == null) "Initialisation…"
                else {
                    val walls = remember(version, rt) { rt.config.walls() }
                    val indoor = remember(version, rt) { rt.config.indoorSensors().size }
                    val outdoor = remember(version, rt) { rt.config.outdoorSensors().size }
                    "$indoor intérieure(s) · $outdoor extérieure(s) · ${walls.size}/4 pan(s)"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                "Une sonde extérieure reste visible mais ne peut plus entrer dans le moteur d'inertie intérieur. " +
                    "Chaque pan peut apprendre sa propre signature solaire et reconstruire le passé à la demande.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            OutlinedButton(
                onClick = { open = true },
                enabled = enabled && rt != null && !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Personnaliser sondes et murs") }
            info?.let {
                Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }

    if (open && rt != null) {
        val sensors = remember(version) { db.sensors().filter { it.id >= 0L } }
        val walls = remember(version) { rt.config.walls() }
        AlertDialog(
            onDismissRequest = { if (!busy) open = false },
            title = { Text("Sondes extérieures & pans de mur") },
            text = {
                Column(
                    Modifier.fillMaxWidth().heightIn(max = 650.dp).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Text(
                        "Le choix est explicite : Intérieure alimente le moteur thermique ; Extérieure sert au climat local/façade ; Non définie reste hors calcul.",
                        style = MaterialTheme.typography.bodySmall
                    )
                    sensors.forEach { sensor ->
                        val config = remember(version, sensor.id) { rt.config.sensorConfig(sensor.id) }
                        SensorThermalEditor(
                            sensor = sensor,
                            config = config,
                            walls = walls,
                            enabled = !busy,
                            onSave = { next ->
                                scope.launch {
                                    busy = true
                                    val r = withContext(Dispatchers.IO) { runCatching { rt.config.setSensorConfig(next) } }
                                    busy = false
                                    r.fold(
                                        onSuccess = {
                                            version++
                                            info = "${sensor.name} · configuration enregistrée"
                                            onChanged()
                                        },
                                        onFailure = { info = it.message ?: "Configuration impossible" }
                                    )
                                }
                            }
                        )
                        HorizontalDivider()
                    }

                    Text("Pans extérieurs", fontWeight = FontWeight.Bold)
                    walls.forEach { wall ->
                        val model = remember(version, wall.id) { rt.solar.model(wall.id) }
                        WallThermalEditor(
                            wall = wall,
                            model = model,
                            enabled = !busy,
                            onSave = { next ->
                                scope.launch {
                                    busy = true
                                    val r = withContext(Dispatchers.IO) { runCatching { rt.config.upsertWall(next) } }
                                    busy = false
                                    r.fold(
                                        onSuccess = {
                                            version++
                                            info = "${next.name} · pan enregistré"
                                            onChanged()
                                        },
                                        onFailure = { info = it.message ?: "Pan impossible" }
                                    )
                                }
                            },
                            onDelete = {
                                scope.launch {
                                    busy = true
                                    withContext(Dispatchers.IO) { rt.config.deleteWall(wall.id) }
                                    busy = false
                                    version++
                                    info = "${wall.name} supprimé"
                                    onChanged()
                                }
                            },
                            onTrain = {
                                scope.launch {
                                    busy = true
                                    info = "${wall.name} · apprentissage solaire…"
                                    val r = withContext(Dispatchers.IO) { runCatching { rt.solar.train(reference, wall.id) } }
                                    busy = false
                                    r.fold(
                                        onSuccess = {
                                            version++
                                            info = "${wall.name} · solaire appris · orientation ${orientationLabel(it.orientationDeg)} · RMSE ${"%.2f".format(it.fitRmseC)} °C · confiance ${(it.confidence * 100).toInt()} %"
                                            onChanged()
                                        },
                                        onFailure = { info = it.message ?: "Apprentissage solaire impossible" }
                                    )
                                }
                            },
                            onReconstruct = {
                                scope.launch {
                                    busy = true
                                    info = "${wall.name} · reconstruction historique…"
                                    val r = withContext(Dispatchers.IO) { runCatching { rt.solar.reconstruct(reference, wall.id) } }
                                    busy = false
                                    r.fold(
                                        onSuccess = {
                                            version++
                                            info = "${wall.name} · ${it.written} point(s) reconstruit(s)" +
                                                if (it.borrowedModel) " · modèle extrapolé d'un autre pan" else ""
                                            onChanged()
                                        },
                                        onFailure = { info = it.message ?: "Reconstruction impossible" }
                                    )
                                }
                            }
                        )
                    }
                    if (walls.size < ThermalWallConfigStore.MAX_WALLS) {
                        Button(
                            onClick = {
                                scope.launch {
                                    busy = true
                                    val r = withContext(Dispatchers.IO) {
                                        runCatching { rt.config.createWall(surfaceM2 = 10.0) }
                                    }
                                    busy = false
                                    r.fold(
                                        onSuccess = {
                                            version++
                                            info = "${it.name} ajouté"
                                            onChanged()
                                        },
                                        onFailure = { info = it.message ?: "Ajout impossible" }
                                    )
                                }
                            },
                            enabled = !busy,
                            modifier = Modifier.fillMaxWidth()
                        ) { Text("Ajouter un pan de mur") }
                    }
                }
            },
            confirmButton = {
                Button(onClick = { open = false }, enabled = !busy) { Text("Terminer") }
            },
            dismissButton = {
                if (busy) Text("Calcul en cours…", style = MaterialTheme.typography.labelSmall)
            }
        )
    }
}

@Composable
private fun SensorThermalEditor(
    sensor: Sensor,
    config: SensorThermalConfig,
    walls: List<ThermalWallSegment>,
    enabled: Boolean,
    onSave: (SensorThermalConfig) -> Unit
) {
    var role by remember(config.updatedAt, config.role) { mutableStateOf(config.role) }
    var kind by remember(config.updatedAt, config.outdoorKind) { mutableStateOf(config.outdoorKind) }
    var wallId by remember(config.updatedAt, config.wallId) { mutableStateOf(config.wallId) }
    var orientationText by remember(config.updatedAt, config.orientationDeg) {
        mutableStateOf(config.orientationDeg?.let { "%.0f".format(it) }.orEmpty())
    }
    Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Text(sensor.name, fontWeight = FontWeight.SemiBold)
        Text(sensor.room, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(
                ThermalSensorRole.UNDEFINED to "Non définie",
                ThermalSensorRole.INDOOR to "Intérieure",
                ThermalSensorRole.OUTDOOR to "Extérieure"
            ).forEach { (value, label) ->
                FilterChip(
                    selected = role == value,
                    onClick = {
                        role = value
                        if (value != ThermalSensorRole.OUTDOOR) {
                            wallId = null
                            kind = OutdoorSensorKind.UNSPECIFIED
                            orientationText = ""
                        }
                    },
                    enabled = enabled,
                    label = { Text(label) }
                )
            }
        }
        if (role == ThermalSensorRole.OUTDOOR) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(
                    OutdoorSensorKind.AIR_REFERENCE to "Air extérieur",
                    OutdoorSensorKind.FACADE_MICROCLIMATE to "Façade",
                    OutdoorSensorKind.SURFACE to "Surface"
                ).forEach { (value, label) ->
                    FilterChip(
                        selected = kind == value,
                        onClick = { kind = value },
                        enabled = enabled,
                        label = { Text(label) }
                    )
                }
            }
            OutlinedTextField(
                value = orientationText,
                onValueChange = { orientationText = it.filter { ch -> ch.isDigit() || ch == '.' || ch == ',' || ch == '-' } },
                label = { Text("Orientation sonde (° · optionnel)") },
                supportingText = { Text("0=N · 90=E · 180=S · 270=O") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
                enabled = enabled,
                modifier = Modifier.fillMaxWidth()
            )
            Text("Pan associé", style = MaterialTheme.typography.labelMedium)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = wallId == null, onClick = { wallId = null }, enabled = enabled, label = { Text("Aucun") })
                walls.forEach { wall ->
                    FilterChip(
                        selected = wallId == wall.id,
                        onClick = {
                            wallId = wall.id
                            if (orientationText.isBlank()) wall.orientationDeg?.let { orientationText = "%.0f".format(it) }
                            if (kind == OutdoorSensorKind.UNSPECIFIED) kind = OutdoorSensorKind.FACADE_MICROCLIMATE
                        },
                        enabled = enabled,
                        label = { Text(wall.name) }
                    )
                }
            }
        }
        OutlinedButton(
            onClick = {
                val orientation = orientationText.replace(',', '.').toDoubleOrNull()?.let(::normalizeDegrees)
                onSave(
                    SensorThermalConfig(
                        sensorId = sensor.id,
                        role = role,
                        outdoorKind = if (role == ThermalSensorRole.OUTDOOR) kind else OutdoorSensorKind.UNSPECIFIED,
                        wallId = if (role == ThermalSensorRole.OUTDOOR) wallId else null,
                        orientationDeg = if (role == ThermalSensorRole.OUTDOOR) orientation else null
                    )
                )
            },
            enabled = enabled,
            modifier = Modifier.fillMaxWidth()
        ) { Text("Enregistrer cette sonde") }
    }
}

@Composable
private fun WallThermalEditor(
    wall: ThermalWallSegment,
    model: WallSolarModel?,
    enabled: Boolean,
    onSave: (ThermalWallSegment) -> Unit,
    onDelete: () -> Unit,
    onTrain: () -> Unit,
    onReconstruct: () -> Unit
) {
    var name by remember(wall.updatedAt) { mutableStateOf(wall.name) }
    var surface by remember(wall.updatedAt) { mutableStateOf("%.1f".format(wall.surfaceM2)) }
    var orientation by remember(wall.updatedAt) { mutableStateOf(wall.orientationDeg ?: 180.0) }
    var orientationAuto by remember(wall.updatedAt) { mutableStateOf(wall.orientationDeg == null) }
    var exposure by remember(wall.updatedAt) { mutableStateOf(wall.exposure) }
    var reconstruct by remember(wall.updatedAt) { mutableStateOf(wall.reconstructHistory) }

    Card(shape = RoundedCornerShape(12.dp)) {
        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text("Nom du pan") },
                singleLine = true,
                enabled = enabled,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = surface,
                onValueChange = { surface = it.filter { ch -> ch.isDigit() || ch == '.' || ch == ',' } },
                label = { Text("Surface du pan (m²)") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
                enabled = enabled,
                modifier = Modifier.fillMaxWidth()
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Checkbox(checked = orientationAuto, onCheckedChange = { orientationAuto = it }, enabled = enabled)
                Column {
                    Text("Orientation auto")
                    Text("Décoche pour imposer la boussole", style = MaterialTheme.typography.labelSmall)
                }
            }
            if (!orientationAuto) {
                CompassDial(value = orientation, enabled = enabled, onValueChange = { orientation = it })
                Slider(
                    value = orientation.toFloat(),
                    onValueChange = { orientation = normalizeDegrees(it.toDouble()) },
                    valueRange = 0f..359f,
                    enabled = enabled
                )
                OutlinedTextField(
                    value = "%.0f".format(orientation),
                    onValueChange = { raw -> raw.replace(',', '.').toDoubleOrNull()?.let { orientation = normalizeDegrees(it) } },
                    label = { Text("Orientation numérique") },
                    supportingText = { Text(orientationLabel(orientation)) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    singleLine = true,
                    enabled = enabled,
                    modifier = Modifier.fillMaxWidth()
                )
            }
            Text("Exposition présumée", style = MaterialTheme.typography.labelMedium)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf(
                    WallExposureMode.AUTO to "Auto",
                    WallExposureMode.SUN to "Soleil",
                    WallExposureMode.SHADE to "Ombre",
                    WallExposureMode.UNKNOWN to "Inconnue"
                ).forEach { (value, label) ->
                    FilterChip(selected = exposure == value, onClick = { exposure = value }, enabled = enabled, label = { Text(label) })
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Checkbox(checked = reconstruct, onCheckedChange = { reconstruct = it }, enabled = enabled)
                Column {
                    Text("Reconstruire ce pan dans le passé")
                    Text("Toujours RECONSTRUCTED ; une vraie mesure gagne.", style = MaterialTheme.typography.labelSmall)
                }
            }
            model?.let {
                Text(
                    "Solaire appris · ${orientationLabel(it.orientationDeg)} · τ ${"%.1f".format(it.responseTauHours)} h · RMSE ${"%.2f".format(it.fitRmseC)} °C · confiance ${(it.confidence * 100).toInt()} %",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Button(
                onClick = {
                    onSave(
                        wall.copy(
                            name = name,
                            surfaceM2 = surface.replace(',', '.').toDoubleOrNull() ?: wall.surfaceM2,
                            orientationDeg = if (orientationAuto) null else orientation,
                            exposure = exposure,
                            reconstructHistory = reconstruct
                        )
                    )
                },
                enabled = enabled,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Enregistrer le pan") }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onTrain, enabled = enabled, modifier = Modifier.weight(1f)) {
                    Text("Entraîner solaire")
                }
                OutlinedButton(onClick = onReconstruct, enabled = enabled && reconstruct, modifier = Modifier.weight(1f)) {
                    Text("Reconstruire")
                }
            }
            TextButton(onClick = onDelete, enabled = enabled) { Text("Supprimer ce pan") }
        }
    }
}

@Composable
private fun CompassDial(
    value: Double,
    enabled: Boolean,
    onValueChange: (Double) -> Unit
) {
    val outline = MaterialTheme.colorScheme.outline
    val primary = MaterialTheme.colorScheme.primary
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Boussole · ${orientationLabel(value)}", fontWeight = FontWeight.SemiBold)
        Canvas(
            Modifier
                .size(150.dp)
                .pointerInput(enabled) {
                    if (!enabled) return@pointerInput
                    detectTapGestures { p ->
                        val cx = size.width / 2f
                        val cy = size.height / 2f
                        val dx = p.x - cx
                        val dy = cy - p.y
                        var degrees = Math.toDegrees(atan2(dx.toDouble(), dy.toDouble()))
                        if (degrees < 0.0) degrees += 360.0
                        onValueChange(degrees)
                    }
                }
        ) {
            val center = Offset(size.width / 2f, size.height / 2f)
            val radius = size.minDimension * 0.43f
            drawCircle(outline, radius = radius, center = center, style = Stroke(width = 3f))
            listOf(0.0, 90.0, 180.0, 270.0).forEach { deg ->
                val rad = Math.toRadians(deg)
                val start = Offset(
                    center.x + (radius * 0.84f * sin(rad)).toFloat(),
                    center.y - (radius * 0.84f * cos(rad)).toFloat()
                )
                val end = Offset(
                    center.x + (radius * sin(rad)).toFloat(),
                    center.y - (radius * cos(rad)).toFloat()
                )
                drawLine(outline, start, end, strokeWidth = 3f)
            }
            val rad = Math.toRadians(normalizeDegrees(value))
            val needle = Offset(
                center.x + (radius * 0.78f * sin(rad)).toFloat(),
                center.y - (radius * 0.78f * cos(rad)).toFloat()
            )
            drawLine(primary, center, needle, strokeWidth = 7f)
            drawCircle(primary, radius = 7f, center = center)
        }
        Text("0° N · 90° E · 180° S · 270° O", style = MaterialTheme.typography.labelSmall)
    }
}
