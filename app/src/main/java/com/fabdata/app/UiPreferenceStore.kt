package com.fabdata.app

import android.content.Context

/**
 * Durable user-facing UI preferences.
 *
 * Keep only choices/orientation here, never transient process state.
 * Keys are intentionally stable across synthetic sensor-ID changes.
 */
class UiPreferenceStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_ui_preferences", Context.MODE_PRIVATE)

    fun curveTemperature(key: String): Boolean? =
        if (prefs.contains("curve_temp:$key")) prefs.getBoolean("curve_temp:$key", false) else null

    fun curveHumidity(key: String): Boolean? =
        if (prefs.contains("curve_humidity:$key")) prefs.getBoolean("curve_humidity:$key", false) else null

    fun saveCurveTemperature(key: String, visible: Boolean) {
        prefs.edit().putBoolean("curve_temp:$key", visible).apply()
    }

    fun saveCurveHumidity(key: String, visible: Boolean) {
        prefs.edit().putBoolean("curve_humidity:$key", visible).apply()
    }

    fun timePresetName(): String? = prefs.getString("time_preset", null)
    fun saveTimePresetName(value: String) { prefs.edit().putString("time_preset", value).apply() }

    fun showAllAnnotations(): Boolean = prefs.getBoolean("show_all_annotations", true)
    fun saveShowAllAnnotations(value: Boolean) { prefs.edit().putBoolean("show_all_annotations", value).apply() }

    fun windowCenter(): Long? = if (prefs.contains("window_center")) prefs.getLong("window_center", 0L) else null
    fun saveWindowCenter(value: Long?) {
        prefs.edit().apply {
            if (value == null) remove("window_center") else putLong("window_center", value)
        }.apply()
    }

    fun customViewSpan(): Long? = if (prefs.contains("custom_view_span")) prefs.getLong("custom_view_span", 0L) else null
    fun saveCustomViewSpan(value: Long?) {
        prefs.edit().apply {
            if (value == null) remove("custom_view_span") else putLong("custom_view_span", value)
        }.apply()
    }

    fun forecastArchiveExpanded(): Boolean = prefs.getBoolean("forecast_archive_expanded", false)
    fun saveForecastArchiveExpanded(value: Boolean) { prefs.edit().putBoolean("forecast_archive_expanded", value).apply() }

    fun bandChooserOpen(): Boolean = prefs.getBoolean("band_chooser_open", false)
    fun saveBandChooserOpen(value: Boolean) { prefs.edit().putBoolean("band_chooser_open", value).apply() }

    fun previewPresetName(): String? = prefs.getString("preview_preset", null)
    fun savePreviewPresetName(value: String) { prefs.edit().putString("preview_preset", value).apply() }

    fun previewZoom(): Float = prefs.getFloat("preview_zoom", 1f).coerceAtLeast(1f)
    fun savePreviewZoom(value: Float) { prefs.edit().putFloat("preview_zoom", value.coerceAtLeast(1f)).apply() }

    fun previewCenter(): Long? = if (prefs.contains("preview_center")) prefs.getLong("preview_center", 0L) else null
    fun savePreviewCenter(value: Long) { prefs.edit().putLong("preview_center", value).apply() }

    fun wideCenter(): Long? = if (prefs.contains("wide_center")) prefs.getLong("wide_center", 0L) else null
    fun saveWideCenter(value: Long) { prefs.edit().putLong("wide_center", value).apply() }
}
