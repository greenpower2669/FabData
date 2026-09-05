package com.fabdata.app

import android.content.Context
import kotlin.math.ceil

private const val HISTORY_DAY_MS = 24L * 60L * 60L * 1000L
private const val HISTORY_MONTH_DAYS = 31

enum class HistoricalDebtState { PENDING, PAUSED, CANCELLED }

data class ThermalHistoryDebt(
    val referenceKey: String,
    val sensorId: Long,
    val from: Long,
    val to: Long,
    val reason: String,
    val state: HistoricalDebtState,
    val updatedAt: Long
) {
    val pendingDays: Int
        get() = ceil((to - from).coerceAtLeast(0L).toDouble() / HISTORY_DAY_MS.toDouble()).toInt()
            .coerceAtLeast(1)
}

data class ThermalHistoryWork(
    val referenceKey: String,
    val sensorId: Long,
    val requestedDays: Int,
    val firstMeasuredTimestamp: Long,
    val nextChunk: Int,
    val totalChunks: Int,
    val reason: String,
    val paused: Boolean
) {
    val oldestRequestedTimestamp: Long
        get() = firstMeasuredTimestamp - requestedDays.toLong() * HISTORY_DAY_MS

    fun nextRange(): LongRange? {
        if (nextChunk !in 0 until totalChunks) return null
        val start = oldestRequestedTimestamp + nextChunk.toLong() * HISTORY_MONTH_DAYS * HISTORY_DAY_MS
        val endExclusive = minOf(
            firstMeasuredTimestamp,
            start + HISTORY_MONTH_DAYS.toLong() * HISTORY_DAY_MS
        )
        if (endExclusive <= start) return null
        return start..(endExclusive - 1L)
    }
}

/**
 * Petit journal persistant de cohérence v0.18.
 *
 * Il ne journalise pas toutes les opérations : uniquement la plage historique qui doit
 * encore être remise à jour et, si une extension longue est en cours, le prochain morceau
 * mensuel à préparer. Ainsi aucune dette ancienne n'est silencieusement oubliée.
 */
class ThermalHistoryDebtStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_thermal_history_debt", Context.MODE_PRIVATE)

    fun loadDebt(): ThermalHistoryDebt? {
        val referenceKey = prefs.getString("debt_reference", null) ?: return null
        val from = prefs.getLong("debt_from", Long.MIN_VALUE)
        val to = prefs.getLong("debt_to", Long.MIN_VALUE)
        if (from == Long.MIN_VALUE || to == Long.MIN_VALUE || to <= from) return null
        return ThermalHistoryDebt(
            referenceKey = referenceKey,
            sensorId = prefs.getLong("debt_sensor", -1L),
            from = from,
            to = to,
            reason = prefs.getString("debt_reason", "Historique ancien à remettre à jour")
                ?: "Historique ancien à remettre à jour",
            state = runCatching {
                HistoricalDebtState.valueOf(prefs.getString("debt_state", HistoricalDebtState.PENDING.name)!!)
            }.getOrDefault(HistoricalDebtState.PENDING),
            updatedAt = prefs.getLong("debt_updated", 0L)
        )
    }

    fun recordDebt(
        referenceKey: String,
        sensorId: Long,
        from: Long,
        to: Long,
        reason: String,
        state: HistoricalDebtState = HistoricalDebtState.PENDING
    ) {
        if (to <= from) return
        val old = loadDebt()?.takeIf { it.referenceKey == referenceKey && it.sensorId == sensorId }
        val mergedFrom = minOf(old?.from ?: from, from)
        val mergedTo = maxOf(old?.to ?: to, to)
        prefs.edit()
            .putString("debt_reference", referenceKey)
            .putLong("debt_sensor", sensorId)
            .putLong("debt_from", mergedFrom)
            .putLong("debt_to", mergedTo)
            .putString("debt_reason", reason)
            .putString("debt_state", state.name)
            .putLong("debt_updated", System.currentTimeMillis())
            .apply()
    }

    fun setDebtState(state: HistoricalDebtState) {
        if (loadDebt() == null) return
        prefs.edit()
            .putString("debt_state", state.name)
            .putLong("debt_updated", System.currentTimeMillis())
            .apply()
    }

    fun clearDebt() {
        prefs.edit()
            .remove("debt_reference")
            .remove("debt_sensor")
            .remove("debt_from")
            .remove("debt_to")
            .remove("debt_reason")
            .remove("debt_state")
            .remove("debt_updated")
            .apply()
    }

    fun beginWork(
        referenceKey: String,
        sensorId: Long,
        requestedDays: Int,
        firstMeasuredTimestamp: Long,
        reason: String
    ): ThermalHistoryWork {
        val days = requestedDays.coerceAtLeast(1)
        val chunks = ceil(days.toDouble() / HISTORY_MONTH_DAYS.toDouble()).toInt().coerceAtLeast(1)
        val work = ThermalHistoryWork(
            referenceKey = referenceKey,
            sensorId = sensorId,
            requestedDays = days,
            firstMeasuredTimestamp = firstMeasuredTimestamp,
            nextChunk = 0,
            totalChunks = chunks,
            reason = reason,
            paused = false
        )
        saveWork(work)
        return work
    }

    fun loadWork(): ThermalHistoryWork? {
        val referenceKey = prefs.getString("work_reference", null) ?: return null
        val requestedDays = prefs.getInt("work_days", 0)
        val first = prefs.getLong("work_first_measured", Long.MIN_VALUE)
        val total = prefs.getInt("work_total_chunks", 0)
        if (requestedDays <= 0 || first == Long.MIN_VALUE || total <= 0) return null
        return ThermalHistoryWork(
            referenceKey = referenceKey,
            sensorId = prefs.getLong("work_sensor", -1L),
            requestedDays = requestedDays,
            firstMeasuredTimestamp = first,
            nextChunk = prefs.getInt("work_next_chunk", 0).coerceIn(0, total),
            totalChunks = total,
            reason = prefs.getString("work_reason", "Extension historique") ?: "Extension historique",
            paused = prefs.getBoolean("work_paused", false)
        )
    }

    fun advanceWork(): ThermalHistoryWork? {
        val work = loadWork() ?: return null
        val next = work.copy(nextChunk = (work.nextChunk + 1).coerceAtMost(work.totalChunks), paused = false)
        saveWork(next)
        return next
    }

    fun pauseWork() {
        loadWork()?.let { saveWork(it.copy(paused = true)) }
    }

    fun resumeWork() {
        loadWork()?.let { saveWork(it.copy(paused = false)) }
    }

    fun clearWork() {
        prefs.edit()
            .remove("work_reference")
            .remove("work_sensor")
            .remove("work_days")
            .remove("work_first_measured")
            .remove("work_next_chunk")
            .remove("work_total_chunks")
            .remove("work_reason")
            .remove("work_paused")
            .apply()
    }

    private fun saveWork(work: ThermalHistoryWork) {
        prefs.edit()
            .putString("work_reference", work.referenceKey)
            .putLong("work_sensor", work.sensorId)
            .putInt("work_days", work.requestedDays)
            .putLong("work_first_measured", work.firstMeasuredTimestamp)
            .putInt("work_next_chunk", work.nextChunk)
            .putInt("work_total_chunks", work.totalChunks)
            .putString("work_reason", work.reason)
            .putBoolean("work_paused", work.paused)
            .apply()
    }
}
