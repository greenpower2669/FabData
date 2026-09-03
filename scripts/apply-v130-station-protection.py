#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable")
    return text.replace(old, new, 1)


# Version uniquement. Aucun fichier du moteur thermique n'est modifié par ce patch.
gradle_path = "app/build.gradle.kts"
gradle = read(gradle_path)
gradle = replace_once(
    gradle,
    '        versionCode = 26\n        versionName = "0.12.2"',
    '        versionCode = 27\n        versionName = "0.13.0"',
    "version"
)
write(gradle_path, gradle)

# Permissions GPS additives : l'adresse/ville/coordonnées restent utilisables sans les accepter.
manifest_path = "app/src/main/AndroidManifest.xml"
manifest = read(manifest_path)
if 'android.permission.ACCESS_COARSE_LOCATION' not in manifest:
    manifest = manifest.replace(
        '    <uses-permission android:name="android.permission.INTERNET" />',
        '    <uses-permission android:name="android.permission.INTERNET" />\n'
        '    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />\n'
        '    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />',
        1
    )
write(manifest_path, manifest)

weather_path = "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt"
weather = read(weather_path)
weather = replace_once(
    weather,
    '''    val longitude: Double,
    val departmentId: String
) {''',
    '''    val longitude: Double,
    val departmentId: String,
    val altitudeM: Double? = null
) {''',
    "WeatherReference altitude"
)

old_prefs = '''class WeatherReferencePrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)
    fun selectedKey(): String = prefs.getString("selected_key", WeatherReferenceCatalog.DEFAULT_KEY)
        ?: WeatherReferenceCatalog.DEFAULT_KEY
    fun select(key: String) = prefs.edit().putString("selected_key", WeatherReferenceCatalog.byKey(key).key).apply()
}'''
new_prefs = '''class WeatherReferencePrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)

    fun selectedReference(): WeatherReference {
        val key = prefs.getString("selected_key", WeatherReferenceCatalog.DEFAULT_KEY)
            ?: WeatherReferenceCatalog.DEFAULT_KEY
        val stationId = prefs.getString("station_id", null)
        val lat = prefs.getString("station_latitude", null)?.toDoubleOrNull()
        val lon = prefs.getString("station_longitude", null)?.toDoubleOrNull()
        if (!stationId.isNullOrBlank() && lat != null && lon != null && prefs.getString("station_key", key) == key) {
            return WeatherReference(
                key = key,
                city = prefs.getString("station_city", null).orEmpty().ifBlank { prefs.getString("station_name", null).orEmpty().ifBlank { "Station" } },
                stationName = prefs.getString("station_name", null).orEmpty().ifBlank { "Station $stationId" },
                stationId = stationId,
                latitude = lat,
                longitude = lon,
                departmentId = prefs.getString("station_department", "").orEmpty(),
                altitudeM = prefs.getString("station_altitude", null)?.toDoubleOrNull()
            )
        }
        return WeatherReferenceCatalog.byKey(key)
    }

    fun selectedKey(): String = selectedReference().key

    /** Compatibilité avec le sélecteur historique codé en dur. */
    fun select(key: String) = select(WeatherReferenceCatalog.byKey(key), autoProtection = false)

    fun select(reference: WeatherReference, autoProtection: Boolean) {
        prefs.edit()
            .putString("selected_key", reference.key)
            .putString("station_key", reference.key)
            .putString("station_id", reference.stationId)
            .putString("station_city", reference.city)
            .putString("station_name", reference.stationName)
            .putString("station_latitude", reference.latitude.toString())
            .putString("station_longitude", reference.longitude.toString())
            .putString("station_department", reference.departmentId)
            .putString("station_altitude", reference.altitudeM?.toString())
            .putBoolean("auto_protection", autoProtection)
            .apply()
    }

    fun autoProtection(): Boolean = prefs.getBoolean("auto_protection", false)

    fun saveSector(origin: StationSearchOrigin, radiusKm: Int) {
        prefs.edit()
            .putString("sector_label", origin.label)
            .putString("sector_latitude", origin.latitude.toString())
            .putString("sector_longitude", origin.longitude.toString())
            .putInt("sector_radius_km", radiusKm.coerceIn(5, 200))
            .apply()
    }

    fun sectorLabel(): String? = prefs.getString("sector_label", null)
    fun sectorLatitude(): Double? = prefs.getString("sector_latitude", null)?.toDoubleOrNull()
    fun sectorLongitude(): Double? = prefs.getString("sector_longitude", null)?.toDoubleOrNull()
    fun sectorRadiusKm(): Int = prefs.getInt("sector_radius_km", 50).coerceIn(5, 200)
}'''
weather = replace_once(weather, old_prefs, new_prefs, "WeatherReferencePrefs")
write(weather_path, weather)

ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)
ui = replace_once(
    ui,
    '''    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
    val reference = WeatherReferenceCatalog.byKey(selectedKey)
    var menuOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
''',
    '''    var reference by remember { mutableStateOf(prefs.selectedReference()) }
    val selectedKey = reference.key
    var menuOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
''',
    "ThermalUi reference"
)
ui = replace_once(
    ui,
    '''    var selectedSensorId by remember { mutableStateOf<Long?>(null) }
    var profileDialog by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
''',
    '''    var selectedSensorId by remember { mutableStateOf<Long?>(null) }
    var profileDialog by remember { mutableStateOf(false) }
    var stationDiscoveryDialog by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
''',
    "ThermalUi dialog state"
)
ui = replace_once(
    ui,
    '''                Column {
                    OutlinedButton(onClick = { menuOpen = true }) { Text("Changer") }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        WeatherReferenceCatalog.stations.forEach { station ->
                            DropdownMenuItem(
                                text = { Text(station.label) },
                                onClick = {
                                    prefs.select(station.key)
                                    selectedKey = station.key
                                    menuOpen = false
                                }
                            )
                        }
                    }
                }
            }

            Text(info, style = MaterialTheme.typography.bodySmall)
''',
    '''                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    OutlinedButton(onClick = { menuOpen = true }, enabled = !busy) { Text("Changer") }
                    OutlinedButton(onClick = { stationDiscoveryDialog = true }, enabled = !busy) { Text("Secteur / Auto") }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        WeatherReferenceCatalog.stations.forEach { station ->
                            DropdownMenuItem(
                                text = { Text(station.label) },
                                onClick = {
                                    prefs.select(station.key)
                                    reference = station
                                    menuOpen = false
                                }
                            )
                        }
                    }
                }
            }

            Text(
                if (prefs.autoProtection()) "★ Auto protection · plus chaude historiquement dans le secteur"
                else "Sélection manuelle · une seule station pilote le RC",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Text(info, style = MaterialTheme.typography.bodySmall)
''',
    "ThermalUi station controls"
)
ui = replace_once(
    ui,
    '''    if (profileDialog) {
        ThermalProfileDialog(
''',
    '''    if (stationDiscoveryDialog) {
        WeatherStationDiscoveryDialog(
            credentials = credentials,
            current = reference,
            prefs = prefs,
            onDismiss = { stationDiscoveryDialog = false },
            onSelect = { station, auto ->
                reference = station
                stationDiscoveryDialog = false
                info = if (auto) {
                    "Auto protection · ${station.label} · actualisation…"
                } else {
                    "Station choisie · ${station.label} · actualisation…"
                }
            }
        )
    }

    if (profileDialog) {
        ThermalProfileDialog(
''',
    "ThermalUi station dialog"
)
write(ui_path, ui)

main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)
main = replace_once(
    main,
    '    val visualReference = WeatherReferenceCatalog.byKey(WeatherReferencePrefs(context).selectedKey())',
    '    val visualReference = WeatherReferencePrefs(context).selectedReference()',
    "MainActivity dynamic reference"
)
write(main_path, main)

print("FabData v0.13.0 station protection patch applied; ThermalEngine untouched")
