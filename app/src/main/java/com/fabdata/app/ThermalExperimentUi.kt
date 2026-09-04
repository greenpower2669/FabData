package com.fabdata.app

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.util.Locale
import kotlin.math.max

@Composable
fun ThermalInertiaExperimentCard(estimate: ThermalInertiaEstimate?) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(13.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            Text("Température inertielle estimée · expérimental", fontWeight = FontWeight.Bold)
            Text(
                "Observation uniquement : mesures intérieures réelles + météo explicative. Cette courbe ne participe ni à la reconstruction ni à la prévision.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            val d = estimate?.diagnostics
            if (d == null) {
                Text(
                    "En attente d'une plage commune suffisamment longue entre mesures réelles et référence météo.",
                    style = MaterialTheme.typography.bodySmall
                )
            } else {
                Text(String.format(Locale.FRANCE, "État inertiel actuel : %.1f °C", d.currentC), fontWeight = FontWeight.SemiBold)
                Text("Tendance : ${d.trendLabel}", style = MaterialTheme.typography.bodySmall)
                Text(
                    "τ ≈ ${formatTau(d.tauHours)} · couplage air ↔ masse ${d.couplingLabel} · confiance ${d.confidenceLabel} ${(d.confidence * 100).toInt()} %",
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    String.format(
                        Locale.FRANCE,
                        "Flux signé actuel : %+.3f °C/h · %s · basé sur %s",
                        d.currentFluxCPerHour,
                        d.fluxLabel,
                        d.sourceRoom
                    ),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    "Diagnostic : ${d.cleanHours} h propres · ${d.plateauHours} plateau(x) · RMSE dérivée ${String.format(Locale.FRANCE, "%.3f", d.fitRmse)} °C/h",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
fun ThermalBusyOverlay(
    progressText: String?,
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    showTemp: Map<Long, Boolean>,
    bounds: LongRange?,
    modifier: Modifier = Modifier
) {
    val transition = rememberInfiniteTransition(label = "thermal-work")
    val angle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(1400, easing = LinearEasing)),
        label = "thermal-gear"
    )
    val colors = listOf(
        MaterialTheme.colorScheme.primary,
        MaterialTheme.colorScheme.tertiary,
        MaterialTheme.colorScheme.secondary,
        MaterialTheme.colorScheme.error
    )

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.97f))
    ) {
        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(
                    Icons.Default.Settings,
                    contentDescription = "Calcul thermique en cours",
                    modifier = Modifier.size(26.dp).graphicsLayer { rotationZ = angle },
                    tint = MaterialTheme.colorScheme.primary
                )
                Column(Modifier.weight(1f)) {
                    Text("FabData calcule…", fontWeight = FontWeight.Bold)
                    Text(
                        progressText ?: "Traitement thermique en cours",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2
                    )
                }
            }

            val b = bounds
            val visible = if (b == null) emptyList() else sensors
                .filter { showTemp[it.id] == true }
                .flatMap { sensor -> sampleMap[sensor.id].orEmpty().filter { it.timestamp in b } }
            if (b != null && visible.size >= 2) {
                val low = visible.minOf { it.temperature }
                val high = visible.maxOf { it.temperature }
                val range = (high - low).coerceAtLeast(0.5)
                val span = (b.last - b.first).coerceAtLeast(1L)
                Canvas(
                    Modifier.fillMaxWidth().height(68.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f), RoundedCornerShape(10.dp))
                ) {
                    sensors.filter { showTemp[it.id] == true }.forEachIndexed { colorIndex, sensor ->
                        val pts = sampleMap[sensor.id].orEmpty().filter { it.timestamp in b }.sortedBy { it.timestamp }
                        if (pts.size >= 2) {
                            val path = Path()
                            var prev: SamplePoint? = null
                            pts.forEach { p ->
                                val x = ((p.timestamp - b.first).toDouble() / span.toDouble()).toFloat() * size.width
                                val y = size.height - (((p.temperature - low) / range).toFloat() * size.height)
                                val gap = prev?.let { p.timestamp - it.timestamp } ?: 0L
                                if (prev == null || gap > 6L * 60L * 60L * 1000L) path.moveTo(x, y) else path.lineTo(x, y)
                                prev = p
                            }
                            drawPath(
                                path,
                                colors[colorIndex % colors.size].copy(alpha = 0.86f),
                                style = Stroke(width = 1.8.dp.toPx())
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun formatTau(hours: Double): String = if (hours >= 48.0) {
    val days = hours / 24.0
    String.format(Locale.FRANCE, "%.1f jours", days)
} else {
    String.format(Locale.FRANCE, "%.0f h", hours)
}
