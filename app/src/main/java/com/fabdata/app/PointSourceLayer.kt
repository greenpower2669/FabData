package com.fabdata.app

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import java.util.Collections
import java.util.WeakHashMap

/**
 * Provenance d'un point FabData.
 *
 * Compatibilité : l'absence d'une ligne de provenance signifie MEASURED.
 * On ne duplique donc pas les anciennes données et on ne force aucune migration
 * destructive de la table samples.
 */
enum class PointSource(val dbValue: String, val priority: Int) {
    MEASURED("measured", 3),
    RECONSTRUCTED("reconstructed", 2),
    FORECAST("forecast", 1);

    companion object {
        fun fromDb(raw: String?): PointSource = when (raw?.trim()?.lowercase()) {
            "reconstructed" -> RECONSTRUCTED
            "forecast" -> FORECAST
            else -> MEASURED
        }
    }
}

data class PointProvenance(
    val source: PointSource,
    val confidence: Double? = null,
    val referenceKey: String? = null,
    val referenceStationId: String? = null,
    val referenceCity: String? = null,
    val calibrationFrom: Long? = null,
    val calibrationTo: Long? = null,
    val modelVersion: String? = null,
    val sigmaC: Double? = null,
    val analogCount: Int? = null
)

enum class PriorityWriteResult { INSERTED, REPLACED, UNCHANGED, REJECTED }

data class PriorityPointWrite(
    val sensorId: Long,
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val provenance: PointProvenance
)

object PointSourceStore {
    const val MODEL_VERSION = "thermal-rc-inertia-4"

    // v0.12.2 : une migration additive n'a besoin d'être vérifiée qu'une seule fois
    // par handle SQLite. WeakHashMap évite de retenir une base fermée en mémoire.
    private val ensuredDatabases = Collections.synchronizedMap(WeakHashMap<SQLiteDatabase, Boolean>())

    fun ensure(db: SQLiteDatabase) {
        synchronized(ensuredDatabases) {
            if (ensuredDatabases[db] == true) return
        }
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS point_sources (
                sensor_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                source TEXT NOT NULL,
                confidence REAL,
                sigma_c REAL,
                analog_count INTEGER,
                reference_key TEXT,
                reference_station_id TEXT,
                reference_city TEXT,
                calibration_from INTEGER,
                calibration_to INTEGER,
                model_version TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(sensor_id, timestamp),
                FOREIGN KEY(sensor_id) REFERENCES sensors(id) ON DELETE CASCADE
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_time ON point_sources(sensor_id, timestamp)")
        ensureColumn(db, "sigma_c", "REAL")
        ensureColumn(db, "analog_count", "INTEGER")
        synchronized(ensuredDatabases) { ensuredDatabases[db] = true }
    }

    private fun ensureColumn(db: SQLiteDatabase, name: String, type: String) {
        val exists = db.rawQuery("PRAGMA table_info(point_sources)", null).use { c ->
            var found = false
            while (c.moveToNext()) {
                if (c.getString(c.getColumnIndexOrThrow("name")) == name) { found = true; break }
            }
            found
        }
        if (!exists) db.execSQL("ALTER TABLE point_sources ADD COLUMN $name $type")
    }

    fun sourceFor(db: FabDataDb, sensorId: Long, timestamp: Long): PointSource {
        ensure(db.readableDatabase)
        db.readableDatabase.rawQuery(
            "SELECT source FROM point_sources WHERE sensor_id=? AND timestamp=? LIMIT 1",
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            return if (c.moveToFirst()) PointSource.fromDb(c.getString(0)) else PointSource.MEASURED
        }
    }

    fun provenanceFor(db: FabDataDb, sensorId: Long, timestamp: Long): PointProvenance {
        ensure(db.readableDatabase)
        db.readableDatabase.rawQuery(
            """
            SELECT source, confidence, reference_key, reference_station_id, reference_city,
                   calibration_from, calibration_to, model_version, sigma_c, analog_count
            FROM point_sources
            WHERE sensor_id=? AND timestamp=? LIMIT 1
            """.trimIndent(),
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) return PointProvenance(PointSource.MEASURED)
            return PointProvenance(
                source = PointSource.fromDb(c.getString(0)),
                confidence = if (c.isNull(1)) null else c.getDouble(1),
                referenceKey = if (c.isNull(2)) null else c.getString(2),
                referenceStationId = if (c.isNull(3)) null else c.getString(3),
                referenceCity = if (c.isNull(4)) null else c.getString(4),
                calibrationFrom = if (c.isNull(5)) null else c.getLong(5),
                calibrationTo = if (c.isNull(6)) null else c.getLong(6),
                modelVersion = if (c.isNull(7)) null else c.getString(7),
                sigmaC = if (c.isNull(8)) null else c.getDouble(8),
                analogCount = if (c.isNull(9)) null else c.getInt(9)
            )
        }
    }

    /**
     * MEASURED est représenté par l'absence de ligne : c'est la valeur par défaut
     * et cela garantit la compatibilité avec les bases et exports antérieurs.
     */
    fun markMeasured(db: FabDataDb, sensorId: Long, timestamp: Long) {
        ensure(db.writableDatabase)
        db.writableDatabase.delete(
            "point_sources",
            "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
        // Une vraie mesure change l'état connu : tout forecast situé après elle
        // appartient désormais à un ancien état du monde et doit disparaître.
        invalidateForecastsAfterMeasured(db, sensorId, timestamp)
    }

    private fun invalidateForecastsAfterMeasured(db: FabDataDb, sensorId: Long, timestamp: Long) {
        ensure(db.writableDatabase)
        val future = mutableListOf<Long>()
        db.readableDatabase.rawQuery(
            "SELECT timestamp FROM point_sources WHERE sensor_id=? AND source='forecast' AND timestamp>?",
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c -> while (c.moveToNext()) future += c.getLong(0) }
        future.forEach { ts ->
            db.writableDatabase.delete("samples", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))
            db.writableDatabase.delete("point_sources", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))
        }
    }

    fun setProvenance(
        db: FabDataDb,
        sensorId: Long,
        timestamp: Long,
        provenance: PointProvenance
    ) {
        ensure(db.writableDatabase)
        if (provenance.source == PointSource.MEASURED) {
            markMeasured(db, sensorId, timestamp)
            return
        }
        val values = ContentValues().apply {
            put("sensor_id", sensorId)
            put("timestamp", timestamp)
            put("source", provenance.source.dbValue)
            provenance.confidence?.let { put("confidence", it.coerceIn(0.0, 1.0)) }
            provenance.sigmaC?.let { put("sigma_c", it.coerceIn(0.0, 20.0)) }
            provenance.analogCount?.let { put("analog_count", it.coerceAtLeast(0)) }
            provenance.referenceKey?.let { put("reference_key", it) }
            provenance.referenceStationId?.let { put("reference_station_id", it) }
            provenance.referenceCity?.let { put("reference_city", it) }
            provenance.calibrationFrom?.let { put("calibration_from", it) }
            provenance.calibrationTo?.let { put("calibration_to", it) }
            provenance.modelVersion?.let { put("model_version", it) }
            put("updated_at", System.currentTimeMillis())
        }
        db.writableDatabase.insertWithOnConflict(
            "point_sources", null, values, SQLiteDatabase.CONFLICT_REPLACE
        )
    }

    /**
     * Écriture unique respectant strictement : MEASURED > RECONSTRUCTED > FORECAST.
     */
    fun upsertByPriority(
        db: FabDataDb,
        sensorId: Long,
        timestamp: Long,
        temperature: Double,
        humidity: Double,
        provenance: PointProvenance
    ): PriorityWriteResult {
        require(temperature in -100.0..150.0)
        require(humidity in 0.0..100.0)
        ensure(db.writableDatabase)

        val existing = db.readableDatabase.rawQuery(
            """
            SELECT p.temperature, p.humidity, ps.source
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND p.timestamp=? LIMIT 1
            """.trimIndent(),
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) null
            else Triple(c.getDouble(0), c.getDouble(1), PointSource.fromDb(if (c.isNull(2)) null else c.getString(2)))
        }

        if (existing == null) {
            val values = ContentValues().apply {
                put("sensor_id", sensorId)
                put("timestamp", timestamp)
                put("temperature", temperature)
                put("humidity", humidity)
            }
            val row = db.writableDatabase.insertWithOnConflict(
                "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
            )
            if (row == -1L) return PriorityWriteResult.UNCHANGED
            setProvenance(db, sensorId, timestamp, provenance)
            return PriorityWriteResult.INSERTED
        }

        val existingSource = existing.third
        if (provenance.source.priority < existingSource.priority) {
            return PriorityWriteResult.REJECTED
        }

        val sameValues = kotlin.math.abs(existing.first - temperature) < 0.001 &&
            kotlin.math.abs(existing.second - humidity) < 0.001

        if (provenance.source.priority == existingSource.priority && sameValues) {
            // La vraie mesure doit quand même effacer une ancienne provenance calculée.
            if (provenance.source == PointSource.MEASURED) markMeasured(db, sensorId, timestamp)
            return PriorityWriteResult.UNCHANGED
        }

        // Même niveau non mesuré : autorise une meilleure reconstruction/prévision à se raffiner.
        // Niveau supérieur : remplace automatiquement la valeur inférieure.
        val values = ContentValues().apply {
            put("temperature", temperature)
            put("humidity", humidity)
        }
        db.writableDatabase.update(
            "samples",
            values,
            "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
        setProvenance(db, sensorId, timestamp, provenance)
        return PriorityWriteResult.REPLACED
    }

    /**
     * Écrit les points calculés par petits lots transactionnels. Un historique de 90 jours
     * passe ainsi d'environ 2000 commits SQLite à quelques commits seulement.
     * Le callback est appelé APRES chaque commit afin que l'UI puisse afficher la progression.
     */
    fun upsertBatchByPriority(
        db: FabDataDb,
        points: List<PriorityPointWrite>,
        chunkSize: Int = 256,
        onChunkCommitted: ((processed: Int, changed: Int) -> Unit)? = null
    ): Int {
        if (points.isEmpty()) return 0
        ensure(db.writableDatabase)
        val size = chunkSize.coerceIn(32, 1024)
        var processed = 0
        var changed = 0
        points.chunked(size).forEach { chunk ->
            db.inTransaction {
                chunk.forEach { p ->
                    val result = upsertByPriority(
                        db, p.sensorId, p.timestamp, p.temperature, p.humidity, p.provenance
                    )
                    if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) changed++
                }
            }
            processed += chunk.size
            onChunkCommitted?.invoke(processed, changed)
        }
        return changed
    }

    fun deleteForecastsAtOrAfter(db: FabDataDb, sensorId: Long, timestamp: Long) {
        ensure(db.writableDatabase)
        val toDelete = mutableListOf<Long>()
        db.readableDatabase.rawQuery(
            "SELECT timestamp FROM point_sources WHERE sensor_id=? AND source='forecast' AND timestamp>=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c -> while (c.moveToNext()) toDelete += c.getLong(0) }
        if (toDelete.isEmpty()) return
        db.inTransaction {
            toDelete.forEach { ts ->
                db.writableDatabase.delete(
                    "samples", "sensor_id=? AND timestamp=?",
                    arrayOf(sensorId.toString(), ts.toString())
                )
                db.writableDatabase.delete(
                    "point_sources", "sensor_id=? AND timestamp=?",
                    arrayOf(sensorId.toString(), ts.toString())
                )
            }
        }
    }

    fun reconstructedBounds(db: FabDataDb, sensorId: Long): LongRange? {
        ensure(db.readableDatabase)
        db.readableDatabase.rawQuery(
            "SELECT MIN(timestamp), MAX(timestamp) FROM point_sources WHERE sensor_id=? AND source='reconstructed'",
            arrayOf(sensorId.toString())
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    fun measuredCount(db: FabDataDb, sensorId: Long, from: Long, to: Long): Int {
        ensure(db.readableDatabase)
        db.readableDatabase.rawQuery(
            """
            SELECT COUNT(*)
            FROM samples p
            LEFT JOIN point_sources s ON s.sensor_id=p.sensor_id AND s.timestamp=p.timestamp
            WHERE p.sensor_id=? AND p.timestamp BETWEEN ? AND ?
              AND (s.source IS NULL OR s.source='measured')
            """.trimIndent(),
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c -> return if (c.moveToFirst()) c.getInt(0) else 0 }
    }
}
