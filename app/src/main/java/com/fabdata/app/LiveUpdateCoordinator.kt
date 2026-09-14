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
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private const val LIVE_FORECAST_INTERVAL_MS = 10L * 60L * 1000L
private val LIVE_SLOT_FORMAT = DateTimeFormatter.ofPattern("HH:mm")

private fun liveSlotLabel(slot: Long): String =
    Instant.ofEpochMilli(slot).atZone(ZoneId.systemDefault()).format(LIVE_SLOT_FORMAT)

/**
 * Foreground scheduler.
 *
 * Network acquisition belongs to one canonical :00/:10/:20/... slot only. A new
 * indoor measurement may immediately recalculate the local/Fab future from the cached
 * weather snapshot, but can never force a second provider request in the same slot.
 */
@Composable
fun FabLiveUpdateCoordinator(
    db: FabDataDb,
    lyonLab: LyonLabStore,
    credentials: MeteoFranceCredentialStore,
    dataVersion: Int,
    onDataChanged: (String) -> Unit
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

    suspend fun slotClosed(referenceKey: String, now: Long = System.currentTimeMillis()): Boolean =
        withContext(Dispatchers.IO) {
            ForecastMemoryStore.captureSlotClosed(db.writableDatabase, referenceKey, now)
        }

    suspend fun recalculateLocal(trigger: String): Boolean {
        if (!foreground || working || FabDataWorkArbiter.criticalImportPending()) return false
        return FabDataWorkArbiter.withDataProducer producer@{
            if (!foreground || working) return@producer false
            val reference = weatherPrefs.selectedReference()
            val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }
            val trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId) ?: return@producer false
            val operationId = FabOperationRegistry.tryStart(
                key = "forecast-local:${reference.key}",
                title = "Recalcul prévision locale",
                detail = "Météo en cache · recalcul Fab uniquement",
                cancellable = true,
                trigger = trigger,
                priority = "DATA",
                network = false
            ) ?: return@producer false
            working = true
            try {
                withContext(Dispatchers.IO) {
                    FabOperationRegistry.ensureNotCancelled(operationId)
                    engine.refreshForecasts(
                        reference,
                        trainedModel.sensorId,
                        profileStore.load(),
                        profileStore.forecastMode(),
                        precalibratedModel = trainedModel
                    )
                }
                onDataChanged("$trigger · recalcul local")
                FabOperationRegistry.finish(operationId, "Prévision locale recalculée · aucun appel météo")
                true
            } catch (cancel: CancellationException) {
                FabOperationRegistry.cancelled(operationId, "Recalcul local arrêté")
                if (!currentCoroutineContext().isActive) throw cancel
                false
            } catch (error: Throwable) {
                FabOperationRegistry.fail(operationId, error.message ?: "Recalcul local impossible")
                false
            } finally {
                working = false
            }
        } ?: false
    }

    suspend fun captureWeatherSlot(trigger: String): Boolean {
        if (!foreground || working || FabDataWorkArbiter.criticalImportPending()) return false
        return FabDataWorkArbiter.withDataProducer producer@{
            if (!foreground || working) return@producer false
            val reference = weatherPrefs.selectedReference()
            val now = System.currentTimeMillis()
            val slot = ForecastMemoryStore.tryClaimCaptureSlot(
                db.writableDatabase,
                reference.key,
                now,
                trigger
            ) ?: return@producer false
            val operationId = FabOperationRegistry.tryStart(
                key = "weather:${reference.key}",
                title = "Mise à jour météo",
                detail = "${reference.label} · jet unique H+1 → H+48",
                cancellable = true,
                trigger = "$trigger · créneau ${liveSlotLabel(slot)}",
                priority = "DATA",
                network = true,
                captureSlot = slot
            ) ?: return@producer false
            working = true
            var captured = false
            try {
                withContext(Dispatchers.IO) {
                    FabOperationRegistry.ensureNotCancelled(operationId)
                    FabOperationRegistry.update(operationId, "${reference.label} · acquisition réseau du créneau…")

                    if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                        if (credentials.hasCredential()) {
                            runCatching { meteoOfficial.syncSixMinute24h() }
                        } else {
                            runCatching { lyonWeather.syncToday() }
                        }
                    }

                    FabOperationRegistry.ensureNotCancelled(operationId)
                    val dominanceNow = System.currentTimeMillis()
                    PointSourceStore.reconcileMeasuredDominance(
                        db,
                        dominanceNow - 48L * 60L * 60L * 1000L,
                        dominanceNow + 12L * 60L * 60L * 1000L
                    )

                    FabOperationRegistry.update(operationId, "${reference.label} · snapshot complet H+1 → H+48…")
                    manager.refreshRecent(reference)
                    captured = ForecastMemoryStore.hasCaptureSlot(db.writableDatabase, reference.key, slot)

                    val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }
                    val trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                    if (trainedModel != null) {
                        FabOperationRegistry.ensureNotCancelled(operationId)
                        engine.refreshForecasts(
                            reference,
                            trainedModel.sensorId,
                            profileStore.load(),
                            profileStore.forecastMode(),
                            precalibratedModel = trainedModel
                        )
                    }
                    ForecastMemoryStore.finishCaptureSlot(
                        db.writableDatabase,
                        reference.key,
                        slot,
                        captured,
                        if (captured) "snapshot H1-H48 archivé" else "cycle terminé sans snapshot futur"
                    )
                }
                if (FabOperationRegistry.cancelRequested(operationId)) {
                    FabOperationRegistry.cancelled(operationId, "Mise à jour météo arrêtée · priorité supérieure")
                } else {
                    onDataChanged("météo · créneau ${liveSlotLabel(slot)}")
                    FabOperationRegistry.finish(
                        operationId,
                        if (captured) "Créneau ${liveSlotLabel(slot)} archivé · H+1 → H+48"
                        else "Créneau ${liveSlotLabel(slot)} consommé · aucune donnée future reçue"
                    )
                }
                true
            } catch (cancel: CancellationException) {
                ForecastMemoryStore.finishCaptureSlot(
                    db.writableDatabase,
                    reference.key,
                    slot,
                    false,
                    "annulé au prochain point sûr"
                )
                val requested = FabOperationRegistry.cancelRequested(operationId)
                FabOperationRegistry.cancelled(
                    operationId,
                    if (requested) "Mise à jour météo arrêtée · priorité supérieure" else "Routine quittée"
                )
                if (!requested || !currentCoroutineContext().isActive) throw cancel
                false
            } catch (error: Throwable) {
                ForecastMemoryStore.finishCaptureSlot(
                    db.writableDatabase,
                    reference.key,
                    slot,
                    false,
                    error.message ?: "erreur réseau"
                )
                FabOperationRegistry.fail(operationId, error.message ?: "Mise à jour météo impossible")
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
            if (foreground && recalculateLocal("nouvelle mesure intérieure")) {
                pendingMeasuredRefresh = false
            }
        }
    }

    // One catch-up at resume if this slot has never been attempted, then exact 10-minute
    // boundaries while the app remains in the foreground.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect
        while (foreground) {
            if (pendingMeasuredRefresh) {
                if (recalculateLocal("nouvelle mesure intérieure en attente")) {
                    pendingMeasuredRefresh = false
                }
            }

            val reference = weatherPrefs.selectedReference()
            val now = System.currentTimeMillis()
            if (slotClosed(reference.key, now)) {
                val nextSlot = ForecastMemoryStore.captureSlot10m(now) + LIVE_FORECAST_INTERVAL_MS
                delay((nextSlot - now).coerceAtLeast(1_000L))
                continue
            }

            val ran = captureWeatherSlot("horloge canonique")
            if (!ran) delay(5_000L)
        }
    }
}
