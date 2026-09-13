package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.net.Uri
import android.provider.OpenableColumns
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Résumé commun utilisé par l'UI pour les imports FabData et thermo classiques. */
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

/** Sauvegarde CSV réimportable de toute la base FabData. */
class FabDataBackup(private val context: Context, private val db: FabDataDb) {
    companion object {
        const val FORMAT_VERSION = "4"
        const val HEADER = "FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms,Source,Confiance,Reference_Station_ID,Reference_Ville,Calibration_Debut_ms,Calibration_Fin_ms,Model_Version"
        private const val PROGRESS_STEP = 500
    }

    private val dateFormatter = DateTimeFormatter.ofPattern("uuuu/MM/dd HH:mm:ss", Locale.ROOT)

    /**
     * Retourne null si le document n'est pas une sauvegarde FabData : l'appelant
     * peut alors le transmettre au parseur thermo standard.
     *
     * v0.22.x import fix :
     * - capteurs mis en cache, donc plus de SELECT/MAX + UPDATE pour chaque SAMPLE ;
     * - chemin rapide pour les vraies mesures, qui sont la très grande majorité des gros exports ;
     * - réconciliation de dominance calculée une fois par capteur et non une fois par point ;
     * - progression réelle par enregistrement dans le panneau Activité FabData ;
     * - première anomalie conservée au lieu d'avaler silencieusement toutes les exceptions.
     */
    fun importIfBackup(uri: Uri): FabDataImportSummary? {
        val sourceName = fileName(uri) ?: "FabData_sauvegarde.csv"
        val input = context.contentResolver.openInputStream(uri) ?: error("Impossible d’ouvrir le fichier")

        BufferedReader(InputStreamReader(input, Charsets.UTF_8)).use { reader ->
            val headerLine = reader.readLine()?.removePrefix("\uFEFF") ?: return null
            val header = splitCsv(headerLine, ',')
            if (header.firstOrNull()?.trim() != "FabData_Record") return null

            val opId = FabOperationRegistry.tryStart(
                key = "backup-import",
                title = "Import sauvegarde FabData",
                detail = "Lecture et validation de $sourceName…",
                cancellable = false
            )

            try {
                val index = header.mapIndexed { i, v -> v.trim() to i }.toMap()
                fun col(fields: List<String>, name: String): String =
                    fields.getOrNull(index[name] ?: -1).orEmpty()

                var measurementsAdded = 0
                var measurementsDuplicates = 0
                var eventsAdded = 0
                var eventsDuplicates = 0
                var sensorsRestored = 0
                var invalid = 0
                var firstProblem: String? = null

                // 21 Mo reste raisonnable en mémoire ; le goulet d'étranglement historique
                // était SQLite par point. Garder les records permet aussi un contrôle v4
                // complet AVANT la moindre écriture dans la base.
                val records = splitCsvRecords(reader.readText())
                fun recordType(line: String): String =
                    splitCsv(line, ',').firstOrNull().orEmpty().trim().uppercase(Locale.ROOT)

                FabOperationRegistry.update(opId, "Contrôle d’intégrité…", 0, records.size)

                val recordTypes = records.map(::recordType)
                val metaIndex = recordTypes.indexOfFirst { it == "META" }
                val metaFields = if (metaIndex >= 0) splitCsv(records[metaIndex], ',') else emptyList()
                val fileVersion = col(metaFields, "Format_Version").trim()

                if (fileVersion == FORMAT_VERSION) {
                    val lastIndex = records.indexOfLast { it.isNotBlank() }
                    if (lastIndex < 0 || recordTypes.getOrNull(lastIndex) != "BACKUP_END") {
                        error("Sauvegarde v4 incomplète : marqueur de fin absent")
                    }
                    val footer = splitCsv(records[lastIndex], ',')
                    val expected = col(footer, "Note").split(';').mapNotNull { token ->
                        val pair = token.split('=', limit = 2)
                        if (pair.size == 2) pair[0].trim() to pair[1].trim().toIntOrNull() else null
                    }.toMap()
                    val actualSensors = recordTypes.count { it == "SENSOR" }
                    val actualSamples = recordTypes.count { it == "SAMPLE" }
                    val actualEvents = recordTypes.count { it == "EVENT" }
                    if (expected["sensors"] != actualSensors ||
                        expected["measurements"] != actualSamples ||
                        expected["events"] != actualEvents
                    ) {
                        error(
                            "Sauvegarde v4 incomplète : compteurs d’intégrité incohérents " +
                                "(attendus ${expected["sensors"]}/${expected["measurements"]}/${expected["events"]}, " +
                                "lus $actualSensors/$actualSamples/$actualEvents)"
                        )
                    }
                }

                val sensorCache = mutableMapOf<String, Sensor>()
                val measuredRanges = mutableMapOf<Long, LongArray>()
                val v3Support = FabDataBackupV3Support(context, db)

                fun sensorForSample(stableKey: String, name: String, room: String, color: Int): Sensor {
                    sensorCache[stableKey]?.let { return it }
                    val sensor = db.getOrCreateSensor(stableKey, name)
                    db.updateSensor(sensor.id, name, room, color)
                    sensorCache[stableKey] = sensor
                    return sensor
                }

                fun sensorForEvent(stableKey: String, name: String): Sensor {
                    sensorCache[stableKey]?.let { return it }
                    // Un événement ne doit jamais écraser la pièce du capteur.
                    return db.getOrCreateSensor(stableKey, name).also { sensorCache[stableKey] = it }
                }

                fun noteMeasuredRange(sensorId: Long, timestamp: Long) {
                    val range = measuredRanges.getOrPut(sensorId) { longArrayOf(timestamp, timestamp) }
                    if (timestamp < range[0]) range[0] = timestamp
                    if (timestamp > range[1]) range[1] = timestamp
                }

                FabOperationRegistry.update(opId, "Import des enregistrements…", 0, records.size)

                db.inTransaction {
                    records.forEachIndexed { recordIndex, line ->
                        if (line.isBlank()) return@forEachIndexed
                        var record = recordTypes.getOrElse(recordIndex) { "?" }
                        try {
                            val fields = splitCsv(line, ',')
                            record = col(fields, "FabData_Record").trim().uppercase(Locale.ROOT)
                            val formatVersion = col(fields, "Format_Version").trim()
                            if (formatVersion.isNotBlank() && formatVersion !in setOf("1", "2", "3", FORMAT_VERSION)) {
                                invalid++
                                if (firstProblem == null) {
                                    firstProblem = "ligne ${recordIndex + 2} · version $formatVersion non prise en charge"
                                }
                                return@forEachIndexed
                            }

                            if (recordIndex % PROGRESS_STEP == 0 || recordIndex == records.lastIndex) {
                                val suffix = if (invalid > 0) " · $invalid anomalie(s)" else ""
                                FabOperationRegistry.update(
                                    opId,
                                    "Import $record$suffix",
                                    recordIndex + 1,
                                    records.size
                                )
                            }

                            val stableKey = col(fields, "Capteur_ID").trim()
                            val sensorName = col(fields, "Capteur").trim()
                                .ifBlank { stableKey.ifBlank { "Capteur" } }
                            val room = col(fields, "Piece").trim().ifBlank { sensorName }
                            val color = col(fields, "Couleur").trim().toIntOrNull()?.coerceIn(0, 15) ?: 0

                            when (record) {
                                "SENSOR" -> {
                                    if (stableKey.isBlank()) {
                                        invalid++
                                        if (firstProblem == null) firstProblem = "ligne ${recordIndex + 2} · SENSOR sans Capteur_ID"
                                    } else {
                                        val sensor = sensorCache[stableKey] ?: db.getOrCreateSensor(stableKey, sensorName)
                                        db.updateSensor(sensor.id, sensorName, room, color)
                                        sensorCache[stableKey] = sensor
                                        sensorsRestored++
                                    }
                                }

                                "SAMPLE" -> {
                                    if (stableKey.isBlank()) {
                                        invalid++
                                        if (firstProblem == null) firstProblem = "ligne ${recordIndex + 2} · SAMPLE sans Capteur_ID"
                                        return@forEachIndexed
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
                                        if (firstProblem == null) {
                                            firstProblem = "ligne ${recordIndex + 2} · SAMPLE invalide " +
                                                "(temps=${col(fields, "Temps")}, T=${col(fields, "Temperature_Celsius")}, HR=${col(fields, "Humidite_relative_Pourcentage")})"
                                        }
                                    } else {
                                        val sensor = sensorForSample(stableKey, sensorName, room, color)
                                        val source = PointSource.fromDb(col(fields, "Source"))
                                        val provenance = PointProvenance(
                                            source = source,
                                            confidence = parseNumber(col(fields, "Confiance"))?.coerceIn(0.0, 1.0),
                                            referenceStationId = col(fields, "Reference_Station_ID").trim().ifBlank { null },
                                            referenceCity = col(fields, "Reference_Ville").trim().ifBlank { null },
                                            calibrationFrom = col(fields, "Calibration_Debut_ms").trim().toLongOrNull(),
                                            calibrationTo = col(fields, "Calibration_Fin_ms").trim().toLongOrNull(),
                                            modelVersion = col(fields, "Model_Version").trim().ifBlank { null },
                                            referenceKey = col(fields, "Reference_Key").trim().ifBlank { null },
                                            sigmaC = parseNumber(col(fields, "Sigma_C")),
                                            analogCount = col(fields, "Analog_Count").trim().toIntOrNull(),
                                            profileHash = col(fields, "Profile_Hash").trim().ifBlank { null },
                                            dependencyHash = col(fields, "Dependency_Hash").trim().ifBlank { null },
                                            sourceUpdatedAt = col(fields, "Source_UpdatedAt_ms").trim().toLongOrNull()
                                        )

                                        val write = if (source == PointSource.MEASURED) {
                                            noteMeasuredRange(sensor.id, timestamp)
                                            upsertMeasuredFast(sensor.id, timestamp, temperature, humidity)
                                        } else {
                                            PointSourceStore.upsertByPriority(
                                                db, sensor.id, timestamp, temperature, humidity, provenance
                                            )
                                        }
                                        if (write == PriorityWriteResult.INSERTED || write == PriorityWriteResult.REPLACED) {
                                            measurementsAdded++
                                        } else {
                                            measurementsDuplicates++
                                        }
                                    }
                                }

                                "EVENT" -> {
                                    val timestamp = parseTimestamp(
                                        col(fields, "Temps_Epoch_ms"),
                                        col(fields, "Temps")
                                    )
                                    if (timestamp == null) {
                                        invalid++
                                        if (firstProblem == null) firstProblem = "ligne ${recordIndex + 2} · EVENT sans date valide"
                                        return@forEachIndexed
                                    }
                                    val title = col(fields, "Titre").trim().ifBlank { "Événement" }
                                    val note = col(fields, "Note")
                                    val type = col(fields, "Type").trim().ifBlank { null }
                                    val eventRoom = col(fields, "Piece").trim().ifBlank { null }
                                    val updatedAt = col(fields, "UpdatedAt_Epoch_ms").trim().toLongOrNull()
                                        ?: System.currentTimeMillis()
                                    val sensorId = if (stableKey.isBlank()) null else sensorForEvent(stableKey, sensorName).id

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

                                "META", "BACKUP_END" -> Unit

                                else -> {
                                    val rowMap = header.mapIndexed { i, name ->
                                        name.trim() to fields.getOrNull(i).orEmpty()
                                    }.toMap()
                                    if (!v3Support.importRecord(record, rowMap)) {
                                        invalid++
                                        if (firstProblem == null) firstProblem = "ligne ${recordIndex + 2} · type $record non reconnu"
                                    }
                                }
                            }
                        } catch (e: Exception) {
                            invalid++
                            if (firstProblem == null) {
                                firstProblem = "ligne ${recordIndex + 2} · $record · ${e.javaClass.simpleName}: ${e.message ?: "erreur inconnue"}"
                            }
                        }
                    }
                }

                // Une seule réconciliation set-based par capteur remplace les dizaines de
                // milliers de prune/invalidate lancés autrefois à chaque mesure réelle.
                if (measuredRanges.isNotEmpty()) {
                    FabOperationRegistry.update(
                        opId,
                        "Réconciliation des mesures réelles…",
                        records.size,
                        records.size
                    )
                    measuredRanges.forEach { (sensorId, range) ->
                        PointSourceStore.reconcileMeasuredDominance(db, range[0], range[1])
                    }
                }

                val summary = FabDataImportSummary(
                    sourceName = sourceName,
                    measurementsAdded = measurementsAdded,
                    measurementsDuplicates = measurementsDuplicates,
                    eventsAdded = eventsAdded,
                    eventsDuplicates = eventsDuplicates,
                    sensorsRestored = sensorsRestored,
                    invalid = invalid
                )

                val endDetail = buildString {
                    append("Terminé · $measurementsAdded mesure(s) ajoutée(s) · $measurementsDuplicates déjà présente(s)")
                    append(" · $eventsAdded événement(s) restauré(s)")
                    if (invalid > 0) append(" · $invalid anomalie(s)")
                    firstProblem?.let { append(" · 1re anomalie : $it") }
                }
                FabOperationRegistry.finish(opId, endDetail)
                return summary
            } catch (e: Exception) {
                FabOperationRegistry.fail(
                    opId,
                    "Échec import · ${e.javaClass.simpleName}: ${e.message ?: "erreur inconnue"}"
                )
                throw e
            }
        }
    }

    /**
     * Chemin rapide réservé aux points MEASURED d'une restauration de sauvegarde.
     * MEASURED a la priorité maximale, donc aucune lecture de priorité n'est nécessaire
     * sur une insertion neuve. En cas de conflit seulement, on vérifie l'ancien point,
     * on le remplace si nécessaire et on retire sa provenance calculée éventuelle.
     */
    private fun upsertMeasuredFast(
        sensorId: Long,
        timestamp: Long,
        temperature: Double,
        humidity: Double
    ): PriorityWriteResult {
        val sql = db.writableDatabase
        val values = ContentValues().apply {
            put("sensor_id", sensorId)
            put("timestamp", timestamp)
            put("temperature", temperature)
            put("humidity", humidity)
        }
        val inserted = sql.insertWithOnConflict(
            "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
        )
        if (inserted != -1L) return PriorityWriteResult.INSERTED

        data class Existing(val temperature: Double, val humidity: Double, val source: PointSource)
        val existing = db.readableDatabase.rawQuery(
            """
            SELECT p.temperature, p.humidity, ps.source
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND p.timestamp=? LIMIT 1
            """.trimIndent(),
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) null else Existing(
                c.getDouble(0), c.getDouble(1),
                PointSource.fromDb(if (c.isNull(2)) null else c.getString(2))
            )
        } ?: return PriorityWriteResult.UNCHANGED

        val sameValues = kotlin.math.abs(existing.temperature - temperature) < 0.001 &&
            kotlin.math.abs(existing.humidity - humidity) < 0.001
        if (existing.source == PointSource.MEASURED && sameValues) {
            return PriorityWriteResult.UNCHANGED
        }

        sql.update(
            "samples",
            ContentValues().apply {
                put("temperature", temperature)
                put("humidity", humidity)
            },
            "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
        sql.delete(
            "point_sources",
            "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
        return PriorityWriteResult.REPLACED
    }

    /** Sauvegarde capteurs + mesures + événements dans un seul CSV réimportable. */
    fun export(uri: Uri): FabDataBackupExportResult {
        val tempFile = File.createTempFile("fabdata-backup-", ".csv", context.cacheDir)
        var sensorCount = 0
        var measurementCount = 0
        var eventCount = 0

        try {
            OutputStreamWriter(tempFile.outputStream(), Charsets.UTF_8).buffered().use { writer ->
                writer.write(HEADER)
                writer.write("\n")
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

                FabDataBackupV3Support(context, db).writeExtraRows(writer)
                writeRow(
                    writer,
                    listOf(
                        "BACKUP_END", FORMAT_VERSION, "", "FabData", "", "", "", "", "", "",
                        "Sauvegarde complète et vérifiée",
                        "sensors=$sensorCount;measurements=$measurementCount;events=$eventCount",
                        "integrity",
                        System.currentTimeMillis().toString()
                    )
                )
            }

            val lastRecord = tempFile.useLines(Charsets.UTF_8) { lines ->
                lines.filter { it.isNotBlank() }.lastOrNull()
            } ?: error("Sauvegarde vide après génération")
            val footer = splitCsv(lastRecord, ',')
            if (footer.firstOrNull()?.trim() != "BACKUP_END") {
                error("Sauvegarde incomplète : footer absent après génération")
            }
            val expectedNote = "sensors=$sensorCount;measurements=$measurementCount;events=$eventCount"
            if (footer.getOrNull(11).orEmpty() != expectedNote) {
                error("Sauvegarde incomplète : compteurs de fin incohérents")
            }

            val output = context.contentResolver.openOutputStream(uri, "wt")
                ?: error("Impossible de créer le fichier de sauvegarde")
            output.use { out ->
                tempFile.inputStream().use { input -> input.copyTo(out, 256 * 1024) }
                out.flush()
            }
            return FabDataBackupExportResult(sensorCount, measurementCount, eventCount)
        } finally {
            tempFile.delete()
        }
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
                timestamp.toString(), title, note, (sensorId ?: -1L).toString(),
                roomName.orEmpty(), type.orEmpty()
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
            try {
                Instant.parse(text).toEpochMilli()
            } catch (_: Exception) {
                null
            }
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

    /** Découpe le document en records CSV sans casser les notes multilignes entre guillemets. */
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
