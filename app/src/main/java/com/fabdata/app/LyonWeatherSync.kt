package com.fabdata.app

import org.jsoup.Jsoup
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

/**
 * Importe les observations horaires réellement affichées pour la station
 * Météo-France Lyon-Bron dans la base FabData.
 *
 * La sonde est volontairement enregistrée avec le même modèle Sensor/Sample
 * que les thermo-hygromètres physiques. Elle est donc automatiquement incluse
 * dans le format de sauvegarde FabData v1 et restaurée par les anciennes
 * sauvegardes sans migration de schéma.
 */
class LyonWeatherSync(private val db: FabDataDb) {
    companion object {
        const val STABLE_KEY = "meteo-france-lyon-bron-mf69029001"
        const val DISPLAY_NAME = "Lyon"
        const val SOURCE_NAME = "Météo-France Lyon-Bron via Infoclimat"
        const val SOURCE_URL = "https://www.infoclimat.fr/observations-meteo/temps-reel/lyon-bron/07480.html"
        private val LYON_ZONE: ZoneId = ZoneId.of("Europe/Paris")
    }

    private data class WeatherPoint(
        val timestamp: Long,
        val temperature: Double,
        val humidity: Double
    )

    private val hourRegex = Regex("(?:^|\\s)([01]?\\d|2[0-3])h(?:\\s|$)", RegexOption.IGNORE_CASE)
    private val temperatureRegex = Regex("(-?\\d+(?:[.,]\\d+)?)\\s*°C", RegexOption.IGNORE_CASE)
    private val humidityRegex = Regex("(?:^|\\s)(\\d{1,3}(?:[.,]\\d+)?)\\s*%")

    /**
     * Synchronise les observations horaires actuellement publiées pour Lyon-Bron.
     * Le tableau temps réel contient aussi les dernières heures de la veille :
     * une heure supérieure à l'heure locale courante est donc rattachée à J-1.
     * Les heures déjà présentes restent intactes grâce à la contrainte
     * UNIQUE(sensor_id, timestamp).
     */
    fun syncToday(): LyonWeatherSyncResult {
        val now = ZonedDateTime.now(LYON_ZONE)
        val date = now.toLocalDate()
        val document = Jsoup.connect(SOURCE_URL)
            .userAgent("FabData/0.8 (Android; weather observation import)")
            .referrer("https://www.infoclimat.fr/")
            .header("Accept-Language", "fr-FR,fr;q=0.9")
            .timeout(15_000)
            .followRedirects(true)
            .get()

        val points = linkedMapOf<Long, WeatherPoint>()

        // Le tableau contient une ligne par heure. On reste volontairement
        // tolérant sur les classes CSS pour ne pas dépendre de la présentation.
        document.select("tr").forEach { row ->
            val text = row.text()
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

        if (points.isEmpty()) {
            error("Aucune observation Lyon-Bron exploitable reçue")
        }

        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)
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

        return LyonWeatherSyncResult(
            parsed = points.size,
            added = added,
            duplicates = duplicates,
            date = date
        )
    }

    fun sourceDescription(): String = String.format(
        Locale.FRANCE,
        "%s · %s",
        DISPLAY_NAME,
        SOURCE_NAME
    )
}
