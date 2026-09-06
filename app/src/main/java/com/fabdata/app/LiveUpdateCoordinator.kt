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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * Orchestrateur toujours composé, indépendant des cartes LazyColumn.
 *
 * - uniquement quand l'app est réellement au premier plan ;
 * - ouverture / retour au focus : météo fraîche de la référence déjà sélectionnée, jamais de rescan ;
 * - le scan des stations proches vit uniquement dans l'écran Sondes proches / Auto protection ;
 * - ensuite toutes les 5 minutes tant que l'utilisateur regarde l'app ;
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

    suspend fun updateLive(): Boolean {
        if (!foreground || working) return false
        working = true
        return try {
            withContext(Dispatchers.IO) {
                // Important : le focus ne choisit jamais une autre station.
                // La référence ne peut changer que depuis l'écran de choix explicite.
                val reference = weatherPrefs.selectedReference()

                if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                    if (credentials.hasCredential()) {
                        runCatching { meteoOfficial.syncSixMinute24h() }
                    } else {
                        runCatching { lyonWeather.syncToday() }
                    }
                }

                PointSourceStore.reconcileMeasuredDominance(db)
                manager.refreshRecent(reference)

                val profile = profileStore.load()
                val mode = profileStore.forecastMode()
                val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }

                // v0.19.8+ : seul le modèle explicitement entraîné et persisté peut servir au live.
                // Une nouvelle mesure ne le remplace pas et aucun historique n'est recalculé ici.
                val trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                if (trainedModel != null) {
                    engine.refreshForecasts(
                        reference, trainedModel.sensorId, profile, mode,
                        precalibratedModel = trainedModel
                    )
                }
            }
            onDataChanged()
            true
        } finally {
            working = false
        }
    }

    LaunchedEffect(dataVersion) {
        val current = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val previous = measuredRevision
        measuredRevision = current
        if (previous != null && current != previous) {
            pendingMeasuredRefresh = true
            if (foreground && updateLive()) {
                pendingMeasuredRefresh = false
            }
        }
    }

    // Le retour au premier plan rafraîchit uniquement la référence déjà choisie.
    // Aucun scan de secteur et aucun changement automatique de station ne sont autorisés ici.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect

        val hadPendingMeasured = pendingMeasuredRefresh
        if (updateLive() && hadPendingMeasured) {
            pendingMeasuredRefresh = false
        }

        while (true) {
            delay(300_000L)
            if (!foreground) break
            val hadPending = pendingMeasuredRefresh
            if (updateLive() && hadPending) {
                pendingMeasuredRefresh = false
            }
        }
    }
}
