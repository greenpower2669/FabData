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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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

/**
 * Tourniquet de sélection v0.13.0.
 * Le dialogue choisit uniquement un WeatherReference. Il ne calibre/reconstruit rien lui-même.
 */
@Composable
fun WeatherStationDiscoveryDialog(
    credentials: MeteoFranceCredentialStore,
    current: WeatherReference,
    prefs: WeatherReferencePrefs,
    onDismiss: () -> Unit,
    onSelect: (WeatherReference, Boolean) -> Unit
) {
    val context = LocalContext.current
    val discovery = remember { WeatherStationDiscovery(context, credentials) }
    val scope = rememberCoroutineScope()

    var query by remember { mutableStateOf(prefs.sectorLabel().orEmpty()) }
    var latitude by remember { mutableStateOf(prefs.sectorLatitude()?.let { String.format(Locale.ROOT, "%.6f", it) }.orEmpty()) }
    var longitude by remember { mutableStateOf(prefs.sectorLongitude()?.let { String.format(Locale.ROOT, "%.6f", it) }.orEmpty()) }
    var radiusKm by remember { mutableIntStateOf(prefs.sectorRadiusKm()) }
    var origin by remember {
        mutableStateOf(
            if (prefs.sectorLatitude() != null && prefs.sectorLongitude() != null) {
                StationSearchOrigin(
                    prefs.sectorLabel() ?: "Secteur enregistré",
                    prefs.sectorLatitude()!!,
                    prefs.sectorLongitude()!!
                )
            } else null
        )
    }
    var result by remember { mutableStateOf<StationDiscoveryResult?>(null) }
    var manualCandidate by remember { mutableStateOf<WeatherStationCandidate?>(null) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("Choisis l'origine du secteur puis lance la recherche.") }

    fun applyResult(value: StationDiscoveryResult) {
        result = value
        origin = value.origin
        latitude = String.format(Locale.ROOT, "%.6f", value.origin.latitude)
        longitude = String.format(Locale.ROOT, "%.6f", value.origin.longitude)
        manualCandidate = value.candidates.firstOrNull { it.reference.key == current.key }
            ?: value.autoSelected
            ?: value.candidates.firstOrNull()
        message = if (value.candidates.isEmpty()) {
            "Aucune station trouvée dans ${value.radiusKm} km · ${value.indexLabel}"
        } else {
            "${value.candidates.size} station(s) · ${value.indexLabel}"
        }
    }

    fun searchFrom(searchOrigin: StationSearchOrigin) {
        if (busy) return
        scope.launch {
            busy = true
            message = "Index des stations puis audit chaleur historique…"
            val loaded = withContext(Dispatchers.IO) {
                runCatching { discovery.discoverAndRank(searchOrigin, radiusKm) }
            }
            busy = false
            loaded.fold(
                onSuccess = ::applyResult,
                onFailure = { message = it.message ?: "Recherche de stations impossible" }
            )
        }
    }

    fun searchAddress() {
        if (busy) return
        scope.launch {
            busy = true
            message = "Localisation de « ${query.trim()} »…"
            val loaded = withContext(Dispatchers.IO) {
                runCatching {
                    val found = discovery.geocode(query)
                    discovery.discoverAndRank(found, radiusKm)
                }
            }
            busy = false
            loaded.fold(
                onSuccess = ::applyResult,
                onFailure = { message = it.message ?: "Adresse / ville introuvable" }
            )
        }
    }

    fun searchGps() {
        if (busy) return
        scope.launch {
            busy = true
            message = "Localisation GPS…"
            val loaded = runCatching { discovery.currentLocation() }
            loaded.fold(
                onSuccess = { found ->
                    busy = false
                    searchFrom(found)
                },
                onFailure = {
                    busy = false
                    message = it.message ?: "GPS indisponible"
                }
            )
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
            grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true
        ) {
            searchGps()
        } else {
            message = "Localisation refusée · utilise adresse, code postal, ville ou coordonnées."
        }
    }

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Station météo · Auto protection") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "FabData cherche seulement dans ton secteur. Une seule station reste la référence du moteur thermique.",
                    style = MaterialTheme.typography.bodySmall
                )

                Card(shape = RoundedCornerShape(14.dp)) {
                    Column(
                        Modifier.fillMaxWidth().padding(10.dp),
                        verticalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        Text("Proche de…", fontWeight = FontWeight.SemiBold)
                        OutlinedTextField(
                            value = query,
                            onValueChange = { query = it },
                            label = { Text("Adresse · code postal · grande ville") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Button(
                                onClick = ::searchAddress,
                                enabled = !busy && query.isNotBlank(),
                                modifier = Modifier.weight(1f)
                            ) { Text("Chercher") }
                            OutlinedButton(
                                onClick = {
                                    val fine = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                                    val coarse = context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
                                    if (fine || coarse) searchGps()
                                    else permissionLauncher.launch(
                                        arrayOf(
                                            Manifest.permission.ACCESS_FINE_LOCATION,
                                            Manifest.permission.ACCESS_COARSE_LOCATION
                                        )
                                    )
                                },
                                enabled = !busy,
                                modifier = Modifier.weight(1f)
                            ) { Text("GPS") }
                        }

                        Text("ou coordonnées GPS", style = MaterialTheme.typography.labelMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            OutlinedTextField(
                                value = latitude,
                                onValueChange = { latitude = it },
                                label = { Text("Latitude") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f)
                            )
                            OutlinedTextField(
                                value = longitude,
                                onValueChange = { longitude = it },
                                label = { Text("Longitude") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f)
                            )
                        }
                        OutlinedButton(
                            onClick = {
                                runCatching { discovery.coordinates(latitude, longitude) }
                                    .fold(::searchFrom) { message = it.message ?: "Coordonnées invalides" }
                            },
                            enabled = !busy && latitude.isNotBlank() && longitude.isNotBlank(),
                            modifier = Modifier.fillMaxWidth()
                        ) { Text("Utiliser ces coordonnées") }
                    }
                }

                Text("Rayon de recherche", style = MaterialTheme.typography.labelMedium)
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    listOf(25, 50, 100).forEach { radius ->
                        FilterChip(
                            selected = radiusKm == radius,
                            onClick = { radiusKm = radius },
                            enabled = !busy,
                            label = { Text("$radius km") }
                        )
                    }
                }

                Text(if (busy) "⏳ $message" else message, style = MaterialTheme.typography.bodySmall)

                result?.autoSelected?.let { auto ->
                    Card(shape = RoundedCornerShape(14.dp)) {
                        Column(
                            Modifier.fillMaxWidth().padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(3.dp)
                        ) {
                            Text("★ Auto protection", fontWeight = FontWeight.Bold)
                            Text(auto.reference.label, fontWeight = FontWeight.SemiBold)
                            Text(
                                "${WeatherStationDiscovery.formatDistance(auto.distanceKm)} · indice chaud ${WeatherStationDiscovery.formatHot(auto.hotIndexC)}",
                                style = MaterialTheme.typography.bodySmall
                            )
                            if (auto.p95C != null && auto.p99C != null) {
                                Text(
                                    "P95 ${WeatherStationDiscovery.formatHot(auto.p95C)} · P99 ${WeatherStationDiscovery.formatHot(auto.p99C)} · ${auto.historyDays} jours chauds analysés",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }
                }

                val candidates = result?.candidates.orEmpty()
                if (candidates.isNotEmpty()) {
                    Text("Tourniquet · choisir une autre station", fontWeight = FontWeight.SemiBold)
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        candidates.forEach { candidate ->
                            FilterChip(
                                selected = manualCandidate?.reference?.key == candidate.reference.key,
                                onClick = { manualCandidate = candidate },
                                label = {
                                    Column {
                                        Text(candidate.reference.stationName)
                                        Text(
                                            "${WeatherStationDiscovery.formatDistance(candidate.distanceKm)} · ${WeatherStationDiscovery.formatHot(candidate.hotIndexC)}",
                                            style = MaterialTheme.typography.labelSmall
                                        )
                                    }
                                }
                            )
                        }
                    }
                }

                Text(
                    "Indice chaud protecteur : 70 % du P95 + 30 % du P99 des maximales quotidiennes de mai à septembre sur 5 ans. C'est un proxy climatique local, pas un record isolé. Le moteur RC/reconstruction 0.12.2 n'est pas modifié.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                val auto = result?.autoSelected
                OutlinedButton(
                    onClick = {
                        val selected = auto ?: return@OutlinedButton
                        val sector = result?.origin ?: origin
                        if (sector != null) prefs.saveSector(sector, radiusKm)
                        prefs.select(selected.reference, autoProtection = true)
                        onSelect(selected.reference, true)
                    },
                    enabled = !busy && auto != null
                ) { Text("Auto protection") }

                Button(
                    onClick = {
                        val selected = manualCandidate ?: return@Button
                        val sector = result?.origin ?: origin
                        if (sector != null) prefs.saveSector(sector, radiusKm)
                        prefs.select(selected.reference, autoProtection = false)
                        onSelect(selected.reference, false)
                    },
                    enabled = !busy && manualCandidate != null
                ) { Text("Choisir") }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !busy) { Text("Annuler") }
        }
    )
}
