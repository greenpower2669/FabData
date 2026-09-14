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
        const val FORMAT_VERSION = "5"
        const val HEADER = "FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms,Source,Confiance,Reference_Station_ID,Reference_Ville,Calibration_Debut_ms,Calibration_Fin_ms,Model_Version"
    }

    private val dateFormatter = DateTimeFormatter.ofPattern("uuuu/MM/dd HH:mm:ss", Locale.ROOT)

    /**
     * Retourne null si le fichier n'est pas une sauvegarde FabData : l'appelant
     * peut alors le transmettre au parseur thermo standard.
     */
    fun importIfBackup(uri: Uri): FabDataImportSummary? {
        val sourceName = fileName(uri) ?: "FabData_sauvegarde.csv"
        val operationId = FabOperationRegistry.activeId("import-data")
        FabOperationRegistry.update(operationId, "Lecture du backup FabData…")

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
            var firstProblem: String? = null

            val records = splitCsvRecords(reader.readText())
            fun recordType(line: String): String =
                splitCsv(line, ',').firstOrNull().orEmpty().trim().uppercase(Locale.ROOT)
            val recordTypes = records.map(::recordType)
            val totalRecords = records.size.coerceAtLeast(1)
            val totalSamples = recordTypes.count { it == "SAMPLE" }
            val totalWeather = recordTypes.count { it == "WEATHER" }
            val totalPreferences = recordTypes.count { it == "UI_PREFERENCES" }
            val archiveTypes = setOf(
                "FORECAST_ARCHIVE", "FORECAST_LOCAL_ARCHIVE", "FORECAST_PAST_API_ARCHIVE",
                "FORECAST_CURVE_10M_ARCHIVE", "FORECAST_ADAPTIVE_ARCHIVE"
            )
            val totalArchives = recordTypes.count { it in archiveTypes }

            FabOperationRegistry.update(
                operationId,
                "Validation · ${records.size} lignes · $totalSamples mesures · $totalWeather météo",
                0,
                totalRecords
            )

            // v4/v5 : intégrité validée une seule fois AVANT la première écriture.
            // Les courbes/archives déjà présentes dans le backup sont restaurées telles
            // quelles par FabDataBackupV3Support : aucun recalcul ou appel météo ici.
            val metaIndex = recordTypes.indexOfFirst { it == "META" }
            val metaFields = if (metaIndex >= 0) splitCsv(records[metaIndex], ',') else emptyList()
            val fileVersion = col(metaFields, "Format_Version").trim()
            if (fileVersion in setOf("4", FORMAT_VERSION)) {
                val footerIndex = records.indexOfLast { it.isNotBlank() }
                if (footerIndex < 0 || recordTypes.getOrNull(footerIndex) != "BACKUP_END") {
                    error("Sauvegarde complète incomplète : marqueur de fin absent")
                }
                val footer = splitCsv(records[footerIndex], ',')
                val note = col(footer, "Note")
                val expected = note.split(';').mapNotNull { token ->
                    val pair = token.split('=', limit = 2)
                    if (pair.size == 2) pair[0].trim() to pair[1].trim().toIntOrNull() else null
                }.toMap()
                val actualSensors = recordTypes.count { it == "SENSOR" }
                val actualSamples = totalSamples
                val actualEvents = recordTypes.count { it == "EVENT" }
                if (expected["sensors"] != actualSensors ||
                    expected["measurements"] != actualSamples ||
                    expected["events"] != actualEvents
                ) {
                    error("Sauvegarde complète incomplète : compteurs d’intégrité incohérents")
                }
            }

            val sensorIds = mutableMapOf<String, Long>()
            val sensorMetadataApplied = mutableSetOf<String>()
            fun resolveSensor(
                stableKey: String,
                sensorName: String,
                room: String,
                color: Int,
                forceMetadata: Boolean = false
            ): Long {
                val sensorId = sensorIds.getOrPut(stableKey) {
                    db.getOrCreateSensor(stableKey, sensorName).id
                }
                if (forceMetadata || sensorMetadataApplied.add(stableKey)) {
                    db.updateSensor(sensorId, sensorName, room, color)
                    sensorMetadataApplied.add(stableKey)
                }
                return sensorId
            }

            val measuredRanges = mutableMapOf<Long, LongArray>()
            val importedForecasts = mutableMapOf<Long, MutableSet<Long>>()
            fun trackMeasured(sensorId: Long, timestamp: Long) {
                val range = measuredRanges.getOrPut(sensorId) { longArrayOf(timestamp, timestamp) }
                if (timestamp < range[0]) range[0] = timestamp
                if (timestamp > range[1]) range[1] = timestamp
            }

            var doneSamples = 0
            var doneWeather = 0
            var donePreferences = 0
            var doneArchives = 0
            var lastStage = ""
            fun stageFor(record: String): String = when {
                record == "SAMPLE" -> "Mesures RAW $doneSamples/$totalSamples"
                record == "WEATHER" -> "Météo $doneWeather/$totalWeather"
                record == "UI_PREFERENCES" -> "Personnalisation $donePreferences/$totalPreferences"
                record in archiveTypes -> "Archives $doneArchives/$totalArchives"
                record == "SENSOR" -> "Capteurs"
                record == "EVENT" -> "Événements"
                record == "BACKUP_END" -> "Finalisation"
                else -> "État FabData"
            }
            fun progress(processed: Int, record: String, force: Boolean = false) {
                val stage = stageFor(record)
                if (operationId != null &&
                    (force || processed == totalRecords || processed == 1 || processed % 500 == 0 || stage != lastStage)
                ) {
                    lastStage = stage
                    FabOperationRegistry.update(
                        operationId,
                        "$stage · ligne $processed/$totalRecords",
                        processed,
                        totalRecords
                    )
                }
            }
            fun problem(rowIndex: Int, record: String, message: String) {
                invalid++
                if (firstProblem == null) {
                    firstProblem = "ligne ${rowIndex + 2} · ${record.ifBlank { "INCONNU" }} · $message"
                }
            }

            PointSourceStore.ensure(db.writableDatabase)
            val v3Support = FabDataBackupV3Support(context, db)

            db.inTransaction {
                records.forEachIndexed { rowIndex, line ->
                    if (line.isBlank()) return@forEachIndexed
                    val record = recordTypes.getOrElse(rowIndex) { "" }
                    try {
                        val fields = splitCsv(line, ',')
                        val formatVersion = col(fields, "Format_Version").trim()
                        if (formatVersion.isNotBlank() && formatVersion !in setOf("1", "2", "3", "4", FORMAT_VERSION)) {
                            problem(rowIndex, record, "version $formatVersion non supportée")
                            progress(rowIndex + 1, record)
                            return@forEachIndexed
                        }

                        val stableKey = col(fields, "Capteur_ID").trim()
                        val sensorName = col(fields, "Capteur").trim().ifBlank { stableKey.ifBlank { "Capteur" } }
                        val room = col(fields, "Piece").trim().ifBlank { sensorName }
                        val color = col(fields, "Couleur").trim().toIntOrNull()?.coerceIn(0, 7) ?: 0

                        when (record) {
                            "SENSOR" -> {
                                if (stableKey.isBlank()) {
                                    problem(rowIndex, record, "Capteur_ID vide")
                                } else {
                                    resolveSensor(stableKey, sensorName, room, color, forceMetadata = true)
                                    sensorsRestored++
                                }
                            }

                            "SAMPLE" -> {
                                doneSamples++
                                if (stableKey.isBlank()) {
                                    problem(rowIndex, record, "Capteur_ID vide")
                                    progress(rowIndex + 1, record)
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
                                    problem(rowIndex, record, "timestamp/température/humidité invalide")
                                } else {
                                    val sensorId = resolveSensor(stableKey, sensorName, room, color)
                                    val source = PointSource.fromDb(col(fields, "Source"))
                                    val write = if (source == PointSource.MEASURED) {
                                        trackMeasured(sensorId, timestamp)
                                        upsertMeasuredFast(sensorId, timestamp, temperature, humidity)
                                    } else {
                                        if (source == PointSource.FORECAST) {
                                            importedForecasts.getOrPut(sensorId) { linkedSetOf() }.add(timestamp)
                                        }
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
                                        PointSourceStore.upsertByPriority(
                                            db, sensorId, timestamp, temperature, humidity, provenance
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
                                    problem(rowIndex, record, "timestamp événement invalide")
                                    progress(rowIndex + 1, record)
                                    return@forEachIndexed
                                }
                                val title = col(fields, "Titre").trim().ifBlank { "Événement" }
                                val note = col(fields, "Note")
                                val type = col(fields, "Type").trim().ifBlank { null }
                                val eventRoom = col(fields, "Piece").trim().ifBlank { null }
                                val updatedAt = col(fields, "UpdatedAt_Epoch_ms").trim().toLongOrNull()
                                    ?: System.currentTimeMillis()

                                val sensorId = if (stableKey.isBlank()) null else
                                    resolveSensor(stableKey, sensorName, room, color)

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
                                if (record == "WEATHER") doneWeather++
                                if (record == "UI_PREFERENCES") donePreferences++
                                if (record in archiveTypes) doneArchives++
                                val rowMap = header.mapIndexed { i, name ->
                                    name.trim() to fields.getOrNull(i).orEmpty()
                                }.toMap()
                                if (!v3Support.importRecord(record, rowMap)) {
                                    problem(rowIndex, record, "type d'enregistrement non reconnu")
                                }
                            }
                        }
                    } catch (error: Exception) {
                        problem(
                            rowIndex,
                            record,
                            "${error::class.java.simpleName}: ${error.message ?: "erreur sans message"}"
                        )
                    }
                    progress(rowIndex + 1, record)
                }
            }

            // Un seul nettoyage set-based pour toute la fenêtre mesurée : la requête
            // traite déjà toutes les sondes, donc surtout pas une relance par sonde.
            if (measuredRanges.isNotEmpty()) {
                val hourMs = 60L * 60L * 1000L
                val from = measuredRanges.values.minOf { (it[0] / hourMs) * hourMs }
                val to = measuredRanges.values.maxOf { (it[1] / hourMs) * hourMs + hourMs - 1L }
                FabOperationRegistry.update(
                    operationId,
                    "Cohérence finale · dominance RAW et prévisions",
                    totalRecords,
                    totalRecords
                )
                PointSourceStore.reconcileMeasuredDominance(db, from, to)
                measuredRanges.forEach { (sensorId, range) ->
                    pruneStaleForecastsAfterImport(
                        sensorId = sensorId,
                        firstMeasuredAt = range[0],
                        keepForecastTimestamps = importedForecasts[sensorId].orEmpty()
                    )
                }
            }

            val issueSuffix = firstProblem?.let { " · 1re anomalie : $it" }.orEmpty()
            FabOperationRegistry.update(
                operationId,
                "Restauration terminée · ${records.size} lignes · $invalid invalide(s)$issueSuffix",
                totalRecords,
                totalRecords
            )

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

    /** Chemin rapide réservé aux vraies mesures. */
    private fun upsertMeasuredFast(
        sensorId: Long,
        timestamp: Long,
        temperature: Double,
        humidity: Double
    ): PriorityWriteResult {
        val sql = db.writableDatabase
        val existing = db.readableDatabase.rawQuery(
            """
            SELECT p.temperature, p.humidity, ps.source
            FROM samples p
            LEFT JOIN point_sources ps
              ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND p.timestamp=? LIMIT 1
            """.trimIndent(),
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) null
            else Triple(
                c.getDouble(0),
                c.getDouble(1),
                PointSource.fromDb(if (c.isNull(2)) null else c.getString(2))
            )
        }

        if (existing == null) {
            val values = ContentValues().apply {
                put("sensor_id", sensorId)
                put("timestamp", timestamp)
                put("temperature", temperature)
                put("humidity", humidity)
            }
            val row = sql.insertWithOnConflict(
                "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
            )
            if (row == -1L) return PriorityWriteResult.UNCHANGED
            sql.delete(
                "point_sources",
                "sensor_id=? AND timestamp=?",
                arrayOf(sensorId.toString(), timestamp.toString())
            )
            return PriorityWriteResult.INSERTED
        }

        val sameValues = kotlin.math.abs(existing.first - temperature) < 0.001 &&
            kotlin.math.abs(existing.second - humidity) < 0.001
        if (existing.third == PointSource.MEASURED && sameValues) {
            return PriorityWriteResult.UNCHANGED
        }

        val values = ContentValues().apply {
            put("temperature", temperature)
            put("humidity", humidity)
        }
        sql.update(
            "samples",
            values,
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

    /**
     * Supprime uniquement les anciens SAMPLE forecast rendus obsolètes. Les forecasts
     * explicitement présents dans le backup et les archives H1→H48 sont conservés.
     */
    private fun pruneStaleForecastsAfterImport(
        sensorId: Long,
        firstMeasuredAt: Long,
        keepForecastTimestamps: Set<Long>
    ): Int {
        val stale = mutableListOf<Long>()
        db.readableDatabase.rawQuery(
            "SELECT timestamp FROM point_sources WHERE sensor_id=? AND source='forecast' AND timestamp>?",
            arrayOf(sensorId.toString(), firstMeasuredAt.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val ts = c.getLong(0)
                if (ts !in keepForecastTimestamps) stale += ts
            }
        }
        stale.forEach { ts ->
            db.writableDatabase.delete(
                "samples", "sensor_id=? AND timestamp=?",
                arrayOf(sensorId.toString(), ts.toString())
            )
            db.writableDatabase.delete(
                "point_sources", "sensor_id=? AND timestamp=?",
                arrayOf(sensorId.toString(), ts.toString())
            )
        }
        return stale.size
    }

    /** Sauvegarde capteurs + mesures + événements dans un seul CSV réimportable. */
    fun export(uri: Uri): FabDataBackupExportResult {
        // Génération locale d'abord : jamais de demi-sauvegarde présentée comme valide.
        // Le document choisi n'est touché qu'après écriture + contrôle du footer.
        val tempFile = File.createTempFile("fabdata-backup-", ".csv", context.cacheDir)

        var sensorCount = 0
        var measurementCount = 0
        var eventCount = 0

        try {
            OutputStreamWriter(tempFile.outputStream(), Charsets.UTF_8).buffered().use { writer ->
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
            // L'état thermique/météo complet reste append-only après les lignes lisibles.
            FabDataBackupV3Support(context, db).writeExtraRows(writer)

            // Le footer est la preuve qu'on a atteint la fin de TOUTES les tables.
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
