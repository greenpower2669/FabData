package com.fabdata.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

/** Configuration locale d'une sonde distante lue par HTTP GET. */
data class RemoteSensorConfig(
    val id: String,
    val name: String,
    val url: String,
    val temperatureKey: String = "temperature",
    val humidityKey: String = "humidity",
    val timestampKey: String = "timestamp"
) {
    val stableKey: String get() = "http-get-$id"
}

data class RemoteSensorSyncResult(
    val sensorId: Long,
    val added: Boolean,
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double
)

/**
 * Les connexions de sondes sont volontairement stockées séparément des mesures.
 * Le format de sauvegarde FabData v1 reste donc inchangé ; les mesures HTTP sont
 * sauvegardées/restaurées comme des SAMPLE ordinaires.
 */
class RemoteSensorStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_remote_sensors", Context.MODE_PRIVATE)

    fun load(): List<RemoteSensorConfig> {
        val raw = prefs.getString("configs", "[]") ?: "[]"
        return runCatching {
            val arr = JSONArray(raw)
            buildList {
                for (i in 0 until arr.length()) {
                    val o = arr.getJSONObject(i)
                    add(
                        RemoteSensorConfig(
                            id = o.optString("id").ifBlank { UUID.randomUUID().toString() },
                            name = o.optString("name", "Sonde HTTP"),
                            url = o.optString("url"),
                            temperatureKey = o.optString("temperatureKey", "temperature"),
                            humidityKey = o.optString("humidityKey", "humidity"),
                            timestampKey = o.optString("timestampKey", "timestamp")
                        )
                    )
                }
            }
        }.getOrDefault(emptyList())
    }

    fun add(name: String, url: String, temperatureKey: String, humidityKey: String, timestampKey: String): RemoteSensorConfig {
        val config = RemoteSensorConfig(
            id = UUID.randomUUID().toString(),
            name = name.trim().ifBlank { "Sonde HTTP" },
            url = url.trim(),
            temperatureKey = temperatureKey.trim().ifBlank { "temperature" },
            humidityKey = humidityKey.trim().ifBlank { "humidity" },
            timestampKey = timestampKey.trim().ifBlank { "timestamp" }
        )
        val all = load().toMutableList().apply { add(config) }
        save(all)
        return config
    }

    fun delete(id: String) {
        save(load().filterNot { it.id == id })
    }

    private fun save(configs: List<RemoteSensorConfig>) {
        val arr = JSONArray()
        configs.forEach { c ->
            arr.put(
                JSONObject()
                    .put("id", c.id)
                    .put("name", c.name)
                    .put("url", c.url)
                    .put("temperatureKey", c.temperatureKey)
                    .put("humidityKey", c.humidityKey)
                    .put("timestampKey", c.timestampKey)
            )
        }
        prefs.edit().putString("configs", arr.toString()).apply()
    }
}

/** Une lecture GET = une mesure FabData. */
class RemoteSensorHttpSync(private val db: FabDataDb) {
    fun sync(config: RemoteSensorConfig): RemoteSensorSyncResult {
        require(config.url.startsWith("http://") || config.url.startsWith("https://")) {
            "URL GET invalide"
        }

        val body = download(config.url)
        val values = parseBody(body)
        val temperature = findValue(values, config.temperatureKey)?.toDoubleValue()
            ?: error("Champ température '${config.temperatureKey}' absent")
        val humidity = findValue(values, config.humidityKey)?.toDoubleValue()
            ?: error("Champ humidité '${config.humidityKey}' absent")
        require(temperature in -100.0..150.0) { "Température hors plage : $temperature" }
        require(humidity in 0.0..100.0) { "Humidité hors plage : $humidity" }

        val timestamp = findValue(values, config.timestampKey)?.let(::parseTimestamp)
            ?: System.currentTimeMillis()
        val sensor = db.getOrCreateSensor(config.stableKey, config.name)
        val added = db.insertSample(sensor.id, timestamp, temperature, humidity)
        return RemoteSensorSyncResult(sensor.id, added, timestamp, temperature, humidity)
    }

    private fun download(url: String): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 12_000
            readTimeout = 12_000
            instanceFollowRedirects = true
            setRequestProperty("Accept", "application/json,text/plain,*/*")
            setRequestProperty("User-Agent", "FabData/0.8 Android HTTP sensor")
        }
        return try {
            val code = connection.responseCode
            if (code !in 200..299) error("HTTP $code")
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }

    /** Accepte JSON ou une réponse simple temperature=23.4&humidity=51. */
    private fun parseBody(body: String): Any {
        val trimmed = body.trim()
        if (trimmed.startsWith("{")) return JSONObject(trimmed)
        if (trimmed.startsWith("[")) {
            val arr = JSONArray(trimmed)
            if (arr.length() == 0) error("Réponse JSON vide")
            return arr.get(0)
        }

        val obj = JSONObject()
        trimmed.split('&', '\n', ';').forEach { pair ->
            val idx = pair.indexOf('=')
            if (idx > 0) {
                val key = decode(pair.substring(0, idx).trim())
                val value = decode(pair.substring(idx + 1).trim())
                obj.put(key, value)
            }
        }
        if (obj.length() == 0) error("Réponse GET non reconnue")
        return obj
    }

    /** Les clés pointées sont acceptées : data.temperature par exemple. */
    private fun findValue(root: Any, path: String): Any? {
        if (path.isBlank()) return null
        var current: Any? = root
        path.split('.').forEach { key ->
            current = when (val c = current) {
                is JSONObject -> if (c.has(key) && !c.isNull(key)) c.get(key) else return null
                else -> return null
            }
        }
        return current
    }

    private fun Any.toDoubleValue(): Double? = when (this) {
        is Number -> toDouble()
        is String -> replace(',', '.').trim().toDoubleOrNull()
        else -> null
    }

    private fun parseTimestamp(value: Any): Long? {
        return when (value) {
            is Number -> normalizeEpoch(value.toLong())
            is String -> {
                value.trim().toLongOrNull()?.let(::normalizeEpoch)
                    ?: runCatching { Instant.parse(value.trim()).toEpochMilli() }.getOrNull()
            }
            else -> null
        }
    }

    private fun normalizeEpoch(value: Long): Long = if (value in 1..9_999_999_999L) value * 1000L else value

    private fun decode(value: String): String =
        URLDecoder.decode(value, StandardCharsets.UTF_8.name())
}
