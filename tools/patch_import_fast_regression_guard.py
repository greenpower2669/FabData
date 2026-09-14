from pathlib import Path


BACKUP = Path("app/src/main/java/com/fabdata/app/BackupLayer.kt")
text = BACKUP.read_text(encoding="utf-8")

MARKER = "// IMPORT_FAST_REGRESSION_GUARD_V1"
if MARKER in text:
    print("BackupLayer already patched")
    raise SystemExit(0)

if "import android.database.sqlite.SQLiteDatabase\n" not in text:
    text = text.replace(
        "import android.content.ContentValues\n",
        "import android.content.ContentValues\nimport android.database.sqlite.SQLiteDatabase\n",
        1,
    )

start_marker = "    fun importIfBackup(uri: Uri): FabDataImportSummary? {\n"
end_marker = "    /** Sauvegarde capteurs + mesures + événements dans un seul CSV réimportable. */\n"
start = text.index(start_marker)
end = text.index(end_marker, start)

replacement = r'''    // IMPORT_FAST_REGRESSION_GUARD_V1
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
            var firstProblem: String? = null

            val records = splitCsvRecords(reader.readText())
            fun recordType(line: String): String =
                splitCsv(line, ',').firstOrNull().orEmpty().trim().uppercase(Locale.ROOT)
            val recordTypes = records.map(::recordType)

            // v4/v5 : intégrité vérifiée AVANT la première écriture. Les v1/v2/v3
            // restent importables pour compatibilité historique.
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
                val actualSamples = recordTypes.count { it == "SAMPLE" }
                val actualEvents = recordTypes.count { it == "EVENT" }
                if (expected["sensors"] != actualSensors ||
                    expected["measurements"] != actualSamples ||
                    expected["events"] != actualEvents
                ) {
                    error("Sauvegarde complète incomplète : compteurs d’intégrité incohérents")
                }
            }

            val operationId = FabOperationRegistry.activeId("import-data")
            val totalRecords = records.size.coerceAtLeast(1)
            fun progress(processed: Int, record: String) {
                if (operationId != null &&
                    (processed == totalRecords || processed == 1 || processed % 500 == 0)
                ) {
                    FabOperationRegistry.update(
                        operationId,
                        "Restauration FabData · $record · $processed/$totalRecords",
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

            // Plages MEASURED nécessaires au nettoyage set-based final. On mémorise aussi
            // les timestamps FORECAST présents DANS la sauvegarde afin de supprimer les
            // vieux forecasts préexistants sans effacer ceux que la sauvegarde restaure.
            val measuredRanges = mutableMapOf<Long, LongArray>()
            val importedForecasts = mutableMapOf<Long, MutableSet<Long>>()
            fun trackMeasured(sensorId: Long, timestamp: Long) {
                val range = measuredRanges.getOrPut(sensorId) { longArrayOf(timestamp, timestamp) }
                if (timestamp < range[0]) range[0] = timestamp
                if (timestamp > range[1]) range[1] = timestamp
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
                                            importedForecasts.getOrPut(sensorId) { mutableSetOf() }.add(timestamp)
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

            // L'ancien chemin faisait ces nettoyages à chaque mesure. Le résultat final
            // est reproduit ici en lots : même dominance, beaucoup moins de SQL.
            val hourMs = 60L * 60L * 1000L
            measuredRanges.forEach { (sensorId, range) ->
                val from = (range[0] / hourMs) * hourMs
                val to = (range[1] / hourMs) * hourMs + hourMs - 1L
                PointSourceStore.reconcileMeasuredDominance(db, from, to)
                pruneStaleForecastsAfterImport(
                    sensorId = sensorId,
                    firstMeasuredAt = range[0],
                    keepForecastTimestamps = importedForecasts[sensorId].orEmpty()
                )
            }

            operationId?.let {
                val suffix = firstProblem?.let { issue -> " · 1re anomalie : $issue" }.orEmpty()
                FabOperationRegistry.update(
                    it,
                    "Restauration FabData terminée · ${records.size} lignes · $invalid invalide(s)$suffix",
                    records.size,
                    records.size.coerceAtLeast(1)
                )
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

    /**
     * Chemin rapide réservé aux vraies mesures. MEASURED est représenté par
     * l'absence de provenance : on écrit la valeur et on supprime une éventuelle
     * provenance calculée, sans lancer les nettoyages historiques point par point.
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
        if (inserted != -1L) {
            sql.delete(
                "point_sources", "sensor_id=? AND timestamp=?",
                arrayOf(sensorId.toString(), timestamp.toString())
            )
            return PriorityWriteResult.INSERTED
        }

        var existingTemperature = Double.NaN
        var existingHumidity = Double.NaN
        var existingSource = PointSource.MEASURED
        val found = sql.rawQuery(
            """
            SELECT s.temperature, s.humidity, ps.source
            FROM samples s
            LEFT JOIN point_sources ps ON ps.sensor_id=s.sensor_id AND ps.timestamp=s.timestamp
            WHERE s.sensor_id=? AND s.timestamp=? LIMIT 1
            """.trimIndent(),
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) false else {
                existingTemperature = c.getDouble(0)
                existingHumidity = c.getDouble(1)
                existingSource = PointSource.fromDb(if (c.isNull(2)) null else c.getString(2))
                true
            }
        }
        if (!found) return PriorityWriteResult.UNCHANGED

        val sameValues = kotlin.math.abs(existingTemperature - temperature) < 0.001 &&
            kotlin.math.abs(existingHumidity - humidity) < 0.001
        if (existingSource == PointSource.MEASURED && sameValues) {
            // Nettoie malgré tout une provenance 'measured' héritée/non canonique.
            sql.delete(
                "point_sources", "sensor_id=? AND timestamp=?",
                arrayOf(sensorId.toString(), timestamp.toString())
            )
            return PriorityWriteResult.UNCHANGED
        }

        val update = ContentValues().apply {
            put("temperature", temperature)
            put("humidity", humidity)
        }
        sql.update(
            "samples", update, "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
        sql.delete(
            "point_sources", "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
        return PriorityWriteResult.REPLACED
    }

    /**
     * markMeasured() invalidait historiquement tous les forecasts futurs à chaque
     * mesure. Après l'import rapide on reproduit ce résultat une fois par capteur,
     * tout en protégeant explicitement les forecasts qui appartiennent au backup.
     */
    private fun pruneStaleForecastsAfterImport(
        sensorId: Long,
        firstMeasuredAt: Long,
        keepForecastTimestamps: Set<Long>
    ) {
        val sql = db.writableDatabase
        val stale = mutableListOf<Long>()
        sql.rawQuery(
            """
            SELECT timestamp FROM point_sources
            WHERE sensor_id=? AND source='forecast' AND timestamp>?
            """.trimIndent(),
            arrayOf(sensorId.toString(), firstMeasuredAt.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val timestamp = c.getLong(0)
                if (timestamp !in keepForecastTimestamps) stale += timestamp
            }
        }
        if (stale.isEmpty()) return
        db.inTransaction {
            stale.forEach { timestamp ->
                val args = arrayOf(sensorId.toString(), timestamp.toString())
                sql.delete("samples", "sensor_id=? AND timestamp=?", args)
                sql.delete("point_sources", "sensor_id=? AND timestamp=?", args)
            }
        }
    }

'''

text = text[:start] + replacement + text[end:]
BACKUP.write_text(text, encoding="utf-8")
print("Patched BackupLayer.kt with fast guarded restore")
