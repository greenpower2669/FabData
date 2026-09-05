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
 * - ouverture / retour au focus : rafraîchissement immédiat ;
 * - ensuite toutes les 5 minutes tant que l'utilisateur regarde l'app ;
 * - lorsqu'une vraie mesure intérieure change : météo fraîche -> inertie/reconstruction -> forecast ;
 * - un changement reçu en arrière-plan est seulement mémorisé, aucun calcul n'y est lancé ;
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
    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }
    val coherenceStore = remember { ThermalCoherenceStore(db) }

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

    suspend fun updateLive(rebuildFromMeasured: Boolean): Boolean {
        // Garde-fou central : même si un effet UI se déclenche tardivement,
        // rien de météo/thermique ne part lorsque l'app n'est plus regardée.
        if (!foreground || working) return false
        working = true
        return try {
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

                PointSourceStore.reconcileMeasuredDominance(db)
                manager.refreshRecent(reference)

                val profile = profileStore.load()
                val mode = profileStore.forecastMode()
                val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }

                if (rebuildFromMeasured) {
                    selectedSensorId?.let { id ->
                        val firstReal = coherenceStore.firstMeasuredTimestamp(id)
                        val existing = PointSourceStore.reconstructedBounds(db, id)
                        if (firstReal != null && existing != null) {
                            val recentStart = firstReal - 366L * 24L * 60L * 60L * 1000L
                            if (existing.first < recentStart) {
                                historyDebtStore.recordDebt(
                                    reference.key, id, existing.first, recentStart,
                                    "Nouvelle mesure réelle : historique antérieur aux 12 derniers mois à remettre à jour"
                                )
                            }
                        }
                    }
                    engine.refreshExistingReconstructions(reference, profile, selectedSensorId, maxHistoryDays = 366)
                }
                engine.refreshForecasts(reference, selectedSensorId, profile, mode)
            }
            onDataChanged()
            true
        } finally {
            working = false
        }
    }

    // Une nouvelle vraie mesure déclenche immédiatement le recalcul seulement si l'app
    // est visible. En arrière-plan on pose juste un drapeau, repris au prochain focus.
    LaunchedEffect(dataVersion) {
        val current = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val previous = measuredRevision
        measuredRevision = current
        if (previous != null && current != previous) {
            pendingMeasuredRefresh = true
            if (foreground && updateLive(rebuildFromMeasured = true)) {
                pendingMeasuredRefresh = false
            }
        }
    }

    // Ouverture / retour au premier plan : immédiat. Puis cadence douce de 5 minutes.
    // Le changement de lifecycle annule cet effet dès que l'app repasse derrière.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect

        val rebuildNow = pendingMeasuredRefresh
        if (updateLive(rebuildFromMeasured = rebuildNow) && rebuildNow) {
            pendingMeasuredRefresh = false
        }

        while (true) {
            delay(300_000L)
            if (!foreground) break
            val rebuild = pendingMeasuredRefresh
            if (updateLive(rebuildFromMeasured = rebuild) && rebuild) {
                pendingMeasuredRefresh = false
            }
        }
    }
}
