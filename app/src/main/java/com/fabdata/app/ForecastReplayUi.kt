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
 * Missing past slots may be bridged with the existing measured/reconstructed weather
 * reference, but those bridge points are display-only and are never training samples.
 */
private enum class ForecastReplayKind {
    ARCHIVED,
    CURRENT,
    BRIDGE
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
    val bridgeCount: Int
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

        // Existing real/reconstructed weather only fills holes on the left. It never
        // replaces an archived prediction and never enters the residual learner.
        val archivedBuckets = archived.map { replayHourBucket(it.timestamp) }.toSet()
        val bridgeCandidates = linkedMapOf<Long, ForecastReplayPoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT timestamp, temperature, source, confidence
            FROM weather_reference_samples
            WHERE reference_key=?
              AND source!='forecast'
              AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), now.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val ts = c.getLong(0)
                val bucket = replayHourBucket(ts)
                if (bucket in archivedBuckets) continue
                val source = PointSource.fromDb(c.getString(2))
                val point = ForecastReplayPoint(
                    timestamp = ts,
                    temperature = c.getDouble(1),
                    confidence = if (c.isNull(3)) 0.60 else c.getDouble(3).coerceIn(0.0, 1.0),
                    kind = ForecastReplayKind.BRIDGE
                )
                val existing = bridgeCandidates[bucket]
                if (existing == null || source.priority >= PointSource.RECONSTRUCTED.priority) {
                    bridgeCandidates[bucket] = point
                }
            }
        }

        val points = (bridgeCandidates.values + archived + future)
            .sortedBy { it.timestamp }

        return ForecastReplayState(
            from = from,
            to = to,
            now = now,
            points = points,
            archivedCount = archived.size,
            currentCount = future.size,
            bridgeCount = bridgeCandidates.size
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
                            "${state.bridgeCount} point(s) de continuité",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        "Les segments pointillés servent seulement à combler un trou d’affichage avec le réel/reconstruit existant ; ils ne servent jamais à entraîner le correcteur.",
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
    val bridgeColor = MaterialTheme.colorScheme.outline
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
                val bridge = a.kind == ForecastReplayKind.BRIDGE || b.kind == ForecastReplayKind.BRIDGE
                val color = when {
                    bridge -> bridgeColor
                    b.timestamp > state.now -> currentColor
                    else -> archivedColor
                }
                drawLine(
                    color = color.copy(alpha = if (bridge) 0.72f else 0.95f),
                    start = Offset(x(a.timestamp), y(a.temperature)),
                    end = Offset(x(b.timestamp), y(b.temperature)),
                    strokeWidth = if (bridge) 1.5.dp.toPx() else 2.4.dp.toPx(),
                    pathEffect = if (bridge) {
                        PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 5.dp.toPx()))
                    } else null
                )
            }
        }

        points.forEach { p ->
            val color = when (p.kind) {
                ForecastReplayKind.ARCHIVED -> archivedColor
                ForecastReplayKind.CURRENT -> currentColor
                ForecastReplayKind.BRIDGE -> bridgeColor
            }
            drawCircle(color.copy(alpha = if (p.kind == ForecastReplayKind.BRIDGE) 0.55f else 0.9f), 2.1.dp.toPx(), Offset(x(p.timestamp), y(p.temperature)))
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
        Text("┄ continuité", color = bridgeColor, style = MaterialTheme.typography.labelSmall)
    }
}

private const val REPLAY_HOUR_MS = 60L * 60L * 1000L
private fun replayHourBucket(ts: Long): Long = (ts / REPLAY_HOUR_MS) * REPLAY_HOUR_MS
