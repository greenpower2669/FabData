package com.fabdata.app

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
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
import androidx.compose.runtime.saveable.rememberSaveable
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
fun StationDiscoveryDialog(
    currentReference: WeatherReference,
    credentials: MeteoFranceCredentialStore,
    onDismiss: () -> Unit,
    onSelect: (WeatherReference, Boolean) -> Unit
) {
    val context = LocalContext.current
    val discovery = remember { WeatherStationDiscovery(context, credentials) }
    val sectorPrefs = remember { WeatherStationSectorPrefs(context) }
    val savedSector = remember { sectorPrefs.load() }
    val scope = rememberCoroutineScope()

    var query by rememberSaveable { mutableStateOf(savedSector?.label ?: currentReference.city) }
    var latitudeText by rememberSaveable { mutableStateOf(savedSector?.latitude?.let { String.format(Locale.ROOT, "%.6f", it) }.orEmpty()) }
    var longitudeText by rememberSaveable { mutableStateOf(savedSector?.longitude?.let { String.format(Locale.ROOT, "%.6f", it) }.orEmpty()) }
    var radiusKm by rememberSaveable { mutableIntStateOf(savedSector?.radiusKm ?: 50) }
    var busy by remember { mutableStateOf(false) }
    var info by remember {
        mutableStateOf(
            savedSector?.let { "Secteur mémorisé · ${it.label} · resondage automatique à l'ouverture." }
                ?: "Choisis un lieu puis FabData cherchera toutes les stations du secteur."
        )
    }
    var result by remember { mutableStateOf<StationDiscoveryResult?>(null) }
    var selectedIndex by remember { mutableIntStateOf(0) }
    var mapOpen by remember { mutableStateOf(false) }
    var openMapAfterScan by remember { mutableStateOf(false) }

    fun runScan(openMapWhenReady: Boolean = false, anchorProvider: suspend () -> StationSearchAnchor) {
        if (busy) return
        if (openMapWhenReady) openMapAfterScan = true
        scope.launch {
            busy = true
            info = "Localisation · nouvel index des stations · classement chaleur…"
            val outcome = withContext(Dispatchers.IO) {
                try {
                    val anchor = anchorProvider()
                    Result.success(discovery.discover(anchor, radiusKm))
                } catch (error: Throwable) {
                    Result.failure(error)
                }
            }
            outcome.fold(
                onSuccess = { found ->
                    result = found
                    sectorPrefs.save(found.anchor, found.radiusKm)
                    sectorPrefs.recordScan(found.candidates.size, found.autoCandidate?.reference?.key)
                    query = found.anchor.label
                    latitudeText = String.format(Locale.ROOT, "%.6f", found.anchor.latitude)
                    longitudeText = String.format(Locale.ROOT, "%.6f", found.anchor.longitude)
                    selectedIndex = found.candidates.indexOfFirst { it.reference.key == currentReference.key }
                        .takeIf { it >= 0 }
                        ?: found.autoCandidate?.let { auto ->
                            found.candidates.indexOfFirst { it.reference.key == auto.reference.key }
                        }?.coerceAtLeast(0)
                        ?: 0
                    val warm = found.candidates.count { it.heat != null }
                    val catalogue = if (credentials.hasCredential()) "index Météo-France" else "catalogue public élargi"
                    info = "${found.anchor.label} · ${found.candidates.size} station(s) à ≤ ${found.radiusKm} km · $warm classée(s) · $catalogue · ${found.historyLabel}"
                    if (openMapAfterScan) {
                        openMapAfterScan = false
                        mapOpen = true
                    }
                },
                onFailure = { error ->
                    openMapAfterScan = false
                    sectorPrefs.recordScan(0, null, error.message)
                    info = error.message ?: "Recherche des stations impossible"
                }
            )
            busy = false
        }
    }

    LaunchedEffect(Unit) {
        savedSector?.let { memory -> runScan { memory.anchor() } }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.any { it }) {
            runScan { discovery.gpsAnchor() }
        } else {
            info = "Permission GPS refusée · utilise adresse, code postal, ville, coordonnées ou la carte."
        }
    }

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Sondes proches · Auto protection") },
        text = {
            Column(
                Modifier.heightIn(max = 610.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    "Auto protection privilégie la station du secteur historiquement la plus chaude. Le secteur et le rayon restent mémorisés ; l'index est resondé à chaque retour dans l'app.",
                    style = MaterialTheme.typography.bodySmall
                )

                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Adresse · code postal · ville") },
                    singleLine = true,
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                )
                Button(
                    onClick = { runScan { discovery.geocode(query) } },
                    enabled = !busy && query.trim().length >= 2,
                    modifier = Modifier.fillMaxWidth()
                ) { Text(if (busy) "Recherche…" else "Chercher autour de ce lieu") }

                OutlinedButton(
                    onClick = {
                        val fine = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                        val coarse = context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
                        if (fine || coarse) {
                            runScan { discovery.gpsAnchor() }
                        } else {
                            permissionLauncher.launch(
                                arrayOf(
                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                    Manifest.permission.ACCESS_COARSE_LOCATION
                                )
                            )
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) { Text("📍 Ma position GPS") }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = latitudeText,
                        onValueChange = { latitudeText = it },
                        label = { Text("Latitude") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                        enabled = !busy,
                        modifier = Modifier.weight(1f)
                    )
                    OutlinedTextField(
                        value = longitudeText,
                        onValueChange = { longitudeText = it },
                        label = { Text("Longitude") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                        enabled = !busy,
                        modifier = Modifier.weight(1f)
                    )
                }
                OutlinedButton(
                    onClick = {
                        val lat = latitudeText.trim().replace(',', '.').toDoubleOrNull()
                        val lon = longitudeText.trim().replace(',', '.').toDoubleOrNull()
                        if (lat == null || lon == null) {
                            info = "Coordonnées invalides"
                        } else {
                            runScan { discovery.reverse(lat, lon) }
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) { Text("Utiliser ces coordonnées") }

                Text("Rayon de recherche", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(25, 50, 100).forEach { km ->
                        FilterChip(
                            selected = radiusKm == km,
                            onClick = {
                                radiusKm = km
                                result?.anchor?.let { anchor -> runScan { anchor } }
                            },
                            label = { Text("$km km") },
                            enabled = !busy
                        )
                    }
                }

                OutlinedButton(
                    onClick = {
                        val found = result
                        if (found != null && found.candidates.isNotEmpty()) {
                            mapOpen = true
                        } else {
                            val lat = latitudeText.trim().replace(',', '.').toDoubleOrNull()
                            val lon = longitudeText.trim().replace(',', '.').toDoubleOrNull()
                            when {
                                lat != null && lon != null -> runScan(openMapWhenReady = true) { discovery.reverse(lat, lon) }
                                query.trim().length >= 2 -> runScan(openMapWhenReady = true) { discovery.geocode(query) }
                                savedSector != null -> runScan(openMapWhenReady = true) { savedSector.anchor() }
                                else -> runScan(openMapWhenReady = true) {
                                    StationSearchAnchor(
                                        "Autour de ${currentReference.label}",
                                        currentReference.latitude,
                                        currentReference.longitude,
                                        currentReference.departmentId
                                    )
                                }
                            }
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) { Text("🗺 Choisir sur la carte") }

                Text(info, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)

                val found = result
                if (found != null && found.candidates.isNotEmpty()) {
                    val auto = found.autoCandidate
                    if (auto != null) {
                        Card(shape = RoundedCornerShape(14.dp)) {
                            Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                Text("★ Auto protection", fontWeight = FontWeight.Bold)
                                Text(auto.reference.stationName, fontWeight = FontWeight.SemiBold)
                                Text(candidateLine(auto), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }

                    Text("Tourniquet · toutes les stations locales", fontWeight = FontWeight.SemiBold)
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        found.candidates.forEachIndexed { index, candidate ->
                            FilterChip(
                                selected = selectedIndex == index,
                                onClick = { selectedIndex = index },
                                label = {
                                    Column {
                                        Text(candidate.reference.stationName)
                                        Text(candidateLine(candidate), style = MaterialTheme.typography.labelSmall)
                                    }
                                }
                            )
                        }
                    }

                    val current = found.candidates[selectedIndex.coerceIn(0, found.candidates.lastIndex)]
                    Card(shape = RoundedCornerShape(14.dp)) {
                        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text("${selectedIndex + 1}/${found.candidates.size} · ${current.reference.stationName}", fontWeight = FontWeight.SemiBold)
                            Text(candidateLine(current), style = MaterialTheme.typography.bodySmall)
                            Text("ID ${current.reference.stationId}", style = MaterialTheme.typography.labelSmall)
                        }
                    }

                    Button(
                        onClick = {
                            val selected = auto ?: return@Button
                            sectorPrefs.save(found.anchor, found.radiusKm)
                            onSelect(selected.reference, true)
                        },
                        enabled = !busy && auto != null,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Utiliser Auto protection") }

                    OutlinedButton(
                        onClick = {
                            sectorPrefs.save(found.anchor, found.radiusKm)
                            onSelect(current.reference, false)
                        },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Choisir cette station manuellement") }

                    Text(
                        "Indice chaud = 95e percentile des maximales estivales (juin–septembre), calculé sur une période homogène. Le record reste un contexte et ne décide pas seul du classement.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !busy) { Text("Fermer") }
        }
    )

    val mapped = result
    if (mapOpen && mapped != null && mapped.candidates.isNotEmpty()) {
        StationMapDialog(
            result = mapped,
            initialIndex = selectedIndex,
            onDismiss = { mapOpen = false },
            onSelectIndex = { index ->
                val safeIndex = index.coerceIn(0, mapped.candidates.lastIndex)
                selectedIndex = safeIndex
                sectorPrefs.save(mapped.anchor, mapped.radiusKm)
                mapOpen = false
                onSelect(mapped.candidates[safeIndex].reference, false)
            }
        )
    }
}

private fun candidateLine(candidate: StationCandidate): String {
    val distance = String.format(Locale.FRANCE, "%.1f km", candidate.distanceKm)
    val heat = candidate.heat ?: return "$distance · indice chaud indisponible"
    return "$distance · P95 ${String.format(Locale.FRANCE, "%.1f", heat.p95C)} °C · record ${String.format(Locale.FRANCE, "%.1f", heat.recordC)} °C · ${heat.years} étés"
}
