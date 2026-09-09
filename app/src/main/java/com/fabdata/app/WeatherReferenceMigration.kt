package com.fabdata.app

import android.content.Context

data class WeatherReferenceMigrationState(
    val oldKey: String,
    val oldLabel: String,
    val oldStationId: String,
    val newKey: String,
    val newLabel: String,
    val newStationId: String,
    val switchedAt: Long,
    val keepOldChosen: Boolean,
    val oldHistoryDeleted: Boolean,
    val reconstructedDepthDays: Int,
    val lastActionAt: Long
)

/**
 * Persistent user-visible migration journal for an exterior weather-reference change.
 *
 * Deliberately NOT auto-cleared: the three actions remain visible after the switch and
 * after app restarts so the user can postpone historical work. This store never deletes
 * data itself; destructive work stays explicit in the UI/service layer.
 */
class WeatherReferenceMigrationStore(context: Context) {
    private val prefs = context.getSharedPreferences(
        "fabdata_weather_reference_migration",
        Context.MODE_PRIVATE
    )

    fun recordSwitch(old: WeatherReference, new: WeatherReference) {
        if (old.key == new.key) return
        val now = System.currentTimeMillis()
        prefs.edit()
            .putString("old_key", old.key)
            .putString("old_label", old.label)
            .putString("old_station_id", old.stationId)
            .putString("new_key", new.key)
            .putString("new_label", new.label)
            .putString("new_station_id", new.stationId)
            .putLong("switched_at", now)
            .putBoolean("keep_old_chosen", false)
            .putBoolean("old_history_deleted", false)
            .putInt("reconstructed_depth_days", 0)
            .putLong("last_action_at", now)
            .apply()
    }

    fun load(): WeatherReferenceMigrationState? {
        val oldKey = prefs.getString("old_key", null) ?: return null
        val newKey = prefs.getString("new_key", null) ?: return null
        return WeatherReferenceMigrationState(
            oldKey = oldKey,
            oldLabel = prefs.getString("old_label", oldKey) ?: oldKey,
            oldStationId = prefs.getString("old_station_id", "") ?: "",
            newKey = newKey,
            newLabel = prefs.getString("new_label", newKey) ?: newKey,
            newStationId = prefs.getString("new_station_id", "") ?: "",
            switchedAt = prefs.getLong("switched_at", 0L),
            keepOldChosen = prefs.getBoolean("keep_old_chosen", false),
            oldHistoryDeleted = prefs.getBoolean("old_history_deleted", false),
            reconstructedDepthDays = prefs.getInt("reconstructed_depth_days", 0).coerceAtLeast(0),
            lastActionAt = prefs.getLong("last_action_at", 0L)
        )
    }

    fun markKeepOld() {
        if (load() == null) return
        prefs.edit()
            .putBoolean("keep_old_chosen", true)
            .putLong("last_action_at", System.currentTimeMillis())
            .apply()
    }

    fun markOldDeleted() {
        if (load() == null) return
        prefs.edit()
            .putBoolean("old_history_deleted", true)
            .putBoolean("keep_old_chosen", false)
            .putLong("last_action_at", System.currentTimeMillis())
            .apply()
    }

    fun addReconstructedDepth(days: Int) {
        val current = load() ?: return
        val next = (current.reconstructedDepthDays + days.coerceAtLeast(0)).coerceAtMost(3650)
        setReconstructedDepth(next)
    }

    /** v0.20.9 : cette valeur est un cache de la profondeur CONTINUE réellement observée. */
    fun setReconstructedDepth(days: Int) {
        if (load() == null) return
        prefs.edit()
            .putInt("reconstructed_depth_days", days.coerceIn(0, 3650))
            .putLong("last_action_at", System.currentTimeMillis())
            .apply()
    }
}
