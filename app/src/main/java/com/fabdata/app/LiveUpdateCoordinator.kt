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
 * - ouverture / retour au focus : resondage Auto du secteur puis météo fraîche ;
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
    val sectorPrefs = remember { WeatherStationSectorPrefs(context) }
    val discovery = remember { WeatherStationDiscovery(context, credentials) }
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

    suspend fun updateLive(rebuildFromMeasured: Boolean, reevaluateAuto: Boolean = false): Boolean {
        if (!foreground || working) return false
        working = true
        return try {
            withContext(Dispatchers.IO) {
                val initialReference = weatherPrefs.selectedReference()
                var reference = initialReference
                var referenceChanged = false

                // v0.18.1 : à chaque ouverture/retour au premier plan, Auto protection
                // relit réellement l'index du secteur mémorisé. Les statistiques historiques
                // sont cachées 7 jours dans WeatherStationDiscovery, donc ce sondage reste léger.
                if (reevaluateAuto && weatherPrefs.autoProtection()) {
                    val sector = sectorPrefs.load()
                    if (sector != null) {
                        runCatching { discovery.discover(sector.anchor(), sector.radiusKm) }
                            .onSuccess { scan ->
                                sectorPrefs.save(scan.anchor, scan.radiusKm)
                                sectorPrefs.recordScan(scan.candidates.size, scan.autoCandidate?.reference?.key)
                                val selected = scan.autoCandidate?.reference
                                if (selected != null && selected.key != reference.key) {
                                    weatherPrefs.select(selected)
                                    weatherPrefs.setAutoProtection(true)
                                    reference = selected
                                    referenceChanged = true
                                }
                            }
                            .onFailure { error ->
                                sectorPrefs.recordScan(0, null, error.message)
                            }
                    }
                }

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
                val rebuildExisting = rebuildFromMeasured || referenceChanged

                if (rebuildExisting) {
                    selectedSensorId?.let { id ->
                        val firstReal = coherenceStore.firstMeasuredTimestamp(id)
                        val existing = PointSourceStore.reconstructedBounds(db, id)
                        if (firstReal != null && existing != null) {
                            val recentStart = firstReal - 366L * 24L * 60L * 60L * 1000L
                            if (existing.first < recentStart) {
                                val reason = if (referenceChanged) {
                                    "Auto protection : changement de station météo, historique antérieur aux 12 derniers mois à remettre à jour"
                                } else {
                                    "Nouvelle mesure réelle : historique antérieur aux 12 derniers mois à remettre à jour"
                                }
                                historyDebtStore.recordDebt(reference.key, id, existing.first, recentStart, reason)
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

    LaunchedEffect(dataVersion) {
        val current = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val previous = measuredRevision
        measuredRevision = current
        if (previous != null && current != previous) {
            pendingMeasuredRefresh = true
            if (foreground && updateLive(rebuildFromMeasured = true, reevaluateAuto = false)) {
                pendingMeasuredRefresh = false
            }
        }
    }

    // Chaque retour au premier plan = un nouveau sondage du secteur en mode Auto.
    // Les boucles de 5 minutes ne resondent pas l'index : elles rafraîchissent seulement
    // la station déjà retenue et les calculs courants.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect

        val rebuildNow = pendingMeasuredRefresh
        if (updateLive(rebuildFromMeasured = rebuildNow, reevaluateAuto = true) && rebuildNow) {
            pendingMeasuredRefresh = false
        }

        while (true) {
            delay(300_000L)
            if (!foreground) break
            val rebuild = pendingMeasuredRefresh
            if (updateLive(rebuildFromMeasured = rebuild, reevaluateAuto = false) && rebuild) {
                pendingMeasuredRefresh = false
            }
        }
    }
}
