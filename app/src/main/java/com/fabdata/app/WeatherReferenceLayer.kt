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

    fun byKeyOrNull(key: String?): WeatherReference? = stations.firstOrNull { it.key == key }
    fun byKey(key: String?): WeatherReference = byKeyOrNull(key) ?: stations.first()
}

class WeatherReferencePrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)

    fun selectedKey(): String = prefs.getString("selected_key", WeatherReferenceCatalog.DEFAULT_KEY)
        ?: WeatherReferenceCatalog.DEFAULT_KEY

    fun selectedReference(): WeatherReference {
        val key = selectedKey()
        WeatherReferenceCatalog.byKeyOrNull(key)?.let { return it }
        if (prefs.getString("custom_key", null) == key) {
            val latitude = prefs.getString("custom_latitude", null)?.toDoubleOrNull()
            val longitude = prefs.getString("custom_longitude", null)?.toDoubleOrNull()
            val stationId = prefs.getString("custom_station_id", null)
            val stationName = prefs.getString("custom_station_name", null)
            val city = prefs.getString("custom_city", null)
            val departmentId = prefs.getString("custom_department_id", null).orEmpty()
            if (latitude != null && longitude != null && !stationId.isNullOrBlank() && !stationName.isNullOrBlank()) {
                return WeatherReference(
                    key = key,
                    city = city?.takeIf { it.isNotBlank() } ?: stationName,
                    stationName = stationName,
                    stationId = stationId,
                    latitude = latitude,
                    longitude = longitude,
                    departmentId = departmentId
                )
            }
        }
        return WeatherReferenceCatalog.byKey(null)
    }

    fun select(key: String) = select(WeatherReferenceCatalog.byKey(key))

    fun select(reference: WeatherReference) {
        val editor = prefs.edit().putString("selected_key", reference.key)
        if (WeatherReferenceCatalog.byKeyOrNull(reference.key) != null) {
            editor.remove("custom_key")
                .remove("custom_city")
                .remove("custom_station_name")
                .remove("custom_station_id")
                .remove("custom_latitude")
                .remove("custom_longitude")
                .remove("custom_department_id")
        } else {
            editor.putString("custom_key", reference.key)
                .putString("custom_city", reference.city)
                .putString("custom_station_name", reference.stationName)
                .putString("custom_station_id", reference.stationId)
                .putString("custom_latitude", reference.latitude.toString())
                .putString("custom_longitude", reference.longitude.toString())
                .putString("custom_department_id", reference.departmentId)
        }
        editor.apply()
    }

    fun autoProtection(): Boolean = prefs.getBoolean("station_auto_protection", false)
    fun setAutoProtection(enabled: Boolean) = prefs.edit().putBoolean("station_auto_protection", enabled).apply()
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

    fun historyBounds(referenceKey: String): LongRange? {
        db.readableDatabase.rawQuery(
            "SELECT MIN(timestamp), MAX(timestamp) FROM weather_reference_samples WHERE reference_key=? AND source<>'forecast'",
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

data class WeatherReferenceCoverage(
    val from: Long,
    val to: Long,
    val expectedHours: Int,
    val presentHours: Int,
    val measuredHours: Int,
    val reconstructedHours: Int,
    val coverage: Double,
    val maxGapHours: Int
) {
    val ready: Boolean get() = coverage >= 0.90 && maxGapHours <= 3
}

data class WeatherReferencePreparation(
    val sync: WeatherReferenceSyncResult,
    val coverage: WeatherReferenceCoverage,
    val days: Int
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
     * Recharge uniquement la station sélectionnée.
     * v0.10.3 : weather_reference_samples EST la série de référence visible ET celle du RC.
     * Les observations officielles gardent la priorité ; Open-Meteo historique sert
     * seulement de reconstruction de secours pour obtenir une entrée longue/continue.
     */
    fun refreshSelected(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {
        store.keepOnly(reference.key)

        // v0.13.1 : l'archive Open-Meteo est volontairement arrêtée avant sa zone
        // de fraîcheur incertaine, puis un pont "past_days" recolle les 14 derniers jours.
        // Une station dynamique garde ainsi une série continue sans toucher au moteur RC.
        runCatching { fetchOpenMeteoHistory(reference, from, to) }
            .getOrDefault(emptyList())
            .forEach { store.upsert(reference.key, it) }
        runCatching { fetchOpenMeteoRecentPast(reference, from, to) }
            .getOrDefault(emptyList())
            .forEach { store.upsert(reference.key, it) }

        if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
            val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
            db.querySamples(sensor.id, from, to, maxPoints = 30_000).forEach { p ->
                val source = PointSourceStore.sourceFor(db, sensor.id, p.timestamp)
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, source))
            }

            // Si un token existe, l'horaire officiel étend Lyon au-delà du seed embarqué.
            if (credentials.hasCredential()) {
                runCatching { fetchOfficialHourly(reference, from, to) }
                    .getOrDefault(emptyList())
                    .forEach { store.upsert(reference.key, it) }
            }

            lyonLab.queryOfficial(LyonSeriesKind.HOURLY, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
            }
            lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
            }
            lyonLab.reconstruct(from, to).points.forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.RECONSTRUCTED, 0.72))
            }
        } else {
            if (credentials.hasCredential()) {
                runCatching { fetchOfficialHourly(reference, from, to) }
                    .getOrDefault(emptyList())
                    .forEach { store.upsert(reference.key, it) }
            }
            reconstructShortGaps(reference.key, from, to)
        }

        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)
        val actual = store.query(reference.key, from, minOf(to, System.currentTimeMillis()))
        return WeatherReferenceSyncResult(
            measured = actual.count { it.source == PointSource.MEASURED },
            reconstructed = actual.count { it.source == PointSource.RECONSTRUCTED },
            forecast = forecast,
            label = reference.label
        )
    }

    /**
     * Prépare explicitement 30/60/90 jours AVANT la première vraie mesure intérieure.
     * 18 h supplémentaires sont chargées en amont : retard RC max 12 h + moyenne 6 h.
     */
    fun prepareHistory(reference: WeatherReference, requestedDays: Int): WeatherReferencePreparation {
        val days = requestedDays.coerceIn(1, 90)
        val indoor = db.physicalMeasuredBounds() ?: db.physicalSensorBounds() ?: db.globalTimeBounds()
            ?: error("Aucune donnée intérieure")
        val coreFrom = indoor.first - days.toLong() * 24L * hourMs
        val loadFrom = coreFrom - 18L * hourMs
        val loadTo = maxOf(indoor.last, System.currentTimeMillis() + 7L * hourMs)
        val sync = refreshSelected(reference, loadFrom, loadTo)
        val coverage = coverage(reference.key, loadFrom, indoor.first)
        return WeatherReferencePreparation(sync, coverage, days)
    }

    fun coverage(referenceKey: String, from: Long, to: Long): WeatherReferenceCoverage {
        val start = roundHour(from)
        val end = roundHour(to)
        if (end < start) return WeatherReferenceCoverage(from, to, 0, 0, 0, 0, 0.0, Int.MAX_VALUE)
        val points = store.query(referenceKey, from, to).filter { it.source != PointSource.FORECAST }
        val byHour = points.groupBy { roundHour(it.timestamp) }
            .filterKeys { it in start..end }
        val expected = (((end - start) / hourMs) + 1L).toInt().coerceAtLeast(1)
        val buckets = byHour.keys.sorted()
        val measured = byHour.values.count { values -> values.any { it.source == PointSource.MEASURED } }
        val reconstructed = byHour.values.count { values -> values.none { it.source == PointSource.MEASURED } }
        val coverage = byHour.size.toDouble() / expected.toDouble()
        val leading = buckets.firstOrNull()?.let { ((it - start) / hourMs).toInt().coerceAtLeast(0) } ?: expected
        val trailing = buckets.lastOrNull()?.let { ((end - it) / hourMs).toInt().coerceAtLeast(0) } ?: expected
        val internal = buckets.zipWithNext().maxOfOrNull { (a, b) ->
            (((b - a) / hourMs).toInt() - 1).coerceAtLeast(0)
        } ?: 0
        return WeatherReferenceCoverage(
            from = start,
            to = end,
            expectedHours = expected,
            presentHours = byHour.size,
            measuredHours = measured,
            reconstructedHours = reconstructed,
            coverage = coverage,
            maxGapHours = maxOf(leading, trailing, internal)
        )
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
        val historyEnd = minOf(to, System.currentTimeMillis())
        val needsHistory = existing.size < 24 ||
            store.bounds(reference.key)?.let { it.first > from || it.last < historyEnd } != false ||
            hasMaterialHourlyGaps(existing, from, historyEnd)
        return if (needsHistory) {
            refreshSelected(reference, from, to)
        } else {
            val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)
            WeatherReferenceSyncResult(measured, reconstructed, forecast, reference.label)
        }
    }

    private fun hasMaterialHourlyGaps(
        points: List<WeatherReferencePoint>,
        from: Long,
        to: Long
    ): Boolean {
        if (to <= from) return true
        val start = roundHour(from)
        val end = roundHour(to)
        val buckets = points.asSequence()
            .filter { it.source != PointSource.FORECAST }
            .map { roundHour(it.timestamp) }
            .filter { it in start..end }
            .distinct()
            .sorted()
            .toList()
        if (buckets.isEmpty()) return true
        val expected = (((end - start) / hourMs) + 1L).coerceAtLeast(1L)
        val coverage = buckets.size.toDouble() / expected.toDouble()
        val maxGap = buckets.zipWithNext().maxOfOrNull { (a, b) -> ((b - a) / hourMs).toInt() } ?: 1
        return coverage < 0.90 || maxGap > 3
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

    private fun fetchOpenMeteoHistory(
        reference: WeatherReference,
        from: Long,
        to: Long
    ): List<WeatherReferencePoint> {
        // L'archive n'est pas une source temps réel. Demander aujourd'hui peut faire
        // échouer toute la requête ; on laisse 10 jours de marge, couverts par past_days=14.
        val historyTo = minOf(to, System.currentTimeMillis() - 10L * 24L * hourMs)
        if (historyTo <= from) return emptyList()
        val startDate = Instant.ofEpochMilli(from).atZone(zone).toLocalDate()
        val endDate = Instant.ofEpochMilli(historyTo).atZone(zone).toLocalDate()
        if (startDate.isAfter(endDate)) return emptyList()
        val url = "https://archive-api.open-meteo.com/v1/archive" +
            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
            "&start_date=$startDate&end_date=$endDate" +
            "&hourly=temperature_2m%2Crelative_humidity_2m&timezone=Europe%2FParis"
        val raw = httpGetAnonymous(url)
        val hourly = JSONObject(raw).getJSONObject("hourly")
        val times = hourly.getJSONArray("time")
        val temps = hourly.getJSONArray("temperature_2m")
        val hums = hourly.getJSONArray("relative_humidity_2m")
        val out = mutableListOf<WeatherReferencePoint>()
        for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {
            val time = times.optString(i)
            val temp = temps.optDouble(i, Double.NaN)
            val hum = hums.optDouble(i, Double.NaN)
            if (!temp.isFinite() || !hum.isFinite()) continue
            val ts = runCatching {
                LocalDateTime.parse(time).atZone(zone).toInstant().toEpochMilli()
            }.getOrNull() ?: continue
            if (ts !in from..historyTo || temp !in -60.0..65.0 || hum !in 0.0..100.0) continue
            out += WeatherReferencePoint(ts, temp, hum, PointSource.RECONSTRUCTED, 0.68)
        }
        return out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }

    /**
     * Pont récent pour les stations dynamiques : les derniers jours sont servis par
     * l'API forecast avec past_days, donc indépendamment du délai de l'archive.
     * Ces points restent RECONSTRUCTED et ne peuvent jamais écraser une observation.
     */
    private fun fetchOpenMeteoRecentPast(
        reference: WeatherReference,
        from: Long,
        to: Long
    ): List<WeatherReferencePoint> {
        val now = System.currentTimeMillis()
        val recentFrom = maxOf(from, now - 14L * 24L * hourMs)
        val recentTo = minOf(to, now - 20L * 60L * 1000L)
        if (recentTo <= recentFrom) return emptyList()

        val url = "https://api.open-meteo.com/v1/forecast" +
            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
            "&hourly=temperature_2m,relative_humidity_2m" +
            "&past_days=14&forecast_days=1&timezone=Europe%2FParis"
        val raw = httpGetAnonymous(url)
        val hourly = JSONObject(raw).getJSONObject("hourly")
        val times = hourly.getJSONArray("time")
        val temps = hourly.getJSONArray("temperature_2m")
        val hums = hourly.getJSONArray("relative_humidity_2m")
        val out = mutableListOf<WeatherReferencePoint>()
        for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {
            val time = times.optString(i)
            val temp = temps.optDouble(i, Double.NaN)
            val hum = hums.optDouble(i, Double.NaN)
            if (!temp.isFinite() || !hum.isFinite()) continue
            val ts = runCatching {
                LocalDateTime.parse(time).atZone(zone).toInstant().toEpochMilli()
            }.getOrNull() ?: continue
            if (ts !in recentFrom..recentTo || temp !in -60.0..65.0 || hum !in 0.0..100.0) continue
            out += WeatherReferencePoint(ts, temp, hum, PointSource.RECONSTRUCTED, 0.72)
        }
        return out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }

    private fun httpGetAnonymous(url: String): String {
        val c = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 20_000
            readTimeout = 30_000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "FabData/0.10.3 Android")
            setRequestProperty("Accept", "application/json")
        }
        return try {
            val code = c.responseCode
            if (code !in 200..299) error("Historique météo HTTP $code")
            c.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    private fun fetchOfficialHourly(reference: WeatherReference, from: Long, to: Long): List<WeatherReferencePoint> {
        val credential = credentials.get().takeIf { it.isNotBlank() } ?: error("Token Météo-France absent")
        val safeTo = minOf(to, System.currentTimeMillis() - 10L * 60L * 1000L)
        if (safeTo <= from) return emptyList()
        val orderBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande-station/horaire"
        val fileBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande/fichier"
        val all = mutableListOf<WeatherReferencePoint>()
        var cursor = Instant.ofEpochMilli(from)
        val end = Instant.ofEpochMilli(safeTo)
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
