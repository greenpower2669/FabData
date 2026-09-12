package com.fabdata.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Read-only replay of the forecast memory.
 *
 * Left of "now": immutable forecast snapshots that really existed before their target.
 * Right of "now": the currently active forecast.
 * This curve is prediction-only. MEASURED and RECONSTRUCTED values never enter it.
 * Missing slots are transient estimates between prediction anchors and are never persisted.
 */
private enum class ForecastReplayKind {
    ARCHIVED,
    CURRENT,
    ESTIMATED
}

private data class ForecastReplayPoint(
    val timestamp: Long,
    val temperature: Double,
    val confidence: Double,
    val kind: ForecastReplayKind
)

private data class ForecastReplayState(
    val from: Long,
    val to: Long,
    val now: Long,
    val points: List<ForecastReplayPoint>,
    val archivedCount: Int,
    val currentCount: Int,
    val estimatedCount: Int
)

private data class ForecastArchiveReplayRow(
    val issuedAt: Long,
    val targetAt: Long,
    val temperature: Double,
    val confidence: Double
)

private class ForecastReplayStore(private val db: FabDataDb) {
    fun load(referenceKey: String, now: Long = System.currentTimeMillis()): ForecastReplayState {
        ForecastMemoryStore.ensure(db.writableDatabase)
        val from = now - 48L * REPLAY_HOUR_MS
        val to = now + 24L * REPLAY_HOUR_MS

        val archiveRows = mutableListOf<ForecastArchiveReplayRow>()
        db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, temperature, confidence
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=?
              AND target_ts BETWEEN ? AND ?
              AND issued_at < target_ts - 300000
            ORDER BY target_ts, issued_at
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                archiveRows += ForecastArchiveReplayRow(
                    issuedAt = c.getLong(0),
                    targetAt = c.getLong(1),
                    temperature = c.getDouble(2),
                    confidence = if (c.isNull(3)) 0.65 else c.getDouble(3).coerceIn(0.0, 1.0)
                )
            }
        }

        // For the past we deliberately keep a prediction that was approximately H+1.
        // This prevents a late refresh from rewriting what the app really predicted then.
        val archived = archiveRows
            .filter { it.targetAt <= now }
            .groupBy { replayHourBucket(it.targetAt) }
            .values
            .mapNotNull { group ->
                group.minByOrNull { abs((it.targetAt - it.issuedAt) - REPLAY_HOUR_MS) }
            }
            .sortedBy { it.targetAt }
            .map {
                ForecastReplayPoint(it.targetAt, it.temperature, it.confidence, ForecastReplayKind.ARCHIVED)
            }

        // The right side is the current forecast cache. If the cache is temporarily empty,
        // use the latest archived fetch for each future target without inventing new values.
        val activeFuture = mutableListOf<ForecastReplayPoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT timestamp, temperature, confidence
            FROM weather_reference_samples
            WHERE reference_key=?
              AND source='forecast'
              AND timestamp > ? AND timestamp <= ?
            ORDER BY timestamp
            """.trimIndent(),
            arrayOf(referenceKey, now.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                activeFuture += ForecastReplayPoint(
                    timestamp = c.getLong(0),
                    temperature = c.getDouble(1),
                    confidence = if (c.isNull(2)) 0.65 else c.getDouble(2).coerceIn(0.0, 1.0),
                    kind = ForecastReplayKind.CURRENT
                )
            }
        }
        val future = if (activeFuture.isNotEmpty()) {
            activeFuture
        } else {
            archiveRows
                .filter { it.targetAt > now && it.issuedAt <= now }
                .groupBy { replayHourBucket(it.targetAt) }
                .values
                .mapNotNull { group -> group.maxByOrNull { it.issuedAt } }
                .sortedBy { it.targetAt }
                .map {
                    ForecastReplayPoint(it.targetAt, it.temperature, it.confidence, ForecastReplayKind.CURRENT)
                }
        }

        // Build a single prediction-only chronology. For small gaps we estimate
        // between two prediction anchors. These estimates exist in RAM only.
        val anchors = (archived + future)
            .groupBy { replayHourBucket(it.timestamp) }
            .values
            .mapNotNull { group ->
                group.maxByOrNull { if (it.kind == ForecastReplayKind.CURRENT) 2 else 1 }
            }
            .sortedBy { it.timestamp }

        val points = mutableListOf<ForecastReplayPoint>()
        if (anchors.isNotEmpty()) {
            anchors.zipWithNext().forEach { (left, right) ->
                points += left
                val gap = right.timestamp - left.timestamp
                if (gap > REPLAY_HOUR_MS && gap <= 6L * REPLAY_HOUR_MS) {
                    var ts = replayHourBucket(left.timestamp) + REPLAY_HOUR_MS
                    while (ts < right.timestamp) {
                        val f = ((ts - left.timestamp).toDouble() / gap.toDouble()).coerceIn(0.0, 1.0)
                        points += ForecastReplayPoint(
                            timestamp = ts,
                            temperature = left.temperature + (right.temperature - left.temperature) * f,
                            confidence = (left.confidence + (right.confidence - left.confidence) * f).coerceIn(0.0, 1.0),
                            kind = ForecastReplayKind.ESTIMATED
                        )
                        ts += REPLAY_HOUR_MS
                    }
                }
            }
            points += anchors.last()
        }

        return ForecastReplayState(
            from = from,
            to = to,
            now = now,
            points = points,
            archivedCount = archived.size,
            currentCount = future.size,
            estimatedCount = points.count { it.kind == ForecastReplayKind.ESTIMATED }
        )
    }
}

@Composable
fun ForecastReplayCard(
    db: FabDataDb,
    reference: WeatherReference,
    refreshToken: Int,
    modifier: Modifier = Modifier
) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    var replay by remember(reference.key) { mutableStateOf<ForecastReplayState?>(null) }

    LaunchedEffect(expanded, reference.key, refreshToken) {
        if (!expanded) return@LaunchedEffect
        loading = true
        replay = withContext(Dispatchers.IO) { ForecastReplayStore(db).load(reference.key) }
        loading = false
    }

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.34f))
    ) {
        Column(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Mémoire prévisionnelle", fontWeight = FontWeight.Bold)
                    Text(
                        "Prévisions sauvegardées à gauche · prévision active à droite",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                OutlinedButton(onClick = { expanded = !expanded }) {
                    Text(if (expanded) "Masquer" else "Afficher")
                }
            }

            if (expanded) {
                if (loading && replay == null) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.width(24.dp).height(24.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                        Text("Lecture de l’historique prévisionnel…", style = MaterialTheme.typography.bodySmall)
                    }
                }

                replay?.let { state ->
                    ForecastReplayChart(state)
                    Text(
                        "${state.archivedCount} prévision(s) archivées · ${state.currentCount} future(s) · " +
                            "${state.estimatedCount} estimation(s) visuelle(s)",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        "Cette courbe n’utilise jamais le réel ni les données reconstruites. Les pointillés sont estimés uniquement entre deux prévisions et ne sont jamais sauvegardés.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
private fun ForecastReplayChart(state: ForecastReplayState) {
    val archivedColor = Color(0xFF2C6EBD)
    val currentColor = Color(0xFFE28A1A)
    val estimatedColor = MaterialTheme.colorScheme.outline
    val nowColor = MaterialTheme.colorScheme.primary
    val surface = MaterialTheme.colorScheme.surface.copy(alpha = 0.52f)
    val textColor = MaterialTheme.colorScheme.onSurfaceVariant

    val points = state.points
    val minTemperature = points.minOfOrNull { it.temperature } ?: 0.0
    val maxTemperature = points.maxOfOrNull { it.temperature } ?: 1.0
    val margin = max(0.5, (maxTemperature - minTemperature) * 0.12)
    val low = minTemperature - margin
    val high = maxTemperature + margin
    val tempSpan = (high - low).coerceAtLeast(1.0)
    val timeSpan = (state.to - state.from).coerceAtLeast(1L)

    Canvas(
        Modifier.fillMaxWidth().height(176.dp)
            .background(surface, RoundedCornerShape(12.dp))
    ) {
        fun x(ts: Long): Float = (((ts - state.from).toDouble() / timeSpan.toDouble()) * size.width)
            .toFloat().coerceIn(0f, size.width)
        fun y(temp: Double): Float = (size.height - (((temp - low) / tempSpan) * size.height).toFloat())
            .coerceIn(0f, size.height)

        val nowX = x(state.now)
        drawLine(
            color = nowColor.copy(alpha = 0.68f),
            start = Offset(nowX, 0f),
            end = Offset(nowX, size.height),
            strokeWidth = 2.dp.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(8.dp.toPx(), 6.dp.toPx()))
        )

        points.zipWithNext().forEach { (a, b) ->
            val gap = b.timestamp - a.timestamp
            if (gap <= 4L * REPLAY_HOUR_MS) {
                val estimated = a.kind == ForecastReplayKind.ESTIMATED || b.kind == ForecastReplayKind.ESTIMATED
                val color = when {
                    estimated -> estimatedColor
                    b.timestamp > state.now -> currentColor
                    else -> archivedColor
                }
                drawLine(
                    color = color.copy(alpha = if (estimated) 0.72f else 0.95f),
                    start = Offset(x(a.timestamp), y(a.temperature)),
                    end = Offset(x(b.timestamp), y(b.temperature)),
                    strokeWidth = if (estimated) 1.5.dp.toPx() else 2.4.dp.toPx(),
                    pathEffect = if (estimated) {
                        PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 5.dp.toPx()))
                    } else null
                )
            }
        }

        points.forEach { p ->
            val color = when (p.kind) {
                ForecastReplayKind.ARCHIVED -> archivedColor
                ForecastReplayKind.CURRENT -> currentColor
                ForecastReplayKind.ESTIMATED -> estimatedColor
            }
            drawCircle(color.copy(alpha = if (p.kind == ForecastReplayKind.ESTIMATED) 0.50f else 0.9f), 2.1.dp.toPx(), Offset(x(p.timestamp), y(p.temperature)))
        }
    }

    Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text("−48 h", style = MaterialTheme.typography.labelSmall, color = textColor)
        Text("maintenant", style = MaterialTheme.typography.labelSmall, color = nowColor, fontWeight = FontWeight.SemiBold)
        Text("+24 h", style = MaterialTheme.typography.labelSmall, color = textColor)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("● archive", color = archivedColor, style = MaterialTheme.typography.labelSmall)
        Text("● futur", color = currentColor, style = MaterialTheme.typography.labelSmall)
        Text("┄ estimé", color = estimatedColor, style = MaterialTheme.typography.labelSmall)
    }
}

private const val REPLAY_HOUR_MS = 60L * 60L * 1000L
private fun replayHourBucket(ts: Long): Long = (ts / REPLAY_HOUR_MS) * REPLAY_HOUR_MS
