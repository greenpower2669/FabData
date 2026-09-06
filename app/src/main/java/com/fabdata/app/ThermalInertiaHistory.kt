package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

private const val INERTIA_HISTORY_HOUR_MS = 60L * 60L * 1000L
private const val INERTIA_HISTORY_DAY_MS = 24L * INERTIA_HISTORY_HOUR_MS
private const val INERTIA_HISTORY_MONTH_DAYS = 31

data class ThermalInertiaPropagationState(
    val surface: Double,
    val deep: Double,
    val timestamp: Long
)

data class ThermalInertiaHistoryWork(
    val referenceKey: String,
    val sensorId: Long,
    val modelSignature: String,
    val requestedDays: Int,
    val firstMeasuredTimestamp: Long,
    val nextChunk: Int,
    val totalChunks: Int,
    val paused: Boolean,
    val seedSurface: Double?,
    val seedDeep: Double?,
    val seedTimestamp: Long?
) {
    val oldestRequestedTimestamp: Long
        get() = firstMeasuredTimestamp - requestedDays.toLong() * INERTIA_HISTORY_DAY_MS

    fun nextRange(): LongRange? {
        if (nextChunk !in 0 until totalChunks) return null
        val start = oldestRequestedTimestamp +
            nextChunk.toLong() * INERTIA_HISTORY_MONTH_DAYS * INERTIA_HISTORY_DAY_MS
        val endExclusive = minOf(
            firstMeasuredTimestamp,
            start + INERTIA_HISTORY_MONTH_DAYS.toLong() * INERTIA_HISTORY_DAY_MS
        )
        if (endExclusive <= start) return null
        return start..(endExclusive - 1L)
    }

    fun seedState(): ThermalInertiaPropagationState? {
        val surface = seedSurface ?: return null
        val deep = seedDeep ?: return null
        val timestamp = seedTimestamp ?: return null
        return ThermalInertiaPropagationState(surface, deep, timestamp)
    }
}

data class ThermalInertiaChunkResult(
    val points: List<SamplePoint>,
    val endState: ThermalInertiaPropagationState,
    val reconstructedHours: Int,
    val coverage: Double
)

data class ThermalInertiaPendingChunk(
    val work: ThermalInertiaHistoryWork,
    val range: LongRange,
    val result: ThermalInertiaChunkResult
)

/**
 * Historique validé du "Sol inertiel estimé".
 *
 * Cette table ne touche jamais aux RAW ni aux reconstructions intérieures. Elle ne contient
 * que des points de surface/sol calculés avec un modèle déjà entraîné et explicitement validés
 * mois par mois par l'utilisateur.
 */
class ThermalInertiaHistoryStore(
    context: Context,
    private val db: FabDataDb
) {
    private val prefs = context.getSharedPreferences(
        "fabdata_thermal_inertia_history",
        Context.MODE_PRIVATE
    )

    init {
        ensure()
    }

    private fun ensure() {
        db.writableDatabase.execSQL(
            """
            CREATE TABLE IF NOT EXISTS thermal_inertia_history (
                reference_key TEXT NOT NULL,
                sensor_id INTEGER NOT NULL,
                model_signature TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                confidence REAL NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(reference_key, sensor_id, model_signature, timestamp)
            )
            """.trimIndent()
        )
        db.writableDatabase.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_thermal_inertia_history_time " +
                "ON thermal_inertia_history(reference_key, sensor_id, model_signature, timestamp)"
        )
    }

    fun query(
        referenceKey: String,
        sensorId: Long,
        modelSignature: String,
        from: Long,
        to: Long
    ): List<SamplePoint> {
        ensure()
        val out = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT timestamp, temperature, humidity, confidence
            FROM thermal_inertia_history
            WHERE reference_key=? AND sensor_id=? AND model_signature=?
              AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
            """.trimIndent(),
            arrayOf(
                referenceKey,
                sensorId.toString(),
                modelSignature,
                from.toString(),
                to.toString()
            )
        ).use { c ->
            while (c.moveToNext()) {
                out += SamplePoint(
                    sensorId = THERMAL_INERTIA_SENSOR_ID,
                    timestamp = c.getLong(0),
                    temperature = c.getDouble(1),
                    humidity = c.getDouble(2),
                    source = PointSource.RECONSTRUCTED,
                    confidence = c.getDouble(3)
                )
            }
        }
        return out
    }

    fun replaceChunk(
        referenceKey: String,
        sensorId: Long,
        modelSignature: String,
        range: LongRange,
        points: List<SamplePoint>
    ) {
        ensure()
        db.inTransaction {
            db.writableDatabase.delete(
                "thermal_inertia_history",
                "reference_key=? AND sensor_id=? AND model_signature=? AND timestamp BETWEEN ? AND ?",
                arrayOf(
                    referenceKey,
                    sensorId.toString(),
                    modelSignature,
                    range.first.toString(),
                    range.last.toString()
                )
            )
            points.forEach { point ->
                val values = ContentValues().apply {
                    put("reference_key", referenceKey)
                    put("sensor_id", sensorId)
                    put("model_signature", modelSignature)
                    put("timestamp", point.timestamp)
                    put("temperature", point.temperature)
                    put("humidity", point.humidity)
                    put("confidence", point.confidence ?: 0.5)
                    put("updated_at", System.currentTimeMillis())
                }
                db.writableDatabase.insertWithOnConflict(
                    "thermal_inertia_history",
                    null,
                    values,
                    SQLiteDatabase.CONFLICT_REPLACE
                )
            }
        }
    }

    fun pruneOtherModels(referenceKey: String, sensorId: Long, keepSignature: String) {
        ensure()
        db.writableDatabase.delete(
            "thermal_inertia_history",
            "reference_key=? AND sensor_id=? AND model_signature<>?",
            arrayOf(referenceKey, sensorId.toString(), keepSignature)
        )
    }

    fun beginWork(
        referenceKey: String,
        sensorId: Long,
        modelSignature: String,
        requestedDays: Int,
        firstMeasuredTimestamp: Long
    ): ThermalInertiaHistoryWork {
        val days = requestedDays.coerceIn(1, 1464)
        val chunks = kotlin.math.ceil(
            days.toDouble() / INERTIA_HISTORY_MONTH_DAYS.toDouble()
        ).toInt().coerceAtLeast(1)
        val work = ThermalInertiaHistoryWork(
            referenceKey = referenceKey,
            sensorId = sensorId,
            modelSignature = modelSignature,
            requestedDays = days,
            firstMeasuredTimestamp = firstMeasuredTimestamp,
            nextChunk = 0,
            totalChunks = chunks,
            paused = false,
            seedSurface = null,
            seedDeep = null,
            seedTimestamp = null
        )
        saveWork(work)
        return work
    }

    fun loadWork(): ThermalInertiaHistoryWork? {
        val referenceKey = prefs.getString("work_reference", null) ?: return null
        val modelSignature = prefs.getString("work_model_signature", null) ?: return null
        val requestedDays = prefs.getInt("work_days", 0)
        val firstMeasured = prefs.getLong("work_first_measured", Long.MIN_VALUE)
        val totalChunks = prefs.getInt("work_total_chunks", 0)
        if (requestedDays <= 0 || firstMeasured == Long.MIN_VALUE || totalChunks <= 0) return null

        val hasSeed = prefs.getBoolean("work_has_seed", false)
        return ThermalInertiaHistoryWork(
            referenceKey = referenceKey,
            sensorId = prefs.getLong("work_sensor", -1L),
            modelSignature = modelSignature,
            requestedDays = requestedDays,
            firstMeasuredTimestamp = firstMeasured,
            nextChunk = prefs.getInt("work_next_chunk", 0).coerceIn(0, totalChunks),
            totalChunks = totalChunks,
            paused = prefs.getBoolean("work_paused", false),
            seedSurface = if (hasSeed) prefs.getString("work_seed_surface", null)?.toDoubleOrNull() else null,
            seedDeep = if (hasSeed) prefs.getString("work_seed_deep", null)?.toDoubleOrNull() else null,
            seedTimestamp = if (hasSeed) prefs.getLong("work_seed_timestamp", Long.MIN_VALUE)
                .takeIf { it != Long.MIN_VALUE } else null
        )
    }

    fun advanceWork(endState: ThermalInertiaPropagationState): ThermalInertiaHistoryWork? {
        val work = loadWork() ?: return null
        val next = work.copy(
            nextChunk = (work.nextChunk + 1).coerceAtMost(work.totalChunks),
            paused = false,
            seedSurface = endState.surface,
            seedDeep = endState.deep,
            seedTimestamp = endState.timestamp
        )
        saveWork(next)
        return next
    }

    fun pauseWork() {
        loadWork()?.let { saveWork(it.copy(paused = true)) }
    }

    fun resumeWork() {
        loadWork()?.let { saveWork(it.copy(paused = false)) }
    }

    fun clearWork() {
        prefs.edit()
            .remove("work_reference")
            .remove("work_sensor")
            .remove("work_model_signature")
            .remove("work_days")
            .remove("work_first_measured")
            .remove("work_next_chunk")
            .remove("work_total_chunks")
            .remove("work_paused")
            .remove("work_has_seed")
            .remove("work_seed_surface")
            .remove("work_seed_deep")
            .remove("work_seed_timestamp")
            .apply()
    }

    private fun saveWork(work: ThermalInertiaHistoryWork) {
        val seed = work.seedState()
        val edit = prefs.edit()
            .putString("work_reference", work.referenceKey)
            .putLong("work_sensor", work.sensorId)
            .putString("work_model_signature", work.modelSignature)
            .putInt("work_days", work.requestedDays)
            .putLong("work_first_measured", work.firstMeasuredTimestamp)
            .putInt("work_next_chunk", work.nextChunk)
            .putInt("work_total_chunks", work.totalChunks)
            .putBoolean("work_paused", work.paused)
            .putBoolean("work_has_seed", seed != null)

        if (seed != null) {
            edit.putString("work_seed_surface", seed.surface.toString())
                .putString("work_seed_deep", seed.deep.toString())
                .putLong("work_seed_timestamp", seed.timestamp)
        } else {
            edit.remove("work_seed_surface")
                .remove("work_seed_deep")
                .remove("work_seed_timestamp")
        }
        edit.apply()
    }
}

private data class InertiaHistoryHour(
    val timestamp: Long,
    val air: Double,
    val humidity: Double,
    val outside: Double,
    val smoothAir: Double,
    val source: PointSource
)

/**
 * Projection historique O(n) utilisant exclusivement les paramètres d'un modèle déjà entraîné.
 * Aucun fit, aucune calibration et aucune écriture de température intérieure.
 */
class ThermalInertiaHistoryProjector(
    private val db: FabDataDb,
    private val referenceStore: WeatherReferenceStore
) {
    fun projectChunk(
        reference: WeatherReference,
        model: ThermalModel,
        range: LongRange,
        seed: ThermalInertiaPropagationState?
    ): ThermalInertiaChunkResult {
        require(model.referenceKey == reference.key) {
            "Référence météo différente du modèle entraîné"
        }
        require(range.last > range.first) { "Période sol inertiel vide" }

        val paddedIndoor = allHourly(
            model.sensorId,
            range.first - 2L * INERTIA_HISTORY_HOUR_MS,
            range.last + 2L * INERTIA_HISTORY_HOUR_MS
        )
        val targetIndoor = paddedIndoor.filter { it.timestamp in range }
        require(targetIndoor.isNotEmpty()) {
            "Aucune température intérieure sur ce mois"
        }

        val expectedHours = (
            (range.last - range.first) / INERTIA_HISTORY_HOUR_MS + 1L
        ).toInt().coerceAtLeast(1)
        val reconstructedHours = targetIndoor.count { it.source == PointSource.RECONSTRUCTED }
        require(reconstructedHours > 0) {
            "Aucune température intérieure reconstruite sur ce mois"
        }
        val indoorCoverage = targetIndoor.size.toDouble() / expectedHours.toDouble()
        require(indoorCoverage >= 0.80) {
            "Température intérieure reconstruite trop incomplète (${(indoorCoverage * 100).toInt()} %)"
        }

        val outside = outsideHourly(
            reference.key,
            range.first - 2L * INERTIA_HISTORY_HOUR_MS,
            range.last + 2L * INERTIA_HISTORY_HOUR_MS
        )
        val outMap = outside.associateBy { it.first }
        val smoothAll = smoothAir(paddedIndoor.map { it.temperature })
        val smoothByTimestamp = paddedIndoor.mapIndexed { index, point ->
            point.timestamp to smoothAll[index]
        }.toMap()

        val hours = targetIndoor.mapNotNull { point ->
            val outsideT = outsideAt(outMap, point.timestamp) ?: return@mapNotNull null
            InertiaHistoryHour(
                timestamp = point.timestamp,
                air = point.temperature,
                humidity = point.humidity,
                outside = outsideT,
                smoothAir = smoothByTimestamp[point.timestamp] ?: point.temperature,
                source = point.source
            )
        }
        val coverage = hours.size.toDouble() / expectedHours.toDouble()
        require(hours.size >= 12 && coverage >= 0.80) {
            "Référence météo insuffisante pour le sol inertiel (${(coverage * 100).toInt()} %)"
        }

        val w = model.inertiaOutsideWeight.coerceIn(0.02, 0.45)
        val surfaceTau = model.inertiaSurfaceTauHours.coerceAtLeast(6.0)
        val deepTau = model.inertiaDeepTauHours.coerceAtLeast(surfaceTau * 2.5)
        val confidence = model.confidence.coerceIn(0.08, 0.95)

        var surface: Double
        var deep: Double
        val points = ArrayList<SamplePoint>(hours.size)

        fun forcing(hour: InertiaHistoryHour): Double =
            hour.smoothAir * (1.0 - w) + hour.outside * w

        fun advance(
            previousSurface: Double,
            previousDeep: Double,
            dtHours: Double,
            forcingValue: Double
        ): Pair<Double, Double> {
            val dt = dtHours.coerceIn(0.5, 24.0)
            val surfaceTarget = 0.82 * forcingValue + 0.18 * previousDeep
            val alphaSurface = 1.0 - exp(-dt / surfaceTau)
            val nextSurface = (
                previousSurface + alphaSurface * (surfaceTarget - previousSurface)
            ).coerceIn(-5.0, 50.0)
            val alphaDeep = 1.0 - exp(-dt / deepTau)
            val nextDeep = (
                previousDeep + alphaDeep * (nextSurface - previousDeep)
            ).coerceIn(-5.0, 50.0)
            return nextSurface to nextDeep
        }

        val first = hours.first()
        if (seed != null && seed.timestamp < first.timestamp) {
            val gapHours = (first.timestamp - seed.timestamp).toDouble() /
                INERTIA_HISTORY_HOUR_MS.toDouble()
            require(gapHours <= 24.0) {
                "Rupture de continuité supérieure à 24 h entre deux mois"
            }
            val advanced = advance(seed.surface, seed.deep, gapHours, forcing(first))
            surface = advanced.first
            deep = advanced.second
        } else {
            surface = forcing(first)
            deep = (first.smoothAir * 0.88 + first.outside * 0.12).coerceIn(-5.0, 50.0)
        }

        points += SamplePoint(
            THERMAL_INERTIA_SENSOR_ID,
            first.timestamp,
            surface,
            first.humidity,
            PointSource.RECONSTRUCTED,
            confidence
        )

        for (i in 1 until hours.size) {
            val dtHours = (
                hours[i].timestamp - hours[i - 1].timestamp
            ).toDouble() / INERTIA_HISTORY_HOUR_MS.toDouble()
            val advanced = advance(surface, deep, dtHours, forcing(hours[i - 1]))
            surface = advanced.first
            deep = advanced.second
            points += SamplePoint(
                THERMAL_INERTIA_SENSOR_ID,
                hours[i].timestamp,
                surface,
                hours[i].humidity,
                PointSource.RECONSTRUCTED,
                confidence
            )
        }

        return ThermalInertiaChunkResult(
            points = points,
            endState = ThermalInertiaPropagationState(
                surface = surface,
                deep = deep,
                timestamp = hours.last().timestamp
            ),
            reconstructedHours = reconstructedHours,
            coverage = min(indoorCoverage, coverage)
        )
    }

    private fun allHourly(sensorId: Long, from: Long, to: Long): List<SamplePoint> {
        PointSourceStore.ensure(db.readableDatabase)
        val raw = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity, ps.source
            FROM samples p
            LEFT JOIN point_sources ps
              ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND p.timestamp BETWEEN ? AND ?
              AND (ps.source IS NULL OR ps.source<>'forecast')
            ORDER BY p.timestamp
            """.trimIndent(),
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val source = PointSource.fromDb(if (c.isNull(3)) null else c.getString(3))
                raw += SamplePoint(
                    sensorId,
                    c.getLong(0),
                    c.getDouble(1),
                    c.getDouble(2),
                    source,
                    1.0
                )
            }
        }
        return raw.groupBy { bucket(it.timestamp) }.map { (timestamp, values) ->
            val priority = values.maxOf { it.source.priority }
            val best = values.filter { it.source.priority == priority }
            SamplePoint(
                sensorId = sensorId,
                timestamp = timestamp,
                temperature = best.map { it.temperature }.average(),
                humidity = best.map { it.humidity }.average(),
                source = best.first().source,
                confidence = 1.0
            )
        }.sortedBy { it.timestamp }
    }

    private fun outsideHourly(referenceKey: String, from: Long, to: Long): List<Pair<Long, Double>> =
        referenceStore.query(referenceKey, from, to)
            .filter { it.source != PointSource.FORECAST }
            .groupBy { bucket(it.timestamp) }
            .map { (timestamp, values) ->
                val priority = values.maxOf { it.source.priority }
                val best = values.filter { it.source.priority == priority }
                timestamp to best.map { it.temperature }.average()
            }
            .sortedBy { it.first }

    private fun outsideAt(
        map: Map<Long, Pair<Long, Double>>,
        timestamp: Long
    ): Double? {
        val b = bucket(timestamp)
        map[b]?.let { return it.second }
        return listOfNotNull(
            map[b - INERTIA_HISTORY_HOUR_MS],
            map[b + INERTIA_HISTORY_HOUR_MS]
        ).minByOrNull { abs(it.first - timestamp) }?.second
    }

    private fun smoothAir(values: List<Double>): List<Double> = values.indices.map { i ->
        val from = max(0, i - 2)
        val to = min(values.lastIndex, i + 2)
        val window = (from..to).map { values[it] }.sorted()
        if (window.size % 2 == 1) window[window.size / 2]
        else (window[window.size / 2 - 1] + window[window.size / 2]) / 2.0
    }

    private fun bucket(timestamp: Long): Long =
        (timestamp / INERTIA_HISTORY_HOUR_MS) * INERTIA_HISTORY_HOUR_MS
}
