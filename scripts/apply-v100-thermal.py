from pathlib import Path

DATA = Path('app/src/main/java/com/fabdata/app/DataLayer.kt')
MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
BACKUP = Path('app/src/main/java/com/fabdata/app/BackupLayer.kt')
LYON_EMBED = Path('app/src/main/java/com/fabdata/app/LyonEmbeddedHistory.kt')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f'v0.10: anchor missing: {label}')
    return text.replace(old, new, 1)

# -----------------------------------------------------------------------------
# DataLayer — optional provenance, priority-aware import, source-aware queries.
# -----------------------------------------------------------------------------
text = DATA.read_text(encoding='utf-8')

text = text.replace('SQLiteOpenHelper(context, "fabdata.db", null, 3)', 'SQLiteOpenHelper(context, "fabdata.db", null, 4)', 1)

text = replace_once(text, '''data class SamplePoint(
    val sensorId: Long,
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double
)
''', '''data class SamplePoint(
    val sensorId: Long,
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val source: PointSource = PointSource.MEASURED,
    val confidence: Double? = null
)
''', 'SamplePoint provenance')

text = replace_once(text, '''        db.execSQL("CREATE INDEX idx_annotations_time ON annotations(timestamp)")
        ensureLyonLabSchema(db)
    }
''', '''        db.execSQL("CREATE INDEX idx_annotations_time ON annotations(timestamp)")
        ensureLyonLabSchema(db)
        PointSourceStore.ensure(db)
        WeatherReferenceStore.ensure(db)
    }
''', 'onCreate source schema')

text = replace_once(text, '''        if (oldVersion < 3) {
            // Migration strictement additive : aucune table historique n'est réécrite.
            ensureLyonLabSchema(db)
        }
    }
''', '''        if (oldVersion < 3) {
            // Migration strictement additive : aucune table historique n'est réécrite.
            ensureLyonLabSchema(db)
        }
        if (oldVersion < 4) {
            // v0.10 : métadonnées additives uniquement. Les anciennes lignes restent measured par défaut.
            PointSourceStore.ensure(db)
            WeatherReferenceStore.ensure(db)
        }
    }
''', 'onUpgrade source schema')

text = replace_once(text, '''        return writableDatabase.insertWithOnConflict(
            "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
        ) != -1L
    }
''', '''        val inserted = writableDatabase.insertWithOnConflict(
            "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
        ) != -1L
        if (inserted) PointSourceStore.markMeasured(this, sensorId, timestamp)
        return inserted
    }
''', 'insertSample measured default')

text = replace_once(text, '''        } ?: return false

        if (kotlin.math.abs(current.first - temperature) < 0.001 &&
''', '''        } ?: return false

        // Cette méthode est réservée aux données réelles revalidées : même si la valeur
        // numérique est identique, elle remplace la provenance calculée éventuelle.
        PointSourceStore.markMeasured(this, sensorId, timestamp)

        if (kotlin.math.abs(current.first - temperature) < 0.001 &&
''', 'updateSample measured priority')

text = replace_once(text, '''        readableDatabase.rawQuery(
            "SELECT timestamp, temperature, humidity FROM samples WHERE sensor_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                all += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2))
            }
        }
''', '''        PointSourceStore.ensure(readableDatabase)
        readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity, ps.source, ps.confidence
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id = ? AND p.timestamp BETWEEN ? AND ?
            ORDER BY p.timestamp
            """.trimIndent(),
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                all += SamplePoint(
                    sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2),
                    PointSource.fromDb(if (c.isNull(3)) null else c.getString(3)),
                    if (c.isNull(4)) null else c.getDouble(4)
                )
            }
        }
''', 'querySamples provenance join')

text = replace_once(text, '''    private data class ParsedPoint(val timestamp: Long, val temperature: Double, val humidity: Double)
''', '''    private data class ParsedPoint(
        val timestamp: Long,
        val temperature: Double,
        val humidity: Double,
        val source: PointSource = PointSource.MEASURED,
        val confidence: Double? = null
    )
''', 'ParsedPoint provenance')

text = replace_once(text, '''                val exactKnownFormat = delimiter == ',' && headers.size >= 3 &&
                    headers[0] == "temps" && headers[1] == "temperaturecelsius" && headers[2] == "humiditerelativepourcentage"

                val rows = reader.lineSequence()''', '''                val exactKnownFormat = delimiter == ',' && headers.size >= 3 &&
                    headers[0] == "temps" && headers[1] == "temperaturecelsius" && headers[2] == "humiditerelativepourcentage"
                val sourceIndex = headers.indexOfFirst { it == "source" }
                val confidenceIndex = headers.indexOfFirst { it == "confidence" || it == "confiance" }

                val rows = reader.lineSequence()''', 'CSV optional source indexes')

text = replace_once(text, '''                            } else {
                                parsed += ParsedPoint(ts, temp, hum)
                            }
''', '''                            } else {
                                val pointSource = if (sourceIndex >= 0) parsePointSource(fields.getOrNull(sourceIndex).orEmpty()) else PointSource.MEASURED
                                val confidence = if (confidenceIndex >= 0) parseNumber(fields.getOrNull(confidenceIndex).orEmpty())?.coerceIn(0.0, 1.0) else null
                                parsed += ParsedPoint(ts, temp, hum, pointSource, confidence)
                            }
''', 'exact CSV source parse')

old_store = '''        db.inTransaction {
            pointsToStore.forEach { point ->
                firstTs = firstTs?.let { minOf(it, point.timestamp) } ?: point.timestamp
                lastTs = lastTs?.let { maxOf(it, point.timestamp) } ?: point.timestamp
                if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) {
                    added++
                    if (isLyonImport) LyonEmbeddedHistory.markProvisional(db, point.timestamp)
                } else if (
                    isLyonImport && LyonEmbeddedHistory.isProvisional(db, point.timestamp) &&
                    db.updateSampleIfDifferent(sensor.id, point.timestamp, point.temperature, point.humidity)
                ) {
                    // Un fichier Lyon peut préciser/remplacer notre propre reconstruction,
                    // mais n'écrase jamais une heure déjà confirmée par une source réelle.
                    added++
                    LyonEmbeddedHistory.markProvisional(db, point.timestamp)
                } else {
                    duplicates++
                }
            }
        }
'''
new_store = '''        db.inTransaction {
            pointsToStore.forEach { point ->
                firstTs = firstTs?.let { minOf(it, point.timestamp) } ?: point.timestamp
                lastTs = lastTs?.let { maxOf(it, point.timestamp) } ?: point.timestamp
                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, point.timestamp, point.temperature, point.humidity,
                    PointProvenance(point.source, point.confidence)
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) added++ else duplicates++
                if (isLyonImport) {
                    if (point.source == PointSource.MEASURED) LyonEmbeddedHistory.markObserved(db, point.timestamp)
                    else LyonEmbeddedHistory.markProvisional(db, point.timestamp)
                }
            }
        }
'''
text = replace_once(text, old_store, new_store, 'priority-aware CSV store')

text = replace_once(text, '''                    out += ParsedPoint(
                        ts,
                        kotlin.math.round(temperature * 10.0) / 10.0,
                        (kotlin.math.round(humidity * 10.0) / 10.0).coerceIn(0.0, 100.0)
                    )
''', '''                    out += ParsedPoint(
                        ts,
                        kotlin.math.round(temperature * 10.0) / 10.0,
                        (kotlin.math.round(humidity * 10.0) / 10.0).coerceIn(0.0, 100.0),
                        PointSource.RECONSTRUCTED,
                        0.72
                    )
''', 'Lyon smoothing reconstructed source')

text = replace_once(text, '''        val humidityIndex = findHeader(headers, listOf("humiditerelativepourcentage", "humiditerelative", "humidite", "humidity", "relativehumidity", "rh", "hygrometrie"))
        if (timeIndex < 0 || tempIndex < 0 || humidityIndex < 0) error("Colonnes Temps / Température / Humidité introuvables")
''', '''        val humidityIndex = findHeader(headers, listOf("humiditerelativepourcentage", "humiditerelative", "humidite", "humidity", "relativehumidity", "rh", "hygrometrie"))
        val sourceIndex = findHeader(headers, listOf("source", "origine"))
        val confidenceIndex = findHeader(headers, listOf("confidence", "confiance"))
        if (timeIndex < 0 || tempIndex < 0 || humidityIndex < 0) error("Colonnes Temps / Température / Humidité introuvables")
''', 'generic source indexes')

text = replace_once(text, '''                if (ts == null || temp == null || hum == null || temp !in -100.0..150.0 || hum !in 0.0..100.0) invalid++
                else target += ParsedPoint(ts, temp, hum)
''', '''                if (ts == null || temp == null || hum == null || temp !in -100.0..150.0 || hum !in 0.0..100.0) invalid++
                else target += ParsedPoint(
                    ts, temp, hum,
                    if (sourceIndex >= 0) parsePointSource(fields.getOrNull(sourceIndex).orEmpty()) else PointSource.MEASURED,
                    if (confidenceIndex >= 0) parseNumber(fields.getOrNull(confidenceIndex).orEmpty())?.coerceIn(0.0, 1.0) else null
                )
''', 'generic source parse')

text = replace_once(text, '''    private fun parseNumber(rawInput: String): Double? {
''', '''    private fun parsePointSource(raw: String): PointSource = PointSource.fromDb(raw.trim().trim('"'))

    private fun parseNumber(rawInput: String): Double? {
''', 'parsePointSource helper')

DATA.write_text(text, encoding='utf-8')

# -----------------------------------------------------------------------------
# Lyon embedded history — bridge old provisional marker to the universal source layer.
# -----------------------------------------------------------------------------
text = LYON_EMBED.read_text(encoding='utf-8')
text = replace_once(text, '''        db.writableDatabase.insertWithOnConflict(
            MARKER_TABLE,
            null,
            values,
            android.database.sqlite.SQLiteDatabase.CONFLICT_IGNORE
        )
    }

    fun markObserved(db: FabDataDb, timestamp: Long) {
''', '''        db.writableDatabase.insertWithOnConflict(
            MARKER_TABLE,
            null,
            values,
            android.database.sqlite.SQLiteDatabase.CONFLICT_IGNORE
        )
        val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
        PointSourceStore.setProvenance(
            db, sensor.id, timestamp,
            PointProvenance(
                source = PointSource.RECONSTRUCTED,
                confidence = 0.72,
                referenceKey = WeatherReferenceCatalog.DEFAULT_KEY,
                referenceStationId = "69029001",
                referenceCity = "Lyon",
                modelVersion = "lyon-embedded-2026-07-08"
            )
        )
    }

    fun markObserved(db: FabDataDb, timestamp: Long) {
''', 'Lyon mark provisional universal')
text = replace_once(text, '''        ensureMarkerTable(db)
        db.writableDatabase.delete(MARKER_TABLE, "timestamp=?", arrayOf(timestamp.toString()))
    }
''', '''        ensureMarkerTable(db)
        db.writableDatabase.delete(MARKER_TABLE, "timestamp=?", arrayOf(timestamp.toString()))
        val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
        PointSourceStore.markMeasured(db, sensor.id, timestamp)
    }
''', 'Lyon mark observed universal')
LYON_EMBED.write_text(text, encoding='utf-8')

# -----------------------------------------------------------------------------
# BackupLayer — full backup preserves provenance, and still accepts v1 files.
# -----------------------------------------------------------------------------
text = BACKUP.read_text(encoding='utf-8')
text = text.replace('const val FORMAT_VERSION = "1"', 'const val FORMAT_VERSION = "2"', 1)
text = text.replace(
    'const val HEADER = "FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms"',
    'const val HEADER = "FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms,Source,Confiance,Reference_Station_ID,Reference_Ville,Calibration_Debut_ms,Calibration_Fin_ms,Model_Version"',
    1
)
text = replace_once(text, '''                        if (formatVersion.isNotBlank() && formatVersion != FORMAT_VERSION) {
''', '''                        if (formatVersion.isNotBlank() && formatVersion !in setOf("1", FORMAT_VERSION)) {
''', 'backup v1/v2 compatibility')

old_import_sample = '''                                    if (db.insertSample(sensor.id, timestamp, temperature, humidity)) {
                                        measurementsAdded++
                                    } else {
                                        measurementsDuplicates++
                                    }
'''
new_import_sample = '''                                    val source = PointSource.fromDb(col(fields, "Source"))
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
'''
text = replace_once(text, old_import_sample, new_import_sample, 'backup sample provenance import')

old_query = '''                SELECT s.stable_key, s.name, s.room, s.color_index,
                       p.timestamp, p.temperature, p.humidity
                FROM samples p
                JOIN sensors s ON s.id = p.sensor_id
                ORDER BY p.timestamp, s.id
'''
new_query = '''                SELECT s.stable_key, s.name, s.room, s.color_index,
                       p.timestamp, p.temperature, p.humidity,
                       ps.source, ps.confidence, ps.reference_station_id, ps.reference_city,
                       ps.calibration_from, ps.calibration_to, ps.model_version
                FROM samples p
                JOIN sensors s ON s.id = p.sensor_id
                LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
                ORDER BY p.timestamp, s.id
'''
text = replace_once(text, old_query, new_query, 'backup provenance query')

old_row = '''                            c.getDouble(5).toString(), c.getDouble(6).toString(),
                            "", "", "", ""
                        )
'''
new_row = '''                            c.getDouble(5).toString(), c.getDouble(6).toString(),
                            "", "", "", "",
                            PointSource.fromDb(if (c.isNull(7)) null else c.getString(7)).dbValue,
                            if (c.isNull(8)) "" else c.getDouble(8).toString(),
                            if (c.isNull(9)) "" else c.getString(9),
                            if (c.isNull(10)) "" else c.getString(10),
                            if (c.isNull(11)) "" else c.getLong(11).toString(),
                            if (c.isNull(12)) "" else c.getLong(12).toString(),
                            if (c.isNull(13)) "" else c.getString(13)
                        )
'''
text = replace_once(text, old_row, new_row, 'backup provenance row')
BACKUP.write_text(text, encoding='utf-8')

# -----------------------------------------------------------------------------
# MainActivity — one chronology per sensor, thermal UI, source-distinct rendering.
# -----------------------------------------------------------------------------
text = MAIN.read_text(encoding='utf-8')

old_lyon_load = '''                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        // La ligne Lyon reste la donnée officielle brute 6 min.
                        val officialSix = lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, chosen.first, chosen.last).map {
                            SamplePoint(sensor.id, it.timestamp, it.temperature, it.humidity)
                        }
                        // Secours lecture seule pour les anciennes bases avant l'API officielle.
                        officialSix.ifEmpty { db.querySamples(sensor.id, chosen.first, chosen.last) }
                    } else {
                        db.querySamples(sensor.id, chosen.first, chosen.last)
                    }
'''
new_lyon_load = '''                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        // v0.10 : une seule chronologie Lyon. Reconstruction d'abord, puis
                        // données stockées, puis officiel 6 min qui garde la priorité absolue.
                        val merged = linkedMapOf<Long, SamplePoint>()
                        lyonLab.reconstruct(chosen.first, chosen.last).points.forEach {
                            merged[it.timestamp] = SamplePoint(
                                sensor.id, it.timestamp, it.temperature, it.humidity,
                                PointSource.RECONSTRUCTED, 0.72
                            )
                        }
                        db.querySamples(sensor.id, chosen.first, chosen.last).forEach { merged[it.timestamp] = it }
                        lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, chosen.first, chosen.last).forEach {
                            merged[it.timestamp] = SamplePoint(sensor.id, it.timestamp, it.temperature, it.humidity, PointSource.MEASURED, 1.0)
                        }
                        merged.values.sortedBy { it.timestamp }
                    } else {
                        db.querySamples(sensor.id, chosen.first, chosen.last)
                    }
'''
text = replace_once(text, old_lyon_load, new_lyon_load, 'unified Lyon chronology')

text = text.replace(
    'SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity)',
    'SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, PointSource.RECONSTRUCTED, 0.72)'
)

old_chart = '''    // Permanent virtual curve: never hidden by token/network/source state.
    val chartSensors = sensors.filterNot { it.id == LYON_RECONSTRUCTED_SENSOR_ID } + lyonReconstructedSensor
    val chartSampleMap = sampleMap + (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples)
'''
new_chart = '''    // v0.10 : measured / reconstructed / forecast restent sur la même sonde.
    // Le capteur virtuel Lyon reconstruit est conservé en mémoire pour compatibilité
    // du détail historique, mais n'est plus présenté comme une seconde sonde.
    val chartSensors = sensors
    val chartSampleMap = sampleMap
'''
text = replace_once(text, old_chart, new_chart, 'single chronology chart sensors')

insert_anchor = '''                item {
                    SeriesSelector(
'''
insert_cards = '''                item {
                    ThermalReferenceCard(
                        db = db,
                        lyonLab = lyonLab,
                        credentials = meteoCredentials,
                        dataVersion = reloadToken,
                        onDataChanged = { reloadToken++ }
                    )
                }

                item {
                    SourceAwareExportCard(db)
                }

                item {
                    SeriesSelector(
'''
text = replace_once(text, insert_anchor, insert_cards, 'thermal cards insertion')

text = text.replace(
    '"Point épais = événement · 1 clic = aperçu · double clic = fiche"',
    '"Plein = réel · tirets = reconstruit · pointillés = prévision · point épais = événement"',
    1
)

old_temp = '''            if (showTemp[sensor.id] == true && points.size >= 2) {
                val path = Path()
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val x = mapX(p.timestamp)
                    val y = mapTemp(p.temperature)
                    val breakHere = (sensor.stableKey == LyonWeatherSync.STABLE_KEY || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) &&
                        previous?.let { p.timestamp - it.timestamp > LYON_DETAIL_GAP_MS } == true
                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                    previous = p
                }
                auraColor?.let { aura ->
                    drawPath(path, aura, style = Stroke(width = (prefs.lineWidth + 7f).dp.toPx()))
                }
                drawPath(path, color, style = Stroke(width = prefs.lineWidth.dp.toPx()))
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        drawCircle(color, 2.2.dp.toPx(), Offset(mapX(p.timestamp), mapTemp(p.temperature)))
                    }
                }
            }
'''
new_temp = '''            if (showTemp[sensor.id] == true && points.size >= 2) {
                val sourcePaths = PointSource.entries.associateWith { Path() }
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val prev = previous
                    if (prev != null) {
                        val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                            p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS
                        if (!breakHere) {
                            val path = sourcePaths[p.source]!!
                            path.moveTo(mapX(prev.timestamp), mapTemp(prev.temperature))
                            path.lineTo(mapX(p.timestamp), mapTemp(p.temperature))
                        }
                    }
                    previous = p
                }
                sourcePaths.forEach { (source, path) ->
                    val alpha = when (source) {
                        PointSource.MEASURED -> 1.0f
                        PointSource.RECONSTRUCTED -> 0.78f
                        PointSource.FORECAST -> 0.62f
                    }
                    val effect = when (source) {
                        PointSource.MEASURED -> null
                        PointSource.RECONSTRUCTED -> PathEffect.dashPathEffect(floatArrayOf(13f, 7f))
                        PointSource.FORECAST -> PathEffect.dashPathEffect(floatArrayOf(3f, 7f))
                    }
                    auraColor?.let { aura ->
                        drawPath(path, aura.copy(alpha = aura.alpha * alpha), style = Stroke(width = (prefs.lineWidth + 7f).dp.toPx(), pathEffect = effect))
                    }
                    drawPath(path, color.copy(alpha = color.alpha * alpha), style = Stroke(width = prefs.lineWidth.dp.toPx(), pathEffect = effect))
                }
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        val alpha = when (p.source) { PointSource.MEASURED -> 1f; PointSource.RECONSTRUCTED -> 0.78f; PointSource.FORECAST -> 0.60f }
                        drawCircle(color.copy(alpha = color.alpha * alpha), 2.2.dp.toPx(), Offset(mapX(p.timestamp), mapTemp(p.temperature)))
                    }
                }
            }
'''
text = replace_once(text, old_temp, new_temp, 'temperature source rendering')

old_hum = '''            if (showHumidity[sensor.id] == true && points.size >= 2) {
                val path = Path()
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val x = mapX(p.timestamp)
                    val y = mapHum(p.humidity)
                    val breakHere = (sensor.stableKey == LyonWeatherSync.STABLE_KEY || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) &&
                        previous?.let { p.timestamp - it.timestamp > LYON_DETAIL_GAP_MS } == true
                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                    previous = p
                }
                drawPath(
                    path,
                    color.copy(alpha = 0.82f),
                    style = Stroke(
                        width = max(1.2f, prefs.lineWidth - 0.5f).dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 7f))
                    )
                )
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        drawCircle(color.copy(alpha = 0.82f), 2.dp.toPx(), Offset(mapX(p.timestamp), mapHum(p.humidity)))
                    }
                }
            }
'''
new_hum = '''            if (showHumidity[sensor.id] == true && points.size >= 2) {
                val sourcePaths = PointSource.entries.associateWith { Path() }
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val prev = previous
                    if (prev != null) {
                        val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                            p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS
                        if (!breakHere) {
                            val path = sourcePaths[p.source]!!
                            path.moveTo(mapX(prev.timestamp), mapHum(prev.humidity))
                            path.lineTo(mapX(p.timestamp), mapHum(p.humidity))
                        }
                    }
                    previous = p
                }
                sourcePaths.forEach { (source, path) ->
                    val alpha = when (source) { PointSource.MEASURED -> 0.82f; PointSource.RECONSTRUCTED -> 0.68f; PointSource.FORECAST -> 0.54f }
                    val effect = when (source) {
                        PointSource.MEASURED -> PathEffect.dashPathEffect(floatArrayOf(10f, 7f))
                        PointSource.RECONSTRUCTED -> PathEffect.dashPathEffect(floatArrayOf(16f, 9f))
                        PointSource.FORECAST -> PathEffect.dashPathEffect(floatArrayOf(3f, 7f))
                    }
                    drawPath(path, color.copy(alpha = color.alpha * alpha), style = Stroke(width = max(1.2f, prefs.lineWidth - 0.5f).dp.toPx(), pathEffect = effect))
                }
                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        drawCircle(color.copy(alpha = if (p.source == PointSource.MEASURED) 0.82f else 0.58f), 2.dp.toPx(), Offset(mapX(p.timestamp), mapHum(p.humidity)))
                    }
                }
            }
'''
text = replace_once(text, old_hum, new_hum, 'humidity source rendering')

MAIN.write_text(text, encoding='utf-8')

print('FabData v0.10 thermal/source/reference patch applied')
