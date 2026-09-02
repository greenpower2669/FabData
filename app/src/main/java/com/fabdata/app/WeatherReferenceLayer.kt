package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs

/** Référence extérieure légère : le catalogue ne contient que des métadonnées. */
data class WeatherReference(
    val key: String,
    val city: String,
    val stationName: String,
    val stationId: String,
    val latitude: Double,
    val longitude: Double,
    val departmentId: String
) {
    val label: String get() = if (city.equals(stationName, ignoreCase = true)) city else "$city · $stationName"
}

object WeatherReferenceCatalog {
    const val DEFAULT_KEY = "mf-69029001"

    // Noyau simple v0.10. L'architecture accepte des milliers d'entrées sans charger
    // aucune série temporelle supplémentaire. Le catalogue distant pourra être branché ensuite.
    val stations = listOf(
        WeatherReference("mf-69029001", "Lyon", "Lyon-Bron", "69029001", 45.7265, 4.9440, "69"),
        WeatherReference("mf-75114001", "Paris", "Paris-Montsouris", "75114001", 48.8217, 2.3378, "75"),
        WeatherReference("mf-13054001", "Marseille", "Marignane", "13054001", 43.4370, 5.2160, "13"),
        WeatherReference("mf-33281001", "Bordeaux", "Bordeaux-Mérignac", "33281001", 44.8306, -0.6914, "33"),
        WeatherReference("mf-59343001", "Lille", "Lille-Lesquin", "59343001", 50.5700, 3.0975, "59"),
        WeatherReference("mf-31069001", "Toulouse", "Toulouse-Blagnac", "31069001", 43.6210, 1.3788, "31"),
        WeatherReference("mf-06088001", "Nice", "Nice Aéroport", "06088001", 43.6489, 7.2092, "06")
    )

    fun byKey(key: String?): WeatherReference = stations.firstOrNull { it.key == key } ?: stations.first()
}

class WeatherReferencePrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)
    fun selectedKey(): String = prefs.getString("selected_key", WeatherReferenceCatalog.DEFAULT_KEY)
        ?: WeatherReferenceCatalog.DEFAULT_KEY
    fun select(key: String) = prefs.edit().putString("selected_key", WeatherReferenceCatalog.byKey(key).key).apply()
}

data class WeatherReferencePoint(
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val source: PointSource,
    val confidence: Double = 1.0
)

class WeatherReferenceStore(private val db: FabDataDb) {
    init { ensure(db.writableDatabase) }

    companion object {
        fun ensure(sql: SQLiteDatabase) {
            sql.execSQL(
                """
                CREATE TABLE IF NOT EXISTS weather_reference_samples (
                    reference_key TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    temperature REAL NOT NULL,
                    humidity REAL NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(reference_key, timestamp)
                )
                """.trimIndent()
            )
            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_weather_reference_time ON weather_reference_samples(reference_key, timestamp)")
        }
    }

    /** Une seule référence temporelle reste en cache, conformément au choix utilisateur. */
    fun keepOnly(referenceKey: String) {
        db.writableDatabase.delete("weather_reference_samples", "reference_key<>?", arrayOf(referenceKey))
    }

    fun upsert(referenceKey: String, point: WeatherReferencePoint) {
        val currentSource = db.readableDatabase.rawQuery(
            "SELECT source FROM weather_reference_samples WHERE reference_key=? AND timestamp=? LIMIT 1",
            arrayOf(referenceKey, point.timestamp.toString())
        ).use { c -> if (c.moveToFirst()) PointSource.fromDb(c.getString(0)) else null }
        if (currentSource != null && currentSource.priority > point.source.priority) return
        val values = ContentValues().apply {
            put("reference_key", referenceKey)
            put("timestamp", point.timestamp)
            put("temperature", point.temperature)
            put("humidity", point.humidity.coerceIn(0.0, 100.0))
            put("source", point.source.dbValue)
            put("confidence", point.confidence.coerceIn(0.0, 1.0))
            put("updated_at", System.currentTimeMillis())
        }
        db.writableDatabase.insertWithOnConflict(
            "weather_reference_samples", null, values, SQLiteDatabase.CONFLICT_REPLACE
        )
    }

    fun query(referenceKey: String, from: Long, to: Long): List<WeatherReferencePoint> {
        val out = mutableListOf<WeatherReferencePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
            WHERE reference_key=? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += WeatherReferencePoint(
                    c.getLong(0), c.getDouble(1), c.getDouble(2),
                    PointSource.fromDb(c.getString(3)), c.getDouble(4)
                )
            }
        }
        return out
    }

    fun bounds(referenceKey: String): LongRange? {
        db.readableDatabase.rawQuery(
            "SELECT MIN(timestamp), MAX(timestamp) FROM weather_reference_samples WHERE reference_key=?",
            arrayOf(referenceKey)
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    fun clear(referenceKey: String) {
        db.writableDatabase.delete("weather_reference_samples", "reference_key=?", arrayOf(referenceKey))
    }
}

data class WeatherReferenceSyncResult(
    val measured: Int,
    val reconstructed: Int,
    val forecast: Int,
    val label: String
)

class WeatherReferenceManager(
    private val context: Context,
    private val db: FabDataDb,
    private val lyonLab: LyonLabStore,
    private val credentials: MeteoFranceCredentialStore
) {
    private val store = WeatherReferenceStore(db)
    private val zone = ZoneId.of("Europe/Paris")
    private val hourMs = 60L * 60L * 1000L

    fun store(): WeatherReferenceStore = store

    /**
     * Recharge uniquement la station sélectionnée. Lyon réutilise les mécanismes déjà
     * validés ; les autres références utilisent l'API officielle Météo-France si un
     * token est disponible. La prévision extérieure H+6 est chargée séparément.
     */
    fun refreshSelected(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {
        store.keepOnly(reference.key)
        var measured = 0
        var reconstructed = 0

        if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
            val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
            val fallback = db.querySamples(sensor.id, from, to, maxPoints = 30_000)
            fallback.forEach { p ->
                val source = PointSourceStore.sourceFor(db, sensor.id, p.timestamp)
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, source))
                if (source == PointSource.MEASURED) measured++ else reconstructed++
            }
            lyonLab.queryOfficial(LyonSeriesKind.HOURLY, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
                measured++
            }
            lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
                measured++
            }
            val recon = lyonLab.reconstruct(from, to).points
            recon.forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.RECONSTRUCTED, 0.72))
            }
            reconstructed += recon.size
        } else {
            if (!credentials.hasCredential()) {
                error("Une clé/token Météo-France est nécessaire pour charger les observations de ${reference.label}")
            }
            val official = fetchOfficialHourly(reference, from, to)
            official.forEach { store.upsert(reference.key, it); measured++ }
            reconstructed += reconstructShortGaps(reference.key, from, to)
        }

        val forecast = refreshForecast(reference)
        return WeatherReferenceSyncResult(measured, reconstructed, forecast, reference.label)
    }

    /** Rafraîchit seulement H+6 sans retélécharger l'historique. */
    fun refreshForecast(reference: WeatherReference): Int {
        val now = System.currentTimeMillis()
        val oldForecasts = store.query(reference.key, now - hourMs, now + 12L * hourMs)
            .filter { it.source == PointSource.FORECAST }
        if (oldForecasts.isNotEmpty()) {
            db.inTransaction {
                oldForecasts.forEach { p ->
                    db.writableDatabase.delete(
                        "weather_reference_samples",
                        "reference_key=? AND timestamp=? AND source='forecast'",
                        arrayOf(reference.key, p.timestamp.toString())
                    )
                }
            }
        }
        val forecast = fetchOpenMeteoForecast(reference)
        forecast.forEach { store.upsert(reference.key, it) }
        return forecast.size
    }

    fun ensureLocalCache(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {
        store.keepOnly(reference.key)
        val existing = store.query(reference.key, from, to)
        val measured = existing.count { it.source == PointSource.MEASURED }
        val reconstructed = existing.count { it.source == PointSource.RECONSTRUCTED }
        val needsHistory = existing.size < 24 || store.bounds(reference.key)?.let { it.first > from || it.last < minOf(to, System.currentTimeMillis()) } != false
        return if (needsHistory) {
            refreshSelected(reference, from, to)
        } else {
            val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)
            WeatherReferenceSyncResult(measured, reconstructed, forecast, reference.label)
        }
    }

    private fun reconstructShortGaps(referenceKey: String, from: Long, to: Long): Int {
        val points = store.query(referenceKey, from, to).filter { it.source == PointSource.MEASURED }.sortedBy { it.timestamp }
        if (points.size < 2) return 0
        var created = 0
        points.zipWithNext().forEach { (left, right) ->
            val gap = right.timestamp - left.timestamp
            if (gap > 90L * 60L * 1000L && gap <= 6L * hourMs) {
                var ts = roundHour(left.timestamp) + hourMs
                while (ts < right.timestamp) {
                    val f = (ts - left.timestamp).toDouble() / gap.toDouble()
                    if (f in 0.0..1.0) {
                        val t = left.temperature + (right.temperature - left.temperature) * f
                        val h = left.humidity + (right.humidity - left.humidity) * f
                        store.upsert(referenceKey, WeatherReferencePoint(ts, t, h, PointSource.RECONSTRUCTED, 0.70))
                        created++
                    }
                    ts += hourMs
                }
            }
        }
        return created
    }

    private fun fetchOfficialHourly(reference: WeatherReference, from: Long, to: Long): List<WeatherReferencePoint> {
        val credential = credentials.get().takeIf { it.isNotBlank() } ?: error("Token Météo-France absent")
        val orderBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande-station/horaire"
        val fileBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande/fichier"
        val all = mutableListOf<WeatherReferencePoint>()
        var cursor = Instant.ofEpochMilli(from)
        val end = Instant.ofEpochMilli(to)
        while (!cursor.isAfter(end)) {
            val chunkEnd = minInstant(cursor.plusSeconds(364L * 24L * 3600L), end)
            val startIso = DateTimeFormatter.ISO_INSTANT.format(cursor)
            val endIso = DateTimeFormatter.ISO_INSTANT.format(chunkEnd)
            val url = orderBase + "?id-station=${reference.stationId}" +
                "&date-deb-periode=${enc(startIso)}&date-fin-periode=${enc(endIso)}"
            val response = httpGet(url, credential)
            val orderId = JSONObject(response)
                .getJSONObject("elaboreProduitAvecDemandeResponse")
                .get("return").toString()
            var csv: String? = null
            repeat(10) { attempt ->
                if (csv != null) return@repeat
                if (attempt > 0) Thread.sleep(1200L)
                runCatching { httpGet("$fileBase?id-cmde=${enc(orderId)}", credential, accept204 = true) }
                    .getOrNull()?.takeIf { it.isNotBlank() }?.let { csv = it }
            }
            csv?.let { all += parseHourlyCsv(it, reference.stationId) }
            cursor = chunkEnd.plusSeconds(1)
        }
        return all.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }

    private fun parseHourlyCsv(raw: String, stationId: String): List<WeatherReferencePoint> {
        val lines = raw.lineSequence().filter { it.isNotBlank() }.toList()
        if (lines.size < 2) return emptyList()
        val header = splitCsv(lines.first().removePrefix("\uFEFF"), ';').map(::normHeader)
        val stationI = findColumn(header, "num_poste", "id_station")
        val dateI = findColumn(header, "aaaammjjhh", "date")
        val tempI = findColumn(header, "t", "temperature")
        val humI = findColumn(header, "u", "humidite", "humidity")
        if (dateI < 0 || tempI < 0 || humI < 0) return emptyList()
        return lines.drop(1).mapNotNull { line ->
            val f = splitCsv(line, ';')
            if (stationI >= 0 && f.getOrNull(stationI)?.trim()?.trim('"') != stationId) return@mapNotNull null
            val ts = parseHourlyDate(f.getOrNull(dateI).orEmpty()) ?: return@mapNotNull null
            val t = f.getOrNull(tempI)?.trim()?.replace(',', '.')?.toDoubleOrNull() ?: return@mapNotNull null
            val h = f.getOrNull(humI)?.trim()?.replace(',', '.')?.toDoubleOrNull() ?: return@mapNotNull null
            if (t !in -60.0..65.0 || h !in 0.0..100.0) return@mapNotNull null
            WeatherReferencePoint(ts, t, h, PointSource.MEASURED, 1.0)
        }
    }

    /** Prévision extérieure courte : modèle météo, jamais présentée comme observation. */
    private fun fetchOpenMeteoForecast(reference: WeatherReference): List<WeatherReferencePoint> {
        val url = "https://api.open-meteo.com/v1/forecast" +
            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
            "&hourly=temperature_2m,relative_humidity_2m&forecast_days=2&timezone=Europe%2FParis"
        val raw = httpGet(url, null)
        val hourly = JSONObject(raw).getJSONObject("hourly")
        val times = hourly.getJSONArray("time")
        val temps = hourly.getJSONArray("temperature_2m")
        val hums = hourly.getJSONArray("relative_humidity_2m")
        val now = System.currentTimeMillis()
        val end = now + 6L * hourMs + 70L * 60L * 1000L
        val out = mutableListOf<WeatherReferencePoint>()
        for (i in 0 until times.length()) {
            val local = runCatching { LocalDateTime.parse(times.getString(i), DateTimeFormatter.ISO_LOCAL_DATE_TIME) }.getOrNull() ?: continue
            val ts = local.atZone(zone).toInstant().toEpochMilli()
            if (ts < now - 30L * 60L * 1000L || ts > end) continue
            val t = temps.optDouble(i, Double.NaN)
            val h = hums.optDouble(i, Double.NaN)
            if (!t.isFinite() || !h.isFinite()) continue
            val horizonHours = ((ts - now).coerceAtLeast(0L).toDouble() / hourMs.toDouble())
            val confidence = (0.92 - 0.055 * horizonHours).coerceIn(0.55, 0.92)
            out += WeatherReferencePoint(ts, t, h, PointSource.FORECAST, confidence)
        }
        return out
    }

    private fun httpGet(url: String, credential: String?, accept204: Boolean = false): String {
        val c = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 18_000
            readTimeout = 30_000
            instanceFollowRedirects = true
            setRequestProperty("Accept", "*/*")
            setRequestProperty("User-Agent", "FabData/0.10.0 Android")
            if (!credential.isNullOrBlank()) {
                setRequestProperty("apikey", credential)
                setRequestProperty("Authorization", "Bearer $credential")
            }
        }
        return try {
            val code = c.responseCode
            if (accept204 && code == 204) return ""
            if (code !in 200..299) {
                val body = c.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                error("HTTP $code${body.take(120).let { if (it.isBlank()) "" else " · $it" }}")
            }
            c.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally { c.disconnect() }
    }

    private fun parseHourlyDate(raw: String): Long? {
        val clean = raw.trim().trim('"')
        if (clean.matches(Regex("\\d{10}"))) {
            return runCatching {
                LocalDateTime.parse(clean, DateTimeFormatter.ofPattern("yyyyMMddHH", Locale.ROOT))
                    .toInstant(ZoneOffset.UTC).toEpochMilli()
            }.getOrNull()
        }
        return runCatching { Instant.parse(clean).toEpochMilli() }.getOrNull()
            ?: runCatching { LocalDateTime.parse(clean).atZone(zone).toInstant().toEpochMilli() }.getOrNull()
    }

    private fun findColumn(headers: List<String>, vararg names: String): Int = headers.indexOfFirst { h ->
        names.any { n -> h == normHeader(n) }
    }

    private fun normHeader(v: String): String = v.trim().trim('"').lowercase(Locale.ROOT)
        .replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace(" ", "_").replace("-", "_")

    private fun splitCsv(line: String, delimiter: Char): List<String> {
        val out = mutableListOf<String>()
        val current = StringBuilder()
        var quoted = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            if (ch == '"') {
                if (quoted && i + 1 < line.length && line[i + 1] == '"') { current.append('"'); i++ }
                else quoted = !quoted
            } else if (ch == delimiter && !quoted) {
                out += current.toString(); current.clear()
            } else current.append(ch)
            i++
        }
        out += current.toString()
        return out
    }

    private fun roundHour(ts: Long): Long = (ts / hourMs) * hourMs
    private fun enc(v: String): String = URLEncoder.encode(v, "UTF-8")
    private fun minInstant(a: Instant, b: Instant): Instant = if (a.isBefore(b)) a else b
}
