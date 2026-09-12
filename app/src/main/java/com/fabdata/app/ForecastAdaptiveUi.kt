package com.fabdata.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun ForecastAdaptiveCard(
    db: FabDataDb,
    reference: WeatherReference,
    refreshToken: Int
) {
    var summary by remember(reference.key) { mutableStateOf<ForecastAdaptiveSummary?>(null) }
    var error by remember(reference.key) { mutableStateOf<String?>(null) }

    LaunchedEffect(reference.key, refreshToken) {
        val result = withContext(Dispatchers.IO) {
            runCatching { ForecastAdaptiveEngine(db).summary(reference.key) }
        }
        result.fold(
            onSuccess = { summary = it; error = null },
            onFailure = { error = it.message ?: "Prévision adaptative indisponible" }
        )
    }

    Card(shape = RoundedCornerShape(18.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp)
        ) {
            Text("Prévision Fab adaptative", fontWeight = FontWeight.Bold)
            Text(
                "H+3 · H+6 · H+12 · H+24 · apprentissage causal + tangente + détection de changement de régime. Les cadrans restent sur le H+24 historique actuel.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            error?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }

            val state = summary
            if (state == null && error == null) {
                Text("Analyse en arrière-plan…", style = MaterialTheme.typography.bodySmall)
            } else if (state != null) {
                FORECAST_ADAPTIVE_HORIZONS.forEach { horizon ->
                    val current = state.current.firstOrNull { it.horizonHour == horizon }
                    val evaluation = state.evaluations.firstOrNull { it.horizonHour == horizon }
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        Text("H+$horizon", fontWeight = FontWeight.Bold, modifier = Modifier.weight(0.19f))
                        Column(Modifier.weight(0.81f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            if (current == null) {
                                Text("En attente d'une émission fixe H+$horizon", style = MaterialTheme.typography.bodySmall)
                            } else {
                                val regime = when {
                                    current.regimeScore >= 0.66 -> "régime exceptionnel · présent prioritaire"
                                    current.regimeScore >= 0.34 -> "adaptation renforcée"
                                    else -> "régime stable · historique pertinent"
                                }
                                Text(
                                    "Météo ${one(current.baselineTemperature)}° → Fab ${one(current.adaptiveTemperature)}° · cible ${hour(current.targetAt)}",
                                    style = MaterialTheme.typography.bodySmall,
                                    fontWeight = FontWeight.SemiBold
                                )
                                Text(
                                    "$regime · tangente ${one(current.tangentTemperature)}° · n=${current.historySamples}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = if (current.regimeScore >= 0.66) MaterialTheme.colorScheme.tertiary
                                    else MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            if (evaluation != null && evaluation.samples > 0 &&
                                evaluation.baselineMae != null && evaluation.adaptiveMae != null
                            ) {
                                val gain = evaluation.gainC ?: 0.0
                                Text(
                                    "Validation n=${evaluation.samples} · MAE météo ${one(evaluation.baselineMae)}° · Fab ${one(evaluation.adaptiveMae)}° · gain ${signed(gain)}°",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = if (gain >= 0.0) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
                                )
                            } else {
                                Text(
                                    "Validation : les premières échéances doivent encore devenir terrain.",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

private val adaptiveTimeFormatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault())

private fun hour(timestamp: Long): String = adaptiveTimeFormatter.format(Instant.ofEpochMilli(timestamp))
private fun one(value: Double): String = String.format(Locale.FRANCE, "%.1f", value)
private fun signed(value: Double): String = String.format(Locale.FRANCE, "%+.2f", value)
