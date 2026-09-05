package com.fabdata.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.unit.dp
import org.maplibre.android.MapLibre
import org.maplibre.android.annotations.MarkerOptions
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.maps.CameraPosition
import org.maplibre.android.maps.MapView

private const val FABDATA_MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty"

/** Carte tactile sans clé Google : MapLibre + OpenFreeMap/OSM. */
@Composable
fun StationMapDialog(
    result: StationDiscoveryResult,
    initialIndex: Int,
    onDismiss: () -> Unit,
    onSelectIndex: (Int) -> Unit
) {
    var selectedIndex by remember(result.candidates, initialIndex) {
        mutableIntStateOf(initialIndex.coerceIn(0, result.candidates.lastIndex))
    }
    var mapView by remember { mutableStateOf<MapView?>(null) }

    DisposableEffect(Unit) {
        onDispose {
            mapView?.onPause()
            mapView?.onStop()
            mapView?.onDestroy()
            mapView = null
        }
    }

    val selected = result.candidates[selectedIndex]

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Choisir une station sur la carte") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                AndroidView(
                    modifier = Modifier.fillMaxWidth().height(410.dp),
                    factory = { ctx ->
                        MapLibre.getInstance(ctx)
                        MapView(ctx).also { view ->
                            mapView = view
                            view.onCreate(null)
                            view.onStart()
                            view.onResume()
                            view.getMapAsync { map ->
                                val zoom = when {
                                    result.radiusKm <= 25 -> 10.0
                                    result.radiusKm <= 50 -> 9.0
                                    else -> 8.0
                                }
                                map.cameraPosition = CameraPosition.Builder()
                                    .target(LatLng(result.anchor.latitude, result.anchor.longitude))
                                    .zoom(zoom)
                                    .build()
                                map.setStyle(FABDATA_MAP_STYLE) {
                                    result.candidates.forEach { candidate ->
                                        map.addMarker(
                                            MarkerOptions()
                                                .position(LatLng(candidate.reference.latitude, candidate.reference.longitude))
                                                .title(candidate.reference.stationId)
                                                .snippet(candidate.reference.stationName)
                                        )
                                    }
                                }
                                map.addOnMarkerClickListener { marker ->
                                    val index = result.candidates.indexOfFirst {
                                        it.reference.stationId == marker.title
                                    }
                                    if (index >= 0) selectedIndex = index
                                    true
                                }
                            }
                        }
                    }
                )
                Text(
                    "${selected.reference.stationName} · ${candidateMapLine(selected)}",
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    "Touchez un repère puis validez. La carte ne change pas le mode Auto tant que vous n'avez pas confirmé.",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        },
        confirmButton = {
            Button(onClick = { onSelectIndex(selectedIndex) }) { Text("Choisir cette station") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Fermer") } }
    )
}

private fun candidateMapLine(candidate: StationCandidate): String {
    val km = String.format(java.util.Locale.FRANCE, "%.1f km", candidate.distanceKm)
    val heat = candidate.heat ?: return "$km · indice chaud non calculé"
    return "$km · P95 ${String.format(java.util.Locale.FRANCE, "%.1f", heat.p95C)} °C"
}
