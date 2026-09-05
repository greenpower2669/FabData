from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app/src/main/java/com/fabdata/app"


def write(path: Path, content: str) -> None:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


write(APP / "StationSectorPrefs.kt", r'''
package com.fabdata.app

import android.content.Context

data class StationSectorMemory(
    val label: String,
    val latitude: Double,
    val longitude: Double,
    val radiusKm: Int
) {
    fun anchor(): StationSearchAnchor = StationSearchAnchor(label, latitude, longitude)
}

/**
 * Restaure la mémoire de secteur introduite en v0.13 sans toucher au format des mesures.
 * Les clés sont volontairement les anciennes clés v0.13 afin de récupérer automatiquement
 * le secteur déjà enregistré sur les installations qui l'avaient utilisé.
 */
class WeatherStationSectorPrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)

    fun load(): StationSectorMemory? {
        val latitude = prefs.getString("sector_latitude", null)?.toDoubleOrNull() ?: return null
        val longitude = prefs.getString("sector_longitude", null)?.toDoubleOrNull() ?: return null
        if (latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return null
        return StationSectorMemory(
            label = prefs.getString("sector_label", null).orEmpty().ifBlank { "Secteur enregistré" },
            latitude = latitude,
            longitude = longitude,
            radiusKm = prefs.getInt("sector_radius_km", 50).coerceIn(10, 150)
        )
    }

    fun save(anchor: StationSearchAnchor, radiusKm: Int) {
        prefs.edit()
            .putString("sector_label", anchor.label)
            .putString("sector_latitude", anchor.latitude.toString())
            .putString("sector_longitude", anchor.longitude.toString())
            .putInt("sector_radius_km", radiusKm.coerceIn(10, 150))
            .apply()
    }

    fun recordScan(candidateCount: Int, autoKey: String?, error: String? = null) {
        prefs.edit()
            .putLong("sector_last_scan_at", System.currentTimeMillis())
            .putInt("sector_last_candidate_count", candidateCount.coerceAtLeast(0))
            .putString("sector_last_auto_key", autoKey)
            .putString("sector_last_scan_error", error)
            .apply()
    }

    fun lastScanAt(): Long = prefs.getLong("sector_last_scan_at", 0L)
    fun lastCandidateCount(): Int = prefs.getInt("sector_last_candidate_count", 0)
    fun lastAutoKey(): String? = prefs.getString("sector_last_auto_key", null)
    fun lastScanError(): String? = prefs.getString("sector_last_scan_error", null)
}
''')

write(APP / "StationDiscovery.kt", r'''
package com.fabdata.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Looper
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL
import java.time.LocalDate
import java.time.ZoneId
import kotlin.coroutines.resume
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
    private val heatPrefs = context.getSharedPreferences("fabdata_station_heat_cache", Context.MODE_PRIVATE)
    private val heatCacheTtlMs = 7L * 24L * 60L * 60L * 1000L

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

    /**
     * GPS v0.18.1 : on réutilise une position récente, sinon on demande réellement
     * une nouvelle position ponctuelle. Une dernière position plus ancienne reste un secours.
     */
    @SuppressLint("MissingPermission")
    suspend fun gpsAnchor(): StationSearchAnchor {
        val fine = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarse = context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (!fine && !coarse) error("Permission de localisation refusée")

        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val providers = listOf(
            LocationManager.GPS_PROVIDER,
            LocationManager.NETWORK_PROVIDER,
            LocationManager.PASSIVE_PROVIDER
        ).filter { runCatching { manager.isProviderEnabled(it) }.getOrDefault(false) }

        val last = providers.mapNotNull { provider ->
            runCatching { manager.getLastKnownLocation(provider) }.getOrNull()
        }.maxByOrNull { it.time }

        val recent = last?.takeIf { System.currentTimeMillis() - it.time <= 30L * 60L * 1000L }
        val fresh = if (recent == null) {
            val provider = providers.firstOrNull { it != LocationManager.PASSIVE_PROVIDER }
                ?: providers.firstOrNull()
            if (provider == null) null
            else withTimeoutOrNull(10_000L) { awaitSingleLocation(manager, provider) }
        } else null

        val best = recent ?: fresh ?: last ?: error("Position GPS indisponible pour l'instant")
        val resolved = runCatching { reverse(best.latitude, best.longitude) }.getOrNull()
        return resolved?.copy(label = "GPS · ${resolved.label}")
            ?: StationSearchAnchor("GPS", best.latitude, best.longitude)
    }

    @SuppressLint("MissingPermission")
    private suspend fun awaitSingleLocation(manager: LocationManager, provider: String): Location? =
        suspendCancellableCoroutine { continuation ->
            val listener = object : LocationListener {
                override fun onLocationChanged(location: Location) {
                    runCatching { manager.removeUpdates(this) }
                    if (continuation.isActive) continuation.resume(location)
                }
            }
            runCatching {
                @Suppress("DEPRECATION")
                manager.requestSingleUpdate(provider, listener, Looper.getMainLooper())
            }.onFailure {
                if (continuation.isActive) continuation.resume(null)
            }
            continuation.invokeOnCancellation { runCatching { manager.removeUpdates(listener) } }
        }

    /**
     * L'index est relu à chaque sondage. Les statistiques climatiques, elles, sont mises
     * en cache 7 jours afin que la réévaluation au retour dans l'app reste légère.
     */
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
            .toList()

        if (stations.isEmpty()) {
            error("Aucune station météo trouvée dans un rayon de $radius km")
        }

        val endYear = LocalDate.now(zone).year - 1
        val startYear = endYear - 9
        val cached = linkedMapOf<String, StationHeatStats>()
        val missing = mutableListOf<WeatherReference>()
        stations.forEach { candidate ->
            val value = readCachedHeat(candidate.reference, startYear, endYear)
            if (value != null) cached[candidate.reference.key] = value
            else missing += candidate.reference
        }

        val fetched = if (missing.isEmpty()) emptyMap() else {
            runCatching { fetchHeatStats(missing, startYear, endYear) }.getOrDefault(emptyMap())
        }
        fetched.forEach { (key, stats) ->
            val ref = missing.firstOrNull { it.key == key }
            if (ref != null) saveCachedHeat(ref, startYear, endYear, stats)
        }
        val heat = cached + fetched

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
        val publicFallback = "https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson"
        if (credential.isBlank()) {
            return httpGet(publicFallback, null)
        }
        val endpoints = listOf(
            "https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations",
            "https://public-api.meteofrance.fr/public/DPObs/liste-stations"
        )
        endpoints.forEach { endpoint ->
            runCatching { httpGet(endpoint, credential) }.onSuccess { return it }
        }
        return httpGet(publicFallback, null)
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

            val id = firstString(props, "id", "geo_id_insee", "num_poste", "id_station", "station_id", "code", "code_station", "numer_sta") ?: continue
            val name = firstString(props, "nom", "nom_usuel", "name", "station", "libelle", "libelle_station", "lieu") ?: "Station $id"
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

    private fun cacheKey(reference: WeatherReference, startYear: Int, endYear: Int): String =
        "${reference.key}:$startYear:$endYear"

    private fun readCachedHeat(reference: WeatherReference, startYear: Int, endYear: Int): StationHeatStats? {
        val raw = heatPrefs.getString(cacheKey(reference, startYear, endYear), null) ?: return null
        return runCatching {
            val json = JSONObject(raw)
            val savedAt = json.getLong("savedAt")
            if (System.currentTimeMillis() - savedAt > heatCacheTtlMs) return null
            StationHeatStats(
                p95C = json.getDouble("p95"),
                recordC = json.getDouble("record"),
                days = json.getInt("days"),
                years = json.getInt("years")
            )
        }.getOrNull()
    }

    private fun saveCachedHeat(
        reference: WeatherReference,
        startYear: Int,
        endYear: Int,
        stats: StationHeatStats
    ) {
        val json = JSONObject()
            .put("savedAt", System.currentTimeMillis())
            .put("p95", stats.p95C)
            .put("record", stats.recordC)
            .put("days", stats.days)
            .put("years", stats.years)
        heatPrefs.edit().putString(cacheKey(reference, startYear, endYear), json.toString()).apply()
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
            setRequestProperty("User-Agent", "FabData/0.18.1 Android")
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
''')

write(APP / "StationDiscoveryUi.kt", r'''
package com.fabdata.app

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

@Composable
fun StationDiscoveryDialog(
    currentReference: WeatherReference,
    credentials: MeteoFranceCredentialStore,
    onDismiss: () -> Unit,
    onSelect: (WeatherReference, Boolean) -> Unit
) {
    val context = LocalContext.current
    val discovery = remember { WeatherStationDiscovery(context, credentials) }
    val sectorPrefs = remember { WeatherStationSectorPrefs(context) }
    val savedSector = remember { sectorPrefs.load() }
    val scope = rememberCoroutineScope()

    var query by rememberSaveable { mutableStateOf(savedSector?.label ?: currentReference.city) }
    var latitudeText by rememberSaveable { mutableStateOf(savedSector?.latitude?.let { String.format(Locale.ROOT, "%.6f", it) }.orEmpty()) }
    var longitudeText by rememberSaveable { mutableStateOf(savedSector?.longitude?.let { String.format(Locale.ROOT, "%.6f", it) }.orEmpty()) }
    var radiusKm by rememberSaveable { mutableIntStateOf(savedSector?.radiusKm ?: 50) }
    var busy by remember { mutableStateOf(false) }
    var info by remember {
        mutableStateOf(
            savedSector?.let { "Secteur mémorisé · ${it.label} · resondage automatique à l'ouverture." }
                ?: "Choisis un lieu puis FabData cherchera toutes les stations du secteur."
        )
    }
    var result by remember { mutableStateOf<StationDiscoveryResult?>(null) }
    var selectedIndex by remember { mutableIntStateOf(0) }
    var mapOpen by remember { mutableStateOf(false) }
    var openMapAfterScan by remember { mutableStateOf(false) }

    fun runScan(openMapWhenReady: Boolean = false, anchorProvider: suspend () -> StationSearchAnchor) {
        if (busy) return
        if (openMapWhenReady) openMapAfterScan = true
        scope.launch {
            busy = true
            info = "Localisation · nouvel index des stations · classement chaleur…"
            val outcome = withContext(Dispatchers.IO) {
                try {
                    val anchor = anchorProvider()
                    Result.success(discovery.discover(anchor, radiusKm))
                } catch (error: Throwable) {
                    Result.failure(error)
                }
            }
            outcome.fold(
                onSuccess = { found ->
                    result = found
                    sectorPrefs.save(found.anchor, found.radiusKm)
                    sectorPrefs.recordScan(found.candidates.size, found.autoCandidate?.reference?.key)
                    query = found.anchor.label
                    latitudeText = String.format(Locale.ROOT, "%.6f", found.anchor.latitude)
                    longitudeText = String.format(Locale.ROOT, "%.6f", found.anchor.longitude)
                    selectedIndex = found.candidates.indexOfFirst { it.reference.key == currentReference.key }
                        .takeIf { it >= 0 }
                        ?: found.autoCandidate?.let { auto ->
                            found.candidates.indexOfFirst { it.reference.key == auto.reference.key }
                        }?.coerceAtLeast(0)
                        ?: 0
                    val warm = found.candidates.count { it.heat != null }
                    val catalogue = if (credentials.hasCredential()) "index Météo-France" else "catalogue public élargi"
                    info = "${found.anchor.label} · ${found.candidates.size} station(s) à ≤ ${found.radiusKm} km · $warm classée(s) · $catalogue · ${found.historyLabel}"
                    if (openMapAfterScan) {
                        openMapAfterScan = false
                        mapOpen = true
                    }
                },
                onFailure = { error ->
                    openMapAfterScan = false
                    sectorPrefs.recordScan(0, null, error.message)
                    info = error.message ?: "Recherche des stations impossible"
                }
            )
            busy = false
        }
    }

    LaunchedEffect(Unit) {
        savedSector?.let { memory -> runScan(anchorProvider = { memory.anchor() }) }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.any { it }) {
            runScan(anchorProvider = { discovery.gpsAnchor() })
        } else {
            info = "Permission GPS refusée · utilise adresse, code postal, ville, coordonnées ou la carte."
        }
    }

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Sondes proches · Auto protection") },
        text = {
            Column(
                Modifier.heightIn(max = 610.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    "Auto protection privilégie la station du secteur historiquement la plus chaude. Le secteur et le rayon restent mémorisés ; l'index est resondé à chaque retour dans l'app.",
                    style = MaterialTheme.typography.bodySmall
                )

                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Adresse · code postal · ville") },
                    singleLine = true,
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                )
                Button(
                    onClick = { runScan(anchorProvider = { discovery.geocode(query) }) },
                    enabled = !busy && query.trim().length >= 2,
                    modifier = Modifier.fillMaxWidth()
                ) { Text(if (busy) "Recherche…" else "Chercher autour de ce lieu") }

                OutlinedButton(
                    onClick = {
                        val fine = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                        val coarse = context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
                        if (fine || coarse) {
                            runScan(anchorProvider = { discovery.gpsAnchor() })
                        } else {
                            permissionLauncher.launch(
                                arrayOf(
                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                    Manifest.permission.ACCESS_COARSE_LOCATION
                                )
                            )
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) { Text("📍 Ma position GPS") }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = latitudeText,
                        onValueChange = { latitudeText = it },
                        label = { Text("Latitude") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                        enabled = !busy,
                        modifier = Modifier.weight(1f)
                    )
                    OutlinedTextField(
                        value = longitudeText,
                        onValueChange = { longitudeText = it },
                        label = { Text("Longitude") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                        enabled = !busy,
                        modifier = Modifier.weight(1f)
                    )
                }
                OutlinedButton(
                    onClick = {
                        val lat = latitudeText.trim().replace(',', '.').toDoubleOrNull()
                        val lon = longitudeText.trim().replace(',', '.').toDoubleOrNull()
                        if (lat == null || lon == null) {
                            info = "Coordonnées invalides"
                        } else {
                            runScan(anchorProvider = { discovery.reverse(lat, lon) })
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) { Text("Utiliser ces coordonnées") }

                Text("Rayon de recherche", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(25, 50, 100).forEach { km ->
                        FilterChip(
                            selected = radiusKm == km,
                            onClick = {
                                radiusKm = km
                                result?.anchor?.let { anchor -> runScan(anchorProvider = { anchor }) }
                            },
                            label = { Text("$km km") },
                            enabled = !busy
                        )
                    }
                }

                OutlinedButton(
                    onClick = {
                        val found = result
                        if (found != null && found.candidates.isNotEmpty()) {
                            mapOpen = true
                        } else {
                            val lat = latitudeText.trim().replace(',', '.').toDoubleOrNull()
                            val lon = longitudeText.trim().replace(',', '.').toDoubleOrNull()
                            when {
                                lat != null && lon != null -> runScan(openMapWhenReady = true, anchorProvider = { discovery.reverse(lat, lon) })
                                query.trim().length >= 2 -> runScan(openMapWhenReady = true, anchorProvider = { discovery.geocode(query) })
                                savedSector != null -> runScan(openMapWhenReady = true, anchorProvider = { savedSector.anchor() })
                                else -> runScan(
                                    openMapWhenReady = true,
                                    anchorProvider = {
                                        StationSearchAnchor(
                                            "Autour de ${currentReference.label}",
                                            currentReference.latitude,
                                            currentReference.longitude,
                                            currentReference.departmentId
                                        )
                                    }
                                )
                            }
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) { Text("🗺 Choisir sur la carte") }

                Text(info, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)

                val found = result
                if (found != null && found.candidates.isNotEmpty()) {
                    val auto = found.autoCandidate
                    if (auto != null) {
                        Card(shape = RoundedCornerShape(14.dp)) {
                            Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                Text("★ Auto protection", fontWeight = FontWeight.Bold)
                                Text(auto.reference.stationName, fontWeight = FontWeight.SemiBold)
                                Text(candidateLine(auto), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }

                    Text("Tourniquet · toutes les stations locales", fontWeight = FontWeight.SemiBold)
                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(7.dp)
                    ) {
                        found.candidates.forEachIndexed { index, candidate ->
                            FilterChip(
                                selected = selectedIndex == index,
                                onClick = { selectedIndex = index },
                                label = {
                                    Column {
                                        Text(candidate.reference.stationName)
                                        Text(candidateLine(candidate), style = MaterialTheme.typography.labelSmall)
                                    }
                                }
                            )
                        }
                    }

                    val current = found.candidates[selectedIndex.coerceIn(0, found.candidates.lastIndex)]
                    Card(shape = RoundedCornerShape(14.dp)) {
                        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text("${selectedIndex + 1}/${found.candidates.size} · ${current.reference.stationName}", fontWeight = FontWeight.SemiBold)
                            Text(candidateLine(current), style = MaterialTheme.typography.bodySmall)
                            Text("ID ${current.reference.stationId}", style = MaterialTheme.typography.labelSmall)
                        }
                    }

                    Button(
                        onClick = {
                            val selected = auto ?: return@Button
                            sectorPrefs.save(found.anchor, found.radiusKm)
                            onSelect(selected.reference, true)
                        },
                        enabled = !busy && auto != null,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Utiliser Auto protection") }

                    OutlinedButton(
                        onClick = {
                            sectorPrefs.save(found.anchor, found.radiusKm)
                            onSelect(current.reference, false)
                        },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth()
                    ) { Text("Choisir cette station manuellement") }

                    Text(
                        "Indice chaud = 95e percentile des maximales estivales (juin–septembre), calculé sur une période homogène. Le record reste un contexte et ne décide pas seul du classement.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !busy) { Text("Fermer") }
        }
    )

    val mapped = result
    if (mapOpen && mapped != null && mapped.candidates.isNotEmpty()) {
        StationMapDialog(
            result = mapped,
            initialIndex = selectedIndex,
            onDismiss = { mapOpen = false },
            onSelectIndex = { index ->
                val safeIndex = index.coerceIn(0, mapped.candidates.lastIndex)
                selectedIndex = safeIndex
                sectorPrefs.save(mapped.anchor, mapped.radiusKm)
                mapOpen = false
                onSelect(mapped.candidates[safeIndex].reference, false)
            }
        )
    }
}

private fun candidateLine(candidate: StationCandidate): String {
    val distance = String.format(Locale.FRANCE, "%.1f km", candidate.distanceKm)
    val heat = candidate.heat ?: return "$distance · indice chaud indisponible"
    return "$distance · P95 ${String.format(Locale.FRANCE, "%.1f", heat.p95C)} °C · record ${String.format(Locale.FRANCE, "%.1f", heat.recordC)} °C · ${heat.years} étés"
}
''')

write(APP / "LiveUpdateCoordinator.kt", r'''
package com.fabdata.app

import androidx.activity.ComponentActivity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * Orchestrateur toujours composé, indépendant des cartes LazyColumn.
 *
 * - uniquement quand l'app est réellement au premier plan ;
 * - ouverture / retour au focus : resondage Auto du secteur puis météo fraîche ;
 * - ensuite toutes les 5 minutes tant que l'utilisateur regarde l'app ;
 * - lorsqu'une vraie mesure intérieure change : météo fraîche -> inertie/reconstruction -> forecast ;
 * - un changement reçu en arrière-plan est seulement mémorisé, aucun calcul n'y est lancé ;
 * - ne modifie jamais directement une mesure MEASURED.
 */
@Composable
fun FabLiveUpdateCoordinator(
    db: FabDataDb,
    lyonLab: LyonLabStore,
    credentials: MeteoFranceCredentialStore,
    dataVersion: Int,
    onDataChanged: () -> Unit
) {
    val context = LocalContext.current
    val activity = context as? ComponentActivity
    val weatherPrefs = remember { WeatherReferencePrefs(context) }
    val sectorPrefs = remember { WeatherStationSectorPrefs(context) }
    val discovery = remember { WeatherStationDiscovery(context, credentials) }
    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val profileStore = remember { ThermalProfileStore(context) }
    val modelPrefs = remember {
        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)
    }
    val lyonWeather = remember { LyonWeatherSync(db) }
    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, credentials) }
    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }
    val coherenceStore = remember { ThermalCoherenceStore(db) }

    var foreground by remember {
        mutableStateOf(activity?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) == true)
    }
    var working by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
    var pendingMeasuredRefresh by remember { mutableStateOf(false) }

    DisposableEffect(activity) {
        if (activity == null) return@DisposableEffect onDispose { }
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> foreground = true
                Lifecycle.Event.ON_PAUSE, Lifecycle.Event.ON_STOP -> foreground = false
                else -> Unit
            }
        }
        activity.lifecycle.addObserver(observer)
        onDispose { activity.lifecycle.removeObserver(observer) }
    }

    suspend fun updateLive(rebuildFromMeasured: Boolean, reevaluateAuto: Boolean = false): Boolean {
        if (!foreground || working) return false
        working = true
        return try {
            withContext(Dispatchers.IO) {
                val initialReference = weatherPrefs.selectedReference()
                var reference = initialReference
                var referenceChanged = false

                // v0.18.1 : à chaque ouverture/retour au premier plan, Auto protection
                // relit réellement l'index du secteur mémorisé. Les statistiques historiques
                // sont cachées 7 jours dans WeatherStationDiscovery, donc ce sondage reste léger.
                if (reevaluateAuto && weatherPrefs.autoProtection()) {
                    val sector = sectorPrefs.load()
                    if (sector != null) {
                        runCatching { discovery.discover(sector.anchor(), sector.radiusKm) }
                            .onSuccess { scan ->
                                sectorPrefs.save(scan.anchor, scan.radiusKm)
                                sectorPrefs.recordScan(scan.candidates.size, scan.autoCandidate?.reference?.key)
                                val selected = scan.autoCandidate?.reference
                                if (selected != null && selected.key != reference.key) {
                                    weatherPrefs.select(selected)
                                    weatherPrefs.setAutoProtection(true)
                                    reference = selected
                                    referenceChanged = true
                                }
                            }
                            .onFailure { error ->
                                sectorPrefs.recordScan(0, null, error.message)
                            }
                    }
                }

                if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                    if (credentials.hasCredential()) {
                        runCatching { meteoOfficial.syncSixMinute24h() }
                    } else {
                        runCatching { lyonWeather.syncToday() }
                    }
                }

                PointSourceStore.reconcileMeasuredDominance(db)
                manager.refreshRecent(reference)

                val profile = profileStore.load()
                val mode = profileStore.forecastMode()
                val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }
                val rebuildExisting = rebuildFromMeasured || referenceChanged

                if (rebuildExisting) {
                    selectedSensorId?.let { id ->
                        val firstReal = coherenceStore.firstMeasuredTimestamp(id)
                        val existing = PointSourceStore.reconstructedBounds(db, id)
                        if (firstReal != null && existing != null) {
                            val recentStart = firstReal - 366L * 24L * 60L * 60L * 1000L
                            if (existing.first < recentStart) {
                                val reason = if (referenceChanged) {
                                    "Auto protection : changement de station météo, historique antérieur aux 12 derniers mois à remettre à jour"
                                } else {
                                    "Nouvelle mesure réelle : historique antérieur aux 12 derniers mois à remettre à jour"
                                }
                                historyDebtStore.recordDebt(reference.key, id, existing.first, recentStart, reason)
                            }
                        }
                    }
                    engine.refreshExistingReconstructions(reference, profile, selectedSensorId, maxHistoryDays = 366)
                }
                engine.refreshForecasts(reference, selectedSensorId, profile, mode)
            }
            onDataChanged()
            true
        } finally {
            working = false
        }
    }

    LaunchedEffect(dataVersion) {
        val current = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val previous = measuredRevision
        measuredRevision = current
        if (previous != null && current != previous) {
            pendingMeasuredRefresh = true
            if (foreground && updateLive(rebuildFromMeasured = true, reevaluateAuto = false)) {
                pendingMeasuredRefresh = false
            }
        }
    }

    // Chaque retour au premier plan = un nouveau sondage du secteur en mode Auto.
    // Les boucles de 5 minutes ne resondent pas l'index : elles rafraîchissent seulement
    // la station déjà retenue et les calculs courants.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect

        val rebuildNow = pendingMeasuredRefresh
        if (updateLive(rebuildFromMeasured = rebuildNow, reevaluateAuto = true) && rebuildNow) {
            pendingMeasuredRefresh = false
        }

        while (true) {
            delay(300_000L)
            if (!foreground) break
            val rebuild = pendingMeasuredRefresh
            if (updateLive(rebuildFromMeasured = rebuild, reevaluateAuto = false) && rebuild) {
                pendingMeasuredRefresh = false
            }
        }
    }
}
''')

thermal = APP / "ThermalUi.kt"
thermal_text = thermal.read_text(encoding="utf-8")
old = '''    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        if (busy) return@LaunchedEffect
'''
new = '''    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        // La station peut avoir changé automatiquement lors du resondage de secteur
        // effectué au retour au premier plan. Synchroniser d'abord l'état Compose,
        // puis seulement lancer les calculs pour éviter de recharger l'ancienne station.
        val persistedKey = prefs.selectedKey()
        if (persistedKey != selectedKey) {
            selectedKey = persistedKey
            return@LaunchedEffect
        }
        if (busy) return@LaunchedEffect
'''
if new not in thermal_text:
    if old not in thermal_text:
        raise SystemExit("ThermalUi anchor not found")
    thermal_text = thermal_text.replace(old, new, 1)
    thermal.write_text(thermal_text, encoding="utf-8")

build = ROOT / "app/build.gradle.kts"
build_text = build.read_text(encoding="utf-8")
build_text = build_text.replace('versionCode = 34', 'versionCode = 35')
build_text = build_text.replace('versionName = "0.18.0"', 'versionName = "0.18.1"')
build.write_text(build_text, encoding="utf-8")

print("FabData v0.18.1 station discovery fix generated")
