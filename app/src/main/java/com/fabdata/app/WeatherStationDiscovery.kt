package com.fabdata.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Looper
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL
import java.text.Normalizer
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.coroutines.resume
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/** Point autour duquel FabData cherche les stations météo. */
data class StationSearchOrigin(
    val label: String,
    val latitude: Double,
    val longitude: Double
)

/**
 * Une station active candidate. hotIndexC est volontairement un indicateur robuste
 * de chaleur locale et non le record absolu d'une seule journée.
 */
data class WeatherStationCandidate(
    val reference: WeatherReference,
    val distanceKm: Double,
    val hotIndexC: Double? = null,
    val p95C: Double? = null,
    val p99C: Double? = null,
    val historyDays: Int = 0
)

data class StationDiscoveryResult(
    val origin: StationSearchOrigin,
    val radiusKm: Int,
    val candidates: List<WeatherStationCandidate>,
    val autoSelected: WeatherStationCandidate?,
    val indexLabel: String
)

/**
 * v0.13.0 : découverte de station entièrement en amont du moteur RC.
 * ThermalEngine n'est ni appelé ni modifié ici.
 *
 * - index actif Météo-France quand une clé/token existe ;
 * - recherche par GPS / adresse / code postal / ville / coordonnées ;
 * - classement protecteur par climat chaud historique autour de chaque station ;
 * - une seule station est ensuite remise au WeatherReferenceManager existant.
 */
class WeatherStationDiscovery(
    private val context: Context,
    private val credentials: MeteoFranceCredentialStore
) {
    private val zone = ZoneId.of("Europe/Paris")

    suspend fun currentLocation(): StationSearchOrigin = suspendCancellableCoroutine { continuation ->
        val fine = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!fine && !coarse) {
            continuation.resumeWith(Result.failure(IllegalStateException("Autorisation de localisation requise")))
            return@suspendCancellableCoroutine
        }

        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val providers = listOf(
            LocationManager.GPS_PROVIDER,
            LocationManager.NETWORK_PROVIDER,
            LocationManager.PASSIVE_PROVIDER
        ).filter { runCatching { manager.isProviderEnabled(it) }.getOrDefault(false) }

        val last = providers.mapNotNull { provider ->
            runCatching { manager.getLastKnownLocation(provider) }.getOrNull()
        }.maxByOrNull { it.time }

        // Une position récente évite de rallumer inutilement le GPS.
        if (last != null && System.currentTimeMillis() - last.time <= 6L * 60L * 60L * 1000L) {
            continuation.resume(StationSearchOrigin("GPS", last.latitude, last.longitude))
            return@suspendCancellableCoroutine
        }

        val provider = providers.firstOrNull() ?: LocationManager.PASSIVE_PROVIDER
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                runCatching { manager.removeUpdates(this) }
                if (continuation.isActive) {
                    continuation.resume(StationSearchOrigin("GPS", location.latitude, location.longitude))
                }
            }
        }

        runCatching {
            @Suppress("DEPRECATION")
            manager.requestSingleUpdate(provider, listener, Looper.getMainLooper())
        }.onFailure { error ->
            if (last != null && continuation.isActive) {
                continuation.resume(StationSearchOrigin("GPS · dernière position", last.latitude, last.longitude))
            } else if (continuation.isActive) {
                continuation.resumeWith(Result.failure(error))
            }
        }
        continuation.invokeOnCancellation { runCatching { manager.removeUpdates(listener) } }
    }

    /** Adresse, code postal ou grande ville. GeoPlateforme IGN d'abord, Open-Meteo en secours. */
    fun geocode(query: String): StationSearchOrigin {
        val q = query.trim()
        require(q.isNotBlank()) { "Adresse, code postal ou ville manquant" }
        val encoded = URLEncoder.encode(q, "UTF-8")

        runCatching {
            val raw = httpGetAnonymous(
                "https://data.geopf.fr/geocodage/search?q=$encoded&index=address&limit=1"
            )
            val root = JSONObject(raw)
            val feature = root.optJSONArray("features")?.optJSONObject(0)
                ?: error("Lieu introuvable")
            val geometry = feature.getJSONObject("geometry")
            val coordinates = geometry.getJSONArray("coordinates")
            val props = feature.optJSONObject("properties")
            val label = props?.optString("label")?.takeIf { it.isNotBlank() }
                ?: props?.optString("name")?.takeIf { it.isNotBlank() }
                ?: q
            StationSearchOrigin(label, coordinates.getDouble(1), coordinates.getDouble(0))
        }.getOrNull()?.let { return it }

        val raw = httpGetAnonymous(
            "https://geocoding-api.open-meteo.com/v1/search?name=$encoded&count=1&language=fr&format=json&countryCode=FR"
        )
        val result = JSONObject(raw).optJSONArray("results")?.optJSONObject(0)
            ?: error("Lieu introuvable")
        val label = listOf(
            result.optString("name"),
            result.optString("admin1"),
            result.optString("country")
        ).filter { it.isNotBlank() }.joinToString(" · ").ifBlank { q }
        return StationSearchOrigin(label, result.getDouble("latitude"), result.getDouble("longitude"))
    }

    fun coordinates(latitude: String, longitude: String): StationSearchOrigin {
        val lat = latitude.trim().replace(',', '.').toDoubleOrNull()
            ?: error("Latitude invalide")
        val lon = longitude.trim().replace(',', '.').toDoubleOrNull()
            ?: error("Longitude invalide")
        require(lat in -90.0..90.0 && lon in -180.0..180.0) { "Coordonnées GPS hors limites" }
        return StationSearchOrigin(
            "${String.format(Locale.FRANCE, "%.5f", lat)}, ${String.format(Locale.FRANCE, "%.5f", lon)}",
            lat,
            lon
        )
    }

    /**
     * Charge l'index au moment de la recherche : une nouvelle station Météo-France peut donc
     * apparaître dans FabData sans nouvelle version de l'application.
     */
    fun discoverAndRank(origin: StationSearchOrigin, requestedRadiusKm: Int): StationDiscoveryResult {
        val radius = requestedRadiusKm.coerceIn(5, 200)
        val indexed = loadStationIndex()
        val nearby = indexed.first.asSequence()
            .map { reference ->
                WeatherStationCandidate(
                    reference = reference,
                    distanceKm = haversineKm(origin.latitude, origin.longitude, reference.latitude, reference.longitude)
                )
            }
            .filter { it.distanceKm <= radius.toDouble() }
            .sortedBy { it.distanceKm }
            .toList()

        if (nearby.isEmpty()) {
            return StationDiscoveryResult(origin, radius, emptyList(), null, indexed.second)
        }

        val ranked = enrichHeatIndex(nearby).sortedWith(
            compareByDescending<WeatherStationCandidate> { it.hotIndexC != null }
                .thenByDescending { it.hotIndexC ?: Double.NEGATIVE_INFINITY }
                .thenBy { it.distanceKm }
        )
        val auto = ranked.firstOrNull { it.hotIndexC != null } ?: ranked.minByOrNull { it.distanceKm }
        return StationDiscoveryResult(origin, radius, ranked, auto, indexed.second)
    }

    private fun loadStationIndex(): Pair<List<WeatherReference>, String> {
        val credential = credentials.get().trim()
        if (credential.isBlank()) {
            return WeatherReferenceCatalog.stations to "Catalogue FabData · ajoute un token Météo-France pour l'index complet"
        }

        val endpoints = listOf(
            "https://public-api.meteofrance.fr/public/DPObs/v2/liste-stations",
            "https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations",
            "https://public-api.meteofrance.fr/public/DPObs/liste-stations"
        )
        var lastError: Throwable? = null
        endpoints.forEach { endpoint ->
            runCatching { parseStationCsv(httpGetMeteoFrance(endpoint, credential)) }
                .onSuccess { parsed ->
                    if (parsed.isNotEmpty()) return parsed to "Index actif Météo-France · actualisé à la demande"
                }
                .onFailure { lastError = it }
        }

        // Dégradation sûre : l'ancien catalogue reste utilisable, le moteur RC n'est pas impacté.
        val detail = lastError?.message?.take(80)?.let { " · $it" }.orEmpty()
        return WeatherReferenceCatalog.stations to "Index Météo-France indisponible$detail · catalogue FabData"
    }

    private fun parseStationCsv(raw: String): List<WeatherReference> {
        val lines = raw.lineSequence().map { it.trimEnd('\r') }.filter { it.isNotBlank() }.toList()
        if (lines.size < 2) return emptyList()
        val first = lines.first().removePrefix("\uFEFF")
        val delimiter = listOf(';', ',', '\t').maxByOrNull { d -> first.count { it == d } } ?: ';'
        val header = splitCsv(first, delimiter).map(::normalizeHeader)

        fun column(vararg names: String): Int {
            val normalized = names.map(::normalizeHeader)
            return header.indexOfFirst { h -> normalized.any { n -> h == n } }
        }

        val idI = column("id_station", "id-station", "geo_id_insee", "num_poste", "numero_poste")
        val nameI = column("nom_usuel", "nom_station", "nom", "libelle_station", "libelle")
        val cityI = column("commune", "nom_commune", "ville")
        val latI = column("latitude", "lat", "lat_dg")
        val lonI = column("longitude", "lon", "long", "lon_dg")
        val altI = column("altitude", "alt", "altitude_m")
        val deptI = column("id_departement", "departement", "num_dep", "dep", "dpt")
        if (idI < 0 || latI < 0 || lonI < 0) return emptyList()

        return lines.drop(1).mapNotNull { line ->
            val fields = splitCsv(line, delimiter)
            val rawId = fields.getOrNull(idI)?.trim()?.trim('"').orEmpty()
            val digits = rawId.filter(Char::isDigit)
            if (digits.isEmpty() || digits.length > 8) return@mapNotNull null
            val stationId = digits.padStart(8, '0')
            val lat = parseNumber(fields.getOrNull(latI)) ?: return@mapNotNull null
            val lon = parseNumber(fields.getOrNull(lonI)) ?: return@mapNotNull null
            if (lat !in -90.0..90.0 || lon !in -180.0..180.0) return@mapNotNull null
            val stationName = fields.getOrNull(nameI)?.trim()?.trim('"')?.takeIf { it.isNotBlank() }
                ?: "Station $stationId"
            val city = fields.getOrNull(cityI)?.trim()?.trim('"')?.takeIf { it.isNotBlank() }
                ?: stationName
            val department = fields.getOrNull(deptI)?.trim()?.trim('"')?.takeIf { it.isNotBlank() }
                ?: stationId.take(2)
            val altitude = parseNumber(fields.getOrNull(altI))
            WeatherReference(
                key = "mf-$stationId",
                city = city,
                stationName = stationName,
                stationId = stationId,
                latitude = lat,
                longitude = lon,
                departmentId = department,
                altitudeM = altitude
            )
        }.distinctBy { it.stationId }
    }

    /**
     * Proxy protecteur : températures maximales quotidiennes mai-septembre sur 5 ans.
     * 70 % P95 + 30 % P99. Un record isolé ne peut donc pas gagner à lui seul.
     * Les coordonnées sont envoyées par lots pour ne pas télécharger toute la France.
     */
    private fun enrichHeatIndex(candidates: List<WeatherStationCandidate>): List<WeatherStationCandidate> {
        if (candidates.isEmpty()) return candidates
        val end = LocalDate.now(zone).minusDays(7)
        val start = end.minusYears(5)
        val out = candidates.toMutableList()

        candidates.indices.chunked(20).forEach { indexes ->
            val latitudes = indexes.joinToString(",") { candidates[it].reference.latitude.toString() }
            val longitudes = indexes.joinToString(",") { candidates[it].reference.longitude.toString() }
            val url = "https://archive-api.open-meteo.com/v1/archive" +
                "?latitude=$latitudes&longitude=$longitudes" +
                "&start_date=$start&end_date=$end" +
                "&daily=temperature_2m_max&timezone=Europe%2FParis"

            val raw = runCatching { httpGetAnonymous(url) }.getOrNull() ?: return@forEach
            val trimmed = raw.trim()
            val nodes = if (trimmed.startsWith("[")) {
                val a = JSONArray(trimmed)
                (0 until a.length()).mapNotNull { a.optJSONObject(it) }
            } else {
                listOf(JSONObject(trimmed))
            }

            indexes.forEachIndexed { position, candidateIndex ->
                val node = nodes.getOrNull(position) ?: return@forEachIndexed
                val daily = node.optJSONObject("daily") ?: return@forEachIndexed
                val times = daily.optJSONArray("time") ?: return@forEachIndexed
                val maxima = daily.optJSONArray("temperature_2m_max") ?: return@forEachIndexed
                val values = mutableListOf<Double>()
                val count = minOf(times.length(), maxima.length())
                for (i in 0 until count) {
                    val date = runCatching { LocalDate.parse(times.optString(i), DateTimeFormatter.ISO_LOCAL_DATE) }.getOrNull()
                        ?: continue
                    if (date.monthValue !in 5..9) continue
                    val value = maxima.optDouble(i, Double.NaN)
                    if (value.isFinite() && value in -30.0..65.0) values += value
                }
                // Environ deux saisons chaudes minimum pour afficher un classement robuste.
                if (values.size < 300) return@forEachIndexed
                values.sort()
                val p95 = percentile(values, 0.95)
                val p99 = percentile(values, 0.99)
                val hot = 0.70 * p95 + 0.30 * p99
                out[candidateIndex] = candidates[candidateIndex].copy(
                    hotIndexC = hot,
                    p95C = p95,
                    p99C = p99,
                    historyDays = values.size
                )
            }
        }
        return out
    }

    private fun percentile(sorted: List<Double>, probability: Double): Double {
        if (sorted.isEmpty()) return Double.NaN
        if (sorted.size == 1) return sorted.first()
        val position = probability.coerceIn(0.0, 1.0) * (sorted.size - 1)
        val low = position.toInt().coerceIn(0, sorted.lastIndex)
        val high = (low + 1).coerceAtMost(sorted.lastIndex)
        val fraction = position - low
        return sorted[low] + (sorted[high] - sorted[low]) * fraction
    }

    private fun haversineKm(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6371.0088
        val p1 = Math.toRadians(lat1)
        val p2 = Math.toRadians(lat2)
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2).pow(2) + cos(p1) * cos(p2) * sin(dLon / 2).pow(2)
        return 2.0 * r * asin(sqrt(a.coerceIn(0.0, 1.0)))
    }

    private fun parseNumber(raw: String?): Double? = raw?.trim()?.trim('"')?.replace(',', '.')?.toDoubleOrNull()

    private fun normalizeHeader(raw: String): String {
        val clean = Normalizer.normalize(raw.trim().trim('"'), Normalizer.Form.NFD)
            .replace(Regex("\\p{Mn}+"), "")
            .lowercase(Locale.ROOT)
        return clean.replace(Regex("[^a-z0-9]+"), "_").trim('_')
    }

    private fun splitCsv(line: String, delimiter: Char): List<String> {
        val out = mutableListOf<String>()
        val current = StringBuilder()
        var quoted = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            when {
                ch == '"' && quoted && i + 1 < line.length && line[i + 1] == '"' -> {
                    current.append('"'); i++
                }
                ch == '"' -> quoted = !quoted
                ch == delimiter && !quoted -> {
                    out += current.toString(); current.clear()
                }
                else -> current.append(ch)
            }
            i++
        }
        out += current.toString()
        return out
    }

    private fun httpGetMeteoFrance(url: String, credential: String): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 18_000
            readTimeout = 30_000
            instanceFollowRedirects = true
            setRequestProperty("Accept", "*/*")
            setRequestProperty("Authorization", "Bearer $credential")
            setRequestProperty("apikey", credential)
            setRequestProperty("User-Agent", "FabData/0.13.0 Android")
        }
        return try {
            val code = connection.responseCode
            if (code !in 200..299) {
                val body = connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                error("Météo-France HTTP $code${body.take(100).let { if (it.isBlank()) "" else " · $it" }}")
            }
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }

    private fun httpGetAnonymous(url: String): String {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 18_000
            readTimeout = 35_000
            instanceFollowRedirects = true
            setRequestProperty("Accept", "application/json, */*")
            setRequestProperty("User-Agent", "FabData/0.13.0 Android")
        }
        return try {
            val code = connection.responseCode
            if (code !in 200..299) error("HTTP $code")
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        fun formatDistance(distanceKm: Double): String = when {
            distanceKm < 1.0 -> "${(distanceKm * 1000.0).roundToInt()} m"
            else -> String.format(Locale.FRANCE, "%.1f km", distanceKm)
        }

        fun formatHot(value: Double?): String = value?.let {
            String.format(Locale.FRANCE, "%.1f °C", it)
        } ?: "indice en attente"
    }
}
