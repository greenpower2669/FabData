package com.fabdata.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

@Composable
fun ThermalReferenceCard(
    db: FabDataDb,
    lyonLab: LyonLabStore,
    credentials: MeteoFranceCredentialStore,
    dataVersion: Int,
    onDataChanged: () -> Unit
) {
    val context = LocalContext.current
    val prefs = remember { WeatherReferencePrefs(context) }
    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val profileStore = remember { ThermalProfileStore(context) }
    var profile by remember { mutableStateOf(profileStore.load()) }
    var forecastMode by remember { mutableStateOf(profileStore.forecastMode()) }
    val scope = rememberCoroutineScope()

    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
    val reference = WeatherReferenceCatalog.byKey(selectedKey)
    var menuOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<ThermalStatus?>(null) }
    var info by remember { mutableStateOf("Référence prête à être chargée") }
    var weatherHistoryDialog by remember { mutableStateOf(false) }
    var weatherHistoryDays by remember { mutableIntStateOf(30) }
    var historyDialog by remember { mutableStateOf(false) }
    var historyDays by remember { mutableIntStateOf(30) }
    var suppressNextAuto by remember { mutableStateOf(false) }
    var selectedSensorId by remember { mutableStateOf<Long?>(null) }
    var profileDialog by remember { mutableStateOf(false) }
    var profileDialog by remember { mutableStateOf(false) }

    suspend fun refresh(allHistory: Boolean, triggerChartReload: Boolean) {
        busy = true
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()
                    ?: error("Aucune donnée intérieure")
                val from = if (allHistory) bounds.first - 90L * 24L * 60L * 60L * 1000L else bounds.first - 18L * 60L * 60L * 1000L
                val to = maxOf(bounds.last, System.currentTimeMillis() + (forecastMode.maxHours + 2L) * 60L * 60L * 1000L)
                val sync = if (allHistory) manager.refreshSelected(reference, from, to)
                    else manager.ensureLocalCache(reference, from, to)
                val thermalStatus = engine.status(reference, selectedSensorId, profile)
                val activeSensor = selectedSensorId ?: thermalStatus.preferred?.sensor?.id
                if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    // Si un historique calculé existait déjà, une nouvelle mesure réelle
                    // l'enrichit automatiquement sans jamais modifier les points MEASURED.
                    engine.refreshExistingReconstructions(reference, profile, activeSensor)
                }
                val forecast = if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    engine.refreshForecasts(reference, activeSensor, profile, forecastMode)
                } else ThermalWriteSummary(0, 0, 0)
                Triple(sync, thermalStatus, forecast)
            }
        }
        result.fold(
            onSuccess = { (sync, thermalStatus, forecast) ->
                status = thermalStatus
                if (selectedSensorId == null || thermalStatus.sensors.none { it.sensor.id == selectedSensorId }) {
                    selectedSensorId = thermalStatus.preferred?.sensor?.id
                }
                val horizon = forecast.forecastHorizonHours.takeIf { it > 0 }?.let { "H+$it" } ?: "—"
                val sigma = forecast.maxForecastSigma.takeIf { it > 0.0 }?.let { " · σ max ${fmt(it)} °C" }.orEmpty()
                val analogues = forecast.analogCount.takeIf { it > 0 }?.let { " · $it analogues" }.orEmpty()
                info = "${sync.label} · ${sync.measured} réel(s) · ${sync.reconstructed} reconstruit(s) · prévision $horizon ${forecast.forecast} point(s)$sigma$analogues"
                if (triggerChartReload) {
                    suppressNextAuto = true
                    onDataChanged()
                }
            },
            onFailure = { error ->
                status = runCatching { engine.status(reference, selectedSensorId, profile) }.getOrNull()
                info = error.message ?: "Référence météo indisponible"
            }
        )
        busy = false
    }

    // Toute nouvelle vraie donnée invalide d'abord l'ancien futur, puis ce cycle
    // recalcule historique calculé existant + nouvelle prévision depuis l'état réel.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        if (suppressNextAuto) {
            suppressNextAuto = false
        } else {
            refresh(allHistory = false, triggerChartReload = true)
        }
    }

    Card(shape = RoundedCornerShape(20.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text("Référence météo & moteur thermique", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "Lyon reste la référence par défaut. Une seule station charge ses séries à la fois.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("Ville / station", style = MaterialTheme.typography.labelMedium)
                    Text(reference.label, fontWeight = FontWeight.SemiBold)
                    Text("ID ${reference.stationId}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Column {
                    OutlinedButton(onClick = { menuOpen = true }) { Text("Changer") }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        WeatherReferenceCatalog.stations.forEach { station ->
                            DropdownMenuItem(
                                text = { Text(station.label) },
                                onClick = {
                                    prefs.select(station.key)
                                    selectedKey = station.key
                                    menuOpen = false
                                }
                            )
                        }
                    }
                }
            }

            Text(info, style = MaterialTheme.typography.bodySmall)

            val s = status
            if (s != null) {
                val preferred = s.preferred
                if (preferred != null) {
                    val selectable = s.sensors.filter { it.realDays >= 16 }.ifEmpty { s.sensors }
                    val index = selectable.indexOfFirst { it.sensor.id == preferred.sensor.id }.coerceAtLeast(0)
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedButton(
                            onClick = {
                                if (selectable.isNotEmpty()) {
                                    val next = (index - 1 + selectable.size) % selectable.size
                                    selectedSensorId = selectable[next].sensor.id
                                }
                            },
                            enabled = !busy && selectable.size > 1
                        ) { Text("◀") }
                        Column(Modifier.weight(1f)) {
                            Text("Sonde du modèle", style = MaterialTheme.typography.labelMedium)
                            Text(
                                "${preferred.sensor.room} · ${preferred.realDays} jour(s) réels",
                                fontWeight = FontWeight.SemiBold
                            )
                            Text(
                                "Conservé ${(preferred.retainedRatio * 100).toInt()} % · ignoré ${preferred.ignoredHours} h",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        OutlinedButton(
                            onClick = {
                                if (selectable.isNotEmpty()) {
                                    val next = (index + 1) % selectable.size
                                    selectedSensorId = selectable[next].sensor.id
                                }
                            },
                            enabled = !busy && selectable.size > 1
                        ) { Text("▶") }
                    }
                }
                val model = preferred?.model
                if (model != null) {
                    val confidenceLabel = when {
                        model.confidence >= 0.75 -> "forte"
                        model.confidence >= 0.50 -> "moyenne"
                        else -> "faible"
                    }
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        AssistChip(onClick = {}, label = { Text("MAE ${fmt(model.metrics.mae)} °C") })
                        AssistChip(onClick = {}, label = { Text("RMSE ${fmt(model.metrics.rmse)} °C") })
                        AssistChip(onClick = {}, label = { Text("Dérive libre ${fmt(model.longHorizonRmse)} °C") })
                        AssistChip(onClick = {}, label = { Text("Biais ${fmt(model.metrics.bias)} °C") })
                        AssistChip(onClick = {}, label = { Text("Retard ${model.lagHours} h") })
                        AssistChip(onClick = {}, label = { Text("τ ${fmt(model.tauHours)} h") })
                        AssistChip(onClick = {}, label = { Text("Confiance $confidenceLabel ${(model.confidence * 100).toInt()} %") })
                    }
                }
                Text(s.message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }

            Card(shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Profil thermique du bâtiment", fontWeight = FontWeight.SemiBold)
                    Text(profile.summary(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(
                        "L'état initial Auto part de la météo autour de J-30 puis applique la tendance chaude/froide. Les mesures réelles restent toujours prioritaires.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    OutlinedButton(onClick = { profileDialog = true }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                        Text("Ajuster le profil")
                    }
                }
            }

            Card(shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("Prévision adaptative", fontWeight = FontWeight.SemiBold)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        ForecastHorizonMode.entries.forEach { mode ->
                            FilterChip(
                                selected = forecastMode == mode,
                                onClick = {
                                    forecastMode = mode
                                    profileStore.saveForecastMode(mode)
                                },
                                label = { Text(mode.label) }
                            )
                        }
                    }
                    Text(
                        "Auto peut prolonger jusqu'à H+24. Les points d'incertitude s'espacent avec l'horizon et la prévision s'arrête après H+3 si σ dépasse 1,5 °C. Une nouvelle mesure réelle efface immédiatement l'ancien futur puis le recalcule.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            OutlinedButton(
                onClick = { weatherHistoryDialog = true },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Étendre historique météo") }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { scope.launch { refresh(allHistory = true, triggerChartReload = true) } },
                    enabled = !busy,
                    modifier = Modifier.weight(1f)
                ) { Text(if (busy) "Chargement…" else "Actualiser référence") }
                Button(
                    onClick = { historyDialog = true },
                    enabled = !busy && status?.canReconstruct == true,
                    modifier = Modifier.weight(1f)
                ) { Text("Estimer historique") }
            }

            Text(
                "Garde-fou : moins de 16 jours réels = aucune reconstruction historique. Au-delà, toutes les données réelles propres disponibles sont utilisées.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }

    if (profileDialog) {
        ThermalProfileDialog(
            profile = profile,
            onDismiss = { profileDialog = false },
            onSave = { updated ->
                profile = updated.normalized()
                profileStore.save(profile)
                profileDialog = false
            },
            onReset = {
                profile = profileStore.reset()
                profileDialog = false
            }
        )
    }

    if (weatherHistoryDialog) {
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

    if (historyDialog) {
        AlertDialog(
            onDismissRequest = { historyDialog = false },
            title = { Text("Estimer l'historique thermique ?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Des données antérieures semblent manquer. FabData peut estimer l'historique thermique du bâtiment avec le modèle validé.")
                    Text("Choisis une limite maximale :")
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(30, 60, 90).forEach { d ->
                            AssistChip(
                                onClick = { historyDays = d },
                                label = { Text("$d jours") }
                            )
                        }
                    }
                    Text("Sélection : $historyDays jours · maximum 3 mois.", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                Button(onClick = {
                    historyDialog = false
                    scope.launch {
                        busy = true
                        val result = withContext(Dispatchers.IO) {
                            runCatching {
                                // Ordre strict v0.10.3 : la référence visible/RC est préparée AVANT tout.
                                val prepared = manager.prepareHistory(reference, historyDays)
                                if (!prepared.coverage.ready) {
                                    error("${reference.city} incomplet : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")
                                }
                                val checked = engine.status(reference, selectedSensorId, profile)
                                if (!checked.canReconstruct) error(checked.message)
                                engine.reconstructHistory(reference, historyDays, selectedSensorId ?: checked.preferred?.sensor?.id, profile)
                            }
                        }
                        busy = false
                        result.fold(
                            onSuccess = {
                                // v0.10.2 : préserver le diagnostic de reconstruction pendant
                                // le rechargement du graphique au lieu de le remplacer aussitôt.
                                val detail = it.diagnostic?.let { d -> " · $d" }.orEmpty()
                                info = "Historique : ${it.reconstructed} point(s) · ${it.raccords} raccord(s) · dérive max ${fmt(it.maxRaccordDrift)} °C · ${it.skippedSensors} refus$detail"
                                suppressNextAuto = true
                                onDataChanged()
                            },
                            onFailure = { info = it.message ?: "Reconstruction refusée" }
                        )
                    }
                }) { Text("Estimer") }
            },
            dismissButton = { TextButton(onClick = { historyDialog = false }) { Text("Annuler") } }
        )
    }
}

@Composable
private fun ThermalProfileDialog(
    profile: ThermalBuildingProfile,
    onDismiss: () -> Unit,
    onSave: (ThermalBuildingProfile) -> Unit,
    onReset: () -> Unit
) {
    var surface by remember(profile) { mutableStateOf(profile.surfaceM2.toString()) }
    var floor by remember(profile) { mutableStateOf(profile.floor.toString()) }
    var insulation by remember(profile) { mutableStateOf(profile.insulation) }
    var inertia by remember(profile) { mutableStateOf(profile.inertia) }
    var exposure by remember(profile) { mutableStateOf(profile.exposure) }
    var initialOverride by remember(profile) { mutableStateOf(profile.initialMassOverrideC?.toString().orEmpty()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Profil thermique du bâtiment") },
        text = {
            Column(
                Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                OutlinedTextField(
                    value = surface,
                    onValueChange = { surface = it },
                    label = { Text("Surface (m²)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = floor,
                    onValueChange = { floor = it },
                    label = { Text("Étage") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.fillMaxWidth()
                )

                Text("Isolation thermique", style = MaterialTheme.typography.labelMedium)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    listOf("A", "B", "C", "D", "E", "F", "G").forEach { rating ->
                        FilterChip(
                            selected = insulation == rating,
                            onClick = { insulation = rating },
                            label = { Text(rating) }
                        )
                    }
                }

                Text("Inertie du bâtiment", style = MaterialTheme.typography.labelMedium)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    ThermalInertia.entries.forEach { value ->
                        FilterChip(
                            selected = inertia == value,
                            onClick = { inertia = value },
                            label = { Text(value.label) }
                        )
                    }
                }

                Text("Exposition / accumulation solaire", style = MaterialTheme.typography.labelMedium)
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    ThermalExposure.entries.forEach { value ->
                        FilterChip(
                            selected = exposure == value,
                            onClick = { exposure = value },
                            label = { Text(value.label) }
                        )
                    }
                }

                OutlinedTextField(
                    value = initialOverride,
                    onValueChange = { initialOverride = it },
                    label = { Text("État thermique initial °C (vide = Auto)") },
                    supportingText = { Text("Auto : météo J-30 + tendance saisonnière chaude/froide") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth()
                )
                Text(
                    "Valeurs par défaut : 70 m² · 4e étage · isolation D · inertie moyenne · exposition moyenne.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            Button(onClick = {
                val s = surface.replace(',', '.').toDoubleOrNull() ?: profile.surfaceM2
                val f = floor.toIntOrNull() ?: profile.floor
                val initial = initialOverride.trim().replace(',', '.').toDoubleOrNull()
                onSave(
                    ThermalBuildingProfile(
                        surfaceM2 = s,
                        floor = f,
                        insulation = insulation,
                        inertia = inertia,
                        exposure = exposure,
                        initialMassOverrideC = initial
                    )
                )
            }) { Text("Enregistrer") }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = onReset) { Text("Défaut") }
                TextButton(onClick = onDismiss) { Text("Annuler") }
            }
        }
    )
}

private fun fmt(v: Double): String = String.format(Locale.FRANCE, "%.2f", v)
