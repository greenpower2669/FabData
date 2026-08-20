package com.fabdata.app

import android.text.Html
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.LocalDate
import java.time.ZonedDateTime
import java.time.ZoneId
import java.util.Locale

/** Résultat d'une synchronisation de la sonde météo virtuelle Lyon. */
data class LyonWeatherSyncResult(
    val parsed: Int,
    val added: Int,
    val duplicates: Int,
    val date: LocalDate
)

data class LyonWeatherCompleteResult(
    val fromDate: LocalDate,
    val toDate: LocalDate,
    val daysRequested: Int,
    val daysDownloaded: Int,
    val daysAlreadyComplete: Int,
    val added: Int,
    val duplicates: Int
)

/**
 * Importe les observations horaires réellement affichées pour la station
 * Météo-France Lyon-Bron dans la base FabData.
 *
 * La sonde est volontairement enregistrée avec le même modèle Sensor/Sample
 * que les thermo-hygromètres physiques. Elle est donc automatiquement incluse
 * dans le format de sauvegarde FabData v1 et restaurée sans migration de schéma.
 */
class LyonWeatherSync(private val db: FabDataDb) {
    companion object {
        const val STABLE_KEY = "meteo-france-lyon-bron-mf69029001"
        const val DISPLAY_NAME = "Lyon"
        const val SOURCE_NAME = "Météo-France Lyon-Bron via Infoclimat"
        const val SOURCE_URL = "https://www.infoclimat.fr/observations-meteo/temps-reel/lyon-bron/07480.html"
        private val LYON_ZONE: ZoneId = ZoneId.of("Europe/Paris")
        private val MONTH_SLUGS = arrayOf(
            "janvier", "fevrier", "mars", "avril", "mai", "juin",
            "juillet", "aout", "septembre", "octobre", "novembre", "decembre"
        )
    }

    private data class WeatherPoint(
        val timestamp: Long,
        val temperature: Double,
        val humidity: Double
    )

    private val rowRegex = Regex("(?is)<tr\\b[^>]*>(.*?)</tr>")
    private val hourRegex = Regex("(?:^|\\s)([01]?\\d|2[0-3])h(?:\\s|$)", RegexOption.IGNORE_CASE)
    private val temperatureRegex = Regex("(-?\\d+(?:[.,]\\d+)?)\\s*°C", RegexOption.IGNORE_CASE)
    private val humidityRegex = Regex("(?:^|\\s)(\\d{1,3}(?:[.,]\\d+)?)\\s*%")

    fun syncToday(): LyonWeatherSyncResult {
        // Create the virtual sensor first so FabData can show it even if the
        // remote weather source is temporarily unavailable.
        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)
        val now = ZonedDateTime.now(LYON_ZONE)
        val date = now.toLocalDate()
        val html = downloadHtml()
        val points = linkedMapOf<Long, WeatherPoint>()

        rowRegex.findAll(html).forEach { match ->
            val text = Html.fromHtml(match.groupValues[1], Html.FROM_HTML_MODE_LEGACY)
                .toString()
                .replace('\u00A0', ' ')
                .replace(Regex("\\s+"), " ")
                .trim()

            val hour = hourRegex.find(text)?.groupValues?.getOrNull(1)?.toIntOrNull()
                ?: return@forEach
            val temperature = temperatureRegex.find(text)?.groupValues?.getOrNull(1)
                ?.replace(',', '.')?.toDoubleOrNull()
                ?: return@forEach
            val humidity = humidityRegex.find(text)?.groupValues?.getOrNull(1)
                ?.replace(',', '.')?.toDoubleOrNull()
                ?: return@forEach

            if (temperature !in -100.0..150.0 || humidity !in 0.0..100.0) return@forEach

            val observationDate = if (hour > now.hour) date.minusDays(1) else date
            val timestamp = observationDate.atTime(hour, 0)
                .atZone(LYON_ZONE)
                .toInstant()
                .toEpochMilli()

            points[timestamp] = WeatherPoint(timestamp, temperature, humidity)
        }

        if (points.isEmpty()) error("Aucune observation Lyon-Bron exploitable reçue")

        var added = 0
        var duplicates = 0
        db.inTransaction {
            points.values.sortedBy { it.timestamp }.forEach { point ->
                if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) {
                    added++
                } else {
                    duplicates++
                }
            }
        }

        return LyonWeatherSyncResult(points.size, added, duplicates, date)
    }

    /**
     * Complète Lyon sur exactement la période couverte par les thermomètres
     * physiques/importés. Les valeurs déjà présentes ne sont jamais écrasées.
     */
    fun completePhysicalPeriod(): LyonWeatherCompleteResult {
        val bounds = db.physicalSensorBounds()
            ?: error("Aucune période de thermomètre connecté à compléter")
        val fromDate = Instant.ofEpochMilli(bounds.first).atZone(LYON_ZONE).toLocalDate()
        val toDate = Instant.ofEpochMilli(bounds.last).atZone(LYON_ZONE).toLocalDate()
        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)

        var date = fromDate
        var requested = 0
        var downloaded = 0
        var alreadyComplete = 0
        var added = 0
        var duplicates = 0

        while (!date.isAfter(toDate)) {
            requested++
            val start = date.atStartOfDay(LYON_ZONE).toInstant().toEpochMilli()
            val end = date.plusDays(1).atStartOfDay(LYON_ZONE).toInstant().toEpochMilli() - 1
            val existing = db.existingSampleTimestamps(sensor.id, start, end)
            val expected = (0..23).map { hour ->
                date.atTime(hour, 0).atZone(LYON_ZONE).toInstant().toEpochMilli()
            }.toSet()

            if (expected.all { it in existing }) {
                alreadyComplete++
                date = date.plusDays(1)
                continue
            }

            val html = runCatching { downloadHtml(archiveUrl(date)) }.getOrElse { firstError ->
                if (date == LocalDate.now(LYON_ZONE)) downloadHtml() else throw firstError
            }
            downloaded++
            val points = parseArchiveDay(html, date)

            db.inTransaction {
                points.values.sortedBy { it.timestamp }.forEach { point ->
                    if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) {
                        added++
                    } else {
                        duplicates++
                    }
                }
            }

            // Reste poli avec la source si plusieurs jours sont nécessaires.
            if (date != toDate) Thread.sleep(80)
            date = date.plusDays(1)
        }

        return LyonWeatherCompleteResult(
            fromDate = fromDate,
            toDate = toDate,
            daysRequested = requested,
            daysDownloaded = downloaded,
            daysAlreadyComplete = alreadyComplete,
            added = added,
            duplicates = duplicates
        )
    }

    private fun archiveUrl(date: LocalDate): String {
        val month = MONTH_SLUGS[date.monthValue - 1]
        return "https://www.infoclimat.fr/observations-meteo/archives/${date.dayOfMonth}/$month/${date.year}/lyon-bron/07480.html"
    }

    private fun parseArchiveDay(html: String, date: LocalDate): LinkedHashMap<Long, WeatherPoint> {
        val points = linkedMapOf<Long, WeatherPoint>()
        rowRegex.findAll(html).forEach { match ->
            val text = Html.fromHtml(match.groupValues[1], Html.FROM_HTML_MODE_LEGACY)
                .toString()
                .replace('\u00A0', ' ')
                .replace(Regex("\\s+"), " ")
                .trim()
            val hour = hourRegex.find(text)?.groupValues?.getOrNull(1)?.toIntOrNull()
                ?: return@forEach
            val temperature = temperatureRegex.find(text)?.groupValues?.getOrNull(1)
                ?.replace(',', '.')?.toDoubleOrNull()
                ?: return@forEach
            val humidity = humidityRegex.find(text)?.groupValues?.getOrNull(1)
                ?.replace(',', '.')?.toDoubleOrNull()
                ?: return@forEach
            if (temperature !in -100.0..150.0 || humidity !in 0.0..100.0) return@forEach

            val timestamp = date.atTime(hour, 0)
                .atZone(LYON_ZONE)
                .toInstant()
                .toEpochMilli()
            points[timestamp] = WeatherPoint(timestamp, temperature, humidity)
        }
        if (points.isEmpty()) error("Aucune archive Lyon-Bron exploitable pour $date")
        return points
    }

    private fun downloadHtml(url: String = SOURCE_URL): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 15_000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/139.0 Mobile Safari/537.36 FabData/0.8")
            setRequestProperty("Accept-Language", "fr-FR,fr;q=0.9")
        }
        return try {
            val code = connection.responseCode
            if (code !in 200..299) error("Source météo HTTP $code")
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }

    fun sourceDescription(): String = String.format(Locale.FRANCE, "%s · %s", DISPLAY_NAME, SOURCE_NAME)
}
