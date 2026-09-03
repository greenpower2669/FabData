package com.fabdata.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL
import java.time.LocalDate
import java.time.ZoneId
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

data class StationSearchAnchor(
    val label: String,
    val latitude: Double,
    val longitude: Double,
    val departmentId: String? = null
)

data class StationHeatStats(
    val p95C: Double,
    val recordC: Double,
    val days: Int,
    val years: Int
)

data class StationCandidate(
    val reference: WeatherReference,
    val distanceKm: Double,
    val heat: StationHeatStats? = null
)

data class StationDiscoveryResult(
    val anchor: StationSearchAnchor,
    val candidates: List<StationCandidate>,
    val autoCandidate: StationCandidate?,
    val radiusKm: Int,
    val historyLabel: String
)

class WeatherStationDiscovery(
    private val context: Context,
    private val credentials: MeteoFranceCredentialStore
) {
    private val zone = ZoneId.of("Europe/Paris")

    fun geocode(query: String): StationSearchAnchor {
        val clean = query.trim()
        require(clean.length >= 2) { "Adresse, code postal ou ville trop court" }
        val url = "https://data.geopf.fr/geocodage/search/?q=${enc(clean)}&limit=5"
        val root = JSONObject(httpGet(url, null))
        val features = root.optJSONArray("features") ?: JSONArray()
        if (features.length() == 0) error("Lieu introuvable")
        return anchorFromFeature(features.getJSONObject(0))
    }

    fun reverse(latitude: Double, longitude: Double): StationSearchAnchor {
        require(latitude in -90.0..90.0 && longitude in -180.0..180.0) { "Coordonnées GPS invalides" }
        val url = "https://data.geopf.fr/geocodage/reverse?lat=$latitude&lon=$longitude"
        val root = JSONObject(httpGet(url, null))
        val features = root.optJSONArray("features") ?: JSONArray()
        if (features.length() == 0) {
            return StationSearchAnchor(
                label = "%.5f, %.5f".format(latitude, longitude),
                latitude = latitude,
                longitude = longitude
            )
        }
        return anchorFromFeature(features.getJSONObject(0))
    }

    @SuppressLint("MissingPermission")
    fun gpsAnchor(): StationSearchAnchor {
        val fine = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!fine && !coarse) error("Permission de localisation refusée")

        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val best = manager.getProviders(true)
            .mapNotNull { provider -> runCatching { manager.getLastKnownLocation(provider) }.getOrNull() }
            .maxByOrNull { it.time }
            ?: error("Position GPS indisponible pour l'instant")

        val resolved = reverse(best.latitude, best.longitude)
        return resolved.copy(label = "GPS · ${resolved.label}")
    }

    fun discover(anchor: StationSearchAnchor, radiusKm: Int): StationDiscoveryResult {
        val radius = radiusKm.coerceIn(10, 150)
        val raw = fetchObservationStationIndex()
        val stations = parseObservationStations(raw)
            .asSequence()
            .map { ref ->
                StationCandidate(ref, distanceKm(anchor.latitude, anchor.longitude, ref.latitude, ref.longitude))
            }
            .filter { it.distanceKm <= radius.toDouble() }
            .sortedBy { it.distanceKm }
            .take(24)
            .toList()

        if (stations.isEmpty()) {
            error("Aucune station Météo-France trouvée dans un rayon de $radius km")
        }

        val endYear = LocalDate.now(zone).year - 1
        val startYear = endYear - 9
        val heat = runCatching { fetchHeatStats(stations.map { it.reference }, startYear, endYear) }
            .getOrDefault(emptyMap())

        val enriched = stations.map { candidate ->
            candidate.copy(heat = heat[candidate.reference.key])
        }

        val auto = enriched
            .filter { it.heat != null }
            .maxWithOrNull(
                compareBy<StationCandidate> { it.heat!!.p95C }
                    .thenBy { it.heat!!.recordC }
                    .thenBy { -it.distanceKm }
            )
            ?: enriched.firstOrNull()

        return StationDiscoveryResult(
            anchor = anchor,
            candidates = enriched,
            autoCandidate = auto,
            radiusKm = radius,
            historyLabel = "$startYear–$endYear · juin à septembre"
        )
    }

    private fun fetchObservationStationIndex(): String {
        val credential = credentials.get().trim()
        if (credential.isBlank()) {
            error("Token Météo-France requis pour découvrir toutes les stations")
        }
        val endpoints = listOf(
            "https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations",
            "https://public-api.meteofrance.fr/public/DPObs/liste-stations"
        )
        var last: Throwable? = null
        endpoints.forEach { endpoint ->
            runCatching { httpGet(endpoint, credential) }
                .onSuccess { return it }
                .onFailure { last = it }
        }
        throw last ?: IllegalStateException("Index des stations Météo-France indisponible")
    }

    private fun parseObservationStations(raw: String): List<WeatherReference> {
        val clean = raw.trim().removePrefix("\uFEFF")
        if (clean.startsWith("[")) return parseJsonStations(JSONArray(clean))
        if (clean.startsWith("{")) {
            val obj = JSONObject(clean)
            val arr = obj.optJSONArray("stations") ?: obj.optJSONArray("features")
            if (arr != null) return parseJsonStations(arr)
        }
        return parseCsvStations(clean)
    }

    private fun parseJsonStations(array: JSONArray): List<WeatherReference> {
        val out = mutableListOf<WeatherReference>()
        for (i in 0 until array.length()) {
            val raw = array.optJSONObject(i) ?: continue
            val props = raw.optJSONObject("properties") ?: raw
            val geometry = raw.optJSONObject("geometry")
            val coords = geometry?.optJSONArray("coordinates")

            val id = firstString(props, "id", "geo_id_insee", "num_poste", "id_station") ?: continue
            val name = firstString(props, "nom", "nom_usuel", "name", "station") ?: "Station $id"
            val lon = firstDouble(props, "lon", "longitude")
                ?: coords?.optDouble(0, Double.NaN)?.takeIf { it.isFinite() }
                ?: continue
            val lat = firstDouble(props, "lat", "latitude")
                ?: coords?.optDouble(1, Double.NaN)?.takeIf { it.isFinite() }
                ?: continue
            if (lat !in -90.0..90.0 || lon !in -180.0..180.0) continue

            out += WeatherReference(
                key = "mf-$id",
                city = name,
                stationName = name,
                stationId = id,
                latitude = lat,
                longitude = lon,
                departmentId = departmentFromStationId(id)
            )
        }
        return out.distinctBy { it.stationId }
    }

    private fun parseCsvStations(raw: String): List<WeatherReference> {
        val lines = raw.lineSequence().filter { it.isNotBlank() }.toList()
        if (lines.size < 2) return emptyList()
        val separator = if (lines.first().count { it == ';' } >= lines.first().count { it == ',' }) ';' else ','
        val headers = splitCsv(lines.first().removePrefix("\uFEFF"), separator).map(::norm)
        val idI = find(headers, "geo_id_insee", "num_poste", "id_station", "id")
        val nameI = find(headers, "nom_usuel", "nom", "name", "station")
        val latI = find(headers, "lat", "latitude")
        val lonI = find(headers, "lon", "longitude")
        if (idI < 0 || latI < 0 || lonI < 0) return emptyList()

        return lines.drop(1).mapNotNull { line ->
            val f = splitCsv(line, separator)
            val id = f.getOrNull(idI)?.trim()?.trim('"').orEmpty()
            if (id.isBlank()) return@mapNotNull null
            val lat = f.getOrNull(latI)?.trim()?.trim('"')?.replace(',', '.')?.toDoubleOrNull()
                ?: return@mapNotNull null
            val lon = f.getOrNull(lonI)?.trim()?.trim('"')?.replace(',', '.')?.toDoubleOrNull()
                ?: return@mapNotNull null
            if (lat !in -90.0..90.0 || lon !in -180.0..180.0) return@mapNotNull null
            val name = f.getOrNull(nameI)?.trim()?.trim('"').orEmpty().ifBlank { "Station $id" }
            WeatherReference(
                key = "mf-$id",
                city = name,
                stationName = name,
                stationId = id,
                latitude = lat,
                longitude = lon,
                departmentId = departmentFromStationId(id)
            )
        }.distinctBy { it.stationId }
    }

    private fun fetchHeatStats(
        references: List<WeatherReference>,
        startYear: Int,
        endYear: Int
    ): Map<String, StationHeatStats> {
        val out = linkedMapOf<String, StationHeatStats>()
        references.chunked(12).forEach { chunk ->
            val latitudes = chunk.joinToString(",") { it.latitude.toString() }
            val longitudes = chunk.joinToString(",") { it.longitude.toString() }
            val url = "https://archive-api.open-meteo.com/v1/archive" +
                "?latitude=${enc(latitudes)}&longitude=${enc(longitudes)}" +
                "&start_date=$startYear-01-01&end_date=$endYear-12-31" +
                "&daily=temperature_2m_max&timezone=Europe%2FParis"
            val parsed = JSONTokener(httpGet(url, null)).nextValue()
            val roots = when (parsed) {
                is JSONArray -> (0 until parsed.length()).mapNotNull { parsed.optJSONObject(it) }
                is JSONObject -> listOf(parsed)
                else -> emptyList()
            }

            roots.forEachIndexed { index, root ->
                val ref = chunk.getOrNull(index) ?: return@forEachIndexed
                val daily = root.optJSONObject("daily") ?: return@forEachIndexed
                val times = daily.optJSONArray("time") ?: return@forEachIndexed
                val temps = daily.optJSONArray("temperature_2m_max") ?: return@forEachIndexed
                val summer = mutableListOf<Double>()
                for (i in 0 until minOf(times.length(), temps.length())) {
                    val date = runCatching { LocalDate.parse(times.optString(i)) }.getOrNull() ?: continue
                    if (date.monthValue !in 6..9) continue
                    val value = temps.optDouble(i, Double.NaN)
                    if (value.isFinite() && value in -60.0..65.0) summer += value
                }
                if (summer.size >= 120) {
                    val sorted = summer.sorted()
                    val p95Index = ((sorted.size - 1) * 0.95).roundToInt().coerceIn(0, sorted.lastIndex)
                    out[ref.key] = StationHeatStats(
                        p95C = sorted[p95Index],
                        recordC = sorted.last(),
                        days = sorted.size,
                        years = endYear - startYear + 1
                    )
                }
            }
        }
        return out
    }

    private fun anchorFromFeature(feature: JSONObject): StationSearchAnchor {
        val geometry = feature.getJSONObject("geometry").getJSONArray("coordinates")
        val props = feature.optJSONObject("properties") ?: JSONObject()
        val lon = geometry.getDouble(0)
        val lat = geometry.getDouble(1)
        val label = props.optString("label")
            .ifBlank { props.optString("city") }
            .ifBlank { "%.5f, %.5f".format(lat, lon) }
        val department = props.optString("context")
            .substringBefore(',')
            .trim()
            .takeIf { it.matches(Regex("[0-9A-Za-z]{2,3}")) }
        return StationSearchAnchor(label, lat, lon, department)
    }

    private fun httpGet(url: String, credential: String?): String {
        val c = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 18_000
            readTimeout = 35_000
            instanceFollowRedirects = true
            setRequestProperty("Accept", "*/*")
            setRequestProperty("User-Agent", "FabData/0.13.0 Android")
            if (!credential.isNullOrBlank()) {
                setRequestProperty("Authorization", "Bearer $credential")
                setRequestProperty("apikey", credential)
            }
        }
        return try {
            val code = c.responseCode
            if (code !in 200..299) {
                val body = c.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                error("HTTP $code${body.take(120).let { if (it.isBlank()) "" else " · $it" }}")
            }
            c.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } finally {
            c.disconnect()
        }
    }

    private fun distanceKm(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6371.0088
        val p1 = Math.toRadians(lat1)
        val p2 = Math.toRadians(lat2)
        val dp = Math.toRadians(lat2 - lat1)
        val dl = Math.toRadians(lon2 - lon1)
        val a = sin(dp / 2).pow(2) + cos(p1) * cos(p2) * sin(dl / 2).pow(2)
        return 2.0 * r * asin(sqrt(a.coerceIn(0.0, 1.0)))
    }

    private fun departmentFromStationId(id: String): String =
        if (id.startsWith("97") || id.startsWith("98")) id.take(3) else id.take(2)

    private fun firstString(obj: JSONObject, vararg names: String): String? {
        names.forEach { name ->
            val value = obj.optString(name).trim()
            if (value.isNotBlank() && value != "null") return value
        }
        return null
    }

    private fun firstDouble(obj: JSONObject, vararg names: String): Double? {
        names.forEach { name ->
            val value = obj.optDouble(name, Double.NaN)
            if (value.isFinite()) return value
            obj.optString(name).replace(',', '.').toDoubleOrNull()?.let { return it }
        }
        return null
    }

    private fun splitCsv(line: String, separator: Char): List<String> {
        val out = mutableListOf<String>()
        val current = StringBuilder()
        var quoted = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            when {
                ch == '"' && quoted && i + 1 < line.length && line[i + 1] == '"' -> {
                    current.append('"')
                    i++
                }
                ch == '"' -> quoted = !quoted
                ch == separator && !quoted -> {
                    out += current.toString()
                    current.setLength(0)
                }
                else -> current.append(ch)
            }
            i++
        }
        out += current.toString()
        return out
    }

    private fun norm(value: String): String = value
        .trim()
        .trim('"')
        .lowercase()
        .replace(Regex("[^a-z0-9_]+"), "_")
        .trim('_')

    private fun find(headers: List<String>, vararg names: String): Int =
        headers.indexOfFirst { header -> names.any { norm(it) == header } }

    private fun enc(value: String): String = URLEncoder.encode(value, "UTF-8")
}
