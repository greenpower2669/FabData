package com.fabdata.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.atomic.AtomicLong

enum class FabOperationState {
    RUNNING,
    CANCEL_REQUESTED,
    DONE,
    FAILED,
    CANCELLED
}

data class FabOperation(
    val id: Long,
    val key: String,
    val title: String,
    val startedAt: Long,
    val detail: String,
    val processed: Int = 0,
    val total: Int = 0,
    val state: FabOperationState = FabOperationState.RUNNING,
    val cancellable: Boolean = true,
    val finishedAt: Long? = null,
    val trigger: String = "interne",
    val priority: String = "NORMAL",
    val network: Boolean = false,
    val generation: Int? = null,
    val captureSlot: Long? = null,
    val mergedRequests: Int = 0
) {
    val active: Boolean
        get() = state == FabOperationState.RUNNING || state == FabOperationState.CANCEL_REQUESTED
}

/**
 * Arbitration des producteurs de données. Un import annonce sa priorité AVANT
 * d'attendre le verrou : les routines automatiques cessent d'en démarrer de nouvelles,
 * puis rendent la main au prochain point sûr. L'import ne partage donc plus SQLite
 * avec une météo automatique longue.
 */
object FabDataWorkArbiter {
    private val dataMutex = Mutex()
    private val stateLock = Any()
    private var criticalImports = 0

    fun criticalImportPending(): Boolean = synchronized(stateLock) { criticalImports > 0 }

    suspend fun <T> withCriticalImport(block: suspend () -> T): T {
        synchronized(stateLock) { criticalImports++ }
        return try {
            dataMutex.withLock { block() }
        } finally {
            synchronized(stateLock) { criticalImports = (criticalImports - 1).coerceAtLeast(0) }
        }
    }

    suspend fun <T> withDataProducer(block: suspend () -> T): T? {
        if (criticalImportPending()) return null
        return dataMutex.withLock {
            if (criticalImportPending()) null else block()
        }
    }
}

object FabOperationRegistry {
    private val nextId = AtomicLong(System.currentTimeMillis())
    val operations = mutableStateListOf<FabOperation>()

    @Synchronized
    fun tryStart(
        key: String,
        title: String,
        detail: String = "Démarrage…",
        cancellable: Boolean = true,
        trigger: String = "interne",
        priority: String = "NORMAL",
        network: Boolean = false,
        generation: Int? = null,
        captureSlot: Long? = null,
        mergedRequests: Int = 0
    ): Long? {
        if (operations.any { it.key == key && it.active }) return null
        val id = nextId.incrementAndGet()
        operations.add(
            0,
            FabOperation(
                id = id,
                key = key,
                title = title,
                startedAt = System.currentTimeMillis(),
                detail = detail,
                cancellable = cancellable,
                trigger = trigger,
                priority = priority,
                network = network,
                generation = generation,
                captureSlot = captureSlot,
                mergedRequests = mergedRequests
            )
        )
        trim()
        return id
    }

    @Synchronized
    fun update(id: Long?, detail: String, processed: Int = 0, total: Int = 0) {
        if (id == null) return
        val index = operations.indexOfFirst { it.id == id }
        if (index < 0) return
        val old = operations[index]
        if (!old.active) return
        operations[index] = old.copy(detail = detail, processed = processed, total = total)
    }

    @Synchronized
    fun requestCancel(id: Long) {
        val index = operations.indexOfFirst { it.id == id }
        if (index < 0) return
        val old = operations[index]
        if (old.state == FabOperationState.RUNNING && old.cancellable) {
            operations[index] = old.copy(
                state = FabOperationState.CANCEL_REQUESTED,
                detail = if (old.detail.contains("annulation", ignoreCase = true)) old.detail
                    else "${old.detail} · annulation demandée"
            )
        }
    }

    @Synchronized
    fun cancelRequested(id: Long?): Boolean {
        if (id == null) return false
        return operations.firstOrNull { it.id == id }?.state == FabOperationState.CANCEL_REQUESTED
    }

    @Synchronized
    fun ensureNotCancelled(id: Long?) {
        if (id == null) return
        if (operations.firstOrNull { it.id == id }?.state == FabOperationState.CANCEL_REQUESTED) {
            throw CancellationException("FabData operation cancellation requested")
        }
    }

    @Synchronized
    fun finish(id: Long?, detail: String = "Terminé") = finishAs(id, FabOperationState.DONE, detail)

    @Synchronized
    fun fail(id: Long?, detail: String) = finishAs(id, FabOperationState.FAILED, detail)

    @Synchronized
    fun cancelled(id: Long?, detail: String = "Annulé") = finishAs(id, FabOperationState.CANCELLED, detail)

    @Synchronized
    private fun finishAs(id: Long?, state: FabOperationState, detail: String) {
        if (id == null) return
        val index = operations.indexOfFirst { it.id == id }
        if (index < 0) return
        val old = operations[index]
        operations[index] = old.copy(
            state = state,
            detail = detail,
            finishedAt = System.currentTimeMillis()
        )
        trim()
    }

    @Synchronized
    fun discard(id: Long?) {
        if (id == null) return
        operations.removeAll { it.id == id }
    }

    @Synchronized
    fun clearFinished() {
        operations.removeAll { !it.active }
    }

    @Synchronized
    fun activeCount(): Int = operations.count { it.active }

    @Synchronized
    fun activeId(key: String): Long? = operations.firstOrNull { it.key == key && it.active }?.id

    @Synchronized
    fun requestYieldForImport() {
        operations.indices.forEach { index ->
            val old = operations[index]
            val lowerPriority = old.key == "ui-reload" || old.key.startsWith("weather:")
            if (old.active && old.cancellable && lowerPriority && old.state == FabOperationState.RUNNING) {
                operations[index] = old.copy(
                    state = FabOperationState.CANCEL_REQUESTED,
                    detail = "${old.detail} · priorité import, arrêt au prochain point sûr"
                )
            }
        }
    }

    @Synchronized
    private fun trim() {
        if (operations.size <= 16) return
        val keep = operations.take(16)
        operations.clear()
        operations.addAll(keep)
    }
}

@Composable
fun FabProcessActivityDialog(onDismiss: () -> Unit) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000L)
            now = System.currentTimeMillis()
        }
    }
    val rows = FabOperationRegistry.operations.toList()
    val activeCount = rows.count { it.active }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                if (activeCount > 0) "↕ Activité FabData · $activeCount en cours" else "↕ Activité FabData",
                fontWeight = FontWeight.Bold
            )
        },
        text = {
            Column(
                Modifier.fillMaxWidth().heightIn(max = 520.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                if (rows.isEmpty()) {
                    Text("Aucune routine enregistrée.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                rows.forEach { op ->
                    Card(shape = RoundedCornerShape(14.dp)) {
                        Column(
                            Modifier.fillMaxWidth().padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text(op.title, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                                Text(operationStateLabel(op.state), style = MaterialTheme.typography.labelMedium)
                            }
                            Text(
                                "Démarré ${formatOperationTime(op.startedAt)} · ${formatElapsed((op.finishedAt ?: now) - op.startedAt)}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text("Déclenché par : ${op.trigger}", style = MaterialTheme.typography.labelSmall)
                            Text(
                                "Priorité ${op.priority} · Réseau : ${if (op.network) "OUI" else "NON"}" +
                                    (op.generation?.let { " · génération #$it" } ?: "") +
                                    (if (op.mergedRequests > 0) " · fusionnées ${op.mergedRequests}" else ""),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            op.captureSlot?.let {
                                Text("Créneau : ${formatOperationTime(it)}", style = MaterialTheme.typography.labelSmall)
                            }
                            Text(op.detail, style = MaterialTheme.typography.bodySmall)
                            if (op.total > 0) {
                                val percent = (100 * op.processed / op.total.coerceAtLeast(1)).coerceIn(0, 100)
                                Text(
                                    "$percent % · ${op.processed}/${op.total}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.primary
                                )
                            }
                            if (op.active && op.cancellable) {
                                OutlinedButton(
                                    onClick = { FabOperationRegistry.requestCancel(op.id) },
                                    enabled = op.state == FabOperationState.RUNNING,
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text(if (op.state == FabOperationState.CANCEL_REQUESTED) "Annulation demandée…" else "Annuler")
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = onDismiss) { Text("Fermer") }
        },
        dismissButton = {
            if (rows.any { !it.active }) {
                TextButton(onClick = { FabOperationRegistry.clearFinished() }) { Text("Effacer terminées") }
            }
        }
    )
}

private fun operationStateLabel(state: FabOperationState): String = when (state) {
    FabOperationState.RUNNING -> "EN COURS"
    FabOperationState.CANCEL_REQUESTED -> "ARRÊT…"
    FabOperationState.DONE -> "TERMINÉ"
    FabOperationState.FAILED -> "ERREUR"
    FabOperationState.CANCELLED -> "ANNULÉ"
}

private fun formatOperationTime(epoch: Long): String =
    Instant.ofEpochMilli(epoch)
        .atZone(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm:ss"))

private fun formatElapsed(ms: Long): String {
    val totalSeconds = (ms.coerceAtLeast(0L) / 1000L)
    val hours = totalSeconds / 3600L
    val minutes = (totalSeconds % 3600L) / 60L
    val seconds = totalSeconds % 60L
    return when {
        hours > 0 -> "${hours} h ${minutes} min"
        minutes > 0 -> "${minutes} min ${seconds} s"
        else -> "${seconds} s"
    }
}
