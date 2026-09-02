package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Résumé commun utilisé par l'UI, qu'il s'agisse d'un export thermo classique
 * ou d'une sauvegarde FabData complète.
 */
data class FabDataImportSummary(
    val sourceName: String,
    val measurementsAdded: Int = 0,
    val measurementsDuplicates: Int = 0,
    val eventsAdded: Int = 0,
    val eventsDuplicates: Int = 0,
    val sensorsRestored: Int = 0,
    val invalid: Int = 0
)

data class FabDataBackupExportResult(
    val sensors: Int,
    val measurements: Int,
    val events: Int
)

fun ImportResult.toFabDataImportSummary() = FabDataImportSummary(
    sourceName = sourceName,
    measurementsAdded = added,
    measurementsDuplicates = duplicates,
    invalid = invalid
)

/**
 * Sauvegarde CSV réimportable de toute la base FabData.
 *
 * Le même bouton Import accepte :
 * - les CSV thermo-hygromètre d'origine ;
 * - les sauvegardes FabData produites par cette classe.
 *
 * Le format est décrit dans /formatexport.md.
 */
class FabDataBackup(private val context: Context, private val db: FabDataDb) {
    companion object {
        const val FORMAT_VERSION = "2"
        const val HEADER = "FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms,Source,Confiance,Reference_Station_ID,Reference_Ville,Calibration_Debut_ms,Calibration_Fin_ms,Model_Version"
    }

    private val dateFormatter = DateTimeFormatter.ofPattern("uuuu/MM/dd HH:mm:ss", Locale.ROOT)

    /**
     * Retourne null si le fichier n'est pas une sauvegarde FabData : l'appelant
     * peut alors le transmettre au parseur thermo standard.
     */
    fun importIfBackup(uri: Uri): FabDataImportSummary? {
        val sourceName = fileName(uri) ?: "FabData_sauvegarde.csv"
        val input = context.contentResolver.openInputStream(uri) ?: error("Impossible d’ouvrir le fichier")

        BufferedReader(InputStreamReader(input, Charsets.UTF_8)).use { reader ->
            val headerLine = reader.readLine()?.removePrefix("\uFEFF") ?: return null
            val header = splitCsv(headerLine, ',')
            if (header.firstOrNull()?.trim() != "FabData_Record") return null

            val index = header.mapIndexed { i, v -> v.trim() to i }.toMap()
            fun col(fields: List<String>, name: String): String = fields.getOrNull(index[name] ?: -1).orEmpty()

            var measurementsAdded = 0
            var measurementsDuplicates = 0
            var eventsAdded = 0
            var eventsDuplicates = 0
            var sensorsRestored = 0
            var invalid = 0

            val records = splitCsvRecords(reader.readText())
            db.inTransaction {
                records.forEach { line ->
                    if (line.isBlank()) return@forEach
                    try {
                        val fields = splitCsv(line, ',')
                        val record = col(fields, "FabData_Record").trim().uppercase(Locale.ROOT)
                        val formatVersion = col(fields, "Format_Version").trim()
                        if (formatVersion.isNotBlank() && formatVersion !in setOf("1", FORMAT_VERSION)) {
                            invalid++
                            return@forEach
                        }

                        val stableKey = col(fields, "Capteur_ID").trim()
                        val sensorName = col(fields, "Capteur").trim().ifBlank { stableKey.ifBlank { "Capteur" } }
                        val room = col(fields, "Piece").trim().ifBlank { sensorName }
                        val color = col(fields, "Couleur").trim().toIntOrNull()?.coerceIn(0, 7) ?: 0

                        when (record) {
                            "SENSOR" -> {
                                if (stableKey.isBlank()) {
                                    invalid++
                                } else {
                                    val sensor = db.getOrCreateSensor(stableKey, sensorName)
                                    db.updateSensor(sensor.id, sensorName, room, color)
                                    sensorsRestored++
                                }
                            }

                            "SAMPLE" -> {
                                if (stableKey.isBlank()) {
                                    invalid++
                                    return@forEach
                                }
                                val timestamp = parseTimestamp(
                                    col(fields, "Temps_Epoch_ms"),
                                    col(fields, "Temps")
                                )
                                val temperature = parseNumber(col(fields, "Temperature_Celsius"))
                                val humidity = parseNumber(col(fields, "Humidite_relative_Pourcentage"))
                                if (timestamp == null || temperature == null || humidity == null ||
                                    temperature !in -100.0..150.0 || humidity !in 0.0..100.0
                                ) {
                                    invalid++
                                } else {
                                    val sensor = db.getOrCreateSensor(stableKey, sensorName)
                                    db.updateSensor(sensor.id, sensorName, room, color)
                                    val source = PointSource.fromDb(col(fields, "Source"))
                                    val provenance = PointProvenance(
                                        source = source,
                                        confidence = parseNumber(col(fields, "Confiance"))?.coerceIn(0.0, 1.0),
                                        referenceStationId = col(fields, "Reference_Station_ID").trim().ifBlank { null },
                                        referenceCity = col(fields, "Reference_Ville").trim().ifBlank { null },
                                        calibrationFrom = col(fields, "Calibration_Debut_ms").trim().toLongOrNull(),
                                        calibrationTo = col(fields, "Calibration_Fin_ms").trim().toLongOrNull(),
                                        modelVersion = col(fields, "Model_Version").trim().ifBlank { null }
                                    )
                                    val write = PointSourceStore.upsertByPriority(
                                        db, sensor.id, timestamp, temperature, humidity, provenance
                                    )
                                    if (write == PriorityWriteResult.INSERTED || write == PriorityWriteResult.REPLACED) measurementsAdded++
                                    else measurementsDuplicates++
                                }
                            }

                            "EVENT" -> {
                                val timestamp = parseTimestamp(
                                    col(fields, "Temps_Epoch_ms"),
                                    col(fields, "Temps")
                                )
                                if (timestamp == null) {
                                    invalid++
                                    return@forEach
                                }
                                val title = col(fields, "Titre").trim().ifBlank { "Événement" }
                                val note = col(fields, "Note")
                                val type = col(fields, "Type").trim().ifBlank { null }
                                val eventRoom = col(fields, "Piece").trim().ifBlank { null }
                                val updatedAt = col(fields, "UpdatedAt_Epoch_ms").trim().toLongOrNull()
                                    ?: System.currentTimeMillis()

                                val sensorId = if (stableKey.isBlank()) {
                                    null
                                } else {
                                    // La ligne SENSOR/SAMPLE porte le vrai paramétrage de la pièce.
                                    // Un événement peut avoir un libellé de lieu différent : il ne doit
                                    // donc jamais écraser le nom de pièce du capteur au réimport.
                                    db.getOrCreateSensor(stableKey, sensorName).id
                                }

                                if (annotationExists(timestamp, title, note, sensorId, eventRoom, type)) {
                                    eventsDuplicates++
                                } else {
                                    val now = System.currentTimeMillis()
                                    val values = ContentValues().apply {
                                        put("timestamp", timestamp)
                                        put("title", title)
                                        put("note", note)
                                        if (sensorId == null) putNull("sensor_id") else put("sensor_id", sensorId)
                                        if (eventRoom.isNullOrBlank()) putNull("room_name") else put("room_name", eventRoom)
                                        if (type.isNullOrBlank()) putNull("type") else put("type", type)
                                        put("created_at", minOf(updatedAt, now))
                                        put("updated_at", updatedAt)
                                    }
                                    db.writableDatabase.insertOrThrow("annotations", null, values)
                                    eventsAdded++
                                }
                            }

                            "META" -> {
                                // Réservé aux évolutions futures du format.
                            }

                            else -> invalid++
                        }
                    } catch (_: Exception) {
                        invalid++
                    }
                }
            }

            return FabDataImportSummary(
                sourceName = sourceName,
                measurementsAdded = measurementsAdded,
                measurementsDuplicates = measurementsDuplicates,
                eventsAdded = eventsAdded,
                eventsDuplicates = eventsDuplicates,
                sensorsRestored = sensorsRestored,
                invalid = invalid
            )
        }
    }

    /** Sauvegarde capteurs + mesures + événements dans un seul CSV réimportable. */
    fun export(uri: Uri): FabDataBackupExportResult {
        val output = context.contentResolver.openOutputStream(uri, "wt")
            ?: error("Impossible de créer le fichier de sauvegarde")

        var sensorCount = 0
        var measurementCount = 0
        var eventCount = 0

        OutputStreamWriter(output, Charsets.UTF_8).buffered().use { writer ->
            writer.write(HEADER)
            writer.write("\n")

            // Ligne META : permet d'identifier rapidement le fichier même dans un tableur.
            writeRow(
                writer,
                listOf("META", FORMAT_VERSION, "", "FabData", "", "", "", "", "", "", "Sauvegarde complète FabData", "", "", System.currentTimeMillis().toString())
            )

            readableDatabase().rawQuery(
                "SELECT id, stable_key, name, room, color_index FROM sensors ORDER BY id",
                null
            ).use { c ->
                while (c.moveToNext()) {
                    writeRow(
                        writer,
                        listOf(
                            "SENSOR", FORMAT_VERSION,
                            c.getString(1), c.getString(2), c.getString(3), c.getInt(4).toString(),
                            "", "", "", "", "", "", "", ""
                        )
                    )
                    sensorCount++
                }
            }

            readableDatabase().rawQuery(
                """
                SELECT s.stable_key, s.name, s.room, s.color_index,
                       p.timestamp, p.temperature, p.humidity,
                       ps.source, ps.confidence, ps.reference_station_id, ps.reference_city,
                       ps.calibration_from, ps.calibration_to, ps.model_version
                FROM samples p
                JOIN sensors s ON s.id = p.sensor_id
                LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
                ORDER BY p.timestamp, s.id
                """.trimIndent(),
                null
            ).use { c ->
                while (c.moveToNext()) {
                    val ts = c.getLong(4)
                    writeRow(
                        writer,
                        listOf(
                            "SAMPLE", FORMAT_VERSION,
                            c.getString(0), c.getString(1), c.getString(2), c.getInt(3).toString(),
                            ts.toString(), formatTimestamp(ts),
                            c.getDouble(5).toString(), c.getDouble(6).toString(),
                            "", "", "", "",
                            PointSource.fromDb(if (c.isNull(7)) null else c.getString(7)).dbValue,
                            if (c.isNull(8)) "" else c.getDouble(8).toString(),
                            if (c.isNull(9)) "" else c.getString(9),
                            if (c.isNull(10)) "" else c.getString(10),
                            if (c.isNull(11)) "" else c.getLong(11).toString(),
                            if (c.isNull(12)) "" else c.getLong(12).toString(),
                            if (c.isNull(13)) "" else c.getString(13)
                        )
                    )
                    measurementCount++
                }
            }

            readableDatabase().rawQuery(
                """
                SELECT a.timestamp, a.title, a.note, a.room_name, a.type, a.updated_at,
                       s.stable_key, s.name, s.room, s.color_index
                FROM annotations a
                LEFT JOIN sensors s ON s.id = a.sensor_id
                ORDER BY a.timestamp, a.id
                """.trimIndent(),
                null
            ).use { c ->
                while (c.moveToNext()) {
                    val ts = c.getLong(0)
                    val stableKey = if (c.isNull(6)) "" else c.getString(6)
                    val sensorName = if (c.isNull(7)) "" else c.getString(7)
                    val sensorRoom = if (c.isNull(8)) "" else c.getString(8)
                    val eventRoom = if (c.isNull(3)) sensorRoom else c.getString(3)
                    val color = if (c.isNull(9)) "" else c.getInt(9).toString()
                    writeRow(
                        writer,
                        listOf(
                            "EVENT", FORMAT_VERSION,
                            stableKey, sensorName, eventRoom, color,
                            ts.toString(), formatTimestamp(ts),
                            "", "",
                            c.getString(1), c.getString(2),
                            if (c.isNull(4)) "" else c.getString(4),
                            if (c.isNull(5)) "" else c.getLong(5).toString()
                        )
                    )
                    eventCount++
                }
            }
        }

        return FabDataBackupExportResult(sensorCount, measurementCount, eventCount)
    }

    private fun readableDatabase() = db.readableDatabase

    private fun annotationExists(
        timestamp: Long,
        title: String,
        note: String,
        sensorId: Long?,
        roomName: String?,
        type: String?
    ): Boolean {
        db.readableDatabase.rawQuery(
            """
            SELECT 1 FROM annotations
            WHERE timestamp = ?
              AND title = ?
              AND note = ?
              AND COALESCE(sensor_id, -1) = ?
              AND COALESCE(room_name, '') = ?
              AND COALESCE(type, '') = ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                timestamp.toString(),
                title,
                note,
                (sensorId ?: -1L).toString(),
                roomName.orEmpty(),
                type.orEmpty()
            )
        ).use { c -> return c.moveToFirst() }
    }

    private fun parseTimestamp(epochRaw: String, formattedRaw: String): Long? {
        epochRaw.trim().toLongOrNull()?.let { return it }
        val text = formattedRaw.trim().trim('"')
        if (text.isBlank()) return null
        return try {
            LocalDateTime.parse(text, dateFormatter)
                .atZone(ZoneId.systemDefault())
                .toInstant()
                .toEpochMilli()
        } catch (_: Exception) {
            try { Instant.parse(text).toEpochMilli() } catch (_: Exception) { null }
        }
    }

    private fun parseNumber(raw: String): Double? = raw.trim().replace(',', '.').toDoubleOrNull()

    private fun formatTimestamp(epoch: Long): String =
        Instant.ofEpochMilli(epoch).atZone(ZoneId.systemDefault()).format(dateFormatter)

    private fun writeRow(writer: java.io.Writer, values: List<String>) {
        writer.write(values.joinToString(",") { csvEscape(it) })
        writer.write("\n")
    }

    private fun csvEscape(value: String): String {
        if (value.none { it == ',' || it == '"' || it == '\n' || it == '\r' }) return value
        return "\"${value.replace("\"", "\"\"")}\""
    }

    /**
     * Découpe le document en enregistrements CSV sans casser une note contenant
     * des retours à la ligne entre guillemets.
     */
    private fun splitCsvRecords(text: String): List<String> {
        val out = mutableListOf<String>()
        val row = StringBuilder()
        var quoted = false
        var i = 0
        while (i < text.length) {
            val ch = text[i]
            when {
                ch == '"' -> {
                    row.append(ch)
                    if (quoted && i + 1 < text.length && text[i + 1] == '"') {
                        row.append('"')
                        i++
                    } else {
                        quoted = !quoted
                    }
                }
                (ch == '\n' || ch == '\r') && !quoted -> {
                    if (ch == '\r' && i + 1 < text.length && text[i + 1] == '\n') i++
                    if (row.isNotEmpty()) {
                        out += row.toString()
                        row.clear()
                    }
                }
                else -> row.append(ch)
            }
            i++
        }
        if (row.isNotEmpty()) out += row.toString()
        return out
    }

    private fun splitCsv(line: String, delimiter: Char): List<String> {
        val out = mutableListOf<String>()
        val cell = StringBuilder()
        var quoted = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            when {
                ch == '"' && quoted && i + 1 < line.length && line[i + 1] == '"' -> {
                    cell.append('"')
                    i++
                }
                ch == '"' -> quoted = !quoted
                ch == delimiter && !quoted -> {
                    out += cell.toString()
                    cell.clear()
                }
                else -> cell.append(ch)
            }
            i++
        }
        out += cell.toString()
        return out
    }

    private fun fileName(uri: Uri): String? {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) return c.getString(0)
        }
        return uri.lastPathSegment
    }
}
