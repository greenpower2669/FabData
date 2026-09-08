package com.fabdata.app

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import java.time.Instant
import java.time.ZoneId
import kotlin.math.abs

private const val WALL_SERVICE_HOUR_MS = 60L * 60L * 1000L

/** Persisted facade model. Real measurements always remain authoritative in samples. */
class ThermalWallSolarModelStore(private val db: FabDataDb) {
    companion object {
        const val MODEL_VERSION = "wall-solar-v1"

        fun ensure(sql: SQLiteDatabase) {
            sql.execSQL(
                """
                CREATE TABLE IF NOT EXISTS thermal_wall_solar_models (
                    wall_id TEXT PRIMARY KEY,
                    orientation_deg REAL NOT NULL,
                    orientation_user_fixed INTEGER NOT NULL,
                    baseline_offset_c REAL NOT NULL,
                    solar_gain_c REAL NOT NULL,
                    response_tau_h REAL NOT NULL,
                    fit_rmse_c REAL NOT NULL,
                    training_hours INTEGER NOT NULL,
                    real_days INTEGER NOT NULL,
                    daylight_hours INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    calibration_from INTEGER NOT NULL,
                    calibration_to INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """.trimIndent()
            )
        }
    }

    init { ensure(db.writableDatabase) }

    fun save(model: WallSolarModel) {
        ensure(db.writableDatabase)
        val v = ContentValues().apply {
            put("wall_id", model.wallId)
            put("orientation_deg", normalizeDegrees(model.orientationDeg))
            put("orientation_user_fixed", if (model.orientationWasUserFixed) 1 else 0)
            put("baseline_offset_c", model.baselineOffsetC)
            put("solar_gain_c", model.solarGainC)
            put("response_tau_h", model.responseTauHours)
            put("fit_rmse_c", model.fitRmseC)
            put("training_hours", model.trainingHours)
            put("real_days", model.realDays)
            put("daylight_hours", model.daylightHours)
            put("confidence", model.confidence.coerceIn(0.0, 1.0))
            put("calibration_from", model.calibrationFrom)
            put("calibration_to", model.calibrationTo)
            put("updated_at", System.currentTimeMillis())
        }
        db.writableDatabase.insertWithOnConflict(
            "thermal_wall_solar_models", null, v, SQLiteDatabase.CONFLICT_REPLACE
        )
    }

    fun load(wallId: String): WallSolarModel? {
        ensure(db.readableDatabase)
        db.readableDatabase.rawQuery(
            """
            SELECT orientation_deg, orientation_user_fixed, baseline_offset_c, solar_gain_c,
                   response_tau_h, fit_rmse_c, training_hours, real_days, daylight_hours,
                   confidence, calibration_from, calibration_to
            FROM thermal_wall_solar_models WHERE wall_id=? LIMIT 1
            """.trimIndent(), arrayOf(wallId)
        ).use { c ->
            if (!c.moveToFirst()) return null
            return WallSolarModel(
                wallId = wallId,
                orientationDeg = c.getDouble(0),
                orientationWasUserFixed = c.getInt(1) != 0,
                baselineOffsetC = c.getDouble(2),
                solarGainC = c.getDouble(3),
                responseTauHours = c.getDouble(4),
                fitRmseC = c.getDouble(5),
                trainingHours = c.getInt(6),
                realDays = c.getInt(7),
                daylightHours = c.getInt(8),
                confidence = c.getDouble(9),
                calibrationFrom = c.getLong(10),
                calibrationTo = c.getLong(11)
            )
        }
    }

    fun all(): List<WallSolarModel> {
        ensure(db.readableDatabase)
        val ids = mutableListOf<String>()
        db.readableDatabase.rawQuery("SELECT wall_id FROM thermal_wall_solar_models ORDER BY updated_at DESC", null)
            .use { c -> while (c.moveToNext()) ids += c.getString(0) }
        return ids.mapNotNull(::load)
    }

    fun delete(wallId: String) {
        db.writableDatabase.delete("thermal_wall_solar_models", "wall_id=?", arrayOf(wallId))
    }
}

data class ThermalWallSolarResult(
    val wallId: String,
    val targetSensorId: Long,
    val written: Int,
    val rejectedByMeasured: Int,
    val borrowedModel: Boolean,
    val model: WallSolarModel
)

/**
 * Facade reconstruction pipeline:
 * official weather -> learned local solar response -> wall curve.
 *
 * A wall may own a real outdoor sensor. If it does, reconstructed points are written
 * into that SAME sensor, and PointSourceStore guarantees MEASURED > RECONSTRUCTED.
 * If no sensor exists, a synthetic wall curve is created and explicitly classified OUTDOOR.
 */
class ThermalWallSolarService(
    private val db: FabDataDb,
    private val referenceStore: WeatherReferenceStore
) {
    private val configStore = ThermalWallConfigStore(db)
    private val modelStore = ThermalWallSolarModelStore(db)
    private val trainer = ThermalWallSolarTrainer()

    fun train(reference: WeatherReference, wallId: String): WallSolarModel {
        val wall = configStore.wallById(wallId) ?: error("Pan de mur introuvable")
        val sensor = linkedRealSensors(wallId)
            .maxByOrNull { measuredPoints(it.id).size }
            ?: error("Aucune sonde extérieure réelle associée à ${wall.name}")
        val measured = measuredPoints(sensor.id)
        require(measured.size >= 6) { "Au moins 6 heures réelles sont nécessaires" }
        val from = measured.first().timestamp - 2L * WALL_SERVICE_HOUR_MS
        val to = measured.last().timestamp + WALL_SERVICE_HOUR_MS
        val official = referenceStore.query(reference.key, from, to)
            .filter { it.source != PointSource.FORECAST }
        require(official.size >= 6) { "Référence météo officielle insuffisante" }
        val officialByHour = official.groupBy { hourBucket(it.timestamp) }
            .mapValues { (_, p) -> p.maxByOrNull { it.source.priority }!! }
        val observations = measured.mapNotNull { p ->
            val out = nearestOfficial(officialByHour, p.timestamp) ?: return@mapNotNull null
            WallSolarObservation(p.timestamp, out.temperature, p.temperature)
        }
        val model = trainer.train(reference, wall, observations)
            ?: error("Signature solaire insuffisante pour entraîner ${wall.name}")
        modelStore.save(model)
        return model
    }

    /**
     * Reconstructs all available official history. A target wall without its own model
     * may borrow the strongest trained wall model; orientation is replaced by the target
     * orientation and confidence is deliberately reduced.
     */
    fun reconstruct(reference: WeatherReference, wallId: String): ThermalWallSolarResult {
        val wall = configStore.wallById(wallId) ?: error("Pan de mur introuvable")
        require(wall.reconstructHistory) { "Reconstruction historique désactivée pour ${wall.name}" }
        val own = modelStore.load(wallId)
        val donor = if (own == null) chooseDonor(wallId) else null
        val baseModel = own ?: donor ?: error("Aucun modèle solaire disponible à extrapoler")
        val borrowed = own == null
        val adapted = if (!borrowed) baseModel else {
            val orientation = wall.orientationDeg ?: baseModel.orientationDeg
            baseModel.copy(
                wallId = wallId,
                orientationDeg = normalizeDegrees(orientation),
                orientationWasUserFixed = wall.orientationDeg != null,
                confidence = (baseModel.confidence * 0.62).coerceIn(0.05, 0.75)
            )
        }

        val bounds = referenceStore.historyBounds(reference.key)
            ?: error("Aucun historique météo pour ${reference.city}")
        val warmup = (adapted.responseTauHours.coerceAtLeast(1.0) * 6.0).toLong()
            .coerceIn(12L, 240L) * WALL_SERVICE_HOUR_MS
        val official = referenceStore.query(reference.key, bounds.first - warmup, bounds.last)
            .filter { it.source != PointSource.FORECAST }
        val reconstructed = trainer.reconstruct(reference, adapted, official, bounds.first, bounds.last)
        require(reconstructed.isNotEmpty()) { "Aucun point de façade reconstruisible" }

        val target = linkedRealSensors(wallId).maxByOrNull { measuredPoints(it.id).size }
            ?: syntheticSensor(wall)
        val officialByHour = official.groupBy { hourBucket(it.timestamp) }
            .mapValues { (_, p) -> p.maxByOrNull { it.source.priority }!! }
        var written = 0
        var rejected = 0
        val profileHash = "wall:${configStore.signature().hashCode()}"
        db.inTransaction {
            reconstructed.forEach { p ->
                val weather = nearestOfficial(officialByHour, p.timestamp)
                val humidity = weather?.humidity?.coerceIn(0.0, 100.0) ?: 50.0
                val provenance = PointProvenance(
                    source = PointSource.RECONSTRUCTED,
                    confidence = p.confidence,
                    referenceKey = reference.key,
                    referenceStationId = reference.stationId,
                    referenceCity = reference.city,
                    modelVersion = ThermalWallSolarModelStore.MODEL_VERSION,
                    profileHash = profileHash,
                    dependencyHash = "wall-solar:${wall.id}:${adapted.calibrationFrom}:${adapted.calibrationTo}:${adapted.orientationDeg}"
                )
                when (PointSourceStore.upsertByPriority(
                    db, target.id, p.timestamp, p.temperature, humidity, provenance
                )) {
                    PriorityWriteResult.INSERTED, PriorityWriteResult.REPLACED -> written++
                    PriorityWriteResult.REJECTED, PriorityWriteResult.UNCHANGED -> rejected++
                }
            }
        }
        return ThermalWallSolarResult(wallId, target.id, written, rejected, borrowed, adapted)
    }

    fun model(wallId: String): WallSolarModel? = modelStore.load(wallId)

    private fun chooseDonor(targetWallId: String): WallSolarModel? = modelStore.all()
        .filter { it.wallId != targetWallId }
        .maxByOrNull { it.confidence * (1.0 / (0.25 + it.fitRmseC)) }

    private fun linkedRealSensors(wallId: String): List<Sensor> = configStore.outdoorSensors().filter { sensor ->
        val c = configStore.sensorConfig(sensor.id)
        c.wallId == wallId && !sensor.stableKey.startsWith("wall-reconstructed-")
    }

    private fun measuredPoints(sensorId: Long): List<SamplePoint> {
        PointSourceStore.ensure(db.readableDatabase)
        val out = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source='measured')
            ORDER BY p.timestamp
            """.trimIndent(), arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) out += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2))
        }
        return out.groupBy { hourBucket(it.timestamp) }.map { (_, values) ->
            SamplePoint(
                sensorId,
                values.first().timestamp / WALL_SERVICE_HOUR_MS * WALL_SERVICE_HOUR_MS,
                values.map { it.temperature }.average(),
                values.map { it.humidity }.average(),
                PointSource.MEASURED
            )
        }.sortedBy { it.timestamp }
    }

    private fun syntheticSensor(wall: ThermalWallSegment): Sensor {
        val stable = "wall-reconstructed-${wall.id}"
        val sensor = db.getOrCreateSensor(stable, "${wall.name} · reconstruit")
        configStore.setSensorConfig(
            SensorThermalConfig(
                sensorId = sensor.id,
                role = ThermalSensorRole.OUTDOOR,
                outdoorKind = OutdoorSensorKind.FACADE_MICROCLIMATE,
                wallId = wall.id,
                orientationDeg = wall.orientationDeg
            )
        )
        return sensor
    }

    private fun nearestOfficial(
        byHour: Map<Long, WeatherReferencePoint>,
        timestamp: Long
    ): WeatherReferencePoint? {
        val bucket = hourBucket(timestamp)
        byHour[bucket]?.let { return it }
        return listOfNotNull(byHour[bucket - WALL_SERVICE_HOUR_MS], byHour[bucket + WALL_SERVICE_HOUR_MS])
            .minByOrNull { abs(it.timestamp - timestamp) }
    }

    private fun hourBucket(timestamp: Long): Long = timestamp / WALL_SERVICE_HOUR_MS * WALL_SERVICE_HOUR_MS
}
