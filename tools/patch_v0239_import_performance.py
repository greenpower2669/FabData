from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"pattern not found: {label}")
    return text.replace(old, new, 1)


backup_path = Path("app/src/main/java/com/fabdata/app/BackupLayer.kt")
backup = backup_path.read_text(encoding="utf-8")
backup = replace_once(
    backup,
    "import android.content.Context\n",
    "import android.content.Context\nimport android.database.sqlite.SQLiteDatabase\n",
    "BackupLayer SQLiteDatabase import",
)

start = backup.find("    fun importIfBackup(uri: Uri): FabDataImportSummary? {")
end = backup.find("    /** Sauvegarde capteurs + mesures + événements dans un seul CSV réimportable. */", start)
if start < 0 or end < 0:
    raise SystemExit("BackupLayer importIfBackup block not found")

new_import = r'''    fun importIfBackup(uri: Uri): FabDataImportSummary? {
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

'''

backup = backup[:start] + new_import + backup[end:]
backup_path.write_text(backup, encoding="utf-8")

v3_path = Path("app/src/main/java/com/fabdata/app/BackupV3Support.kt")
v3 = v3_path.read_text(encoding="utf-8")
v3 = replace_once(
    v3,
    '            "ui", "curve", "style", "dial", "overview", "context", "display", "appearance"\n',
    '            "ui", "curve", "style", "dial", "overview", "context", "display", "appearance",\n            "animation", "motion", "transition"\n',
    "personalization animation whitelist",
)
v3_path.write_text(v3, encoding="utf-8")

print("FabData v0.23.9 import performance patch applied")
