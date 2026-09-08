package com.fabdata.app

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import kotlin.math.roundToInt

/**
 * Semantic role of a FabData sensor for thermal modelling.
 *
 * IMPORTANT:
 * - legacy physical sensors are migrated to INDOOR once;
 * - future ordinary CSV sensors start as UNDEFINED and are therefore safe until
 *   the user classifies them in building/sensor customisation;
 * - weather references remain separate from ordinary sensors.
 */
enum class ThermalSensorRole {
    UNDEFINED,
    INDOOR,
    OUTDOOR,
    SYSTEM_REFERENCE
}

enum class OutdoorSensorKind {
    AIR_REFERENCE,
    FACADE_MICROCLIMATE,
    SURFACE,
    UNSPECIFIED
}

enum class WallExposureMode {
    AUTO,
    SUN,
    SHADE,
    UNKNOWN
}

enum class ThermalTrainingTarget {
    INERTIA,
    SOLAR,
    BOTH
}

data class SensorThermalConfig(
    val sensorId: Long,
    val role: ThermalSensorRole,
    val outdoorKind: OutdoorSensorKind = OutdoorSensorKind.UNSPECIFIED,
    val wallId: String? = null,
    val orientationDeg: Double? = null,
    val updatedAt: Long = 0L
)

data class ThermalWallSegment(
    val id: String,
    val index: Int,
    val name: String,
    val surfaceM2: Double,
    val orientationDeg: Double?,
    val exposure: WallExposureMode,
    val reconstructHistory: Boolean,
    val updatedAt: Long = 0L
) {
    val compassLabel: String
        get() = orientationDeg?.let(::orientationLabel) ?: "Orientation auto"
}

/**
 * Persistent thermal-building topology.
 *
 * This store deliberately lives beside the old ThermalBuildingProfile instead of
 * replacing it. That keeps v0.19.8 behaviour available as the fallback when no
 * explicit wall topology is used.
 */
class ThermalWallConfigStore(private val db: FabDataDb) {
    companion object {
        const val MAX_WALLS = 4

        fun ensure(sql: SQLiteDatabase) {
            sql.execSQL(
                """
                CREATE TABLE IF NOT EXISTS sensor_thermal_config (
                    sensor_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL,
                    outdoor_kind TEXT NOT NULL DEFAULT 'UNSPECIFIED',
                    wall_id TEXT,
                    orientation_deg REAL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(sensor_id) REFERENCES sensors(id) ON DELETE CASCADE
                )
                """.trimIndent()
            )
            sql.execSQL(
                """
                CREATE TABLE IF NOT EXISTS thermal_wall_segments (
                    wall_id TEXT PRIMARY KEY,
                    sort_index INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    surface_m2 REAL NOT NULL,
                    orientation_deg REAL,
                    exposure TEXT NOT NULL,
                    reconstruct_history INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                )
                """.trimIndent()
            )
            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_sensor_thermal_role ON sensor_thermal_config(role)")
            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_sensor_thermal_wall ON sensor_thermal_config(wall_id)")
            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_thermal_wall_order ON thermal_wall_segments(sort_index)")

            // One-time conservative migration for the already existing database:
            // all ordinary physical sensors predate v0.20 and were used as indoor
            // sensors by the old engine, so preserve that behaviour exactly.
            sql.execSQL(
                """
                INSERT OR IGNORE INTO sensor_thermal_config(
                    sensor_id, role, outdoor_kind, wall_id, orientation_deg, updated_at
                )
                SELECT id,
                       CASE
                           WHEN stable_key LIKE 'meteo-%' THEN 'SYSTEM_REFERENCE'
                           WHEN stable_key LIKE 'http-get-%' THEN 'OUTDOOR'
                           ELSE 'INDOOR'
                       END,
                       CASE
                           WHEN stable_key LIKE 'http-get-%' THEN 'AIR_REFERENCE'
                           ELSE 'UNSPECIFIED'
                       END,
                       NULL, NULL, strftime('%s','now') * 1000
                FROM sensors
                """.trimIndent()
            )

            // Future sensors are deliberately not assumed to be indoor. This prevents
            // a newly imported exterior CSV from silently contaminating the indoor RC
            // model before the user has classified it.
            sql.execSQL(
                """
                CREATE TRIGGER IF NOT EXISTS trg_sensor_thermal_config_after_insert
                AFTER INSERT ON sensors
                BEGIN
                    INSERT OR IGNORE INTO sensor_thermal_config(
                        sensor_id, role, outdoor_kind, wall_id, orientation_deg, updated_at
                    ) VALUES (
                        NEW.id,
                        CASE
                            WHEN NEW.stable_key LIKE 'meteo-%' THEN 'SYSTEM_REFERENCE'
                            WHEN NEW.stable_key LIKE 'http-get-%' THEN 'OUTDOOR'
                            ELSE 'UNDEFINED'
                        END,
                        CASE
                            WHEN NEW.stable_key LIKE 'http-get-%' THEN 'AIR_REFERENCE'
                            ELSE 'UNSPECIFIED'
                        END,
                        NULL, NULL, strftime('%s','now') * 1000
                    );
                END
                """.trimIndent()
            )
        }
    }

    init {
        ensure(db.writableDatabase)
    }

    fun sensorConfig(sensorId: Long): SensorThermalConfig {
        ensure(db.readableDatabase)
        db.readableDatabase.rawQuery(
            """
            SELECT role, outdoor_kind, wall_id, orientation_deg, updated_at
            FROM sensor_thermal_config
            WHERE sensor_id=? LIMIT 1
            """.trimIndent(),
            arrayOf(sensorId.toString())
        ).use { c ->
            if (c.moveToFirst()) {
                return SensorThermalConfig(
                    sensorId = sensorId,
                    role = enumOr(c.getString(0), ThermalSensorRole.UNDEFINED),
                    outdoorKind = enumOr(c.getString(1), OutdoorSensorKind.UNSPECIFIED),
                    wallId = if (c.isNull(2)) null else c.getString(2),
                    orientationDeg = if (c.isNull(3)) null else normalizeDegrees(c.getDouble(3)),
                    updatedAt = c.getLong(4)
                )
            }
        }

        // Defensive fallback for a database where the trigger was not yet active.
        val sensor = db.sensors().firstOrNull { it.id == sensorId }
        val inferred = when {
            sensor == null -> ThermalSensorRole.UNDEFINED
            sensor.stableKey.startsWith("meteo-") -> ThermalSensorRole.SYSTEM_REFERENCE
            sensor.stableKey.startsWith("http-get-") -> ThermalSensorRole.OUTDOOR
            else -> ThermalSensorRole.UNDEFINED
        }
        return SensorThermalConfig(sensorId, inferred)
    }

    fun setSensorConfig(raw: SensorThermalConfig) {
        ensure(db.writableDatabase)
        val wall = raw.wallId?.let { wallById(it) }
        if (raw.wallId != null) require(wall != null) { "Pan de mur introuvable: ${raw.wallId}" }
        if (raw.wallId != null) require(raw.role == ThermalSensorRole.OUTDOOR) {
            "Seule une sonde extérieure peut être associée à un pan de mur"
        }
        val now = System.currentTimeMillis()
        val values = ContentValues().apply {
            put("sensor_id", raw.sensorId)
            put("role", raw.role.name)
            put("outdoor_kind", raw.outdoorKind.name)
            if (raw.wallId == null) putNull("wall_id") else put("wall_id", raw.wallId)
            val orientation = raw.orientationDeg?.let(::normalizeDegrees)
            if (orientation == null) putNull("orientation_deg") else put("orientation_deg", orientation)
            put("updated_at", now)
        }
        db.writableDatabase.insertWithOnConflict(
            "sensor_thermal_config", null, values, SQLiteDatabase.CONFLICT_REPLACE
        )
    }

    fun setSensorRole(sensorId: Long, role: ThermalSensorRole) {
        val current = sensorConfig(sensorId)
        setSensorConfig(
            if (role == ThermalSensorRole.OUTDOOR) current.copy(role = role)
            else current.copy(
                role = role,
                outdoorKind = OutdoorSensorKind.UNSPECIFIED,
                wallId = null,
                orientationDeg = null
            )
        )
    }

    fun indoorSensors(): List<Sensor> = db.sensors().filter {
        it.id >= 0L && sensorConfig(it.id).role == ThermalSensorRole.INDOOR
    }

    fun outdoorSensors(): List<Sensor> = db.sensors().filter {
        it.id >= 0L && sensorConfig(it.id).role == ThermalSensorRole.OUTDOOR
    }

    fun undefinedSensors(): List<Sensor> = db.sensors().filter {
        it.id >= 0L && sensorConfig(it.id).role == ThermalSensorRole.UNDEFINED
    }

    fun walls(): List<ThermalWallSegment> {
        ensure(db.readableDatabase)
        val out = mutableListOf<ThermalWallSegment>()
        db.readableDatabase.rawQuery(
            """
            SELECT wall_id, sort_index, name, surface_m2, orientation_deg,
                   exposure, reconstruct_history, updated_at
            FROM thermal_wall_segments
            ORDER BY sort_index, wall_id
            """.trimIndent(), null
        ).use { c ->
            while (c.moveToNext()) {
                out += ThermalWallSegment(
                    id = c.getString(0),
                    index = c.getInt(1),
                    name = c.getString(2),
                    surfaceM2 = c.getDouble(3),
                    orientationDeg = if (c.isNull(4)) null else normalizeDegrees(c.getDouble(4)),
                    exposure = enumOr(c.getString(5), WallExposureMode.AUTO),
                    reconstructHistory = c.getInt(6) != 0,
                    updatedAt = c.getLong(7)
                )
            }
        }
        return out
    }

    fun wallById(id: String): ThermalWallSegment? = walls().firstOrNull { it.id == id }

    fun upsertWall(raw: ThermalWallSegment): ThermalWallSegment {
        ensure(db.writableDatabase)
        val current = walls()
        val exists = current.any { it.id == raw.id }
        require(exists || current.size < MAX_WALLS) { "Maximum $MAX_WALLS pans de mur" }
        val normalized = raw.copy(
            index = raw.index.coerceIn(0, MAX_WALLS - 1),
            name = raw.name.trim().ifBlank { "Pan ${raw.index + 1}" },
            surfaceM2 = raw.surfaceM2.coerceIn(0.5, 1000.0),
            orientationDeg = raw.orientationDeg?.let(::normalizeDegrees),
            updatedAt = System.currentTimeMillis()
        )
        val values = ContentValues().apply {
            put("wall_id", normalized.id)
            put("sort_index", normalized.index)
            put("name", normalized.name)
            put("surface_m2", normalized.surfaceM2)
            if (normalized.orientationDeg == null) putNull("orientation_deg")
            else put("orientation_deg", normalized.orientationDeg)
            put("exposure", normalized.exposure.name)
            put("reconstruct_history", if (normalized.reconstructHistory) 1 else 0)
            put("updated_at", normalized.updatedAt)
        }
        db.writableDatabase.insertWithOnConflict(
            "thermal_wall_segments", null, values, SQLiteDatabase.CONFLICT_REPLACE
        )
        return normalized
    }

    fun createWall(
        surfaceM2: Double,
        orientationDeg: Double? = null,
        exposure: WallExposureMode = WallExposureMode.AUTO,
        reconstructHistory: Boolean = false
    ): ThermalWallSegment {
        val existing = walls()
        require(existing.size < MAX_WALLS) { "Maximum $MAX_WALLS pans de mur" }
        val nextIndex = (0 until MAX_WALLS).first { wanted -> existing.none { it.index == wanted } }
        val now = System.currentTimeMillis()
        return upsertWall(
            ThermalWallSegment(
                id = "wall-${now}-${nextIndex}",
                index = nextIndex,
                name = "Pan ${nextIndex + 1}",
                surfaceM2 = surfaceM2,
                orientationDeg = orientationDeg,
                exposure = exposure,
                reconstructHistory = reconstructHistory,
                updatedAt = now
            )
        )
    }

    fun deleteWall(id: String) {
        ensure(db.writableDatabase)
        db.inTransaction {
            val detached = ContentValues().apply { putNull("wall_id") }
            db.writableDatabase.update("sensor_thermal_config", detached, "wall_id=?", arrayOf(id))
            db.writableDatabase.delete("thermal_wall_segments", "wall_id=?", arrayOf(id))
        }
    }

    /**
     * Stable signature for reconstruction coherence. Any semantic change in the
     * wall topology or sensor assignment must invalidate old calculated curves,
     * while never touching MEASURED values.
     */
    fun signature(): String {
        ensure(db.readableDatabase)
        val wallPart = walls().joinToString("|") { w ->
            listOf(
                w.id, w.index.toString(), w.name,
                "%.4f".format(java.util.Locale.ROOT, w.surfaceM2),
                w.orientationDeg?.let { "%.3f".format(java.util.Locale.ROOT, it) } ?: "auto",
                w.exposure.name,
                if (w.reconstructHistory) "1" else "0"
            ).joinToString(":")
        }
        val sensorPart = db.sensors().sortedBy { it.id }.joinToString("|") { s ->
            val c = sensorConfig(s.id)
            listOf(
                s.stableKey,
                c.role.name,
                c.outdoorKind.name,
                c.wallId ?: "none",
                c.orientationDeg?.let { "%.3f".format(java.util.Locale.ROOT, it) } ?: "auto"
            ).joinToString(":")
        }
        return "$wallPart#$sensorPart"
    }
}

fun normalizeDegrees(value: Double): Double {
    var out = value % 360.0
    if (out < 0.0) out += 360.0
    return out
}

fun orientationLabel(degrees: Double): String {
    val d = normalizeDegrees(degrees)
    val labels = listOf("N", "NE", "E", "SE", "S", "SO", "O", "NO")
    val index = ((d / 45.0).roundToInt()) % 8
    return "${d.roundToInt()}° ${labels[index]}"
}

private inline fun <reified T : Enum<T>> enumOr(raw: String?, fallback: T): T =
    runCatching { enumValueOf<T>(raw.orEmpty()) }.getOrDefault(fallback)
