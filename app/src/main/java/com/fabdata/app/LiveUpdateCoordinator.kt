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
 * - au focus/ouverture puis toutes les 60 s : rafraîchissement météo léger + forecast ;
 * - lorsqu'une vraie mesure intérieure change : météo fraîche -> inertie/reconstruction -> forecast ;
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
    val lyonWeather = remember { LyonWeatherSync(db) }
    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, credentials) }

    var foreground by remember {
        mutableStateOf(activity?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) == true)
    }
    var working by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }

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

    suspend fun updateLive(rebuildFromMeasured: Boolean) {
        if (working) return
        working = true
        try {
            val reference = weatherPrefs.selectedReference()
            withContext(Dispatchers.IO) {
                // La station système Lyon possède une vraie source d'observation fraîche.
                if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                    if (credentials.hasCredential()) {
                        runCatching { meteoOfficial.syncSixMinute24h() }
                    } else {
                        runCatching { lyonWeather.syncToday() }
                    }
                }

                // Nettoie d'abord d'éventuels anciens calculs qui cohabitaient dans
                // la même heure qu'une vraie mesure, sans jamais supprimer MEASURED.
                PointSourceStore.reconcileMeasuredDominance(db)
                manager.refreshRecent(reference)

                val profile = profileStore.load()
                val mode = profileStore.forecastMode()
                val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }

                if (rebuildFromMeasured) {
                    // refreshExistingReconstructions réestime l'inertie via le moteur
                    // avant de réécrire uniquement les couches calculées concernées.
                    engine.refreshExistingReconstructions(reference, profile, selectedSensorId)
                }
                engine.refreshForecasts(reference, selectedSensorId, profile, mode)
            }
            onDataChanged()
        } finally {
            working = false
        }
    }

    // Réagit à toute arrivée/import de données même si la carte thermique est hors écran.
    LaunchedEffect(dataVersion) {
        val current = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val previous = measuredRevision
        measuredRevision = current
        if (previous != null && current != previous) {
            updateLive(rebuildFromMeasured = true)
        }
    }

    // Ouverture / retour au premier plan : immédiat, puis une fois par minute.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect
        while (foreground) {
            updateLive(rebuildFromMeasured = false)
            delay(60_000L)
        }
    }
}
