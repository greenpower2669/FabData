package com.fabdata.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
    val scope = rememberCoroutineScope()

    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
    val reference = WeatherReferenceCatalog.byKey(selectedKey)
    var menuOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<ThermalStatus?>(null) }
    var info by remember { mutableStateOf("Référence prête à être chargée") }
    var historyDialog by remember { mutableStateOf(false) }
    var historyDays by remember { mutableIntStateOf(30) }
    var suppressNextAuto by remember { mutableStateOf(false) }
    var selectedSensorId by remember { mutableStateOf<Long?>(null) }

    suspend fun refresh(allHistory: Boolean, triggerChartReload: Boolean) {
        busy = true
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()
                    ?: error("Aucune donnée intérieure")
                val from = if (allHistory) bounds.first - 90L * 24L * 60L * 60L * 1000L else bounds.first - 18L * 60L * 60L * 1000L
                val to = maxOf(bounds.last, System.currentTimeMillis() + 7L * 60L * 60L * 1000L)
                val sync = if (allHistory) manager.refreshSelected(reference, from, to)
                    else manager.ensureLocalCache(reference, from, to)
                val thermalStatus = engine.status(reference, selectedSensorId)
                val forecast = if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    engine.refreshForecasts(reference, selectedSensorId ?: thermalStatus.preferred?.sensor?.id)
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
                info = "${sync.label} · ${sync.measured} réel(s) · ${sync.reconstructed} reconstruit(s) · H+6 ${forecast.forecast} point(s)"
                if (triggerChartReload && forecast.forecast > 0) {
                    suppressNextAuto = true
                    onDataChanged()
                }
            },
            onFailure = { error ->
                status = runCatching { engine.status(reference, selectedSensorId) }.getOrNull()
                info = error.message ?: "Référence météo indisponible"
            }
        )
        busy = false
    }

    // Prévision H+6 automatique après changement de données/référence.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId) {
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
                        AssistChip(onClick = {}, label = { Text("Biais ${fmt(model.metrics.bias)} °C") })
                        AssistChip(onClick = {}, label = { Text("Retard ${model.lagHours} h") })
                        AssistChip(onClick = {}, label = { Text("τ ${fmt(model.tauHours)} h") })
                        AssistChip(onClick = {}, label = { Text("Confiance $confidenceLabel ${(model.confidence * 100).toInt()} %") })
                    }
                }
                Text(s.message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }

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
                                // Ordre strict : construire d'abord la référence extérieure complète,
                                // puis seulement lancer le modèle intérieur dans le sens du temps.
                                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()
                                    ?: error("Aucune donnée intérieure")
                                val from = bounds.first - historyDays.toLong() * 24L * 60L * 60L * 1000L - 18L * 60L * 60L * 1000L
                                val to = maxOf(bounds.last, System.currentTimeMillis() + 7L * 60L * 60L * 1000L)
                                manager.refreshSelected(reference, from, to)
                                val checked = engine.status(reference, selectedSensorId)
                                if (!checked.canReconstruct) error(checked.message)
                                engine.reconstructHistory(reference, historyDays, selectedSensorId ?: checked.preferred?.sensor?.id)
                            }
                        }
                        busy = false
                        result.fold(
                            onSuccess = {
                                info = "Historique : ${it.reconstructed} point(s) · ${it.raccords} raccord(s) · dérive max ${fmt(it.maxRaccordDrift)} °C · ${it.skippedSensors} refus"
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

private fun fmt(v: Double): String = String.format(Locale.FRANCE, "%.2f", v)
