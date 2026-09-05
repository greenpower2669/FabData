package com.fabdata.app

import android.content.Context

data class StationSectorMemory(
    val label: String,
    val latitude: Double,
    val longitude: Double,
    val radiusKm: Int
) {
    fun anchor(): StationSearchAnchor = StationSearchAnchor(label, latitude, longitude)
}

/**
 * Restaure la mémoire de secteur introduite en v0.13 sans toucher au format des mesures.
 * Les clés sont volontairement les anciennes clés v0.13 afin de récupérer automatiquement
 * le secteur déjà enregistré sur les installations qui l'avaient utilisé.
 */
class WeatherStationSectorPrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)

    fun load(): StationSectorMemory? {
        val latitude = prefs.getString("sector_latitude", null)?.toDoubleOrNull() ?: return null
        val longitude = prefs.getString("sector_longitude", null)?.toDoubleOrNull() ?: return null
        if (latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return null
        return StationSectorMemory(
            label = prefs.getString("sector_label", null).orEmpty().ifBlank { "Secteur enregistré" },
            latitude = latitude,
            longitude = longitude,
            radiusKm = prefs.getInt("sector_radius_km", 50).coerceIn(10, 150)
        )
    }

    fun save(anchor: StationSearchAnchor, radiusKm: Int) {
        prefs.edit()
            .putString("sector_label", anchor.label)
            .putString("sector_latitude", anchor.latitude.toString())
            .putString("sector_longitude", anchor.longitude.toString())
            .putInt("sector_radius_km", radiusKm.coerceIn(10, 150))
            .apply()
    }

    fun recordScan(candidateCount: Int, autoKey: String?, error: String? = null) {
        prefs.edit()
            .putLong("sector_last_scan_at", System.currentTimeMillis())
            .putInt("sector_last_candidate_count", candidateCount.coerceAtLeast(0))
            .putString("sector_last_auto_key", autoKey)
            .putString("sector_last_scan_error", error)
            .apply()
    }

    fun lastScanAt(): Long = prefs.getLong("sector_last_scan_at", 0L)
    fun lastCandidateCount(): Int = prefs.getInt("sector_last_candidate_count", 0)
    fun lastAutoKey(): String? = prefs.getString("sector_last_auto_key", null)
    fun lastScanError(): String? = prefs.getString("sector_last_scan_error", null)
}
