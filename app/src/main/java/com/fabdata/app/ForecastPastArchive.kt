package com.fabdata.app

import android.database.sqlite.SQLiteDatabase
import android.util.Log
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import kotlin.math.abs
import kotlin.math.exp

/**
 * API-backed past forecast reconstruction.
 *
 * This table never pretends to be a locally emitted snapshot. It is kept separate from
 * ForecastMemoryStore so strict skill/training logic cannot accidentally treat a later API
 * reconstruction as something FabData really knew at the time.
 */
data class ForecastPastArchivePoint(
    val targetAt: Long,
    val weatherTemperature: Double,
    val humidity: Double,
    val fabTemperature: Double,
    val weatherConfidence: Double,
    val fabConfidence: Double,
    val provider: String
)

object ForecastPastArchiveStore {
    const val TABLE = "forecast_past_api_archive"
    const val PROVIDER = "open-meteo-previous-runs-h24-meteofrance"

    fun ensure(sql: SQLiteDatabase) {
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE (
                reference_key TEXT NOT NULL,
                target_ts INTEGER NOT NULL,
                weather_temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                fab_temperature REAL,
                weather_confidence REAL NOT NULL DEFAULT 0.78,
                fab_confidence REAL,
                provider TEXT NOT NULL,
                fetched_at INTEGER NOT NULL,
                PRIMARY KEY(reference_key, target_ts, provider)
            )
            """.trimIndent()
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_past_api_target ON $TABLE(reference_key, target_ts)"
        )
        sql.delete(TABLE, "provider=?", arrayOf("open-meteo-historical-forecast"))
    }

    fun restore(
        sql: SQLiteDatabase,
        referenceKey: String,
        targetAt: Long,
        weatherTemperature: Double,
        humidity: Double,
        fabTemperature: Double?,
        weatherConfidence: Double,
        fabConfidence: Double?,
        provider: String,
        fetchedAt: Long
    ) {
        ensure(sql)
        val safeProvider = provider.ifBlank { PROVIDER }
        sql.execSQL(
            """
            INSERT OR IGNORE INTO $TABLE(
                reference_key, target_ts, weather_temperature, humidity, fab_temperature,
                weather_confidence, fab_confidence, provider, fetched_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """.trimIndent(),
            arrayOf(
                referenceKey, targetAt, weatherTemperature, humidity.coerceIn(0.0, 100.0),
                fabTemperature, weatherConfidence.coerceIn(0.0, 1.0), fabConfidence, safeProvider, fetchedAt
            )
        )
        // API refresh may update the weather anchor, but must never erase a restored/user-specific
        // Fab backtest. A non-null backup value is allowed to restore/replace it explicitly.
        sql.execSQL(
            """
            UPDATE $TABLE SET
                weather_temperature=?, humidity=?, weather_confidence=?, fetched_at=?,
                fab_temperature=COALESCE(?, fab_temperature),
                fab_confidence=COALESCE(?, fab_confidence)
            WHERE reference_key=? AND target_ts=? AND provider=?
            """.trimIndent(),
            arrayOf(
                weatherTemperature, humidity.coerceIn(0.0, 100.0),
                weatherConfidence.coerceIn(0.0, 1.0), fetchedAt,
                fabTemperature, fabConfidence, referenceKey, targetAt, safeProvider
            )
        )
    }

    fun query(
        db: FabDataDb,
        referenceKey: String,
        from: Long,
        to: Long
    ): List<ForecastPastArchivePoint> {
        ensure(db.writableDatabase)
        val out = mutableListOf<ForecastPastArchivePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT target_ts, weather_temperature, humidity, fab_temperature,
                   weather_confidence, fab_confidence, provider
            FROM $TABLE
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND provider=?
            ORDER BY target_ts
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString(), PROVIDER)
        ).use { c ->
            while (c.moveToNext()) {
                val weather = c.getDouble(1)
                out += ForecastPastArchivePoint(
                    targetAt = c.getLong(0),
                    weatherTemperature = weather,
                    humidity = c.getDouble(2),
                    fabTemperature = if (c.isNull(3)) weather else c.getDouble(3),
                    weatherConfidence = c.getDouble(4).coerceIn(0.0, 1.0),
                    fabConfidence = if (c.isNull(5)) 0.40 else c.getDouble(5).coerceIn(0.0, 1.0),
                    provider = c.getString(6)
                )
            }
        }
        return out
    }
}

class ForecastPastArchiveBackfill(private val db: FabDataDb) {
    private val zone = ZoneId.of("Europe/Paris")
    private val hourMs = 60L * 60L * 1000L
    private val earliest = LocalDate.of(2024, 1, 1).atStartOfDay(zone).toInstant().toEpochMilli()
    private val fixedLeadMs = 24L * hourMs

    /**
     * Completes missing past forecast anchors from Open-Meteo Previous Runs at fixed H+24.
     * Météo-France seamless supplies values predicted exactly one day before valid time.
     */
    fun ensure(
        reference: WeatherReference,
        from: Long,
        to: Long,
        now: Long = System.currentTimeMillis()
    ): Int {
        ForecastPastArchiveStore.ensure(db.writableDatabase)
        val safeFrom = maxOf(from, earliest)
        val safeTo = minOf(to, now - hourMs)
        if (safeTo <= safeFrom) return 0
        if (hasDenseCoverage(reference.key, safeFrom, safeTo)) {
            rebuildFabCausally(reference.key, safeFrom, safeTo)
            return 0
        }

        var added = 0
        var failures = 0
        val fromDate = Instant.ofEpochMilli(safeFrom).atZone(zone).toLocalDate()
        val toDate = Instant.ofEpochMilli(safeTo).atZone(zone).toLocalDate()
        var cursor = fromDate
        while (!cursor.isAfter(toDate)) {
            val chunkEnd = minOf(cursor.plusDays(30), toDate)
            val rows = runCatching {
                fetchFixedLeadH24(reference, cursor, chunkEnd, safeFrom, safeTo)
            }.getOrElse { error ->
                failures++
                Log.w("FabDataForecast", "Previous Runs H+24 failed for $cursor..$chunkEnd", error)
                emptyList()
            }
            if (rows.isNotEmpty()) {
                db.inTransaction {
                    rows.forEach { p ->
                        ForecastPastArchiveStore.restore(
                            sql = db.writableDatabase,
                            referenceKey = reference.key,
                            targetAt = p.targetAt,
                            weatherTemperature = p.weatherTemperature,
                            humidity = p.humidity,
                            fabTemperature = null,
                            weatherConfidence = p.weatherConfidence,
                            fabConfidence = null,
                            provider = ForecastPastArchiveStore.PROVIDER,
                            fetchedAt = System.currentTimeMillis()
                        )
                        added++
                    }
                }
            }
            cursor = chunkEnd.plusDays(1)
        }
        rebuildFabCausally(reference.key, safeFrom, safeTo)
        if (failures > 0) Log.w("FabDataForecast", "H+24 archive: $failures failed chunk(s), $added point(s) added")
        return added
    }

    private fun hasDenseCoverage(referenceKey: String, from: Long, to: Long): Boolean {
        val expected = (((to - from) / hourMs) + 1L).coerceAtLeast(1L)
        return db.readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(target_ts), MAX(target_ts)
            FROM ${ForecastPastArchiveStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND provider=?
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString(), ForecastPastArchiveStore.PROVIDER)
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(1) || c.isNull(2)) return@use false
            val count = c.getLong(0)
            val minTs = c.getLong(1)
            val maxTs = c.getLong(2)
            count >= (expected - 3L).coerceAtLeast(1L) &&
                minTs <= from + 2L * hourMs &&
                maxTs >= to - 2L * hourMs
        }
    }

    private fun fetchFixedLeadH24(
        reference: WeatherReference,
        fromDate: LocalDate,
        toDate: LocalDate,
        clipFrom: Long,
        clipTo: Long
    ): List<ForecastPastArchivePoint> {
        val url = "https://previous-runs-api.open-meteo.com/v1/meteofrance" +
            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
            "&start_date=$fromDate&end_date=$toDate" +
            "&hourly=temperature_2m_previous_day1,relative_humidity_2m_previous_day1" +
            "&timezone=Europe%2FParis"
        val raw = httpGet(url)
        val hourly = JSONObject(raw).getJSONObject("hourly")
        val times = hourly.getJSONArray("time")
        val temps = hourly.getJSONArray("temperature_2m_previous_day1")
        val hums = hourly.getJSONArray("relative_humidity_2m_previous_day1")
        val out = mutableListOf<ForecastPastArchivePoint>()
        for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {
            val local = runCatching { LocalDateTime.parse(times.getString(i)) }.getOrNull() ?: continue
            val ts = local.atZone(zone).toInstant().toEpochMilli()
            if (ts !in clipFrom..clipTo) continue
            val t = temps.optDouble(i, Double.NaN)
            val h = hums.optDouble(i, Double.NaN)
            if (!t.isFinite() || !h.isFinite() || t !in -70.0..70.0 || h !in 0.0..100.0) continue
            out += ForecastPastArchivePoint(
                targetAt = ts, weatherTemperature = t, humidity = h, fabTemperature = t,
                weatherConfidence = 0.72, fabConfidence = 0.40,
                provider = ForecastPastArchiveStore.PROVIDER
            )
        }
        return out.distinctBy { it.targetAt }.sortedBy { it.targetAt }
    }

    /**
     * Backtests the Fab local corrector without future leakage.
     * For target T, only residuals verified by T-24h are used.
     * The result is explicitly a reconstructed Fab history, never an emitted snapshot.
     */
    private fun rebuildFabCausally(referenceKey: String, from: Long, to: Long) {
        val rows = ForecastPastArchiveStore.query(db, referenceKey, from - fixedLeadMs - 25L * hourMs, to)
        if (rows.isEmpty()) return
        val measured = measuredByHour(referenceKey, from - fixedLeadMs - 26L * hourMs, to)
        val residualCandidates = rows.mapNotNull { row ->
            measured[row.targetAt / hourMs]?.let { actual ->
                BackfillResidual(row.targetAt, actual - row.weatherTemperature)
            }
        }
        var addIndex = 0
        val window = ArrayDeque<BackfillResidual>()

        rows.filter { it.targetAt in from..to }.forEach { row ->
            val cutoff = row.targetAt - fixedLeadMs
            while (addIndex < residualCandidates.size && residualCandidates[addIndex].targetAt <= cutoff) {
                window.addLast(residualCandidates[addIndex])
                addIndex++
            }
            while (window.isNotEmpty() && window.first().targetAt < cutoff - 24L * hourMs) {
                window.removeFirst()
            }
            val model = fit(window.toList(), cutoff)
            val horizonHours = fixedLeadMs.toDouble() / hourMs.toDouble()
            val correction = (model.bias + model.slope * horizonHours + 0.5 * model.acceleration * horizonHours * horizonHours).coerceIn(-5.0, 5.0)
            val fab = (row.weatherTemperature + correction).coerceIn(-70.0, 70.0)
            val confidenceFactor = (0.40 + (model.samples.coerceAtMost(12) / 12.0) * 0.55).coerceIn(0.40, 0.95)
            db.writableDatabase.execSQL(
                """
                UPDATE ${ForecastPastArchiveStore.TABLE}
                SET fab_temperature=COALESCE(fab_temperature, ?),
                    fab_confidence=COALESCE(fab_confidence, ?)
                WHERE reference_key=? AND target_ts=? AND provider=?
                """.trimIndent(),
                arrayOf(
                    fab,
                    (row.weatherConfidence * confidenceFactor).coerceIn(0.0, 1.0),
                    referenceKey,
                    row.targetAt,
                    ForecastPastArchiveStore.PROVIDER
                )
            )
        }
    }

    private fun measuredByHour(referenceKey: String, from: Long, to: Long): Map<Long, Double> {
        val best = mutableMapOf<Long, Pair<Long, Double>>()
        db.readableDatabase.rawQuery(
            """
            SELECT timestamp, temperature
            FROM weather_reference_samples
            WHERE reference_key=? AND source='measured' AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val ts = c.getLong(0)
                val bucket = ts / hourMs
                val center = bucket * hourMs
                val distance = abs(ts - center)
                val previous = best[bucket]
                if (previous == null || distance < previous.first) {
                    best[bucket] = distance to c.getDouble(1)
                }
            }
        }
        return best.mapValues { it.value.second }
    }

    private fun fit(points: List<BackfillResidual>, asOf: Long): BackfillModel {
        if (points.isEmpty()) return BackfillModel()
        if (points.size == 1) return BackfillModel(points.first().residual.coerceIn(-4.0, 4.0), samples = 1)

        var sw = 0.0
        var sx = 0.0
        var sy = 0.0
        var sxx = 0.0
        var sxy = 0.0
        points.forEach { p ->
            val x = (p.targetAt - asOf).toDouble() / hourMs.toDouble()
            val w = exp(x / 6.0).coerceAtLeast(0.01)
            sw += w
            sx += w * x
            sy += w * p.residual
            sxx += w * x * x
            sxy += w * x * p.residual
        }
        val denom = sw * sxx - sx * sx
        val slope = if (abs(denom) > 1e-9) ((sw * sxy - sx * sy) / denom).coerceIn(-1.2, 1.2) else 0.0
        val bias = if (sw > 0.0) ((sy - slope * sx) / sw).coerceIn(-4.0, 4.0) else 0.0

        val accelerations = points.zipWithNext().zipWithNext().mapNotNull { (leftPair, rightPair) ->
            val (a, b) = leftPair
            val (_, c) = rightPair
            val dt1 = (b.targetAt - a.targetAt).toDouble() / hourMs.toDouble()
            val dt2 = (c.targetAt - b.targetAt).toDouble() / hourMs.toDouble()
            if (dt1 !in 0.5..2.0 || dt2 !in 0.5..2.0) return@mapNotNull null
            val s1 = (b.residual - a.residual) / dt1
            val s2 = (c.residual - b.residual) / dt2
            ((s2 - s1) / ((dt1 + dt2) / 2.0)).coerceIn(-1.5, 1.5) to c.targetAt
        }
        var acceleration = 0.0
        if (accelerations.isNotEmpty()) {
            var aw = 0.0
            var av = 0.0
            accelerations.forEach { (value, ts) ->
                val x = (ts - asOf).toDouble() / hourMs.toDouble()
                val w = exp(x / 4.0).coerceAtLeast(0.01)
                aw += w
                av += w * value
            }
            if (aw > 0.0) acceleration = (av / aw).coerceIn(-0.8, 0.8)
        }
        return BackfillModel(bias, slope, acceleration, points.size)
    }

    private fun httpGet(url: String): String {
        val c = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 20_000
            readTimeout = 35_000
            instanceFollowRedirects = true
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "FabData/0.21.5 Android")
        }
        return try {
            val code = c.responseCode
            if (code !in 200..299) error("Previous Runs H+24 HTTP $code")
            c.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    private data class BackfillResidual(val targetAt: Long, val residual: Double)
    private data class BackfillModel(
        val bias: Double = 0.0,
        val slope: Double = 0.0,
        val acceleration: Double = 0.0,
        val samples: Int = 0
    )
}
