package com.fabdata.app

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.ui.graphics.graphicsLayer
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
    ThermalHistoryChoice("36 mois", 1098),
    ThermalHistoryChoice("48 mois", 1464)
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

/**
 * Runtime thermique construit hors du thread UI.
 *
 * La carte thermique vit dans un LazyColumn : elle n'est composée qu'au moment où
 * l'utilisateur descend dessus. Avant v0.19.3, cette première composition construisait
 * plusieurs objets qui ouvrent/initialisent SQLite dans leurs constructeurs. Sur une base
 * réelle occupée par un recalcul/sync, le thread UI pouvait attendre le verrou SQLite et
 * Android proposait de fermer l'application (ANR).
 */
private data class ThermalUiRuntime(
    val manager: WeatherReferenceManager,
    val engine: ThermalEngine,
    val coherenceStore: ThermalCoherenceStore,
    val inertiaHistoryStore: ThermalInertiaHistoryStore,
    val inertiaHistoryProjector: ThermalInertiaHistoryProjector
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
    val profileStore = remember { ThermalProfileStore(context) }
    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }
    val trainedModelStore = remember { ThermalTrainedModelStore(context) }
    val modelSensorPrefs = remember {
        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)
    }
    var profile by remember { mutableStateOf(profileStore.load()) }
    var forecastMode by remember { mutableStateOf(profileStore.forecastMode()) }
    val scope = rememberCoroutineScope()

    // IMPORTANT v0.19.3 : aucun constructeur DB-bound n'est exécuté pendant la
    // composition de cette carte LazyColumn. Le premier scroll ne peut donc plus
    // bloquer le thread UI sur un verrou/PRAGMA/CREATE TABLE SQLite.
    var runtime by remember(db) { mutableStateOf<ThermalUiRuntime?>(null) }
    var runtimeError by remember(db) { mutableStateOf<String?>(null) }
    LaunchedEffect(db) {
        val built = withContext(Dispatchers.IO) {
            runCatching {
                val manager = WeatherReferenceManager(context, db, lyonLab, credentials)
                val engine = ThermalEngine(db, manager.store())
                val coherenceStore = ThermalCoherenceStore(db)
                val inertiaHistoryStore = ThermalInertiaHistoryStore(context, db)
                val inertiaHistoryProjector = ThermalInertiaHistoryProjector(db, manager.store())
                ThermalUiRuntime(
                    manager,
                    engine,
                    coherenceStore,
                    inertiaHistoryStore,
                    inertiaHistoryProjector
                )
            }
        }
        built.fold(
            onSuccess = {
                runtime = it
                runtimeError = null
            },
            onFailure = {
                runtimeError = it.message ?: "Initialisation thermique impossible"
            }
        )
    }

    val readyRuntime = runtime
    if (readyRuntime == null) {
        Card(shape = RoundedCornerShape(20.dp)) {
            Column(
                Modifier.fillMaxWidth().padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text("Référence météo & moteur thermique", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    runtimeError ?: "Initialisation thermique en arrière-plan…",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (runtimeError == null) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error
                )
            }
        }
        return
    }
    val manager = readyRuntime.manager
    val engine = readyRuntime.engine
    val coherenceStore = readyRuntime.coherenceStore
    val inertiaHistoryStore = readyRuntime.inertiaHistoryStore
    val inertiaHistoryProjector = readyRuntime.inertiaHistoryProjector

    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
    val reference = remember(selectedKey) { prefs.selectedReference() }
    var trainedModel by remember { mutableStateOf<ThermalModel?>(null) }
    var menuOpen by remember { mutableStateOf(false) }
    var stationDiscoveryOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(busy) { onBusyChanged(busy) }
    var status by remember { mutableStateOf<ThermalStatus?>(null) }
    var info by remember { mutableStateOf("État thermique prêt") }
    LaunchedEffect(busy, info) { onProgressChanged(if (busy) info else null) }
    var weatherHistoryDialog by remember { mutableStateOf(false) }
    var weatherHistoryDays by remember { mutableIntStateOf(30) }
    var historyDialog by remember { mutableStateOf(false) }
    var historyDays by remember { mutableIntStateOf(30) }
    var inertiaHistoryDialog by remember { mutableStateOf(false) }
    var inertiaHistoryDays by remember { mutableIntStateOf(30) }
    var inertiaPending by remember { mutableStateOf<ThermalInertiaPendingChunk?>(null) }
    var suppressNextAuto by remember { mutableStateOf(false) }
    var selectedSensorId by remember {
        mutableStateOf(modelSensorPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L })
    }
    var profileDialog by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
    var coherenceBaselineReady by remember { mutableStateOf(false) }
    var observedReferenceKey by remember { mutableStateOf(selectedKey) }
    var observedDataVersion by remember { mutableIntStateOf(dataVersion) }
    var observedForecastMode by remember { mutableStateOf(forecastMode) }
    var debtSnapshot by remember { mutableStateOf(historyDebtStore.loadDebt()) }
    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }

    LaunchedEffect(selectedKey, selectedSensorId, dataVersion) {
        trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
        status = engine.statusFromTrainedModel(reference, selectedSensorId, trainedModel)
    }

    fun refreshDebtState() { debtSnapshot = historyDebtStore.loadDebt() }

    suspend fun processNextHistoryChunk() {
        val work = historyDebtStore.loadWork() ?: return
        historyDebtStore.resumeWork()
        val range = work.nextRange() ?: return
        busy = true
        info = "Historique · mois ${work.nextChunk + 1}/${work.totalChunks} · préparation météo…"
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val prepared = manager.prepareHistoryRange(reference, range.first, range.last)
                if (!prepared.coverage.ready) {
                    error("${reference.city} incomplet sur ce mois : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")
                }
                val advanced = historyDebtStore.advanceWork() ?: error("Session historique perdue")
                if (advanced.nextChunk >= advanced.totalChunks) {
                    val activeModel = trainedModelStore.loadUsable(reference.key, advanced.sensorId)
                        ?: error("Modèle vide ou à réentraîner")
                    val summary = engine.reconstructHistory(
                        reference = reference,
                        requestedDays = advanced.requestedDays,
                        sensorId = advanced.sensorId,
                        profile = profile,
                        precalibratedModel = activeModel
                    ) { p ->
                        scope.launch {
                            info = if (p.total > 0) {
                                val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                                "${p.stage} · $percent % · ${p.changed} point(s)"
                            } else p.stage
                            if (p.total > 0 && p.processed > 0) {
                                suppressNextAuto = true
                                onDataChanged()
                            }
                        }
                    }
                    historyDebtStore.clearWork()
                    historyDebtStore.clearDebt()
                    Triple(prepared, summary, null)
                } else {
                    Triple(prepared, null, advanced)
                }
            }
        }
        busy = false
        result.fold(
            onSuccess = { (_, summary, next) ->
                refreshDebtState()
                if (summary != null) {
                    continuationWork = null
                    val detail = summary.diagnostic?.let { " · $it" }.orEmpty()
                    info = "Historique terminé · ${summary.reconstructed} point(s) · ${summary.raccords} raccord(s)$detail"
                    suppressNextAuto = true
                    onDataChanged()
                } else if (next != null) {
                    continuationWork = next
                    info = "Mois ${next.nextChunk}/${next.totalChunks} validé · choisir Continuer, Pause ou Annuler"
                }
            },
            onFailure = { error ->
                historyDebtStore.pauseWork()
                historyDebtStore.setDebtState(HistoricalDebtState.PAUSED)
                refreshDebtState()
                continuationWork = null
                info = error.message ?: "Morceau historique impossible · session mise en pause"
            }
        )
    }

    suspend fun beginHistoryWork(days: Int, reason: String) {
        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
            ?: run { info = "Modèle vide ou à réentraîner"; return }
        val activeId = activeModel.sensorId
        val firstReal = withContext(Dispatchers.IO) { coherenceStore.firstMeasuredTimestamp(activeId) }
            ?: run { info = "Aucune vraie mesure pour initialiser l'historique"; return }
        val boundedDays = days.coerceIn(1, 1464)
        historyDebtStore.beginWork(reference.key, activeId, boundedDays, firstReal, reason)
        historyDebtStore.recordDebt(
            reference.key, activeId,
            firstReal - boundedDays.toLong() * 24L * 60L * 60L * 1000L,
            firstReal, reason, HistoricalDebtState.PENDING
        )
        refreshDebtState()
        processNextHistoryChunk()
    }


    suspend fun processNextInertiaChunk() {
        val work = inertiaHistoryStore.loadWork() ?: return
        inertiaHistoryStore.resumeWork()
        if (work.referenceKey != reference.key) {
            inertiaHistoryStore.pauseWork()
            info = "Sol inertiel en pause · référence météo différente"
            return
        }
        val range = work.nextRange() ?: run {
            inertiaHistoryStore.clearWork()
            info = "Sol inertiel historique terminé"
            return
        }
        busy = true
        info = "Sol inertiel · mois ${work.nextChunk + 1}/${work.totalChunks} · contrôle des prérequis…"
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val activeModel = trainedModelStore.loadUsable(reference.key, work.sensorId)
                    ?: error("Modèle entraîné requis pour cette sonde")
                if (activeModel.stableSignature() != work.modelSignature) {
                    error("Le modèle a changé · relancer l'extension du sol inertiel")
                }
                val prepared = manager.prepareHistoryRange(reference, range.first, range.last)
                if (!prepared.coverage.ready) {
                    error(
                        "${reference.city} incomplet sur ce mois : couverture " +
                            "${(prepared.coverage.coverage * 100).toInt()} %"
                    )
                }
                inertiaHistoryProjector.projectChunk(
                    reference = reference,
                    model = activeModel,
                    range = range,
                    seed = work.seedState()
                )
            }
        }
        busy = false
        result.fold(
            onSuccess = { chunk ->
                inertiaPending = ThermalInertiaPendingChunk(work, range, chunk)
                info = "Sol inertiel · mois ${work.nextChunk + 1}/${work.totalChunks} calculé · validation utilisateur requise"
            },
            onFailure = { error ->
                inertiaHistoryStore.pauseWork()
                inertiaPending = null
                info = error.message ?: "Sol inertiel impossible · session mise en pause"
            }
        )
    }

    suspend fun beginInertiaHistoryWork(days: Int) {
        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
            ?: run {
                info = "Modèle entraîné requis avant de prolonger le sol inertiel"
                return
            }
        val firstReal = withContext(Dispatchers.IO) {
            coherenceStore.firstMeasuredTimestamp(activeModel.sensorId)
        } ?: run {
            info = "Aucune vraie mesure intérieure pour borner le sol inertiel"
            return
        }
        inertiaHistoryStore.pruneOtherModels(
            reference.key,
            activeModel.sensorId,
            activeModel.stableSignature()
        )
        inertiaHistoryStore.beginWork(
            referenceKey = reference.key,
            sensorId = activeModel.sensorId,
            modelSignature = activeModel.stableSignature(),
            requestedDays = days.coerceIn(1, 1464),
            firstMeasuredTimestamp = firstReal
        )
        inertiaPending = null
        processNextInertiaChunk()
    }

    suspend fun validateInertiaChunk(pauseAfter: Boolean) {
        val pending = inertiaPending ?: return
        val activeModel = trainedModelStore.loadUsable(
            pending.work.referenceKey,
            pending.work.sensorId
        ) ?: run {
            inertiaHistoryStore.pauseWork()
            inertiaPending = null
            info = "Modèle devenu indisponible · sol inertiel mis en pause"
            return
        }
        if (activeModel.stableSignature() != pending.work.modelSignature) {
            inertiaHistoryStore.pauseWork()
            inertiaPending = null
            info = "Le modèle a changé · sol inertiel mis en pause"
            return
        }

        withContext(Dispatchers.IO) {
            inertiaHistoryStore.replaceChunk(
                pending.work.referenceKey,
                pending.work.sensorId,
                pending.work.modelSignature,
                pending.range,
                pending.result.points
            )
            inertiaHistoryStore.advanceWork(pending.result.endState)
        }
        val advanced = inertiaHistoryStore.loadWork()
        inertiaPending = null
        suppressNextAuto = true
        onDataChanged()

        if (advanced == null || advanced.nextChunk >= advanced.totalChunks) {
            inertiaHistoryStore.clearWork()
            info = "Sol inertiel historique terminé · tous les mois validés sont conservés"
        } else if (pauseAfter) {
            inertiaHistoryStore.pauseWork()
            info = "Sol inertiel mis en pause · ${advanced.nextChunk}/${advanced.totalChunks} mois validé(s)"
        } else {
            processNextInertiaChunk()
        }
    }

    suspend fun refresh(
        allHistory: Boolean,
        triggerChartReload: Boolean
    ) {
        info = if (allHistory) "Actualisation complète de la référence météo…" else "Actualisation météo récente et futur…"
        busy = true
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()
                    ?: error("Aucune donnée intérieure")
                val from = if (allHistory) bounds.first - 90L * 24L * 60L * 60L * 1000L else bounds.first - 18L * 60L * 60L * 1000L
                val to = maxOf(bounds.last, System.currentTimeMillis() + (forecastMode.maxHours + 2L) * 60L * 60L * 1000L)
                val sync = if (allHistory) manager.refreshSelected(reference, from, to)
                    else manager.ensureLocalCache(reference, from, to)
                val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                val thermalStatus = engine.statusFromTrainedModel(reference, selectedSensorId, activeModel)

                // v0.19.8: refresh never recalculates the past and never retrains.
                val forecast = if (activeModel?.acceptableForForecast == true) {
                    engine.refreshForecasts(
                        reference, activeModel.sensorId, profile, forecastMode,
                        precalibratedModel = activeModel
                    )
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
                val passive = withContext(Dispatchers.IO) {
                    val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                    activeModel to engine.statusFromTrainedModel(reference, selectedSensorId, activeModel)
                }
                trainedModel = passive.first
                status = passive.second
                info = error.message ?: "Référence météo indisponible"
            }
        )
        busy = false
    }

    suspend fun trainPersistedModel() {
        if (busy) return
        busy = true
        info = "Entraînement du modèle · préparation des mesures réelles…"
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val bounds = db.physicalMeasuredBounds() ?: error("Aucune mesure réelle")
                manager.ensureLocalCache(
                    reference,
                    bounds.first - 18L * 60L * 60L * 1000L,
                    bounds.last
                )
                val model = engine.trainModel(reference, selectedSensorId, profile)
                trainedModelStore.save(model)
                model
            }
        }
        result.fold(
            onSuccess = { model ->
                trainedModel = model
                selectedSensorId = model.sensorId
                modelSensorPrefs.edit().putLong("selected_sensor_id", model.sensorId).apply()
                status = engine.statusFromTrainedModel(reference, model.sensorId, model)
                val k = model.coefficients.firstOrNull() ?: 0.0
                info = "Modèle entraîné une fois · k ${fmt(k)} · Δ ${model.lagHours} h · futur prêt"
                suppressNextAuto = true
                onDataChanged()
            },
            onFailure = { error ->
                info = error.message ?: "Entraînement impossible"
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
                val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                    ?: error("Modèle vide ou à réentraîner")
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

                fun reconStates() = coherenceStore.calculatedSensorIds().filter { it == activeModel.sensorId }.mapNotNull { id ->
                    coherenceStore.inspect(reference, targetProfile, id, PointSource.RECONSTRUCTED, trainedModel = activeModel)
                }
                fun forecastStates() = coherenceStore.calculatedSensorIds().filter { it == activeModel.sensorId }.mapNotNull { id ->
                    coherenceStore.inspect(reference, targetProfile, id, PointSource.FORECAST, forecastMode, activeModel)
                }

                var staleRecon = reconStates().filterNot { it.current }
                var staleForecast = forecastStates().filterNot { it.current }

                // Si une reconstruction ancienne est réellement périmée, préparer sa profondeur
                // AVANT toute suppression. On garde ainsi les vraies mesures et les sources sûres
                // tant que les dépendances nécessaires au recalcul ne sont pas prêtes.
                val fullHistoryDays = staleRecon.mapNotNull { state ->
                    val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId) ?: return@mapNotNull null
                    if (state.bounds.first >= firstReal) 0
                    else (((firstReal - state.bounds.first) + dayMs - 1L) / dayMs).toInt().coerceIn(1, 1464)
                }.maxOrNull() ?: 0
                val maxHistoryDays = minOf(fullHistoryDays, 366)
                if (fullHistoryDays > 366) {
                    staleRecon.forEach { state ->
                        val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId) ?: return@forEach
                        val recentStart = firstReal - 366L * dayMs
                        if (state.bounds.first < recentStart) {
                            historyDebtStore.recordDebt(
                                reference.key, state.sensorId, state.bounds.first, recentStart, reason,
                                HistoricalDebtState.PENDING
                            )
                        }
                    }
                }
                if (maxHistoryDays > 0) {
                    info = "Rationalisation · 12 mois max automatiques · préparation ${thermalHistoryLabel(maxHistoryDays)}…"
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
                    val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId)
                    val recentStart = firstReal?.let { maxOf(previousBounds.first, it - 366L * dayMs) } ?: previousBounds.first
                    removed += PointSourceStore.deleteBySourceRange(
                        db, state.sensorId, PointSource.RECONSTRUCTED, recentStart, previousBounds.last
                    )
                    val rebuilt = engine.rebuildCalculatedExtent(
                        reference, targetProfile, state.sensorId, recentStart..previousBounds.last, progressCallback,
                        precalibratedModel = activeModel
                    )
                    reconstructed += rebuilt.reconstructed
                    skipped += rebuilt.skippedSensors
                }

                // Une reconstruction n'entre jamais dans l'apprentissage (MEASURED only), donc
                // le hash du forecast ne dépend pas des points reconstruits. On peut traiter ensuite.
                staleForecast.forEach { state ->
                    removed += PointSourceStore.deleteBySource(db, state.sensorId, PointSource.FORECAST)
                    val rebuilt = engine.refreshForecasts(reference, state.sensorId, targetProfile, forecastMode, precalibratedModel = activeModel)
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
                refreshDebtState()
                suppressNextAuto = true
                onDataChanged()
            },
            onFailure = { error ->
                info = error.message ?: "Rationalisation impossible"
            }
        )
    }

    // v0.19.8+ : la carte ne lance plus de chargement/calibration à sa première composition.
    // Les mises à jour de focus sont gérées par FabLiveUpdateCoordinator avec le modèle figé.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        // Une station peut changer uniquement après validation explicite dans l'écran de choix.
        // Synchroniser alors l'état Compose avec la préférence persistée.
        val persistedKey = prefs.selectedKey()
        if (persistedKey != selectedKey) {
            selectedKey = persistedKey
            return@LaunchedEffect
        }
        if (busy) return@LaunchedEffect
        val currentMeasuredRevision = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val measuredChanged = measuredRevision != null && currentMeasuredRevision != measuredRevision
        val referenceChanged = coherenceBaselineReady && selectedKey != observedReferenceKey
        val dataChanged = coherenceBaselineReady && dataVersion != observedDataVersion
        val forecastModeChanged = coherenceBaselineReady && forecastMode != observedForecastMode
        measuredRevision = currentMeasuredRevision
        observedReferenceKey = selectedKey
        observedDataVersion = dataVersion
        observedForecastMode = forecastMode

        if (!coherenceBaselineReady) {
            coherenceBaselineReady = true
            val passive = withContext(Dispatchers.IO) {
                val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                activeModel to engine.statusFromTrainedModel(reference, selectedSensorId, activeModel)
            }
            trainedModel = passive.first
            status = passive.second
            info = if (passive.first != null) {
                "Modèle figé chargé · futur géré par le mode live"
            } else {
                trainedModelStore.dirtyReason()?.let { "Modèle à réentraîner · $it" }
                    ?: "Modèle thermique non entraîné"
            }
        } else if (suppressNextAuto) {
            suppressNextAuto = false
        } else {
            when {
                referenceChanged -> {
                    trainedModelStore.markDirty("Référence météo modifiée")
                    trainedModel = null
                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)
                    info = "Référence météo modifiée · modèle à réentraîner · aucun calcul du passé lancé"
                }
                measuredChanged -> {
                    // Le coordinateur global, toujours composé, traite météo + futur.
                    // Cette carte ne lance aucun second calcul concurrent.
                    info = "Nouvelle mesure réelle détectée · futur actualisé sans réentraîner le modèle"
                }
                dataChanged -> {
                    val passive = withContext(Dispatchers.IO) {
                        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                        activeModel to engine.statusFromTrainedModel(reference, selectedSensorId, activeModel)
                    }
                    trainedModel = passive.first
                    status = passive.second
                }
                forecastModeChanged -> refresh(allHistory = false, triggerChartReload = true)
                else -> {
                    val passive = withContext(Dispatchers.IO) {
                        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                        activeModel to engine.statusFromTrainedModel(reference, selectedSensorId, activeModel)
                    }
                    trainedModel = passive.first
                    status = passive.second
                }
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

            val interruptedInertiaWork = inertiaHistoryStore.loadWork()
            if (interruptedInertiaWork != null && inertiaPending == null) {
                Button(
                    onClick = {
                        scope.launch {
                            inertiaHistoryStore.resumeWork()
                            processNextInertiaChunk()
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        "⚠ Reprendre sol inertiel · " +
                            "${interruptedInertiaWork.nextChunk}/${interruptedInertiaWork.totalChunks}"
                    )
                }
            }

            val interruptedWork = historyDebtStore.loadWork()
            if (interruptedWork != null) {
                Button(
                    onClick = {
                        scope.launch {
                            historyDebtStore.resumeWork()
                            continuationWork = null
                            processNextHistoryChunk()
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("⚠ Reprendre chargement morcelé · ${interruptedWork.nextChunk}/${interruptedWork.totalChunks}")
                }
            }

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

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { stationDiscoveryOpen = true },
                    enabled = !busy,
                    modifier = Modifier.weight(1f)
                ) { Text("Sondes proches · Auto") }
                TextButton(
                    onClick = {
                        prefs.setAutoProtection(false)
                        prefs.select(WeatherReferenceCatalog.DEFAULT_KEY)
                        selectedKey = WeatherReferenceCatalog.DEFAULT_KEY
                    },
                    enabled = !busy
                ) { Text("Réinitialiser") }
            }

            debtSnapshot?.let { debt ->
                Text(
                    "◐ Historique ancien en attente · ~${debt.pendingDays} j · ${debt.reason}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary
                )
                val savedWork = historyDebtStore.loadWork()
                Button(
                    onClick = {
                        scope.launch {
                            if (savedWork != null) {
                                historyDebtStore.resumeWork()
                                continuationWork = null
                                processNextHistoryChunk()
                            } else {
                                val firstReal = withContext(Dispatchers.IO) {
                                    coherenceStore.firstMeasuredTimestamp(debt.sensorId)
                                }
                                val days = firstReal?.let { (((it - debt.from).coerceAtLeast(24L * 60L * 60L * 1000L)) / (24L * 60L * 60L * 1000L)).toInt() }
                                    ?: debt.pendingDays
                                beginHistoryWork(days, debt.reason)
                            }
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) { Text(if (savedWork != null) "Reprendre l'historique" else "Mettre à jour l'historique ancien") }
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
                                if (preferred.model != null) {
                                    "Conservé ${(preferred.retainedRatio * 100).toInt()} % · " +
                                        "ignoré ${preferred.ignoredHours} h"
                                } else {
                                    "Modèle non entraîné pour cette sonde"
                                },
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

            ThermalWallSettingsCard(
                db = db,
                reference = reference,
                enabled = !busy,
                onChanged = {
                    trainedModelStore.markDirty("Sondes ou pans extérieurs modifiés")
                    trainedModel = null
                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)
                    info = "Configuration thermique modifiée · réentraînement intérieur manuel requis"
                }
            )

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

            val trainingRequired = trainedModel == null
            val blinkTransition = rememberInfiniteTransition(label = "model-training-blink")
            val trainAlpha by blinkTransition.animateFloat(
                initialValue = 0.45f,
                targetValue = 1.0f,
                animationSpec = infiniteRepeatable(tween(650), RepeatMode.Reverse),
                label = "model-training-alpha"
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { weatherHistoryDialog = true },
                    enabled = !busy && trainedModel != null,
                    modifier = Modifier.weight(1f)
                ) { Text("Étendre historique") }
                Button(
                    onClick = { scope.launch { trainPersistedModel() } },
                    enabled = !busy,
                    modifier = Modifier.weight(1f).graphicsLayer(alpha = if (trainingRequired) trainAlpha else 1f)
                ) { Text(if (trainingRequired) "⚠ Entraîner modèle" else "Réentraîner modèle") }
            }
            Text(
                if (trainingRequired) {
                    trainedModelStore.dirtyReason()?.let { "Modèle à entraîner · $it" }
                        ?: "Modèle vide : aucun calcul du passé ne part automatiquement."
                } else {
                    "Modèle figé : réutilisé pour le futur jusqu'à un réentraînement explicite."
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            OutlinedButton(
                onClick = { inertiaHistoryDialog = true },
                enabled = !busy && trainedModel != null,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Prolonger le sol inertiel") }
            Text(
                "Uniquement le sol/surface inertiel : exige un modèle entraîné et de la " +
                    "température intérieure RECONSTRUCTED. Calcul du plus ancien vers le présent, " +
                    "un mois à la fois, sans réentraînement.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

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
                    trainedModelStore.markDirty("Profil bâtiment modifié")
                    trainedModel = null
                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)
                    info = "Profil modifié · modèle à réentraîner manuellement"
                }
            },
            onReset = {
                val next = profileStore.reset()
                val changed = next != profile
                profile = next
                profileDialog = false
                if (changed) {
                    trainedModelStore.markDirty("Profil bâtiment réinitialisé")
                    trainedModel = null
                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)
                    info = "Profil réinitialisé · modèle à réentraîner manuellement"
                }
            }
        )
    }


    if (inertiaHistoryDialog) {
        AlertDialog(
            onDismissRequest = { inertiaHistoryDialog = false },
            title = { Text("Prolonger uniquement le sol inertiel ?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        "Aucun réentraînement et aucune reconstruction de l'air intérieur : " +
                            "FabData utilise uniquement le modèle figé et les températures " +
                            "intérieures déjà RECONSTRUCTED."
                    )
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        THERMAL_HISTORY_CHOICES.forEach { choice ->
                            FilterChip(
                                selected = inertiaHistoryDays == choice.days,
                                onClick = { inertiaHistoryDays = choice.days },
                                label = { Text(choice.label) }
                            )
                        }
                    }
                    Text(
                        "Sélection : ${thermalHistoryLabel(inertiaHistoryDays)}. Chaque mois est " +
                            "calculé du passé vers le présent puis attend ta validation.",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            },
            confirmButton = {
                Button(onClick = {
                    inertiaHistoryDialog = false
                    scope.launch { beginInertiaHistoryWork(inertiaHistoryDays) }
                }) { Text("Commencer") }
            },
            dismissButton = {
                TextButton(onClick = { inertiaHistoryDialog = false }) { Text("Annuler") }
            }
        )
    }

    inertiaPending?.let { pending ->
        val nextNumber = pending.work.nextChunk + 1
        val lastChunk = nextNumber >= pending.work.totalChunks
        AlertDialog(
            onDismissRequest = {},
            title = { Text("Sol inertiel · mois $nextNumber/${pending.work.totalChunks}") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        "${pending.result.points.size} point(s) calculé(s) · " +
                            "${pending.result.reconstructedHours} h intérieures reconstruites · " +
                            "couverture ${(pending.result.coverage * 100).toInt()} %."
                    )
                    Text(
                        "Rien de ce mois n'est enregistré tant que tu ne le valides pas. " +
                            "Après validation, son état final devient le départ physique du mois suivant."
                    )
                }
            },
            confirmButton = {
                Button(onClick = {
                    scope.launch { validateInertiaChunk(pauseAfter = false) }
                }) {
                    Text(if (lastChunk) "Valider et terminer" else "Valider et continuer")
                }
            },
            dismissButton = {
                Row {
                    if (!lastChunk) {
                        TextButton(onClick = {
                            scope.launch { validateInertiaChunk(pauseAfter = true) }
                        }) { Text("Valider et pause") }
                    }
                    TextButton(onClick = {
                        inertiaHistoryStore.clearWork()
                        inertiaPending = null
                        info = "Sol inertiel annulé · les mois déjà validés restent conservés"
                    }) { Text("Annuler") }
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
                    scope.launch { beginHistoryWork(weatherHistoryDays, "Extension historique demandée") }
                }) { Text("Étendre") }
            },
            dismissButton = { TextButton(onClick = { weatherHistoryDialog = false }) { Text("Annuler") } }
        )
    }

    continuationWork?.let { work ->
        AlertDialog(
            onDismissRequest = {},
            title = { Text("Morceau historique terminé") },
            text = {
                Text("${work.nextChunk}/${work.totalChunks} mois préparé(s). La suite reste strictement du plus ancien vers le présent.")
            },
            confirmButton = {
                Button(onClick = {
                    continuationWork = null
                    scope.launch { processNextHistoryChunk() }
                }) { Text("Continuer") }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = {
                        historyDebtStore.pauseWork()
                        historyDebtStore.setDebtState(HistoricalDebtState.PAUSED)
                        refreshDebtState()
                        continuationWork = null
                        info = "Historique mis en pause · reprise mémorisée"
                    }) { Text("Mettre en pause") }
                    TextButton(onClick = {
                        historyDebtStore.clearWork()
                        historyDebtStore.setDebtState(HistoricalDebtState.CANCELLED)
                        refreshDebtState()
                        continuationWork = null
                        info = "Traitement annulé · historique non traité conservé dans la liste des mises à jour"
                    }) { Text("Annuler") }
                }
            }
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
                    Text("Sélection : ${thermalHistoryLabel(historyDays)} · maximum 48 mois.", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                Button(onClick = {
                    historyDialog = false
                    scope.launch { beginHistoryWork(historyDays, "Reconstruction historique demandée") }
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
