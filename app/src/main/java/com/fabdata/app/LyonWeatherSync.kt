package com.fabdata.app

import android.text.Html
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.LocalDate
import java.time.ZonedDateTime
import java.time.ZoneId
import java.util.Locale
import kotlin.math.abs

/** Résultat d'une synchronisation de la sonde météo virtuelle Lyon. */
data class LyonWeatherSyncResult(
    val parsed: Int,
    val added: Int,
    val corrected: Int,
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
    val corrected: Int,
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
        // Crée la sonde même si la source distante est indisponible.
        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)
        val date = ZonedDateTime.now(LYON_ZONE).toLocalDate()

        // Préfère l'URL datée : on ne devine plus la date d'une ligne à partir
        // de l'heure courante. Le temps-réel reste un repli pour la journée en cours.
        val html = runCatching { downloadHtml(archiveUrl(date)) }
            .getOrElse { downloadHtml() }
        val points = parseArchiveDay(html, date)

        var added = 0
        var corrected = 0
        var duplicates = 0
        db.inTransaction {
            points.values.sortedBy { it.timestamp }.forEach { point ->
                if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) {
                    added++
                } else if (db.updateSampleIfDifferent(
                        sensor.id, point.timestamp, point.temperature, point.humidity
                    )
                ) {
                    // Les doublons météo peuvent être corrigés après revalidation.
                    corrected++
                } else {
                    duplicates++
                }
            }
        }

        return LyonWeatherSyncResult(points.size, added, corrected, duplicates, date)
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
        var corrected = 0
        var duplicates = 0

        // Les 31 derniers jours de la période physique sont toujours revalidés
        // lors d'un « Compléter ». Au-delà, on ne retélécharge que les journées
        // incomplètes ou manifestement suspectes afin d'éviter des milliers de GET.
        val recentRepairCutoff = toDate.minusDays(31)

        while (!date.isAfter(toDate)) {
            requested++
            val start = date.atStartOfDay(LYON_ZONE).toInstant().toEpochMilli()
            val end = date.plusDays(1).atStartOfDay(LYON_ZONE).toInstant().toEpochMilli() - 1
            val existingPoints = db.querySamples(sensor.id, start, end, maxPoints = 72)
            val existingTimestamps = existingPoints.map { it.timestamp }.toSet()
            val expected = (0..23).map { hour ->
                date.atTime(hour, 0).atZone(LYON_ZONE).toInstant().toEpochMilli()
            }.toSet()
            val complete = expected.all { it in existingTimestamps }
            val suspicious = isSuspiciousDay(existingPoints)
            val revalidateRecent = !date.isBefore(recentRepairCutoff)

            if (complete && !suspicious && !revalidateRecent) {
                alreadyComplete++
                date = date.plusDays(1)
                continue
            }

            // Fusionne uniquement des observations réelles Lyon-Bron :
            // archive datée + temps réel pour aujourd'hui/hier. Aucun remplissage artificiel.
            val points = mergedObservedDay(date)
            downloaded++

            db.inTransaction {
                points.values.sortedBy { it.timestamp }.forEach { point ->
                    if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) {
                        added++
                    } else if (db.updateSampleIfDifferent(
                            sensor.id, point.timestamp, point.temperature, point.humidity
                        )
                    ) {
                        corrected++
                    } else {
                        duplicates++
                    }
                }
            }

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
            corrected = corrected,
            duplicates = duplicates
        )
    }

    /**
     * Fusionne les méthodes d'acquisition sans mélanger des modèles météo :
     * - temps réel Lyon-Bron pour combler les dernières heures disponibles ;
     * - archive Lyon-Bron, prioritaire au même timestamp.
     * Si aucune observation réelle n'existe, aucun point n'est inventé.
     */
    private fun mergedObservedDay(date: LocalDate): LinkedHashMap<Long, WeatherPoint> {
        val now = ZonedDateTime.now(LYON_ZONE)
        val merged = linkedMapOf<Long, WeatherPoint>()

        // La page temps réel est utile pour aujourd'hui et parfois la veille.
        if (!date.isBefore(now.toLocalDate().minusDays(1))) {
            runCatching { downloadHtml() }.getOrNull()?.let { html ->
                parseRealtimeWindow(html, now).values
                    .filter { point ->
                        Instant.ofEpochMilli(point.timestamp).atZone(LYON_ZONE).toLocalDate() == date
                    }
                    .forEach { point -> merged[point.timestamp] = point }
            }
        }

        // L'archive est la référence finale quand elle possède le même horaire.
        runCatching { downloadHtml(archiveUrl(date)) }.getOrNull()?.let { html ->
            runCatching { parseArchiveDay(html, date) }.getOrNull()?.values?.forEach { point ->
                merged[point.timestamp] = point
            }
        }

        if (merged.isEmpty()) error("Aucune observation réelle Lyon-Bron exploitable pour $date")
        return merged
    }

    /** Parse la fenêtre roulante temps réel sans fabriquer les heures absentes. */
    private fun parseRealtimeWindow(
        html: String,
        now: ZonedDateTime
    ): LinkedHashMap<Long, WeatherPoint> {
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

            val observationDate = if (hour > now.hour) now.toLocalDate().minusDays(1) else now.toLocalDate()
            val timestamp = observationDate.atTime(hour, 0)
                .atZone(LYON_ZONE)
                .toInstant()
                .toEpochMilli()
            points[timestamp] = WeatherPoint(timestamp, temperature, humidity)
        }
        return points
    }

    /**
     * Détecte les anomalies grossières avant de décider qu'une journée météo
     * existante est « complète ». Un saut > 8 °C en <= 2 h mérite revalidation.
     */
    private fun isSuspiciousDay(points: List<SamplePoint>): Boolean {
        if (points.any { it.temperature !in -35.0..50.0 || it.humidity !in 0.0..100.0 }) return true
        val sorted = points.sortedBy { it.timestamp }
        return sorted.zipWithNext().any { (a, b) ->
            val dt = b.timestamp - a.timestamp
            dt in 1..(2L * 60L * 60L * 1000L) && abs(b.temperature - a.temperature) > 8.0
        }
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
            setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/139.0 Mobile Safari/537.36 FabData/0.8.7")
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
