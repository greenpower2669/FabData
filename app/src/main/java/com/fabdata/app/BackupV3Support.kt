package com.fabdata.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.Writer

/**
 * Extra state required for a true FabData v3 restore.
 *
 * The ordinary SAMPLE/SENSOR/EVENT rows stay human-readable and backward compatible.
 * v3 adds typed rows for the exact weather reference, building topology, trained
 * models and per-engine training selections. All of them are ignored by old v1/v2
 * files because those rows simply do not exist there.
 */
class FabDataBackupV3Support(
    private val context: Context,
    private val db: FabDataDb
) {
    companion object {
        private val columns = listOf(
            "FabData_Record", "Format_Version", "Capteur_ID", "Capteur", "Piece", "Couleur",
            "Temps_Epoch_ms", "Temps", "Temperature_Celsius", "Humidite_relative_Pourcentage",
            "Titre", "Note", "Type", "UpdatedAt_Epoch_ms", "Source", "Confiance",
            "Reference_Station_ID", "Reference_Ville", "Calibration_Debut_ms", "Calibration_Fin_ms",
            "Model_Version"
        )
    }

    fun writeExtraRows(writer: Writer) {
        ThermalTrainingPolicyStore.ensure(db.writableDatabase)
        ThermalWallConfigStore.ensure(db.writableDatabase)
        ThermalWallSolarModelStore.ensure(db.writableDatabase)
        WeatherReferenceStore.ensure(db.writableDatabase)

        writeJson(writer, "WEATHER_META", weatherMetaJson())
        writeJson(writer, "THERMAL_PROFILE", profileJson())
        ThermalTrainedModelStore(context).loadAny()?.let { writeJson(writer, "TRAINED_MODEL", trainedModelJson(it)) }

        ThermalWallConfigStore(db).walls().forEach { wall ->
            writeJson(writer, "WALL", JSONObject().apply {
                put("id", wall.id)
                put("index", wall.index)
                put("name", wall.name)
                put("surfaceM2", wall.surfaceM2)
                putNullable("orientationDeg", wall.orientationDeg)
                put("exposure", wall.exposure.name)
                put("reconstructHistory", wall.reconstructHistory)
            })
        }

        db.sensors().forEach { sensor ->
            val cfg = ThermalWallConfigStore(db).sensorConfig(sensor.id)
            writeJson(writer, "SENSOR_THERMAL", JSONObject().apply {
                put("stableKey", sensor.stableKey)
                put("role", cfg.role.name)
                put("outdoorKind", cfg.outdoorKind.name)
                putNullable("wallId", cfg.wallId)
                putNullable("orientationDeg", cfg.orientationDeg)
            })
        }

        ThermalWallSolarModelStore(db).all().forEach { model ->
            writeJson(writer, "WALL_SOLAR_MODEL", wallSolarModelJson(model))
        }

        ThermalTrainingPolicyStore(db).allRanges(enabledOnly = false).forEach { range ->
            writeJson(writer, "TRAINING_POLICY", JSONObject().apply {
                put("target", range.target.name)
                put("mode", range.mode.name)
                put("from", range.from)
                put("to", range.to)
                put("enabled", range.enabled)
            })
        }

        if (tableExists("thermal_training_exclusions")) {
            db.readableDatabase.rawQuery(
                """
                SELECT s.stable_key, e.start_ts, e.end_ts, e.reason, e.enabled
                FROM thermal_training_exclusions e
                JOIN sensors s ON s.id=e.sensor_id
                ORDER BY e.start_ts, e.id
                """.trimIndent(), null
            ).use { c ->
                while (c.moveToNext()) {
                    writeJson(writer, "TRAINING_EXCLUSION", JSONObject().apply {
                        put("stableKey", c.getString(0))
                        put("from", c.getLong(1))
                        put("to", c.getLong(2))
                        put("reason", c.getString(3))
                        put("enabled", c.getInt(4) != 0)
                    })
                }
            }
        }

        // Exact reference series used by the engines. This is deliberately separate
        // from ordinary sensor samples and therefore must be explicitly backed up.
        db.readableDatabase.rawQuery(
            """
            SELECT reference_key, timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
            ORDER BY reference_key, timestamp
            """.trimIndent(), null
        ).use { c ->
            while (c.moveToNext()) {
                val values = mutableMapOf<String, String>()
                values["FabData_Record"] = "WEATHER"
                values["Format_Version"] = FabDataBackup.FORMAT_VERSION
                values["Capteur_ID"] = c.getString(0)
                values["Temps_Epoch_ms"] = c.getLong(1).toString()
                values["Temperature_Celsius"] = c.getDouble(2).toString()
                values["Humidite_relative_Pourcentage"] = c.getDouble(3).toString()
                values["Source"] = c.getString(4)
                values["Confiance"] = c.getDouble(5).toString()
                writeRow(writer, values)
            }
        }
    }

    /** Returns true when the v3 record was recognized and restored. */
    fun importRecord(record: String, values: Map<String, String>): Boolean {
        return runCatching {
            when (record) {
                "WEATHER_META" -> restoreWeatherMeta(json(values))
                "THERMAL_PROFILE" -> restoreProfile(json(values))
                "TRAINED_MODEL" -> restoreTrainedModel(json(values))
                "WALL" -> restoreWall(json(values))
                "SENSOR_THERMAL" -> restoreSensorThermal(json(values))
                "WALL_SOLAR_MODEL" -> restoreWallSolarModel(json(values))
                "TRAINING_POLICY" -> restoreTrainingPolicy(json(values))
                "TRAINING_EXCLUSION" -> restoreTrainingExclusion(json(values))
                "WEATHER" -> restoreWeather(values)
                else -> return false
            }
            true
        }.getOrElse { false }
    }

    private fun weatherMetaJson(): JSONObject {
        val ref = WeatherReferencePrefs(context).selectedReference()
        return JSONObject().apply {
            put("key", ref.key)
            put("city", ref.city)
            put("stationName", ref.stationName)
            put("stationId", ref.stationId)
            put("latitude", ref.latitude)
            put("longitude", ref.longitude)
            put("departmentId", ref.departmentId)
        }
    }

    private fun profileJson(): JSONObject {
        val store = ThermalProfileStore(context)
        val p = store.load()
        return JSONObject().apply {
            put("surfaceM2", p.surfaceM2)
            put("floor", p.floor)
            put("insulation", p.insulation)
            put("inertia", p.inertia.name)
            put("exposure", p.exposure.name)
            putNullable("initialMassOverrideC", p.initialMassOverrideC)
            put("forecastMode", store.forecastMode().name)
        }
    }

    private fun trainedModelJson(model: ThermalModel): JSONObject = JSONObject().apply {
        put("sensorId", model.sensorId)
        put("sensorStableKey", db.sensors().firstOrNull { it.id == model.sensorId }?.stableKey ?: "")
        put("sensorName", model.sensorName)
        put("room", model.room)
        put("referenceKey", model.referenceKey)
        put("referenceStationId", model.referenceStationId)
        put("referenceCity", model.referenceCity)
        put("lagHours", model.lagHours)
        put("coefficients", JSONArray().apply { model.coefficients.forEach { put(it) } })
        put("calibrationFrom", model.calibrationFrom)
        put("calibrationTo", model.calibrationTo)
        put("usablePoints", model.usablePoints)
        put("realDays", model.realDays)
        put("mae", model.metrics.mae)
        put("rmse", model.metrics.rmse)
        put("bias", model.metrics.bias)
        put("maxError", model.metrics.maxError)
        put("validationPoints", model.metrics.validationPoints)
        put("longHorizonRmse", model.longHorizonRmse)
        put("confidence", model.confidence)
        put("tauHours", model.tauHours)
        put("inertiaSurfaceTauHours", model.inertiaSurfaceTauHours)
        put("inertiaDeepTauHours", model.inertiaDeepTauHours)
        put("inertiaDeepShare", model.inertiaDeepShare)
        put("inertiaOutsideWeight", model.inertiaOutsideWeight)
        put("inertiaCouplingPerHour", model.inertiaCouplingPerHour)
        put("inertiaFitRmse", model.inertiaFitRmse)
        put("inertiaCleanHours", model.inertiaCleanHours)
        put("inertiaPlateauHours", model.inertiaPlateauHours)
        put("inertiaTangentPenalty", model.inertiaTangentPenalty)
        put("inertiaRegimeHours", model.inertiaRegimeHours)
    }

    private fun wallSolarModelJson(model: WallSolarModel): JSONObject = JSONObject().apply {
        put("wallId", model.wallId)
        put("orientationDeg", model.orientationDeg)
        put("orientationWasUserFixed", model.orientationWasUserFixed)
        put("baselineOffsetC", model.baselineOffsetC)
        put("solarGainC", model.solarGainC)
        put("responseTauHours", model.responseTauHours)
        put("fitRmseC", model.fitRmseC)
        put("trainingHours", model.trainingHours)
        put("realDays", model.realDays)
        put("daylightHours", model.daylightHours)
        put("confidence", model.confidence)
        put("calibrationFrom", model.calibrationFrom)
        put("calibrationTo", model.calibrationTo)
    }

    private fun restoreWeatherMeta(o: JSONObject) {
        val ref = WeatherReference(
            key = o.getString("key"),
            city = o.getString("city"),
            stationName = o.getString("stationName"),
            stationId = o.getString("stationId"),
            latitude = o.getDouble("latitude"),
            longitude = o.getDouble("longitude"),
            departmentId = o.optString("departmentId", "")
        )
        WeatherReferencePrefs(context).select(ref)
    }

    private fun restoreProfile(o: JSONObject) {
        val store = ThermalProfileStore(context)
        store.save(
            ThermalBuildingProfile(
                surfaceM2 = o.optDouble("surfaceM2", 70.0),
                floor = o.optInt("floor", 4),
                insulation = o.optString("insulation", "D"),
                inertia = enumValueOr(o.optString("inertia"), ThermalInertia.MEDIUM),
                exposure = enumValueOr(o.optString("exposure"), ThermalExposure.MEDIUM),
                initialMassOverrideC = nullableDouble(o, "initialMassOverrideC")
            )
        )
        store.saveForecastMode(enumValueOr(o.optString("forecastMode"), ForecastHorizonMode.AUTO))
    }

    private fun restoreTrainedModel(o: JSONObject) {
        val stableKey = o.optString("sensorStableKey", "")
        val sensorId = db.sensors().firstOrNull { it.stableKey == stableKey }?.id
            ?: o.optLong("sensorId", -1L)
        if (sensorId < 0L) return
        val coeffJson = o.optJSONArray("coefficients") ?: JSONArray()
        val coeff = DoubleArray(coeffJson.length()) { coeffJson.optDouble(it, 0.0) }
        if (coeff.isEmpty()) return
        val model = ThermalModel(
            sensorId = sensorId,
            sensorName = o.optString("sensorName", "Sonde"),
            room = o.optString("room", "Pièce"),
            referenceKey = o.optString("referenceKey", ""),
            referenceStationId = o.optString("referenceStationId", ""),
            referenceCity = o.optString("referenceCity", ""),
            lagHours = o.optInt("lagHours", 0),
            coefficients = coeff,
            calibrationFrom = o.optLong("calibrationFrom", 0L),
            calibrationTo = o.optLong("calibrationTo", 0L),
            usablePoints = o.optInt("usablePoints", 0),
            realDays = o.optInt("realDays", 0),
            metrics = ThermalMetrics(
                mae = o.optDouble("mae", 99.0),
                rmse = o.optDouble("rmse", 99.0),
                bias = o.optDouble("bias", 99.0),
                maxError = o.optDouble("maxError", 99.0),
                validationPoints = o.optInt("validationPoints", 0)
            ),
            longHorizonRmse = o.optDouble("longHorizonRmse", 99.0),
            confidence = o.optDouble("confidence", 0.0),
            tauHours = o.optDouble("tauHours", 336.0),
            inertiaSurfaceTauHours = o.optDouble("inertiaSurfaceTauHours", 48.0),
            inertiaDeepTauHours = o.optDouble("inertiaDeepTauHours", 336.0),
            inertiaDeepShare = o.optDouble("inertiaDeepShare", 0.72),
            inertiaOutsideWeight = o.optDouble("inertiaOutsideWeight", 0.15),
            inertiaCouplingPerHour = o.optDouble("inertiaCouplingPerHour", 0.012),
            inertiaFitRmse = o.optDouble("inertiaFitRmse", 0.80),
            inertiaCleanHours = o.optInt("inertiaCleanHours", 0),
            inertiaPlateauHours = o.optInt("inertiaPlateauHours", 0),
            inertiaTangentPenalty = o.optDouble("inertiaTangentPenalty", 0.0),
            inertiaRegimeHours = o.optInt("inertiaRegimeHours", 0)
        )
        ThermalTrainedModelStore(context).save(model)
    }

    private fun restoreWall(o: JSONObject) {
        ThermalWallConfigStore(db).upsertWall(
            ThermalWallSegment(
                id = o.getString("id"),
                index = o.optInt("index", 0),
                name = o.optString("name", "Pan"),
                surfaceM2 = o.optDouble("surfaceM2", 10.0),
                orientationDeg = nullableDouble(o, "orientationDeg"),
                exposure = enumValueOr(o.optString("exposure"), WallExposureMode.AUTO),
                reconstructHistory = o.optBoolean("reconstructHistory", false)
            )
        )
    }

    private fun restoreSensorThermal(o: JSONObject) {
        val sensor = db.sensors().firstOrNull { it.stableKey == o.optString("stableKey") } ?: return
        ThermalWallConfigStore(db).setSensorConfig(
            SensorThermalConfig(
                sensorId = sensor.id,
                role = enumValueOr(o.optString("role"), ThermalSensorRole.UNDEFINED),
                outdoorKind = enumValueOr(o.optString("outdoorKind"), OutdoorSensorKind.UNSPECIFIED),
                wallId = nullableString(o, "wallId"),
                orientationDeg = nullableDouble(o, "orientationDeg")
            )
        )
    }

    private fun restoreWallSolarModel(o: JSONObject) {
        ThermalWallSolarModelStore(db).save(
            WallSolarModel(
                wallId = o.getString("wallId"),
                orientationDeg = o.optDouble("orientationDeg", 0.0),
                orientationWasUserFixed = o.optBoolean("orientationWasUserFixed", false),
                baselineOffsetC = o.optDouble("baselineOffsetC", 0.0),
                solarGainC = o.optDouble("solarGainC", 0.0),
                responseTauHours = o.optDouble("responseTauHours", 6.0),
                fitRmseC = o.optDouble("fitRmseC", 99.0),
                trainingHours = o.optInt("trainingHours", 0),
                realDays = o.optInt("realDays", 0),
                daylightHours = o.optInt("daylightHours", 0),
                confidence = o.optDouble("confidence", 0.0),
                calibrationFrom = o.optLong("calibrationFrom", 0L),
                calibrationTo = o.optLong("calibrationTo", 0L)
            )
        )
    }

    private fun restoreTrainingPolicy(o: JSONObject) {
        if (!o.optBoolean("enabled", true)) return
        val target = enumValueOr(o.optString("target"), ThermalTrainingTarget.INERTIA)
        val mode = enumValueOr(o.optString("mode"), ThermalTrainingRangeMode.EXCLUDE)
        ThermalTrainingPolicyStore(db).apply(target, mode, o.getLong("from"), o.getLong("to"))
    }

    private fun restoreTrainingExclusion(o: JSONObject) {
        if (!o.optBoolean("enabled", true)) return
        val sensor = db.sensors().firstOrNull { it.stableKey == o.optString("stableKey") } ?: return
        ThermalTrainingMaskStore(db).addMerged(
            sensor.id,
            o.getLong("from"),
            o.getLong("to"),
            o.optString("reason", "Sauvegarde v3")
        )
    }

    private fun restoreWeather(values: Map<String, String>) {
        val key = values["Capteur_ID"].orEmpty().trim()
        val ts = values["Temps_Epoch_ms"].orEmpty().trim().toLongOrNull() ?: return
        val temp = values["Temperature_Celsius"].orEmpty().trim().replace(',', '.').toDoubleOrNull() ?: return
        val humidity = values["Humidite_relative_Pourcentage"].orEmpty().trim().replace(',', '.').toDoubleOrNull() ?: return
        val source = PointSource.fromDb(values["Source"])
        val confidence = values["Confiance"].orEmpty().trim().replace(',', '.').toDoubleOrNull() ?: 1.0
        if (key.isBlank()) return
        WeatherReferenceStore(db).upsert(
            key,
            WeatherReferencePoint(ts, temp, humidity, source, confidence.coerceIn(0.0, 1.0))
        )
    }

    private fun writeJson(writer: Writer, record: String, json: JSONObject) {
        writeRow(writer, mapOf(
            "FabData_Record" to record,
            "Format_Version" to FabDataBackup.FORMAT_VERSION,
            "Note" to json.toString()
        ))
    }

    private fun writeRow(writer: Writer, values: Map<String, String>) {
        writer.write(columns.joinToString(",") { csvEscape(values[it].orEmpty()) })
        writer.write("\n")
    }

    private fun json(values: Map<String, String>): JSONObject = JSONObject(values["Note"].orEmpty())

    private fun tableExists(name: String): Boolean = db.readableDatabase.rawQuery(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        arrayOf(name)
    ).use { it.moveToFirst() }

    private fun JSONObject.putNullable(key: String, value: Any?) {
        if (value == null) put(key, JSONObject.NULL) else put(key, value)
    }

    private fun nullableDouble(o: JSONObject, key: String): Double? =
        if (!o.has(key) || o.isNull(key)) null else o.optDouble(key).takeIf { !it.isNaN() }

    private fun nullableString(o: JSONObject, key: String): String? =
        if (!o.has(key) || o.isNull(key)) null else o.optString(key).takeIf { it.isNotBlank() }

    private inline fun <reified T : Enum<T>> enumValueOr(raw: String?, fallback: T): T =
        runCatching { enumValueOf<T>(raw.orEmpty()) }.getOrDefault(fallback)

    private fun csvEscape(value: String): String {
        if (value.none { it == ',' || it == '"' || it == '\n' || it == '\r' }) return value
        return "\"${value.replace("\"", "\"\"")}\""
    }
}
