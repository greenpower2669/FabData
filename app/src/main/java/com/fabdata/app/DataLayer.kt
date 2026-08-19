package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.net.Uri
import android.provider.OpenableColumns
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.text.Normalizer
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale
import kotlin.math.ceil

data class Sensor(
    val id: Long,
    val stableKey: String,
    val name: String,
    val room: String,
    val colorIndex: Int,
    val latestTimestamp: Long?
)

data class SamplePoint(
    val sensorId: Long,
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double
)

data class AnnotationItem(
    val id: Long,
    val timestamp: Long,
    val title: String,
    val note: String,
    val sensorId: Long?,
    val roomName: String?,
    val type: String?,
    val updatedAt: Long
)

data class SensorStats(
    val sensorId: Long,
    val count: Int,
    val tempMin: Double,
    val tempMax: Double,
    val tempAvg: Double,
    val humidityMin: Double,
    val humidityMax: Double,
    val humidityAvg: Double,
    val latest: SamplePoint?
)

data class ImportResult(
    val sourceName: String,
    val sensorName: String,
    val added: Int,
    val duplicates: Int,
    val invalid: Int,
    val firstTimestamp: Long?,
    val lastTimestamp: Long?
)

class FabDataDb(context: Context) : SQLiteOpenHelper(context, "fabdata.db", null, 2) {
    private val appContext = context.applicationContext

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE sensors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stable_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                room TEXT NOT NULL,
                color_index INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
            """.trimIndent()
        )
        db.execSQL(
            """
            CREATE TABLE samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL NOT NULL,
                FOREIGN KEY(sensor_id) REFERENCES sensors(id) ON DELETE CASCADE,
                UNIQUE(sensor_id, timestamp) ON CONFLICT IGNORE
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX idx_samples_sensor_time ON samples(sensor_id, timestamp)")
        db.execSQL(
            """
            CREATE TABLE annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                title TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                sensor_id INTEGER,
                room_name TEXT,
                type TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(sensor_id) REFERENCES sensors(id) ON DELETE SET NULL
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX idx_annotations_time ON annotations(timestamp)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE annotations ADD COLUMN room_name TEXT")
            db.execSQL("ALTER TABLE annotations ADD COLUMN type TEXT")
            db.execSQL("ALTER TABLE annotations ADD COLUMN updated_at INTEGER NOT NULL DEFAULT 0")
            db.execSQL("UPDATE annotations SET updated_at = created_at WHERE updated_at = 0")
        }
    }

    override fun onConfigure(db: SQLiteDatabase) {
        super.onConfigure(db)
        db.setForeignKeyConstraintsEnabled(true)
    }

    fun getOrCreateSensor(stableKey: String, displayName: String): Sensor {
        readableDatabase.rawQuery(
            "SELECT id, stable_key, name, room, color_index FROM sensors WHERE stable_key = ?",
            arrayOf(stableKey)
        ).use { c ->
            if (c.moveToFirst()) {
                val id = c.getLong(0)
                return Sensor(
                    id = id,
                    stableKey = c.getString(1),
                    name = c.getString(2),
                    room = c.getString(3),
                    colorIndex = c.getInt(4),
                    latestTimestamp = latestTimestamp(id)
                )
            }
        }

        val nextColor = readableDatabase.rawQuery("SELECT COUNT(*) FROM sensors", null).use { c ->
            c.moveToFirst()
            c.getInt(0) % 8
        }
        val values = ContentValues().apply {
            put("stable_key", stableKey)
            put("name", displayName)
            put("room", displayName)
            put("color_index", nextColor)
            put("created_at", System.currentTimeMillis())
        }
        val id = writableDatabase.insertOrThrow("sensors", null, values)
        return Sensor(id, stableKey, displayName, displayName, nextColor, null)
    }

    fun insertSample(sensorId: Long, timestamp: Long, temperature: Double, humidity: Double): Boolean {
        val values = ContentValues().apply {
            put("sensor_id", sensorId)
            put("timestamp", timestamp)
            put("temperature", temperature)
            put("humidity", humidity)
        }
        return writableDatabase.insertWithOnConflict(
            "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
        ) != -1L
    }

    fun inTransaction(block: () -> Unit) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            block()
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun sensors(): List<Sensor> {
        val out = mutableListOf<Sensor>()
        readableDatabase.rawQuery(
            """
            SELECT s.id, s.stable_key, s.name, s.room, s.color_index, MAX(p.timestamp)
            FROM sensors s
            JOIN samples p ON p.sensor_id = s.id
            GROUP BY s.id
            ORDER BY s.id
            """.trimIndent(), null
        ).use { c ->
            while (c.moveToNext()) {
                out += Sensor(
                    c.getLong(0), c.getString(1), c.getString(2), c.getString(3), c.getInt(4),
                    if (c.isNull(5)) null else c.getLong(5)
                )
            }
        }
        return out
    }

    fun updateSensor(id: Long, name: String, room: String, colorIndex: Int) {
        val values = ContentValues().apply {
            put("name", name.trim().ifBlank { "Capteur" })
            put("room", room.trim().ifBlank { name.trim().ifBlank { "Pièce" } })
            put("color_index", colorIndex.coerceIn(0, 7))
        }
        writableDatabase.update("sensors", values, "id = ?", arrayOf(id.toString()))
    }

    fun deleteSensor(id: Long) {
        writableDatabase.delete("sensors", "id = ?", arrayOf(id.toString()))
    }

    fun globalTimeBounds(): LongRange? {
        readableDatabase.rawQuery("SELECT MIN(timestamp), MAX(timestamp) FROM samples", null).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    fun querySamples(sensorId: Long, from: Long, to: Long, maxPoints: Int = 5000): List<SamplePoint> {
        val all = ArrayList<SamplePoint>()
        readableDatabase.rawQuery(
            "SELECT timestamp, temperature, humidity FROM samples WHERE sensor_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                all += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2))
            }
        }
        if (all.size <= maxPoints) return all

        val targetBuckets = (maxPoints / 6).coerceAtLeast(1)
        val bucketSize = ceil(all.size.toDouble() / targetBuckets.toDouble()).toInt().coerceAtLeast(1)
        val out = ArrayList<SamplePoint>(maxPoints + 16)
        var start = 0
        while (start < all.size) {
            val end = minOf(all.size, start + bucketSize)
            val bucket = all.subList(start, end)
            val selected = linkedSetOf<SamplePoint>()
            selected += bucket.first()
            selected += bucket.minByOrNull { it.temperature } ?: bucket.first()
            selected += bucket.maxByOrNull { it.temperature } ?: bucket.first()
            selected += bucket.minByOrNull { it.humidity } ?: bucket.first()
            selected += bucket.maxByOrNull { it.humidity } ?: bucket.first()
            selected += bucket.last()
            out += selected.sortedBy { it.timestamp }
            start = end
        }
        return out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }

    fun stats(sensorId: Long, from: Long, to: Long): SensorStats? {
        readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(temperature), MAX(temperature), AVG(temperature),
                   MIN(humidity), MAX(humidity), AVG(humidity)
            FROM samples
            WHERE sensor_id = ? AND timestamp BETWEEN ? AND ?
            """.trimIndent(),
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c ->
            if (!c.moveToFirst() || c.getInt(0) == 0) return null
            val latest = readableDatabase.rawQuery(
                "SELECT timestamp, temperature, humidity FROM samples WHERE sensor_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT 1",
                arrayOf(sensorId.toString(), from.toString(), to.toString())
            ).use { lc ->
                if (lc.moveToFirst()) SamplePoint(sensorId, lc.getLong(0), lc.getDouble(1), lc.getDouble(2)) else null
            }
            return SensorStats(
                sensorId, c.getInt(0), c.getDouble(1), c.getDouble(2), c.getDouble(3),
                c.getDouble(4), c.getDouble(5), c.getDouble(6), latest
            )
        }
    }

    fun addAnnotation(timestamp: Long, title: String, note: String, sensorId: Long?, roomName: String?, type: String?): Long {
        val now = System.currentTimeMillis()
        val values = ContentValues().apply {
            put("timestamp", timestamp)
            put("title", title.trim().ifBlank { "Événement" })
            put("note", note.trim())
            if (sensorId == null) putNull("sensor_id") else put("sensor_id", sensorId)
            if (roomName.isNullOrBlank()) putNull("room_name") else put("room_name", roomName.trim())
            if (type.isNullOrBlank()) putNull("type") else put("type", type.trim())
            put("created_at", now)
            put("updated_at", now)
        }
        return writableDatabase.insertOrThrow("annotations", null, values)
    }

    fun updateAnnotation(id: Long, timestamp: Long, title: String, note: String, sensorId: Long?, roomName: String?, type: String?) {
        val values = ContentValues().apply {
            put("timestamp", timestamp)
            put("title", title.trim().ifBlank { "Événement" })
            put("note", note.trim())
            if (sensorId == null) putNull("sensor_id") else put("sensor_id", sensorId)
            if (roomName.isNullOrBlank()) putNull("room_name") else put("room_name", roomName.trim())
            if (type.isNullOrBlank()) putNull("type") else put("type", type.trim())
            put("updated_at", System.currentTimeMillis())
        }
        writableDatabase.update("annotations", values, "id = ?", arrayOf(id.toString()))
    }

    fun annotations(from: Long, to: Long): List<AnnotationItem> {
        val out = mutableListOf<AnnotationItem>()
        readableDatabase.rawQuery(
            "SELECT id, timestamp, title, note, sensor_id, room_name, type, updated_at FROM annotations WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
            arrayOf(from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += AnnotationItem(
                    id = c.getLong(0), timestamp = c.getLong(1), title = c.getString(2), note = c.getString(3),
                    sensorId = if (c.isNull(4)) null else c.getLong(4),
                    roomName = if (c.isNull(5)) null else c.getString(5),
                    type = if (c.isNull(6)) null else c.getString(6),
                    updatedAt = if (c.isNull(7)) 0L else c.getLong(7)
                )
            }
        }
        return out
    }

    fun deleteAnnotation(id: Long) {
        writableDatabase.delete("annotations", "id = ?", arrayOf(id.toString()))
    }

    fun clearAll() {
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.delete("annotations", null, null)
            db.delete("samples", null, null)
            db.delete("sensors", null, null)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun exportAllCsv(uri: Uri): Int {
        var count = 0
        val formatter = DateTimeFormatter.ofPattern("yyyy/MM/dd HH:mm:ss")
        val output = appContext.contentResolver.openOutputStream(uri, "wt") ?: error("Impossible de créer le fichier d’export")
        OutputStreamWriter(output, Charsets.UTF_8).buffered().use { writer ->
            writer.write("Capteur_ID,Capteur,Piece,Temps,Temperature_Celsius,Humidite_relative_Pourcentage\n")
            readableDatabase.rawQuery(
                """
                SELECT s.stable_key, s.name, s.room, p.timestamp, p.temperature, p.humidity
                FROM samples p JOIN sensors s ON s.id = p.sensor_id
                ORDER BY p.timestamp, s.id
                """.trimIndent(), null
            ).use { c ->
                while (c.moveToNext()) {
                    val ts = Instant.ofEpochMilli(c.getLong(3)).atZone(ZoneId.systemDefault()).format(formatter)
                    val row = listOf(c.getString(0), c.getString(1), c.getString(2), ts, c.getDouble(4).toString(), c.getDouble(5).toString())
                        .joinToString(",") { csvEscape(it) }
                    writer.write(row)
                    writer.write("\n")
                    count++
                }
            }
        }
        return count
    }

    private fun latestTimestamp(sensorId: Long): Long? {
        readableDatabase.rawQuery("SELECT MAX(timestamp) FROM samples WHERE sensor_id = ?", arrayOf(sensorId.toString())).use { c ->
            return if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null
        }
    }

    private fun csvEscape(value: String): String {
        if (value.none { it == ',' || it == '"' || it == '\n' || it == '\r' }) return value
        return "\"${value.replace("\"", "\"\"")}\""
    }
}

class CsvImporter(private val context: Context, private val db: FabDataDb) {
    private data class ParsedPoint(val timestamp: Long, val temperature: Double, val humidity: Double)

    private val genericLocalFormatters = listOf(
        "uuuu/M/d H:m", "uuuu/M/d H:m:s", "uuuu/M/d H:m:s.SSS",
        "uuuu-M-d H:m", "uuuu-M-d H:m:s", "uuuu-M-d H:m:s.SSS",
        "uuuu.M.d H:m", "uuuu.M.d H:m:s",
        "d/M/uuuu H:m", "d/M/uuuu H:m:s", "d-M-uuuu H:m", "d-M-uuuu H:m:s",
        "d.M.uuuu H:m", "d.M.uuuu H:m:s", "M/d/uuuu h:m a", "M/d/uuuu h:m:s a"
    ).map { DateTimeFormatter.ofPattern(it, Locale.ROOT) } + listOf(DateTimeFormatter.ISO_LOCAL_DATE_TIME)

    private val exactThermoTime = DateTimeFormatter.ofPattern("uuuu/MM/dd HH:mm", Locale.ROOT)

    fun import(uri: Uri): ImportResult {
        val sourceName = fileName(uri) ?: "import.csv"
        val sensorBase = sourceName.substringBefore("_Exporter", sourceName.substringBeforeLast('.'))
            .replace('_', ' ').trim().ifBlank { "Thermo-hygromètre" }
        val stableKey = normalize(sensorBase)
        val parsed = mutableListOf<ParsedPoint>()
        var invalid = 0

        context.contentResolver.openInputStream(uri)?.use { input ->
            BufferedReader(InputStreamReader(input, Charsets.UTF_8)).use { reader ->
                val headerLine = reader.readLine()?.removePrefix("\uFEFF") ?: error("Fichier CSV vide")
                val delimiter = detectDelimiter(headerLine)
                val headers = splitCsv(headerLine, delimiter).map(::normalize)
                val exactKnownFormat = delimiter == ',' && headers.size >= 3 &&
                    headers[0] == "temps" && headers[1] == "temperaturecelsius" && headers[2] == "humiditerelativepourcentage"

                val rows = reader.lineSequence().map { it.trimEnd('\r') }.filter { it.isNotBlank() }.toList()
                if (exactKnownFormat && rows.isNotEmpty()) {
                    val firstFields = splitCsv(rows.first(), delimiter)
                    val anchor = parseExactThermoTime(firstFields.getOrNull(0).orEmpty())
                    val secondAnchor = rows.getOrNull(1)?.let { parseExactThermoTime(splitCsv(it, delimiter).getOrNull(0).orEmpty()) }
                    if (anchor != null) {
                        val stepMs = when {
                            secondAnchor == null -> -60_000L
                            secondAnchor < anchor -> -60_000L
                            secondAnchor > anchor -> 60_000L
                            else -> -60_000L
                        }
                        rows.forEachIndexed { index, line ->
                            try {
                                val fields = splitCsv(line, delimiter)
                                val temp = parseNumber(fields.getOrNull(1).orEmpty())
                                val hum = parseNumber(fields.getOrNull(2).orEmpty())
                                if (temp == null || hum == null || temp !in -100.0..150.0 || hum !in 0.0..100.0) {
                                    invalid++
                                } else {
                                    parsed += ParsedPoint(anchor + index.toLong() * stepMs, temp, hum)
                                }
                            } catch (_: Exception) {
                                invalid++
                            }
                        }
                    } else {
                        invalid += parseGenericRows(rows, delimiter, headers, parsed)
                    }
                } else {
                    invalid += parseGenericRows(rows, delimiter, headers, parsed)
                }
            }
        } ?: error("Impossible d’ouvrir le fichier")

        if (parsed.isEmpty()) return ImportResult(sourceName, sensorBase, 0, 0, invalid, null, null)

        val sensor = db.getOrCreateSensor(stableKey, sensorBase)
        var added = 0
        var duplicates = 0
        var firstTs: Long? = null
        var lastTs: Long? = null
        db.inTransaction {
            parsed.forEach { point ->
                firstTs = firstTs?.let { minOf(it, point.timestamp) } ?: point.timestamp
                lastTs = lastTs?.let { maxOf(it, point.timestamp) } ?: point.timestamp
                if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) added++ else duplicates++
            }
        }
        return ImportResult(sourceName, sensor.name, added, duplicates, invalid, firstTs, lastTs)
    }

    private fun parseGenericRows(rows: List<String>, delimiter: Char, headers: List<String>, target: MutableList<ParsedPoint>): Int {
        val timeIndex = findHeader(headers, listOf("temps", "heure", "time", "timestamp", "date", "datetime"))
        val tempIndex = findHeader(headers, listOf("temperaturecelsius", "temperature", "temp", "tempc", "celsius"))
        val humidityIndex = findHeader(headers, listOf("humiditerelativepourcentage", "humiditerelative", "humidite", "humidity", "relativehumidity", "rh", "hygrometrie"))
        if (timeIndex < 0 || tempIndex < 0 || humidityIndex < 0) error("Colonnes Temps / Température / Humidité introuvables")
        var invalid = 0
        rows.forEach { line ->
            try {
                val fields = splitCsv(line, delimiter)
                val ts = parseGenericTime(fields.getOrNull(timeIndex).orEmpty())
                val temp = parseNumber(fields.getOrNull(tempIndex).orEmpty())
                val hum = parseNumber(fields.getOrNull(humidityIndex).orEmpty())
                if (ts == null || temp == null || hum == null || temp !in -100.0..150.0 || hum !in 0.0..100.0) invalid++
                else target += ParsedPoint(ts, temp, hum)
            } catch (_: Exception) {
                invalid++
            }
        }
        return invalid
    }

    private fun parseExactThermoTime(raw: String): Long? = try {
        LocalDateTime.parse(raw.trim().trim('"'), exactThermoTime).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
    } catch (_: Exception) { null }

    private fun findHeader(headers: List<String>, aliases: List<String>): Int {
        val normalizedAliases = aliases.map(::normalize)
        return headers.indexOfFirst { h -> normalizedAliases.any { a -> h == a || h.contains(a) } }
    }

    private fun parseGenericTime(rawInput: String): Long? {
        var raw = rawInput.trim().trim('"').replace('\u00A0', ' ').removePrefix("\uFEFF")
        if (raw.isBlank()) return null
        raw = raw.replace(Regex("\\s+"), " ")
        raw.toLongOrNull()?.let { n ->
            when {
                n in 946684800L..4102444800L -> return n * 1000L
                n in 946684800000L..4102444800000L -> return n
            }
        }
        try { return Instant.parse(raw).toEpochMilli() } catch (_: Exception) {}
        try { return OffsetDateTime.parse(raw, DateTimeFormatter.ISO_OFFSET_DATE_TIME).toInstant().toEpochMilli() } catch (_: Exception) {}
        try { return ZonedDateTime.parse(raw, DateTimeFormatter.ISO_ZONED_DATE_TIME).toInstant().toEpochMilli() } catch (_: Exception) {}
        for (formatter in genericLocalFormatters) {
            try {
                return LocalDateTime.parse(raw, formatter).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
            } catch (_: DateTimeParseException) {}
        }
        val ymd = Regex("(\\d{4})[./-](\\d{1,2})[./-](\\d{1,2})[^0-9]+(\\d{1,2}):(\\d{1,2})(?::(\\d{1,2}))?").find(raw)
        if (ymd != null) return buildEpoch(
            ymd.groupValues[1].toIntOrNull(), ymd.groupValues[2].toIntOrNull(), ymd.groupValues[3].toIntOrNull(),
            ymd.groupValues[4].toIntOrNull(), ymd.groupValues[5].toIntOrNull(), ymd.groupValues[6].toIntOrNull() ?: 0
        )
        val dmy = Regex("(\\d{1,2})[./-](\\d{1,2})[./-](\\d{4})[^0-9]+(\\d{1,2}):(\\d{1,2})(?::(\\d{1,2}))?").find(raw)
        if (dmy != null) return buildEpoch(
            dmy.groupValues[3].toIntOrNull(), dmy.groupValues[2].toIntOrNull(), dmy.groupValues[1].toIntOrNull(),
            dmy.groupValues[4].toIntOrNull(), dmy.groupValues[5].toIntOrNull(), dmy.groupValues[6].toIntOrNull() ?: 0
        )
        return null
    }

    private fun buildEpoch(year: Int?, month: Int?, day: Int?, hour: Int?, minute: Int?, second: Int?): Long? {
        if (year == null || month == null || day == null || hour == null || minute == null || second == null) return null
        return try {
            LocalDateTime.of(year, month, day, hour, minute, second).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
        } catch (_: Exception) { null }
    }

    private fun parseNumber(rawInput: String): Double? {
        val raw = rawInput.trim().trim('"').replace('\u00A0', ' ')
        if (raw.isBlank()) return null
        raw.replace(',', '.').toDoubleOrNull()?.let { return it }
        val match = Regex("[-+]?\\d+(?:[.,]\\d+)?").find(raw) ?: return null
        return match.value.replace(',', '.').toDoubleOrNull()
    }

    private fun fileName(uri: Uri): String? {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) return c.getString(0)
        }
        return uri.lastPathSegment
    }

    private fun detectDelimiter(header: String): Char {
        val options = listOf(',', ';', '\t')
        return options.maxByOrNull { d -> header.count { it == d } } ?: ','
    }

    private fun splitCsv(line: String, delimiter: Char): List<String> {
        val out = mutableListOf<String>()
        val cell = StringBuilder()
        var quoted = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            when {
                ch == '"' && quoted && i + 1 < line.length && line[i + 1] == '"' -> { cell.append('"'); i++ }
                ch == '"' -> quoted = !quoted
                ch == delimiter && !quoted -> { out += cell.toString(); cell.clear() }
                else -> cell.append(ch)
            }
            i++
        }
        out += cell.toString()
        return out
    }

    private fun normalize(input: String): String {
        val n = Normalizer.normalize(input.lowercase(Locale.ROOT), Normalizer.Form.NFD)
        return n.replace("\\p{Mn}+".toRegex(), "").replace("[^a-z0-9]".toRegex(), "")
    }
}
