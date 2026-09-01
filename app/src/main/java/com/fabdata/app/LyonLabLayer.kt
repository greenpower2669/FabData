package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.graphics.Color as AndroidColor
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
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
import kotlin.math.max
import kotlin.math.min

/**
 * Couche Lyon v0.9 : données officielles séparées, reconstruction déterministe,
 * overrides manuels et personnalisation. Aucune écriture dans samples.
 */
enum class LyonSeriesKind(val dbKey: String, val label: String) {
    SIX_MIN("official_6m", "6 min officiel"),
    HOURLY("official_hourly", "Horaire officiel"),
    RECONSTRUCTED("reconstructed", "Reconstruit");

    fun next(): LyonSeriesKind = entries[(ordinal + 1) % entries.size]
}

data class LyonLabPoint(
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val source: LyonSeriesKind
)

data class LyonDecision(
    val timestamp: Long,
    val sixMin: LyonLabPoint?,
    val hourly: LyonLabPoint?,
    val reconstructed: LyonLabPoint?,
    val state: String,
    val reason1: String,
    val reason2: String?,
    val manual: Boolean
)

data class LyonReconstruction(
    val points: List<LyonLabPoint>,
    val decisions: List<LyonDecision>
)

data class LyonManualOverride(
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val note: String,
    val updatedAt: Long
)

data class CurveVisualPrefs(
    val styleA: String = "BASE",
    val styleB: String = "BASE",
    val auraA: String = "NONE",
    val auraB: String = "NONE",
    val opacity: Float = 1f
)

private const val SIX_MIN_MS = 6L * 60L * 1000L
private const val HOUR_MS = 60L * 60L * 1000L
private const val MAX_RECON_GAP_MS = 6L * HOUR_MS

fun ensureLyonLabSchema(db: android.database.sqlite.SQLiteDatabase) {
    db.execSQL(
        """
        CREATE TABLE IF NOT EXISTS lyon_official_samples (
            source TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            received_at INTEGER NOT NULL,
            PRIMARY KEY(source, timestamp)
        )
        """.trimIndent()
    )
    db.execSQL("CREATE INDEX IF NOT EXISTS idx_lyon_official_time ON lyon_official_samples(source, timestamp)")
    db.execSQL(
        """
        CREATE TABLE IF NOT EXISTS lyon_overrides (
            timestamp INTEGER PRIMARY KEY,
            temperature REAL NOT NULL,
            humidity REAL NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL
        )
        """.trimIndent()
    )
}

class LyonLabStore(private val db: FabDataDb) {
    init {
        ensureLyonLabSchema(db.writableDatabase)
    }

    fun upsertOfficial(kind: LyonSeriesKind, points: List<LyonLabPoint>): Int {
        require(kind != LyonSeriesKind.RECONSTRUCTED)
        var changed = 0
        val sqlDb = db.writableDatabase
        sqlDb.beginTransaction()
        try {
            points.forEach { point ->
                if (point.temperature !in -60.0..65.0 || point.humidity !in 0.0..100.0) return@forEach
                val values = ContentValues().apply {
                    put("source", kind.dbKey)
                    put("timestamp", point.timestamp)
                    put("temperature", point.temperature)
                    put("humidity", point.humidity)
                    put("received_at", System.currentTimeMillis())
                }
                val row = sqlDb.insertWithOnConflict(
                    "lyon_official_samples", null, values,
                    android.database.sqlite.SQLiteDatabase.CONFLICT_REPLACE
                )
                if (row != -1L) changed++
            }
            sqlDb.setTransactionSuccessful()
        } finally {
            sqlDb.endTransaction()
        }
        return changed
    }

    fun queryOfficial(kind: LyonSeriesKind, from: Long, to: Long): List<LyonLabPoint> {
        if (kind == LyonSeriesKind.RECONSTRUCTED) return emptyList()
        val out = mutableListOf<LyonLabPoint>()
        db.readableDatabase.rawQuery(
            "SELECT timestamp, temperature, humidity FROM lyon_official_samples WHERE source=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            arrayOf(kind.dbKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += LyonLabPoint(c.getLong(0), c.getDouble(1), c.getDouble(2), kind)
            }
        }
        return out
    }

    fun saveOverride(timestamp: Long, temperature: Double, humidity: Double, note: String) {
        val values = ContentValues().apply {
            put("timestamp", timestamp)
            put("temperature", temperature)
            put("humidity", humidity)
            put("note", note.trim())
            put("updated_at", System.currentTimeMillis())
        }
        db.writableDatabase.insertWithOnConflict(
            "lyon_overrides", null, values,
            android.database.sqlite.SQLiteDatabase.CONFLICT_REPLACE
        )
    }

    fun deleteOverride(timestamp: Long) {
        db.writableDatabase.delete("lyon_overrides", "timestamp=?", arrayOf(timestamp.toString()))
    }

    fun queryOverrides(from: Long, to: Long): Map<Long, LyonManualOverride> {
        val out = linkedMapOf<Long, LyonManualOverride>()
        db.readableDatabase.rawQuery(
            "SELECT timestamp, temperature, humidity, note, updated_at FROM lyon_overrides WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
            arrayOf(from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val item = LyonManualOverride(c.getLong(0), c.getDouble(1), c.getDouble(2), c.getString(3), c.getLong(4))
                out[item.timestamp] = item
            }
        }
        return out
    }

    fun bounds(): LongRange? {
        db.readableDatabase.rawQuery("SELECT MIN(timestamp), MAX(timestamp) FROM lyon_official_samples", null).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    private fun queryLegacyFallback(from: Long, to: Long): List<LyonLabPoint> {
        val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
        return db.querySamples(sensor.id, from, to).map {
            LyonLabPoint(it.timestamp, it.temperature, it.humidity, LyonSeriesKind.RECONSTRUCTED)
        }
    }

    fun reconstruct(from: Long, to: Long): LyonReconstruction {
        val paddedFrom = from - 2L * HOUR_MS
        val paddedTo = to + 2L * HOUR_MS
        val six = queryOfficial(LyonSeriesKind.SIX_MIN, paddedFrom, paddedTo).sortedBy { it.timestamp }
        val hourly = queryOfficial(LyonSeriesKind.HOURLY, paddedFrom, paddedTo).sortedBy { it.timestamp }
        val fallback = queryLegacyFallback(paddedFrom, paddedTo).sortedBy { it.timestamp }
        val overrides = queryOverrides(from, to)

        val sixByTs = six.associateBy { it.timestamp }
        val validSix = six.filterIndexed { index, p -> !isSuspectSix(p, index, six, hourly) }
        val validFallback = fallback.filterIndexed { index, p -> !isSuspectFallback(p, index, fallback, hourly) }
        val fallbackByTs = validFallback.associateBy { it.timestamp }
        val anchorsByTs = linkedMapOf<Long, LyonLabPoint>()
        // Priority: fallback < hourly official < six-minute official < manual override.
        validFallback.forEach { anchorsByTs[it.timestamp] = it }
        hourly.forEach { anchorsByTs[it.timestamp] = it }
        validSix.forEach { anchorsByTs[it.timestamp] = it }
        overrides.values.forEach { o ->
            anchorsByTs[o.timestamp] = LyonLabPoint(o.timestamp, o.temperature, o.humidity, LyonSeriesKind.RECONSTRUCTED)
        }
        val anchors = anchorsByTs.values.sortedBy { it.timestamp }

        val out = mutableListOf<LyonLabPoint>()
        val decisions = mutableListOf<LyonDecision>()
        if (anchors.isEmpty()) return LyonReconstruction(emptyList(), emptyList())

        var ts = roundUpSix(max(from, anchors.first().timestamp))
        val last = min(to, anchors.last().timestamp)
        while (ts <= last) {
            val manual = overrides[ts]
            val raw6 = sixByTs[ts]
            val rawHour = nearestWithin(hourly, ts, 31L * 60L * 1000L)

            if (manual != null) {
                val p = LyonLabPoint(ts, manual.temperature, manual.humidity, LyonSeriesKind.RECONSTRUCTED)
                out += p
                decisions += LyonDecision(
                    ts, raw6, rawHour, p, "CORRIGÉ MANUELLEMENT",
                    "Valeur imposée manuellement.",
                    manual.note.ifBlank { "Les données officielles restent intactes." }, true
                )
                ts += SIX_MIN_MS
                continue
            }

            if (raw6 != null && !isSuspectSix(raw6, six.indexOf(raw6), six, hourly)) {
                out += LyonLabPoint(ts, raw6.temperature, raw6.humidity, LyonSeriesKind.RECONSTRUCTED)
                ts += SIX_MIN_MS
                continue
            }

            // Exact fallback point is accepted only after anomaly filtering.
            val rawFallback = fallbackByTs[ts]
            if (raw6 == null && rawFallback != null) {
                out += LyonLabPoint(ts, rawFallback.temperature, rawFallback.humidity, LyonSeriesKind.RECONSTRUCTED)
                ts += SIX_MIN_MS
                continue
            }

            val interpolated = interpolateAt(anchors, ts)
            if (interpolated != null) {
                val p = LyonLabPoint(ts, interpolated.first, interpolated.second, LyonSeriesKind.RECONSTRUCTED)
                out += p
                if (raw6 != null) {
                    decisions += LyonDecision(
                        ts, raw6, rawHour, p, "REJETÉ COMME SUSPECT",
                        "Point 6 min écarté : excursion incohérente avec ses voisins.",
                        "Horaire officiel et tendance locale servent d’ancre.", false
                    )
                } else {
                    decisions += LyonDecision(
                        ts, null, rawHour, p, "INTERPOLÉ",
                        "Aucune observation 6 min fiable à cet instant.",
                        "Continuité bornée entre ancres fiables ; l’officiel garde la priorité.", false
                    )
                }
            }
            ts += SIX_MIN_MS
        }

        // Overrides hors grille 6 minutes restent visibles et éditables.
        overrides.values.filter { it.timestamp !in out.map { p -> p.timestamp }.toSet() }.forEach { o ->
            val p = LyonLabPoint(o.timestamp, o.temperature, o.humidity, LyonSeriesKind.RECONSTRUCTED)
            out += p
            decisions += LyonDecision(
                o.timestamp, nearestWithin(six, o.timestamp, 10L * 60L * 1000L),
                nearestWithin(hourly, o.timestamp, 31L * 60L * 1000L), p,
                "CORRIGÉ MANUELLEMENT", "Valeur imposée manuellement.", o.note.ifBlank { null }, true
            )
        }
        return LyonReconstruction(out.sortedBy { it.timestamp }, decisions.sortedBy { it.timestamp })
    }

    private fun isSuspectSix(
        point: LyonLabPoint,
        index: Int,
        six: List<LyonLabPoint>,
        hourly: List<LyonLabPoint>
    ): Boolean {
        if (point.temperature !in -35.0..50.0 || point.humidity !in 0.0..100.0) return true
        if (index !in six.indices) return false
        val prev = six.getOrNull(index - 1)?.takeIf { point.timestamp - it.timestamp <= 18L * 60L * 1000L }
        val next = six.getOrNull(index + 1)?.takeIf { it.timestamp - point.timestamp <= 18L * 60L * 1000L }
        val spike = if (prev != null && next != null) {
            val neighborMean = (prev.temperature + next.temperature) / 2.0
            abs(point.temperature - neighborMean) >= 5.0 && abs(prev.temperature - next.temperature) <= 3.0
        } else false
        val hour = nearestWithin(hourly, point.timestamp, 31L * 60L * 1000L)
        val contradictsHourly = hour != null && abs(point.temperature - hour.temperature) >= 7.0
        val returnSpike = prev != null && next != null &&
            abs(point.temperature - prev.temperature) >= 6.0 && abs(next.temperature - prev.temperature) <= 2.5
        return (spike && contradictsHourly) || (returnSpike && abs(point.temperature - (hour?.temperature ?: prev!!.temperature)) >= 6.0)
    }

    private fun isSuspectFallback(
        point: LyonLabPoint,
        index: Int,
        fallback: List<LyonLabPoint>,
        hourly: List<LyonLabPoint>
    ): Boolean {
        if (point.temperature !in -35.0..50.0 || point.humidity !in 0.0..100.0) return true
        if (index !in fallback.indices) return false

        val hour = nearestWithin(hourly, point.timestamp, 31L * 60L * 1000L)
        if (hour != null && abs(point.temperature - hour.temperature) >= 5.0) return true

        // Reject a short-lived V/peak: a nearby value before and after agree,
        // while the current point is >= 5 °C away from their baseline.
        val before = fallback.subList(max(0, index - 4), index)
        val after = fallback.subList(index + 1, min(fallback.size, index + 5))
        val excursion = before.any { left ->
            point.timestamp - left.timestamp <= 4L * HOUR_MS && after.any { right ->
                right.timestamp - point.timestamp <= 4L * HOUR_MS &&
                    abs(left.temperature - right.temperature) <= 3.0 &&
                    abs(point.temperature - ((left.temperature + right.temperature) / 2.0)) >= 5.0
            }
        }
        return excursion
    }

    private fun interpolateAt(anchors: List<LyonLabPoint>, timestamp: Long): Pair<Double, Double>? {
        var rightIndex = anchors.binarySearchBy(timestamp) { it.timestamp }
        if (rightIndex >= 0) return anchors[rightIndex].temperature to anchors[rightIndex].humidity
        rightIndex = -rightIndex - 1
        val leftIndex = rightIndex - 1
        val left = anchors.getOrNull(leftIndex) ?: return null
        val right = anchors.getOrNull(rightIndex) ?: return null
        val gap = right.timestamp - left.timestamp
        if (gap <= 0L || gap > MAX_RECON_GAP_MS) return null
        val fraction = (timestamp - left.timestamp).toDouble() / gap.toDouble()
        if (fraction !in 0.0..1.0) return null
        val prev = anchors.getOrNull(leftIndex - 1)
        val next = anchors.getOrNull(rightIndex + 1)
        val temp = boundedHermite(prev?.temperature, left.temperature, right.temperature, next?.temperature, fraction)
        val hum = boundedHermite(prev?.humidity, left.humidity, right.humidity, next?.humidity, fraction).coerceIn(0.0, 100.0)
        return temp to hum
    }

    /** Hermite monotone bornée : garde la tangente locale sans sur-oscillation libre. */
    private fun boundedHermite(yPrev: Double?, y0: Double, y1: Double, yNext: Double?, t: Double): Double {
        val d = y1 - y0
        if (abs(d) < 1e-9) return y0
        var m0 = if (yPrev == null) d else (y1 - yPrev) / 2.0
        var m1 = if (yNext == null) d else (yNext - y0) / 2.0
        if (m0 * d <= 0.0) m0 = 0.0
        if (m1 * d <= 0.0) m1 = 0.0
        val limit = 3.0 * abs(d)
        m0 = m0.coerceIn(-limit, limit)
        m1 = m1.coerceIn(-limit, limit)
        val t2 = t * t
        val t3 = t2 * t
        val h00 = 2 * t3 - 3 * t2 + 1
        val h10 = t3 - 2 * t2 + t
        val h01 = -2 * t3 + 3 * t2
        val h11 = t3 - t2
        val value = h00 * y0 + h10 * m0 + h01 * y1 + h11 * m1
        return value.coerceIn(min(y0, y1), max(y0, y1))
    }

    private fun roundUpSix(ts: Long): Long = ((ts + SIX_MIN_MS - 1L) / SIX_MIN_MS) * SIX_MIN_MS

    private fun nearestWithin(points: List<LyonLabPoint>, timestamp: Long, tolerance: Long): LyonLabPoint? {
        if (points.isEmpty()) return null
        val idx = points.binarySearchBy(timestamp) { it.timestamp }
        if (idx >= 0) return points[idx]
        val insert = -idx - 1
        val candidates = listOfNotNull(points.getOrNull(insert), points.getOrNull(insert - 1))
        return candidates.minByOrNull { abs(it.timestamp - timestamp) }
            ?.takeIf { abs(it.timestamp - timestamp) <= tolerance }
    }
}

class MeteoFranceCredentialStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_meteofrance", Context.MODE_PRIVATE)
    fun get(): String = prefs.getString("credential", "").orEmpty()
    fun save(value: String) = prefs.edit().putString("credential", value.trim()).apply()
    fun hasCredential(): Boolean = get().isNotBlank()
}

data class MeteoSyncResult(val received: Int, val stored: Int, val label: String)

class MeteoFranceOfficialClient(
    private val context: Context,
    private val store: LyonLabStore,
    private val credentials: MeteoFranceCredentialStore
) {
    companion object {
        const val STATION_ID = "69029001"
        private const val OBS_PACKAGE = "https://public-api.meteofrance.fr/public/DPPaquetObs/paquet/infra-horaire-6m"
        private const val OBS_TARGET = "https://public-api.meteofrance.fr/public/DPObs/v2/station/infrahoraire-6m"
        private const val CLIM_ORDER = "https://public-api.meteofrance.fr/public/DPClim/v1/commande-station/horaire"
        private const val CLIM_FILE = "https://public-api.meteofrance.fr/public/DPClim/v1/commande/fichier"
    }

    fun syncSixMinute24h(): MeteoSyncResult {
        val credential = requireCredential()
        val primaryUrl = "$OBS_PACKAGE?id_station=$STATION_ID&format=csv"
        val raw = runCatching { get(primaryUrl, credential) }.getOrElse {
            // Repli officiel : au moins la dernière observation ciblée, jamais Infoclimat.
            get("$OBS_TARGET?id_station=$STATION_ID&format=geojson", credential)
        }
        val points = parseObservationPayload(raw)
        if (points.isEmpty()) error("Météo-France : aucune observation 6 min exploitable")
        val stored = store.upsertOfficial(LyonSeriesKind.SIX_MIN, points)
        return MeteoSyncResult(points.size, stored, "6 min officiel")
    }

    fun syncHourly(from: Long, to: Long): MeteoSyncResult {
        val credential = requireCredential()
        if (to < from) return MeteoSyncResult(0, 0, "Horaire officiel")
        var cursor = Instant.ofEpochMilli(from)
        val end = Instant.ofEpochMilli(to)
        val all = mutableListOf<LyonLabPoint>()
        while (!cursor.isAfter(end)) {
            val chunkEnd = minInstant(cursor.plusSeconds(364L * 24L * 3600L), end)
            val startIso = DateTimeFormatter.ISO_INSTANT.format(cursor)
            val endIso = DateTimeFormatter.ISO_INSTANT.format(chunkEnd)
            val url = CLIM_ORDER + "?id-station=$STATION_ID" +
                "&date-deb-periode=${enc(startIso)}&date-fin-periode=${enc(endIso)}"
            val response = get(url, credential)
            val orderId = JSONObject(response)
                .getJSONObject("elaboreProduitAvecDemandeResponse")
                .get("return").toString()
            var csv: String? = null
            repeat(10) { attempt ->
                if (csv != null) return@repeat
                if (attempt > 0) Thread.sleep(1300L)
                runCatching { get("$CLIM_FILE?id-cmde=${enc(orderId)}", credential, accept204 = true) }
                    .getOrNull()?.takeIf { it.isNotBlank() }?.let { csv = it }
            }
            csv?.let { all += parseHourlyCsv(it) }
            cursor = chunkEnd.plusSeconds(1)
        }
        val unique = all.distinctBy { it.timestamp }.sortedBy { it.timestamp }
        val stored = store.upsertOfficial(LyonSeriesKind.HOURLY, unique)
        return MeteoSyncResult(unique.size, stored, "Horaire officiel")
    }

    private fun requireCredential(): String = credentials.get().takeIf { it.isNotBlank() }
        ?: error("Ajoute d’abord ta clé/token Météo-France dans Détail Lyon")

    private fun get(url: String, credential: String, accept204: Boolean = false): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 18_000
            readTimeout = 25_000
            instanceFollowRedirects = true
            setRequestProperty("accept", "*/*")
            // Les deux mécanismes existent sur le portail selon le type de souscription.
            setRequestProperty("apikey", credential)
            setRequestProperty("Authorization", "Bearer $credential")
            setRequestProperty("User-Agent", "FabData/0.9.0 Android")
        }
        return try {
            val code = connection.responseCode
            if (accept204 && code == 204) return ""
            if (code !in 200..299) {
                val body = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                error("Météo-France HTTP $code${body.take(120).let { if (it.isBlank()) "" else " · $it" }}")
            }
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }

    private fun parseObservationPayload(raw: String): List<LyonLabPoint> {
        val trimmed = raw.trim()
        return if (trimmed.startsWith("[") || trimmed.startsWith("{")) parseObservationJson(trimmed) else parseObservationCsv(trimmed)
    }

    private fun parseObservationJson(raw: String): List<LyonLabPoint> {
        val root: JSONArray = if (raw.startsWith("[")) JSONArray(raw) else {
            val obj = JSONObject(raw)
            obj.optJSONArray("features") ?: JSONArray().put(obj)
        }
        val out = mutableListOf<LyonLabPoint>()
        for (i in 0 until root.length()) {
            val node = root.optJSONObject(i) ?: continue
            val p = node.optJSONObject("properties") ?: node
            val station = p.optString("geo_id_insee", p.optString("id_station", ""))
            if (station.isNotBlank() && station != STATION_ID) continue
            val time = p.optString("validity_time", p.optString("reference_time", ""))
            val ts = runCatching { Instant.parse(time).toEpochMilli() }.getOrNull() ?: continue
            if (!p.has("t") || p.isNull("t") || !p.has("u") || p.isNull("u")) continue
            val rawT = p.optDouble("t", Double.NaN)
            val hum = p.optDouble("u", Double.NaN)
            if (!rawT.isFinite() || !hum.isFinite()) continue
            val temp = if (rawT > 170.0) rawT - 273.15 else rawT
            if (temp !in -60.0..65.0 || hum !in 0.0..100.0) continue
            out += LyonLabPoint(ts, temp, hum, LyonSeriesKind.SIX_MIN)
        }
        return out
    }

    private fun parseObservationCsv(raw: String): List<LyonLabPoint> {
        val lines = raw.lineSequence().filter { it.isNotBlank() }.toList()
        if (lines.size < 2) return emptyList()
        val delimiter = if (lines.first().count { it == ';' } >= lines.first().count { it == ',' }) ';' else ','
        val header = splitCsvLine(lines.first(), delimiter).map { normalizeHeader(it) }
        val stationI = findColumn(header, "geo_id_insee", "id_station", "num_poste")
        val timeI = findColumn(header, "validity_time", "date", "reference_time")
        val tempI = findColumn(header, "t", "temperature")
        val humI = findColumn(header, "u", "humidite", "humidity")
        if (timeI < 0 || tempI < 0 || humI < 0) return emptyList()
        return lines.drop(1).mapNotNull { line ->
            val f = splitCsvLine(line, delimiter)
            if (stationI >= 0 && f.getOrNull(stationI)?.trim()?.trim('"')?.let { it.isNotBlank() && it != STATION_ID } == true) return@mapNotNull null
            val ts = parseFlexibleInstant(f.getOrNull(timeI).orEmpty()) ?: return@mapNotNull null
            val rawT = f.getOrNull(tempI)?.trim()?.replace(',', '.')?.toDoubleOrNull() ?: return@mapNotNull null
            val hum = f.getOrNull(humI)?.trim()?.replace(',', '.')?.toDoubleOrNull() ?: return@mapNotNull null
            val temp = if (rawT > 170.0) rawT - 273.15 else rawT
            if (temp !in -60.0..65.0 || hum !in 0.0..100.0) return@mapNotNull null
            LyonLabPoint(ts, temp, hum, LyonSeriesKind.SIX_MIN)
        }
    }

    private fun parseHourlyCsv(raw: String): List<LyonLabPoint> {
        val lines = raw.lineSequence().filter { it.isNotBlank() }.toList()
        if (lines.size < 2) return emptyList()
        val delimiter = ';'
        val header = splitCsvLine(lines.first().removePrefix("\uFEFF"), delimiter).map { normalizeHeader(it) }
        val stationI = findColumn(header, "num_poste", "id_station")
        val dateI = findColumn(header, "aaaammjjhh", "date")
        val tempI = findColumn(header, "t", "temperature")
        val humI = findColumn(header, "u", "humidite", "humidity")
        if (dateI < 0 || tempI < 0 || humI < 0) return emptyList()
        return lines.drop(1).mapNotNull { line ->
            val f = splitCsvLine(line, delimiter)
            if (stationI >= 0 && f.getOrNull(stationI)?.trim()?.trim('"') != STATION_ID) return@mapNotNull null
            val ts = parseHourlyDate(f.getOrNull(dateI).orEmpty()) ?: return@mapNotNull null
            val temp = f.getOrNull(tempI)?.trim()?.replace(',', '.')?.toDoubleOrNull() ?: return@mapNotNull null
            val hum = f.getOrNull(humI)?.trim()?.replace(',', '.')?.toDoubleOrNull() ?: return@mapNotNull null
            if (temp !in -60.0..65.0 || hum !in 0.0..100.0) return@mapNotNull null
            LyonLabPoint(ts, temp, hum, LyonSeriesKind.HOURLY)
        }
    }

    private fun parseHourlyDate(raw: String): Long? {
        val clean = raw.trim().trim('"')
        if (clean.matches(Regex("\\d{10}"))) {
            return runCatching {
                LocalDateTime.parse(clean, DateTimeFormatter.ofPattern("yyyyMMddHH", Locale.ROOT))
                    .toInstant(ZoneOffset.UTC).toEpochMilli()
            }.getOrNull()
        }
        return parseFlexibleInstant(clean)
    }

    private fun parseFlexibleInstant(raw: String): Long? {
        val clean = raw.trim().trim('"')
        return runCatching { Instant.parse(clean).toEpochMilli() }.getOrNull()
            ?: runCatching {
                LocalDateTime.parse(clean, DateTimeFormatter.ISO_LOCAL_DATE_TIME)
                    .atZone(ZoneId.of("Europe/Paris")).toInstant().toEpochMilli()
            }.getOrNull()
    }

    private fun findColumn(headers: List<String>, vararg names: String): Int = headers.indexOfFirst { h ->
        names.any { n -> h == normalizeHeader(n) }
    }

    private fun normalizeHeader(v: String): String = v.trim().trim('"').lowercase(Locale.ROOT)
        .replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace(" ", "_").replace("-", "_")

    private fun splitCsvLine(line: String, delimiter: Char): List<String> {
        val out = mutableListOf<String>()
        val current = StringBuilder()
        var quoted = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            if (ch == '"') {
                if (quoted && i + 1 < line.length && line[i + 1] == '"') {
                    current.append('"'); i++
                } else quoted = !quoted
            } else if (ch == delimiter && !quoted) {
                out += current.toString(); current.clear()
            } else current.append(ch)
            i++
        }
        out += current.toString()
        return out
    }

    private fun enc(v: String): String = URLEncoder.encode(v, "UTF-8")
    private fun minInstant(a: Instant, b: Instant): Instant = if (a.isBefore(b)) a else b
}

class CurveStyleStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_curve_styles", Context.MODE_PRIVATE)

    fun load(key: String): CurveVisualPrefs = CurveVisualPrefs(
        styleA = prefs.getString("$key.styleA", "BASE") ?: "BASE",
        styleB = prefs.getString("$key.styleB", "BASE") ?: "BASE",
        auraA = prefs.getString("$key.auraA", "NONE") ?: "NONE",
        auraB = prefs.getString("$key.auraB", "NONE") ?: "NONE",
        opacity = prefs.getFloat("$key.opacity", 1f).coerceIn(0f, 1f)
    )

    fun save(key: String, value: CurveVisualPrefs) {
        prefs.edit()
            .putString("$key.styleA", value.styleA)
            .putString("$key.styleB", value.styleB)
            .putString("$key.auraA", value.auraA)
            .putString("$key.auraB", value.auraB)
            .putFloat("$key.opacity", value.opacity.coerceIn(0f, 1f))
            .apply()
    }
}

private val STYLE_OPTIONS = listOf(
    "BASE", "RED", "ORANGE", "YELLOW", "GREEN", "CYAN", "BLUE", "PURPLE",
    "RAINBOW", "IRIDESCENT", "NONE"
)
private val AURA_OPTIONS = listOf("NONE", "SUN", "SHADOW", "ICE", "NATURE")

fun resolveCurveColor(base: Color, prefs: CurveVisualPrefs, tickMs: Long, position: Float = 0f): Color? {
    val useB = prefs.styleA != prefs.styleB && ((tickMs / 2200L) % 2L == 1L)
    val style = if (useB) prefs.styleB else prefs.styleA
    val alpha = prefs.opacity.coerceIn(0f, 1f)
    return when {
        style == "NONE" -> null
        style == "BASE" -> base.copy(alpha = alpha)
        style == "RED" -> Color(0xFFE53935).copy(alpha = alpha)
        style == "ORANGE" -> Color(0xFFFB8C00).copy(alpha = alpha)
        style == "YELLOW" -> Color(0xFFFDD835).copy(alpha = alpha)
        style == "GREEN" -> Color(0xFF43A047).copy(alpha = alpha)
        style == "CYAN" -> Color(0xFF00ACC1).copy(alpha = alpha)
        style == "BLUE" -> Color(0xFF1E88E5).copy(alpha = alpha)
        style == "PURPLE" -> Color(0xFF8E24AA).copy(alpha = alpha)
        style == "RAINBOW" -> {
            val hue = ((tickMs / 25L + (position * 360f).toLong()) % 360L).toFloat()
            Color.hsv(hue, 0.90f, 0.95f, alpha)
        }
        style == "IRIDESCENT" -> {
            val hue = ((tickMs / 45L + (position * 160f).toLong()) % 360L).toFloat()
            Color.hsv(hue, 0.42f, 1f, alpha)
        }
        style.startsWith("CUSTOM:") -> {
            runCatching { Color(AndroidColor.parseColor(style.removePrefix("CUSTOM:"))) }.getOrDefault(base).copy(alpha = alpha)
        }
        else -> base.copy(alpha = alpha)
    }
}

fun resolveAuraColor(prefs: CurveVisualPrefs, tickMs: Long): Color? {
    val useB = prefs.auraA != prefs.auraB && ((tickMs / 2700L) % 2L == 1L)
    return when (if (useB) prefs.auraB else prefs.auraA) {
        "SUN" -> Color(0xFFFFC107).copy(alpha = 0.22f * prefs.opacity)
        "SHADOW" -> Color.Black.copy(alpha = 0.18f * prefs.opacity)
        "ICE" -> Color(0xFF80DEEA).copy(alpha = 0.25f * prefs.opacity)
        "NATURE" -> Color(0xFF66BB6A).copy(alpha = 0.23f * prefs.opacity)
        else -> null
    }
}

@Composable
fun CurveStyleDialog(
    curveLabel: String,
    initial: CurveVisualPrefs,
    onDismiss: () -> Unit,
    onSave: (CurveVisualPrefs) -> Unit
) {
    var value by remember(initial) { mutableStateOf(initial) }
    var customColor by remember { mutableStateOf("#1565C0") }

    fun next(current: String, options: List<String>): String = options[(options.indexOf(current).takeIf { it >= 0 } ?: 0).let { (it + 1) % options.size }]
    fun display(v: String): String = when (v) {
        "BASE" -> "Couleur sonde"
        "RED" -> "Rouge"
        "ORANGE" -> "Orange"
        "YELLOW" -> "Jaune"
        "GREEN" -> "Vert"
        "CYAN" -> "Cyan"
        "BLUE" -> "Bleu"
        "PURPLE" -> "Violet"
        "RAINBOW" -> "Arc-en-ciel"
        "IRIDESCENT" -> "Iridescence"
        "NONE" -> "Pas de couleur"
        "SUN" -> "Soleil"
        "SHADOW" -> "Ombre"
        "ICE" -> "Glace"
        "NATURE" -> "Nature"
        else -> if (v.startsWith("CUSTOM:")) "Personnalisée ${v.removePrefix("CUSTOM:")}" else v
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Personnalisation · $curveLabel") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                StyleCarousel("Style A", display(value.styleA)) { value = value.copy(styleA = next(value.styleA, STYLE_OPTIONS)) }
                StyleCarousel("Style B", display(value.styleB)) { value = value.copy(styleB = next(value.styleB, STYLE_OPTIONS)) }
                OutlinedTextField(
                    value = customColor,
                    onValueChange = { customColor = it },
                    label = { Text("Couleur personnalisée #RRGGBB") },
                    singleLine = true
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = { value = value.copy(styleA = "CUSTOM:${customColor.trim()}") }) { Text("→ Style A") }
                    TextButton(onClick = { value = value.copy(styleB = "CUSTOM:${customColor.trim()}") }) { Text("→ Style B") }
                }
                StyleCarousel("Aura A", display(value.auraA)) { value = value.copy(auraA = next(value.auraA, AURA_OPTIONS)) }
                StyleCarousel("Aura B", display(value.auraB)) { value = value.copy(auraB = next(value.auraB, AURA_OPTIONS)) }
                Text("Opacité : ${(value.opacity * 100).toInt()} %")
                Slider(value = value.opacity, onValueChange = { value = value.copy(opacity = it) }, valueRange = 0f..1f)
            }
        },
        confirmButton = { Button(onClick = { onSave(value) }) { Text("Enregistrer") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
}

@Composable
private fun StyleCarousel(label: String, value: String, onNext: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.width(82.dp), fontWeight = FontWeight.SemiBold)
        OutlinedButton(onClick = onNext, modifier = Modifier.weight(1f)) { Text("‹ $value ›") }
    }
}

@Composable
fun CurvePersonalizationCard(
    sensors: List<Sensor>,
    onEdit: (String, String) -> Unit
) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text("Personnalisation des courbes", fontWeight = FontWeight.Bold)
            Text(
                "Style A/B · Aura A/B · Opacité, indépendants pour chaque courbe.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            sensors.forEach { sensor ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    val isRecon = sensor.stableKey == "lyon-reconstructed"
                    val label = when {
                        isRecon -> "Lyon reconstruit"
                        sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon officiel · 6 min"
                        else -> sensor.room
                    }
                    val key = if (isRecon) "lyon:reconstructed" else "sensor:${sensor.stableKey}"
                    Text(label, Modifier.weight(1f))
                    TextButton(onClick = { onEdit(key, label) }) { Text("Personnaliser") }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LyonDetailSheet(
    store: LyonLabStore,
    client: MeteoFranceOfficialClient,
    credentialStore: MeteoFranceCredentialStore,
    styleStore: CurveStyleStore,
    initialBounds: LongRange?,
    onDismiss: () -> Unit,
    onDataChanged: () -> Unit,
    onStyleEdit: (String, String) -> Unit
) {
    val scope = rememberCoroutineScope()
    var kind by remember { mutableStateOf(LyonSeriesKind.RECONSTRUCTED) }
    var credential by remember { mutableStateOf(credentialStore.get()) }
    var status by remember { mutableStateOf("") }
    var reload by remember { mutableStateOf(0) }
    var selected by remember { mutableStateOf<Long?>(null) }
    var editTimestamp by remember { mutableStateOf<Long?>(null) }
    var points by remember { mutableStateOf<List<LyonLabPoint>>(emptyList()) }
    var decisions by remember { mutableStateOf<List<LyonDecision>>(emptyList()) }

    var lyonStyleTick by remember { mutableStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            lyonStyleTick = System.currentTimeMillis()
            delay(180L)
        }
    }

    val now = System.currentTimeMillis()
    val bounds = initialBounds ?: (now - 48L * HOUR_MS)..now

    LaunchedEffect(kind, reload, bounds.first, bounds.last) {
        val data = withContext(Dispatchers.IO) {
            when (kind) {
                LyonSeriesKind.SIX_MIN -> store.queryOfficial(kind, bounds.first, bounds.last) to emptyList()
                LyonSeriesKind.HOURLY -> store.queryOfficial(kind, bounds.first, bounds.last) to emptyList()
                LyonSeriesKind.RECONSTRUCTED -> store.reconstruct(bounds.first, bounds.last).let { it.points to it.decisions }
            }
        }
        points = data.first
        decisions = data.second
        if (selected == null && points.isNotEmpty()) selected = points[points.size / 2].timestamp
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Détail Lyon", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text("Météo-France Lyon-Bron · 69029001", style = MaterialTheme.typography.labelSmall)
                }
                OutlinedButton(onClick = { kind = kind.next(); selected = null }) { Text("‹ ${kind.label} ›") }
            }

            OutlinedTextField(
                value = credential,
                onValueChange = { credential = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Clé / token Météo-France (facultatif)") },
                singleLine = true
            )
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = {
                    credentialStore.save(credential)
                    status = "Clé enregistrée localement"
                }) { Text("Enregistrer clé") }
                Button(onClick = {
                    credentialStore.save(credential)
                    scope.launch {
                        status = "Synchronisation 6 min…"
                        val result = withContext(Dispatchers.IO) { runCatching { client.syncSixMinute24h() } }
                        status = result.fold(
                            { "${it.label} : ${it.received} reçues · ${it.stored} stockées" },
                            { "Erreur : ${it.message ?: "synchro impossible"}" }
                        )
                        reload++
                        onDataChanged()
                    }
                }) { Text("Récupérer 24 h · 6 min") }
                OutlinedButton(onClick = {
                    credentialStore.save(credential)
                    scope.launch {
                        status = "Récupération horaire…"
                        val result = withContext(Dispatchers.IO) { runCatching { client.syncHourly(bounds.first, bounds.last) } }
                        status = result.fold(
                            { "${it.label} : ${it.received} reçues · ${it.stored} stockées" },
                            { "Erreur : ${it.message ?: "archive impossible"}" }
                        )
                        reload++
                        onDataChanged()
                    }
                }) { Text("Horaire de la période") }
            }
            if (status.isNotBlank()) Text(status, style = MaterialTheme.typography.bodySmall)

            LyonMiniChart(
                points = points,
                selectedTimestamp = selected,
                visualPrefs = styleStore.load("lyon:${kind.dbKey}"),
                styleTick = lyonStyleTick,
                onTap = { selected = it },
                onDoubleTap = {
                    selected = it
                    if (kind == LyonSeriesKind.RECONSTRUCTED) editTimestamp = it
                }
            )

            selected?.let { ts ->
                val nearest = points.minByOrNull { abs(it.timestamp - ts) }
                Text(
                    nearest?.let { "${formatLyonTime(it.timestamp)} · ${String.format(Locale.FRANCE, "%.1f °C · %.0f %%", it.temperature, it.humidity)}" }
                        ?: "Aucune valeur à cet instant",
                    fontWeight = FontWeight.SemiBold
                )
            }

            TextButton(onClick = {
                onStyleEdit("lyon:${kind.dbKey}", "Lyon · ${kind.label}")
            }) { Text("Personnaliser cette courbe") }

            HorizontalDivider()
            Text("Journal de reconstruction", fontWeight = FontWeight.Bold)
            if (kind != LyonSeriesKind.RECONSTRUCTED) {
                Text("Le journal s’applique à la vue Reconstruit.", style = MaterialTheme.typography.bodySmall)
            } else if (decisions.isEmpty()) {
                Text("Aucune correction/reconstruction sur cette période.", style = MaterialTheme.typography.bodySmall)
            } else {
                decisions.takeLast(160).forEach { d ->
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = if (d.manual) MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.45f)
                            else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                        )
                    ) {
                        Column(Modifier.fillMaxWidth().padding(9.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Row(Modifier.fillMaxWidth()) {
                                Text(formatLyonTime(d.timestamp), Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                                Text(if (d.manual) "MANUEL" else "AUTO", style = MaterialTheme.typography.labelSmall)
                            }
                            Text(d.state, style = MaterialTheme.typography.labelMedium)
                            Text(d.reason1, style = MaterialTheme.typography.bodySmall)
                            d.reason2?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                        }
                    }
                }
            }
            Spacer(Modifier.height(30.dp))
        }
    }

    editTimestamp?.let { ts ->
        val current = points.minByOrNull { abs(it.timestamp - ts) }
        LyonOverrideDialog(
            timestamp = ts,
            initialTemperature = current?.temperature,
            initialHumidity = current?.humidity,
            onDismiss = { editTimestamp = null },
            onSave = { t, h, note ->
                scope.launch {
                    withContext(Dispatchers.IO) { store.saveOverride(ts, t, h, note) }
                    editTimestamp = null
                    reload++
                    onDataChanged()
                }
            },
            onReset = {
                scope.launch {
                    withContext(Dispatchers.IO) { store.deleteOverride(ts) }
                    editTimestamp = null
                    reload++
                    onDataChanged()
                }
            }
        )
    }
}

@Composable
private fun LyonMiniChart(
    points: List<LyonLabPoint>,
    selectedTimestamp: Long?,
    visualPrefs: CurveVisualPrefs,
    styleTick: Long,
    onTap: (Long) -> Unit,
    onDoubleTap: (Long) -> Unit
) {
    val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f)
    val line = resolveCurveColor(MaterialTheme.colorScheme.primary, visualPrefs, styleTick)
        ?: Color.Transparent
    val aura = resolveAuraColor(visualPrefs, styleTick)
    val select = MaterialTheme.colorScheme.tertiary
    if (points.size < 2) {
        Box(Modifier.fillMaxWidth().height(220.dp).background(surface, RoundedCornerShape(14.dp)), contentAlignment = Alignment.Center) {
            Text("Pas encore de données pour cette vue")
        }
        return
    }
    val from = points.first().timestamp
    val to = points.last().timestamp
    val span = (to - from).coerceAtLeast(1L)
    val minT = points.minOf { it.temperature }
    val maxT = points.maxOf { it.temperature }
    val range = (maxT - minT).coerceAtLeast(1.0)
    Canvas(
        Modifier.fillMaxWidth().height(250.dp).background(surface, RoundedCornerShape(14.dp))
            .pointerInput(from, to, points.size) {
                detectTapGestures(
                    onTap = { p -> onTap(from + (span * (p.x / size.width).coerceIn(0f, 1f)).toLong()) },
                    onDoubleTap = { p -> onDoubleTap(from + (span * (p.x / size.width).coerceIn(0f, 1f)).toLong()) }
                )
            }
    ) {
        val path = Path()
        points.forEachIndexed { index, p ->
            val x = ((p.timestamp - from).toDouble() / span.toDouble()).toFloat() * size.width
            val y = size.height - (((p.temperature - minT) / range).toFloat() * size.height)
            if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        aura?.let { drawPath(path, it, style = Stroke(width = 10.dp.toPx())) }
        drawPath(path, line, style = Stroke(width = 2.5.dp.toPx()))
        selectedTimestamp?.takeIf { it in from..to }?.let { ts ->
            val x = ((ts - from).toDouble() / span.toDouble()).toFloat() * size.width
            drawLine(select, Offset(x, 0f), Offset(x, size.height), 2.dp.toPx())
        }
    }
}

@Composable
private fun LyonOverrideDialog(
    timestamp: Long,
    initialTemperature: Double?,
    initialHumidity: Double?,
    onDismiss: () -> Unit,
    onSave: (Double, Double, String) -> Unit,
    onReset: () -> Unit
) {
    var temp by remember(timestamp) { mutableStateOf(initialTemperature?.let { String.format(Locale.ROOT, "%.2f", it) }.orEmpty()) }
    var hum by remember(timestamp) { mutableStateOf(initialHumidity?.let { String.format(Locale.ROOT, "%.1f", it) }.orEmpty()) }
    var note by remember(timestamp) { mutableStateOf("") }
    var error by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Correction Lyon · ${formatLyonTime(timestamp)}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
                Text("La correction ne modifie jamais les données officielles.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(temp, { temp = it; error = false }, label = { Text("Température °C") }, isError = error, singleLine = true)
                OutlinedTextField(hum, { hum = it; error = false }, label = { Text("Humidité %") }, isError = error, singleLine = true)
                OutlinedTextField(note, { note = it }, label = { Text("Note facultative") })
                TextButton(onClick = onReset) { Text("Revenir à Auto") }
            }
        },
        confirmButton = {
            Button(onClick = {
                val t = temp.replace(',', '.').toDoubleOrNull()
                val h = hum.replace(',', '.').toDoubleOrNull()
                if (t == null || h == null || t !in -60.0..65.0 || h !in 0.0..100.0) error = true
                else onSave(t, h, note)
            }) { Text("Enregistrer") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
}

private fun formatLyonTime(epoch: Long): String = Instant.ofEpochMilli(epoch)
    .atZone(ZoneId.systemDefault())
    .format(DateTimeFormatter.ofPattern("dd/MM HH:mm", Locale.FRANCE))


fun sensorStatsFromSamples(sensorId: Long, points: List<SamplePoint>): SensorStats? {
    if (points.isEmpty()) return null
    val latest = points.maxByOrNull { it.timestamp }
    return SensorStats(
        sensorId = sensorId,
        count = points.size,
        tempMin = points.minOf { it.temperature },
        tempMax = points.maxOf { it.temperature },
        tempAvg = points.map { it.temperature }.average(),
        humidityMin = points.minOf { it.humidity },
        humidityMax = points.maxOf { it.humidity },
        humidityAvg = points.map { it.humidity }.average(),
        latest = latest
    )
}
