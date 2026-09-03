package com.fabdata.app

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.weight
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
    val scope = rememberCoroutineScope()

    var query by rememberSaveable { mutableStateOf(currentReference.city) }
    var latitudeText by rememberSaveable { mutableStateOf("") }
    var longitudeText by rememberSaveable { mutableStateOf("") }
    var radiusKm by rememberSaveable { mutableIntStateOf(50) }
    var busy by remember { mutableStateOf(false) }
    var info by remember { mutableStateOf("Choisis un lieu puis FabData cherchera les stations du secteur.") }
    var result by remember { mutableStateOf<StationDiscoveryResult?>(null) }
    var selectedIndex by remember { mutableIntStateOf(0) }

    fun runScan(anchorProvider: () -> StationSearchAnchor) {
        if (busy) return
        scope.launch {
            busy = true
            info = "Localisation · index Météo-France · classement chaleur…"
            val outcome = withContext(Dispatchers.IO) {
                runCatching {
                    val anchor = anchorProvider()
                    discovery.discover(anchor, radiusKm)
                }
            }
            outcome.fold(
                onSuccess = { found ->
                    result = found
                    selectedIndex = found.autoCandidate?.let { auto ->
                        found.candidates.indexOfFirst { it.reference.key == auto.reference.key }
                    }?.coerceAtLeast(0) ?: 0
                    val warm = found.candidates.count { it.heat != null }
                    info = "${found.anchor.label} · ${found.candidates.size} station(s) à ≤ ${found.radiusKm} km · $warm classée(s) sur ${found.historyLabel}"
                },
                onFailure = { error ->
                    info = error.message ?: "Recherche des stations impossible"
                }
            )
            busy = false
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.any { it }) {
            runScan { discovery.gpsAnchor() }
        } else {
            info = "Permission GPS refusée · utilise adresse, code postal, ville ou coordonnées."
        }
    }

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Sondes proches · Auto protection") },
        text = {
            Column(
                Modifier.heightIn(max = 570.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    "Auto protection privilégie la station du secteur historiquement la plus chaude. Le moteur RC lui-même n'est pas modifié.",
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

                    val current = found.candidates[selectedIndex.coerceIn(0, found.candidates.lastIndex)]
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = {
                                selectedIndex = (selectedIndex - 1 + found.candidates.size) % found.candidates.size
                            },
                            enabled = !busy && found.candidates.size > 1
                        ) { Text("◀") }
                        Card(Modifier.weight(1f), shape = RoundedCornerShape(14.dp)) {
                            Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                Text("${selectedIndex + 1}/${found.candidates.size} · ${current.reference.stationName}", fontWeight = FontWeight.SemiBold)
                                Text(candidateLine(current), style = MaterialTheme.typography.bodySmall)
                                Text("ID ${current.reference.stationId}", style = MaterialTheme.typography.labelSmall)
                            }
                        }
                        OutlinedButton(
                            onClick = { selectedIndex = (selectedIndex + 1) % found.candidates.size },
                            enabled = !busy && found.candidates.size > 1
                        ) { Text("▶") }
                    }

                    Button(
                        onClick = { auto?.let { onSelect(it.reference, true) } },
                        enabled = !busy && auto != null,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Utiliser Auto protection") }

                    OutlinedButton(
                        onClick = { onSelect(current.reference, false) },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Choisir cette station manuellement") }

                    Text(
                        "Indice chaud = 95e percentile des maximales estivales (juin–septembre), calculé sur une réanalyse historique homogène. Le record est affiché à titre de contexte mais ne décide pas seul du classement.",
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
}

private fun candidateLine(candidate: StationCandidate): String {
    val distance = String.format(Locale.FRANCE, "%.1f km", candidate.distanceKm)
    val heat = candidate.heat ?: return "$distance · indice chaud indisponible"
    return "$distance · P95 ${String.format(Locale.FRANCE, "%.1f", heat.p95C)} °C · record ${String.format(Locale.FRANCE, "%.1f", heat.recordC)} °C · ${heat.years} étés"
}
