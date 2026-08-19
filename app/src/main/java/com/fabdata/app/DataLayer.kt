package com.fabdata.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.net.Uri
import android.provider.OpenableColumns
import java.io.BufferedReader
import java.io.InputStreamReader
import java.text.Normalizer
import java.time.LocalDateTime
import java.time.ZoneId
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
    val sensorId: Long?
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

class FabDataDb(context: Context) : SQLiteOpenHelper(context, "fabdata.db", null, 1) {
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
                created_at INTEGER NOT NULL,
                FOREIGN KEY(sensor_id) REFERENCES sensors(id) ON DELETE SET NULL
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX idx_annotations_time ON annotations(timestamp)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

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
                return Sensor(
                    id = c.getLong(0), stableKey = c.getString(1), name = c.getString(2),
                    room = c.getString(3), colorIndex = c.getInt(4), latestTimestamp = latestTimestamp(c.getLong(0))
                )
            }
        }
        val nextColor = readableDatabase.rawQuery("SELECT COUNT(*) FROM sensors", null).use { c ->
            c.moveToFirst(); c.getInt(0) % 8
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
            FROM sensors s LEFT JOIN samples p ON p.sensor_id = s.id
            GROUP BY s.id ORDER BY s.id
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

    fun querySamples(sensorId: Long, from: Long, to: Long, maxPoints: Int = 2600): List<SamplePoint> {
        val count = readableDatabase.rawQuery(
            "SELECT COUNT(*) FROM samples WHERE sensor_id = ? AND timestamp BETWEEN ? AND ?",
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c -> c.moveToFirst(); c.getInt(0) }
        if (count == 0) return emptyList()
        val stride = ceil(count.toDouble() / maxPoints.coerceAtLeast(1)).toInt().coerceAtLeast(1)
        val out = ArrayList<SamplePoint>(minOf(count, maxPoints + 2))
        var index = 0
        var last: SamplePoint? = null
        readableDatabase.rawQuery(
            "SELECT timestamp, temperature, humidity FROM samples WHERE sensor_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val p = SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2))
                last = p
                if (index % stride == 0) out += p
                index++
            }
        }
        if (last != null && (out.isEmpty() || out.last().timestamp != last!!.timestamp)) out += last!!
        return out
    }

    fun stats(sensorId: Long, from: Long, to: Long): SensorStats? {
        readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(temperature), MAX(temperature), AVG(temperature),
                   MIN(humidity), MAX(humidity), AVG(humidity)
            FROM samples WHERE sensor_id = ? AND timestamp BETWEEN ? AND ?
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

    fun addAnnotation(timestamp: Long, title: String, note: String, sensorId: Long?) {
        val values = ContentValues().apply {
            put("timestamp", timestamp)
            put("title", title.trim().ifBlank { "Annotation" })
            put("note", note.trim())
            if (sensorId == null) putNull("sensor_id") else put("sensor_id", sensorId)
            put("created_at", System.currentTimeMillis())
        }
        writableDatabase.insertOrThrow("annotations", null, values)
    }

    fun annotations(from: Long, to: Long): List<AnnotationItem> {
        val out = mutableListOf<AnnotationItem>()
        readableDatabase.rawQuery(
            "SELECT id, timestamp, title, note, sensor_id FROM annotations WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
            arrayOf(from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += AnnotationItem(c.getLong(0), c.getLong(1), c.getString(2), c.getString(3), if (c.isNull(4)) null else c.getLong(4))
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

    private fun latestTimestamp(sensorId: Long): Long? {
        readableDatabase.rawQuery("SELECT MAX(timestamp) FROM samples WHERE sensor_id = ?", arrayOf(sensorId.toString())).use { c ->
            return if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null
        }
    }
}

class CsvImporter(private val context: Context, private val db: FabDataDb) {
    private val timeFormatters = listOf(
        DateTimeFormatter.ofPattern("yyyy/MM/dd HH:mm"),
        DateTimeFormatter.ofPattern("yyyy/MM/dd HH:mm:ss"),
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"),
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"),
        DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm"),
        DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm:ss"),
        DateTimeFormatter.ISO_LOCAL_DATE_TIME
    )

    fun import(uri: Uri): ImportResult {
        val sourceName = fileName(uri) ?: "import.csv"
        val sensorBase = sourceName.substringBefore("_Exporter", sourceName.substringBeforeLast('.'))
            .replace('_', ' ').trim().ifBlank { "Thermo-hygromètre" }
        val stableKey = normalize(sensorBase)
        val sensor = db.getOrCreateSensor(stableKey, sensorBase)

        var added = 0
        var duplicates = 0
        var invalid = 0
        var firstTs: Long? = null
        var lastTs: Long? = null

        context.contentResolver.openInputStream(uri)?.use { input ->
            BufferedReader(InputStreamReader(input, Charsets.UTF_8)).use { reader ->
                val headerLine = reader.readLine() ?: error("Fichier CSV vide")
                val delimiter = detectDelimiter(headerLine)
                val headers = splitCsv(headerLine, delimiter).map(::normalize)
                val timeIndex = findHeader(headers, listOf("temps", "time", "timestamp", "date", "datetime"))
                val tempIndex = findHeader(headers, listOf("temperaturecelsius", "temperature", "temp", "tempc"))
                val humidityIndex = findHeader(headers, listOf("humiditerelativepourcentage", "humidite", "humidity", "rh", "pourcentage"))
                if (timeIndex < 0 || tempIndex < 0 || humidityIndex < 0) {
                    error("Colonnes Temps / Température / Humidité introuvables")
                }

                db.inTransaction {
                    reader.forEachLine { line ->
                        if (line.isBlank()) return@forEachLine
                        try {
                            val fields = splitCsv(line, delimiter)
                            val ts = parseTime(fields.getOrNull(timeIndex)?.trim().orEmpty())
                            val temp = parseNumber(fields.getOrNull(tempIndex).orEmpty())
                            val hum = parseNumber(fields.getOrNull(humidityIndex).orEmpty())
                            if (ts == null || temp == null || hum == null) {
                                invalid++
                            } else {
                                firstTs = firstTs?.let { minOf(it, ts) } ?: ts
                                lastTs = lastTs?.let { maxOf(it, ts) } ?: ts
                                if (db.insertSample(sensor.id, ts, temp, hum)) added++ else duplicates++
                            }
                        } catch (_: Exception) {
                            invalid++
                        }
                    }
                }
            }
        } ?: error("Impossible d’ouvrir le fichier")

        return ImportResult(sourceName, sensor.name, added, duplicates, invalid, firstTs, lastTs)
    }

    private fun findHeader(headers: List<String>, aliases: List<String>): Int {
        val normalizedAliases = aliases.map(::normalize)
        return headers.indexOfFirst { h -> normalizedAliases.any { a -> h == a || h.contains(a) } }
    }

    private fun parseTime(raw: String): Long? {
        for (formatter in timeFormatters) {
            try {
                return LocalDateTime.parse(raw, formatter).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
            } catch (_: DateTimeParseException) {
            }
        }
        return null
    }

    private fun parseNumber(raw: String): Double? = raw.trim().replace(',', '.').toDoubleOrNull()

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
                ch == '"' && quoted && i + 1 < line.length && line[i + 1] == '"' -> {
                    cell.append('"'); i++
                }
                ch == '"' -> quoted = !quoted
                ch == delimiter && !quoted -> {
                    out += cell.toString(); cell.clear()
                }
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
