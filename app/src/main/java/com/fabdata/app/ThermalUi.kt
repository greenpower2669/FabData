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

private data class ThermalHistoryChoice(val label: String, val days: Int)

private val THERMAL_HISTORY_CHOICES = listOf(
    ThermalHistoryChoice("30 j", 30),
    ThermalHistoryChoice("90 j", 90),
    ThermalHistoryChoice("6 mois", 183),
    ThermalHistoryChoice("12 mois", 366),
    ThermalHistoryChoice("24 mois", 732),
    ThermalHistoryChoice("36 mois", 1098)
)

private fun thermalHistoryLabel(days: Int): String =
    THERMAL_HISTORY_CHOICES.firstOrNull { it.days == days }?.label ?: "$days jours"

private data class RationalizeResult(
    val removed: Int,
    val reconstructed: Int,
    val forecasts: Int,
    val skipped: Int,
    val alreadyCoherent: Boolean,
    val reason: String
)

@Composable
fun ThermalReferenceCard(
    db: FabDataDb,
    lyonLab: LyonLabStore,
    credentials: MeteoFranceCredentialStore,
    dataVersion: Int,
    onDataChanged: () -> Unit,
    onBusyChanged: (Boolean) -> Unit = {},
    onProgressChanged: (String?) -> Unit = {}
) {
    val context = LocalContext.current
    val prefs = remember { WeatherReferencePrefs(context) }
    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val coherenceStore = remember { ThermalCoherenceStore(db) }
    val profileStore = remember { ThermalProfileStore(context) }
    val modelSensorPrefs = remember {
        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)
    }
    var profile by remember { mutableStateOf(profileStore.load()) }
    var forecastMode by remember { mutableStateOf(profileStore.forecastMode()) }
    val scope = rememberCoroutineScope()

    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
    val reference = remember(selectedKey) { prefs.selectedReference() }
    var menuOpen by remember { mutableStateOf(false) }
    var stationDiscoveryOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(busy) { onBusyChanged(busy) }
    var status by remember { mutableStateOf<ThermalStatus?>(null) }
    var info by remember { mutableStateOf("Référence prête à être chargée") }
    LaunchedEffect(busy, info) { onProgressChanged(if (busy) info else null) }
    var weatherHistoryDialog by remember { mutableStateOf(false) }
    var weatherHistoryDays by remember { mutableIntStateOf(30) }
    var historyDialog by remember { mutableStateOf(false) }
    var historyDays by remember { mutableIntStateOf(30) }
    var suppressNextAuto by remember { mutableStateOf(false) }
    var selectedSensorId by remember {
        mutableStateOf(modelSensorPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L })
    }
    var profileDialog by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
    var coherenceBaselineReady by remember { mutableStateOf(false) }
    var observedReferenceKey by remember { mutableStateOf(selectedKey) }
    var observedDataVersion by remember { mutableIntStateOf(dataVersion) }

    suspend fun refresh(
        allHistory: Boolean,
        triggerChartReload: Boolean,
        rebuildHistoryFromNewMeasured: Boolean = false
    ) {
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
                if (rebuildHistoryFromNewMeasured && thermalStatus.sensors.any { it.model?.acceptableForHistory == true }) {
                    // v0.12.1 : recalcul du passé uniquement après une vraie variation
                    // du jeu de mesures MEASURED, jamais sur un simple changement d'UI.
                    engine.refreshExistingReconstructions(reference, profile, activeSensor)
                }
                val forecast = if (thermalStatus.sensors.any { it.model?.acceptableForForecast == true }) {
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
                    selectedSensorId?.let { modelSensorPrefs.edit().putLong("selected_sensor_id", it).apply() }
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

    suspend fun rationalizeCurves(
        reason: String,
        targetProfile: ThermalBuildingProfile = profile,
        manual: Boolean = false
    ) {
        if (busy) return
        busy = true
        info = "Rationalisation · analyse des dépendances…"
        val progressCallback: (ThermalProgress) -> Unit = { p ->
            scope.launch {
                info = if (p.total > 0) {
                    val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                    "Rationalisation · ${p.stage} · $percent %"
                } else "Rationalisation · ${p.stage}"
            }
        }
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val measuredBounds = db.physicalMeasuredBounds() ?: db.physicalSensorBounds()
                    ?: error("Aucune donnée intérieure")
                val hourMs = 60L * 60L * 1000L
                val dayMs = 24L * hourMs

                // En automatique on remet d'abord la petite fenêtre météo courante à jour.
                // En manuel, on examine strictement l'état présent : une base déjà cohérente
                // ne doit pas être rendue artificiellement périmée par un téléchargement.
                if (!manual) {
                    manager.ensureLocalCache(
                        reference,
                        measuredBounds.first - 18L * hourMs,
                        maxOf(measuredBounds.last, System.currentTimeMillis() + (forecastMode.maxHours + 2L) * hourMs)
                    )
                }

                fun reconStates() = coherenceStore.calculatedSensorIds().mapNotNull { id ->
                    coherenceStore.inspect(reference, targetProfile, id, PointSource.RECONSTRUCTED)
                }
                fun forecastStates() = coherenceStore.calculatedSensorIds().mapNotNull { id ->
                    coherenceStore.inspect(reference, targetProfile, id, PointSource.FORECAST, forecastMode)
                }

                var staleRecon = reconStates().filterNot { it.current }
                var staleForecast = forecastStates().filterNot { it.current }

                // Si une reconstruction ancienne est réellement périmée, préparer sa profondeur
                // AVANT toute suppression. On garde ainsi les vraies mesures et les sources sûres
                // tant que les dépendances nécessaires au recalcul ne sont pas prêtes.
                val maxHistoryDays = staleRecon.mapNotNull { state ->
                    val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId) ?: return@mapNotNull null
                    if (state.bounds.first >= firstReal) 0
                    else (((firstReal - state.bounds.first) + dayMs - 1L) / dayMs).toInt().coerceIn(1, 1098)
                }.maxOrNull() ?: 0
                if (maxHistoryDays > 0) {
                    info = "Rationalisation · préparation météo ${thermalHistoryLabel(maxHistoryDays)}…"
                    val prepared = manager.prepareHistory(reference, maxHistoryDays)
                    if (!prepared.coverage.ready) {
                        error("Référence ${reference.city} incomplète : aucune courbe existante n'a été supprimée")
                    }
                    // La préparation peut elle-même avoir amélioré la référence : recalculer les hashes.
                    staleRecon = reconStates().filterNot { it.current }
                    staleForecast = forecastStates().filterNot { it.current }
                }

                if (staleRecon.isEmpty() && staleForecast.isEmpty()) {
                    return@runCatching RationalizeResult(0, 0, 0, 0, true, reason)
                }

                var removed = 0
                var reconstructed = 0
                var forecasts = 0
                var skipped = 0

                staleRecon.forEach { state ->
                    val previousBounds = state.bounds
                    removed += PointSourceStore.deleteBySource(db, state.sensorId, PointSource.RECONSTRUCTED)
                    val rebuilt = engine.rebuildCalculatedExtent(
                        reference, targetProfile, state.sensorId, previousBounds, progressCallback
                    )
                    reconstructed += rebuilt.reconstructed
                    skipped += rebuilt.skippedSensors
                }

                // Une reconstruction n'entre jamais dans l'apprentissage (MEASURED only), donc
                // le hash du forecast ne dépend pas des points reconstruits. On peut traiter ensuite.
                staleForecast.forEach { state ->
                    removed += PointSourceStore.deleteBySource(db, state.sensorId, PointSource.FORECAST)
                    val rebuilt = engine.refreshForecasts(reference, state.sensorId, targetProfile, forecastMode)
                    forecasts += rebuilt.forecast
                    skipped += rebuilt.skippedSensors
                }

                RationalizeResult(removed, reconstructed, forecasts, skipped, false, reason)
            }
        }
        busy = false
        result.fold(
            onSuccess = { r ->
                info = if (r.alreadyCoherent) {
                    "Courbes déjà cohérentes · aucune donnée calculée supprimée"
                } else {
                    "Rationalisation terminée · ${r.removed} périmée(s) retirée(s) · ${r.reconstructed} historique(s) écrit(s) · ${r.forecasts} prévision(s) · ${r.skipped} refus"
                }
                suppressNextAuto = true
                onDataChanged()
            },
            onFailure = { error ->
                info = error.message ?: "Rationalisation impossible"
            }
        )
    }

    // v0.16 : le premier affichage ne détruit jamais une ancienne sauvegarde inconnue.
    // Après cette baseline, mesure/référence changée = chaîne aval rationalisée.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        if (busy) return@LaunchedEffect
        val currentMeasuredRevision = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val measuredChanged = measuredRevision != null && currentMeasuredRevision != measuredRevision
        val referenceChanged = coherenceBaselineReady && selectedKey != observedReferenceKey
        val dataChanged = coherenceBaselineReady && dataVersion != observedDataVersion
        measuredRevision = currentMeasuredRevision
        observedReferenceKey = selectedKey
        observedDataVersion = dataVersion

        if (!coherenceBaselineReady) {
            coherenceBaselineReady = true
            refresh(allHistory = false, triggerChartReload = true)
        } else if (suppressNextAuto) {
            suppressNextAuto = false
        } else {
            when {
                referenceChanged -> rationalizeCurves("Référence météo modifiée", profile, manual = false)
                measuredChanged -> {
                    // Le coordinateur global, toujours composé, traite la chaîne lourde.
                    // Cette carte ne lance pas un second recalcul concurrent.
                    info = "Nouvelle mesure réelle détectée · synchronisation globale en cours…"
                }
                dataChanged -> {
                    status = withContext(Dispatchers.IO) { runCatching { engine.status(reference, selectedSensorId, profile) }.getOrNull() }
                }
                else -> refresh(allHistory = false, triggerChartReload = true)
            }
        }
    }

    Card(shape = RoundedCornerShape(20.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text("Référence météo & moteur thermique", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "Lyon reste le secours par défaut. Auto protection peut choisir la station historiquement la plus chaude du secteur ; une seule station charge ses séries à la fois.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("Ville / station", style = MaterialTheme.typography.labelMedium)
                    Text(reference.label, fontWeight = FontWeight.SemiBold)
                    Text("ID ${reference.stationId} · ${if (prefs.autoProtection()) "★ Auto protection" else "choix manuel"}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Column {
                    OutlinedButton(onClick = { menuOpen = true }) { Text("Changer") }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        WeatherReferenceCatalog.stations.forEach { station ->
                            DropdownMenuItem(
                                text = { Text(station.label) },
                                onClick = {
                                    prefs.setAutoProtection(false)
                                    prefs.select(station.key)
                                    selectedKey = station.key
                                    menuOpen = false
                                }
                            )
                        }
                    }
                }
            }

            OutlinedButton(
                onClick = { stationDiscoveryOpen = true },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Sondes proches · Auto protection") }

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
                                    modelSensorPrefs.edit().putLong("selected_sensor_id", selectable[next].sensor.id).apply()
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
                                    modelSensorPrefs.edit().putLong("selected_sensor_id", selectable[next].sensor.id).apply()
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

            Button(
                onClick = { scope.launch { rationalizeCurves("Rationalisation manuelle", profile, manual = true) } },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Rationaliser les courbes") }
            Text(
                "Vérifie les empreintes des calculs, conserve le réel et les résultats encore cohérents, puis ne reconstruit que ce qui est périmé ou incertain.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

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
            ) { Text("Étendre historique météo + bâtiment") }

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
                "Garde-fou : apprentissage uniquement sur MEASURED propres. Clim probable, fenêtre, saut brutal ou donnée douteuse restent visibles mais sont exclues de l’apprentissage. Météo + inertie sont obligatoires pour prolonger le passé.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }

    if (stationDiscoveryOpen) {
        StationDiscoveryDialog(
            currentReference = reference,
            credentials = credentials,
            onDismiss = { stationDiscoveryOpen = false },
            onSelect = { station, auto ->
                prefs.setAutoProtection(auto)
                prefs.select(station)
                selectedKey = station.key
                stationDiscoveryOpen = false
            }
        )
    }

    if (profileDialog) {
        ThermalProfileDialog(
            profile = profile,
            onDismiss = { profileDialog = false },
            onSave = { updated ->
                val next = updated.normalized()
                val changed = next != profile
                profile = next
                profileStore.save(next)
                profileDialog = false
                if (changed) {
                    suppressNextAuto = true
                    scope.launch { rationalizeCurves("Profil bâtiment modifié", next, manual = false) }
                }
            },
            onReset = {
                val next = profileStore.reset()
                val changed = next != profile
                profile = next
                profileDialog = false
                if (changed) {
                    suppressNextAuto = true
                    scope.launch { rationalizeCurves("Profil bâtiment réinitialisé", next, manual = false) }
                }
            }
        )
    }

    if (weatherHistoryDialog) {
        AlertDialog(
            onDismissRequest = { weatherHistoryDialog = false },
            title = { Text("Étendre l’historique complet ?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("FabData prépare automatiquement les deux petits loups : météo extérieure + inertie bâtiment, puis reconstruit l’air intérieur sur la même profondeur. Pas de courbe historique intérieure sans inertie.")
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        THERMAL_HISTORY_CHOICES.forEach { choice ->
                            FilterChip(
                                selected = weatherHistoryDays == choice.days,
                                onClick = { weatherHistoryDays = choice.days },
                                label = { Text(choice.label) }
                            )
                        }
                    }
                    Text("Sélection : ${thermalHistoryLabel(weatherHistoryDays)} avant la première vraie mesure intérieure.", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                Button(onClick = {
                    weatherHistoryDialog = false
                    scope.launch {
                        busy = true
                        info = "Historique météo · préparation ${thermalHistoryLabel(weatherHistoryDays)}…"
                        val result = withContext(Dispatchers.IO) {
                            runCatching {
                                val prepared = manager.prepareHistory(reference, weatherHistoryDays)
                                if (!prepared.coverage.ready) {
                                    error("${reference.city} incomplet : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")
                                }
                                val checked = engine.status(reference, selectedSensorId, profile)
                                if (!checked.canReconstruct) error(checked.message)
                                val activeId = selectedSensorId ?: checked.preferred?.sensor?.id
                                val activeModel = checked.preferred?.model?.takeIf { it.sensorId == activeId }
                                val summary = engine.reconstructHistory(
                                    reference = reference,
                                    requestedDays = weatherHistoryDays,
                                    sensorId = activeId,
                                    profile = profile,
                                    precalibratedModel = activeModel
                                ) { p ->
                                    scope.launch {
                                        info = if (p.total > 0) {
                                            val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                                            "${p.stage} · $percent % · ${p.changed} point(s) écrit(s)"
                                        } else p.stage
                                        if (p.total > 0 && p.processed > 0) {
                                            suppressNextAuto = true
                                            onDataChanged()
                                        }
                                    }
                                }
                                prepared to summary
                            }
                        }
                        busy = false
                        result.fold(
                            onSuccess = { (prepared, summary) ->
                                val c = prepared.coverage
                                val detail = summary.diagnostic?.let { d -> " · $d" }.orEmpty()
                                info = "Deux petits loups prêts · météo ${prepared.days} j ${(c.coverage * 100).toInt()} % · bâtiment ${summary.reconstructed} point(s) · ${summary.raccords} raccord(s)$detail"
                                suppressNextAuto = true
                                onDataChanged()
                            },
                            onFailure = { info = it.message ?: "Extension météo + bâtiment impossible" }
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
                    Text("FabData prolonge ensemble la météo, l’état inertiel du bâtiment puis l’air intérieur. Les paramètres sont appris uniquement sur les mesures réelles propres.")
                    Text("Choisis une limite maximale :")
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        THERMAL_HISTORY_CHOICES.forEach { choice ->
                            FilterChip(
                                selected = historyDays == choice.days,
                                onClick = { historyDays = choice.days },
                                label = { Text(choice.label) }
                            )
                        }
                    }
                    Text("Sélection : ${thermalHistoryLabel(historyDays)} · maximum 36 mois.", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                Button(onClick = {
                    historyDialog = false
                    scope.launch {
                        busy = true
                        info = "Reconstruction · préparation météo…"
                        val result = withContext(Dispatchers.IO) {
                            runCatching {
                                // Ordre strict v0.10.3 : la référence visible/RC est préparée AVANT tout.
                                val prepared = manager.prepareHistory(reference, historyDays)
                                if (!prepared.coverage.ready) {
                                    error("${reference.city} incomplet : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")
                                }
                                val checked = engine.status(reference, selectedSensorId, profile)
                                if (!checked.canReconstruct) error(checked.message)
                                val activeId = selectedSensorId ?: checked.preferred?.sensor?.id
                                val activeModel = checked.preferred?.model?.takeIf { it.sensorId == activeId }
                                engine.reconstructHistory(
                                    reference = reference,
                                    requestedDays = historyDays,
                                    sensorId = activeId,
                                    profile = profile,
                                    precalibratedModel = activeModel
                                ) { p ->
                                    scope.launch {
                                        info = if (p.total > 0) {
                                            val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                                            "${p.stage} · $percent % · ${p.changed} point(s) écrit(s)"
                                        } else p.stage
                                        // Le callback arrive après un commit SQLite de 256 points :
                                        // la courbe peut donc montrer la reconstruction sans attendre la fin.
                                        if (p.total > 0 && p.processed > 0) {
                                            suppressNextAuto = true
                                            onDataChanged()
                                        }
                                    }
                                }
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
