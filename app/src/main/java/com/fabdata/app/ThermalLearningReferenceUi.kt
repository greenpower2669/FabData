package com.fabdata.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private const val LEARNING_DAY_MS = 24L * 60L * 60L * 1000L

private enum class LearningReferenceTone { OK, WARNING, ERROR, EMPTY }

private data class LearningReferenceUiState(
    val activeLabel: String,
    val modelLabel: String?,
    val weatherFrom: Long?,
    val weatherTo: Long?,
    val calibrationFrom: Long?,
    val calibrationTo: Long?,
    val status: String,
    val detail: String,
    val tone: LearningReferenceTone
)

/**
 * Explicit, read-only provenance panel for the frozen thermal model.
 * It never trains or recalculates anything; it only makes reference/history coherence visible.
 */
@Composable
fun ThermalLearningReferenceStatusCard(
    db: FabDataDb,
    reference: WeatherReference,
    refreshToken: Int
) {
    val context = LocalContext.current
    val modelStore = remember { ThermalTrainedModelStore(context) }
    var state by remember(reference.key) { mutableStateOf<LearningReferenceUiState?>(null) }

    LaunchedEffect(reference.key, refreshToken) {
        state = withContext(Dispatchers.IO) {
            val model = modelStore.loadAny()
            val dirty = modelStore.isDirty()
            val dirtyReason = modelStore.dirtyReason()
            val range = db.readableDatabase.rawQuery(
                """
                SELECT MIN(timestamp), MAX(timestamp)
                FROM weather_reference_samples
                WHERE reference_key=? AND source<>'forecast'
                """.trimIndent(),
                arrayOf(reference.key)
            ).use { c ->
                if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) null
                else c.getLong(0) to c.getLong(1)
            }

            val modelLabel = model?.let { trained ->
                WeatherReferenceCatalog.byKeyOrNull(trained.referenceKey)?.label
                    ?: WeatherReferenceStore(db).referenceMetadata(trained.referenceKey)?.asReference()?.label
                    ?: listOf(trained.referenceCity, trained.referenceStationId)
                        .filter { it.isNotBlank() }
                        .joinToString(" · ")
                        .ifBlank { trained.referenceKey }
            }
            val mismatch = model != null && model.referenceKey != reference.key
            val historyExtended = model != null && !mismatch && range != null &&
                model.calibrationFrom > 0L && range.first < model.calibrationFrom - LEARNING_DAY_MS

            val statusTriple = when {
                model == null -> Triple(
                    "Modèle thermique non entraîné",
                    "La référence météo est prête, mais aucun modèle figé n'est encore disponible.",
                    LearningReferenceTone.EMPTY
                )
                mismatch -> Triple(
                    "Référence météo différente · réentraînement requis",
                    "Le modèle figé appartient à une autre référence météo. Aucun réentraînement automatique n'est lancé.",
                    LearningReferenceTone.ERROR
                )
                dirty -> Triple(
                    "Modèle à réentraîner",
                    dirtyReason?.let { "$it · réentraînement manuel requis" }
                        ?: "La sélection ou la configuration a changé · réentraînement manuel requis.",
                    LearningReferenceTone.WARNING
                )
                historyExtended -> Triple(
                    "Historique météo étendu · réentraînement requis pour en profiter",
                    "La référence contient désormais des données antérieures à la calibration du modèle. Le modèle reste figé tant que tu ne relances pas l'entraînement.",
                    LearningReferenceTone.WARNING
                )
                else -> Triple(
                    "Modèle figé · référence météo inchangée",
                    "Le modèle utilise toujours la même référence. Les nouvelles mesures et prévisions n'entraînent pas automatiquement le modèle.",
                    LearningReferenceTone.OK
                )
            }

            LearningReferenceUiState(
                activeLabel = reference.label,
                modelLabel = modelLabel,
                weatherFrom = range?.first,
                weatherTo = range?.second,
                calibrationFrom = model?.calibrationFrom,
                calibrationTo = model?.calibrationTo,
                status = statusTriple.first,
                detail = statusTriple.second,
                tone = statusTriple.third
            )
        }
    }

    val current = state ?: return
    val container = when (current.tone) {
        LearningReferenceTone.OK -> MaterialTheme.colorScheme.secondaryContainer
        LearningReferenceTone.WARNING -> MaterialTheme.colorScheme.tertiaryContainer
        LearningReferenceTone.ERROR -> MaterialTheme.colorScheme.errorContainer
        LearningReferenceTone.EMPTY -> MaterialTheme.colorScheme.surfaceVariant
    }
    val content = when (current.tone) {
        LearningReferenceTone.ERROR -> MaterialTheme.colorScheme.onErrorContainer
        LearningReferenceTone.WARNING -> MaterialTheme.colorScheme.onTertiaryContainer
        LearningReferenceTone.OK -> MaterialTheme.colorScheme.onSecondaryContainer
        LearningReferenceTone.EMPTY -> MaterialTheme.colorScheme.onSurfaceVariant
    }

    Card(
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = container)
    ) {
        Column(
            Modifier.fillMaxWidth().padding(13.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            Text("Référence d’apprentissage", fontWeight = FontWeight.Bold, color = content)
            Text("Référence météo active : ${current.activeLabel}", color = content)
            Text(
                "Référence météo du modèle : ${current.modelLabel ?: "aucun modèle"}",
                fontWeight = FontWeight.SemiBold,
                color = content
            )
            Text(
                "Période météo disponible : ${formatLearningRange(current.weatherFrom, current.weatherTo)}",
                style = MaterialTheme.typography.bodySmall,
                color = content
            )
            if (current.calibrationFrom != null && current.calibrationTo != null &&
                current.calibrationFrom > 0L && current.calibrationTo > 0L
            ) {
                Text(
                    "Calibration du modèle : ${formatLearningRange(current.calibrationFrom, current.calibrationTo)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = content
                )
            }
            Text(current.status, fontWeight = FontWeight.Bold, color = content)
            Text(current.detail, style = MaterialTheme.typography.labelSmall, color = content)
            Text(
                "Référence terrain = réel prioritaire + reconstruction · Prévision météo H+24 = archive fixe · Prévision Fab H+24 = correction locale · Sol inertiel estimé = moteur thermique indépendant.",
                style = MaterialTheme.typography.labelSmall,
                color = content
            )
        }
    }
}

private val learningDateFormatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm").withZone(ZoneId.systemDefault())

private fun formatLearningRange(from: Long?, to: Long?): String =
    if (from == null || to == null) "indisponible"
    else "${learningDateFormatter.format(Instant.ofEpochMilli(from))} → ${learningDateFormatter.format(Instant.ofEpochMilli(to))}"
