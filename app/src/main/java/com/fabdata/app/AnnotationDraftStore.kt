package com.fabdata.app

import android.content.Context

data class AnnotationDraft(
    val timestamp: Long,
    val dateText: String,
    val title: String,
    val note: String,
    val sensorId: Long?,
    val roomName: String,
    val type: String
)

class AnnotationDraftStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_annotation_drafts", Context.MODE_PRIVATE)

    fun load(key: String): AnnotationDraft? {
        if (!prefs.getBoolean("$key.exists", false)) return null
        val sensor = prefs.getLong("$key.sensor", Long.MIN_VALUE).let { if (it == Long.MIN_VALUE) null else it }
        return AnnotationDraft(
            timestamp = prefs.getLong("$key.timestamp", System.currentTimeMillis()),
            dateText = prefs.getString("$key.date_text", "").orEmpty(),
            title = prefs.getString("$key.title", "").orEmpty(),
            note = prefs.getString("$key.note", "").orEmpty(),
            sensorId = sensor,
            roomName = prefs.getString("$key.room", "").orEmpty(),
            type = prefs.getString("$key.type", "").orEmpty()
        )
    }

    fun save(key: String, draft: AnnotationDraft) {
        prefs.edit()
            .putBoolean("$key.exists", true)
            .putLong("$key.timestamp", draft.timestamp)
            .putString("$key.date_text", draft.dateText)
            .putString("$key.title", draft.title)
            .putString("$key.note", draft.note)
            .putLong("$key.sensor", draft.sensorId ?: Long.MIN_VALUE)
            .putString("$key.room", draft.roomName)
            .putString("$key.type", draft.type)
            .apply()
    }

    fun clear(key: String) {
        prefs.edit()
            .remove("$key.exists")
            .remove("$key.timestamp")
            .remove("$key.date_text")
            .remove("$key.title")
            .remove("$key.note")
            .remove("$key.sensor")
            .remove("$key.room")
            .remove("$key.type")
            .apply()
    }
}
