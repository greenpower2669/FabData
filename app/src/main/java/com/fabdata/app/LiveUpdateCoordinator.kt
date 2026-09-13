package com.fabdata.app

import androidx.activity.ComponentActivity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext

private const val LIVE_FORECAST_INTERVAL_MS = 10L * 60L * 1000L

/**
 * Orchestrateur toujours composé, indépendant des cartes LazyColumn.
 *
 * - uniquement quand l'app est réellement au premier plan ;
 * - ouverture / retour au focus : météo fraîche de la référence déjà sélectionnée, jamais de rescan ;
 * - le scan des stations proches vit uniquement dans l'écran Sondes proches / Auto protection ;
 * - ensuite toutes les 10 minutes tant que l'utilisateur regarde l'app ;
 * - lorsqu'une vraie mesure intérieure change : météo fraîche puis futur avec le modèle figé ;
 * - un changement reçu en arrière-plan est seulement mémorisé, aucun calcul n'y est lancé ;
 * - ne réentraîne jamais le modèle et ne recalcule jamais le passé ;
 * - ne modifie jamais directement une mesure MEASURED.
 */
@Composable
fun FabLiveUpdateCoordinator(
    db: FabDataDb,
    lyonLab: LyonLabStore,
    credentials: MeteoFranceCredentialStore,
    dataVersion: Int,
    onDataChanged: () -> Unit
) {
    val context = LocalContext.current
    val activity = context as? ComponentActivity
    val weatherPrefs = remember { WeatherReferencePrefs(context) }
    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val profileStore = remember { ThermalProfileStore(context) }
    val modelPrefs = remember {
        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)
    }
    val trainedModelStore = remember { ThermalTrainedModelStore(context) }
    val lyonWeather = remember { LyonWeatherSync(db) }
    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, credentials) }

    var foreground by remember {
        mutableStateOf(activity?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) == true)
    }
    var working by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
    var pendingMeasuredRefresh by remember { mutableStateOf(false) }

    DisposableEffect(activity) {
        if (activity == null) return@DisposableEffect onDispose { }
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> foreground = true
                Lifecycle.Event.ON_PAUSE, Lifecycle.Event.ON_STOP -> foreground = false
                else -> Unit
            }
        }
        activity.lifecycle.addObserver(observer)
        onDispose { activity.lifecycle.removeObserver(observer) }
    }

    suspend fun currentForecastSlotCaptured(referenceKey: String, now: Long = System.currentTimeMillis()): Boolean =
        withContext(Dispatchers.IO) {
            ForecastMemoryStore.hasCaptureSlot(db.writableDatabase, referenceKey, now)
        }

    suspend fun updateLive(force: Boolean = false): Boolean {
        if (!foreground || working || FabDataWorkArbiter.criticalImportPending()) return false
        return FabDataWorkArbiter.withDataProducer producer@{
            if (!foreground || working) return@producer false
            val referenceForOperation = weatherPrefs.selectedReference()
            if (!force && currentForecastSlotCaptured(referenceForOperation.key)) return@producer false
            val operationId = FabOperationRegistry.tryStart(
                "weather:${referenceForOperation.key}",
                "Mise à jour automatique",
                "${referenceForOperation.label} · ouverture / focus"
            ) ?: return@producer false
            working = true
            try {
                withContext(Dispatchers.IO) {
                    // Important : le focus ne choisit jamais une autre station.
                    val reference = referenceForOperation
                    FabOperationRegistry.ensureNotCancelled(operationId)
                    FabOperationRegistry.update(operationId, "${reference.label} · météo récente…")

                    if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                        if (credentials.hasCredential()) {
                            runCatching { meteoOfficial.syncSixMinute24h() }
                        } else {
                            runCatching { lyonWeather.syncToday() }
                        }
                    }

                    FabOperationRegistry.ensureNotCancelled(operationId)
                    val dominanceNow = System.currentTimeMillis()
                    val recentFrom = dominanceNow - 48L * 60L * 60L * 1000L
                    val recentTo = dominanceNow + 12L * 60L * 60L * 1000L
                    FabOperationRegistry.update(operationId, "${reference.label} · cohérence récente…")
                    PointSourceStore.reconcileMeasuredDominance(db, recentFrom, recentTo)

                    FabOperationRegistry.ensureNotCancelled(operationId)
                    FabOperationRegistry.update(operationId, "${reference.label} · référence récente…")
                    manager.refreshRecent(reference)
                    FabOperationRegistry.ensureNotCancelled(operationId)

                    FabOperationRegistry.update(operationId, "${reference.label} · prévision / cohérence…")
                    val profile = profileStore.load()
                    val mode = profileStore.forecastMode()
                    val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }
                    val trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                    if (trainedModel != null) {
                        FabOperationRegistry.ensureNotCancelled(operationId)
                        engine.refreshForecasts(
                            reference, trainedModel.sensorId, profile, mode,
                            precalibratedModel = trainedModel
                        )
                        FabOperationRegistry.ensureNotCancelled(operationId)
                    }
                }
                if (FabOperationRegistry.cancelRequested(operationId)) {
                    FabOperationRegistry.cancelled(operationId, "Mise à jour automatique arrêtée · priorité supérieure")
                } else {
                    onDataChanged()
                    FabOperationRegistry.finish(operationId, "Météo et prévision à jour")
                }
                true
            } catch (cancel: CancellationException) {
                val requested = FabOperationRegistry.cancelRequested(operationId)
                FabOperationRegistry.cancelled(
                    operationId,
                    if (requested) "Mise à jour automatique arrêtée · priorité supérieure" else "Routine remplacée / composition quittée"
                )
                if (!requested || !currentCoroutineContext().isActive) throw cancel
                false
            } catch (error: Throwable) {
                FabOperationRegistry.fail(operationId, error.message ?: "Mise à jour automatique impossible")
                false
            } finally {
                working = false
            }
        } ?: false
    }

    LaunchedEffect(dataVersion) {
        val current = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val previous = measuredRevision
        measuredRevision = current
        if (previous != null && current != previous) {
            pendingMeasuredRefresh = true
            if (foreground && updateLive(force = true)) {
                pendingMeasuredRefresh = false
            }
        }
    }

    // Horloge canonique : :00 / :10 / :20 / :30 / :40 / :50.
    // Si le créneau courant manque (ouverture tardive), on le rattrape immédiatement ;
    // sinon on dort jusqu'à la prochaine frontière. Le vrai issued_at reste conservé.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect
        while (foreground) {
            val hadPending = pendingMeasuredRefresh
            if (!hadPending) {
                val reference = weatherPrefs.selectedReference()
                val now = System.currentTimeMillis()
                if (currentForecastSlotCaptured(reference.key, now)) {
                    val nextSlot = ForecastMemoryStore.captureSlot10m(now) + LIVE_FORECAST_INTERVAL_MS
                    delay((nextSlot - now).coerceAtLeast(1_000L))
                    if (!foreground) break
                }
            }
            val ran = updateLive(force = hadPending)
            if (ran && hadPending) pendingMeasuredRefresh = false
            if (!ran) delay(30_000L)
        }
    }
}
