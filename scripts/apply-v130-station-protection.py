#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"{label}: déjà appliqué")
        return
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: OK")


replace_once(
    "app/build.gradle.kts",
    '        versionCode = 26\n        versionName = "0.12.2"',
    '        versionCode = 27\n        versionName = "0.13.0"',
    "Version 0.13.0 / code 27",
)

replace_once(
    "app/src/main/AndroidManifest.xml",
    '    <uses-permission android:name="android.permission.INTERNET" />',
    '    <uses-permission android:name="android.permission.INTERNET" />\n    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />\n    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />',
    "Permissions GPS",
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '    fun byKey(key: String?): WeatherReference = stations.firstOrNull { it.key == key } ?: stations.first()\n}\n\nclass WeatherReferencePrefs(context: Context) {\n    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)\n    fun selectedKey(): String = prefs.getString("selected_key", WeatherReferenceCatalog.DEFAULT_KEY)\n        ?: WeatherReferenceCatalog.DEFAULT_KEY\n    fun select(key: String) = prefs.edit().putString("selected_key", WeatherReferenceCatalog.byKey(key).key).apply()\n}',
    '''    fun byKeyOrNull(key: String?): WeatherReference? = stations.firstOrNull { it.key == key }
    fun byKey(key: String?): WeatherReference = byKeyOrNull(key) ?: stations.first()
}

class WeatherReferencePrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)

    fun selectedKey(): String = prefs.getString("selected_key", WeatherReferenceCatalog.DEFAULT_KEY)
        ?: WeatherReferenceCatalog.DEFAULT_KEY

    fun selectedReference(): WeatherReference {
        val key = selectedKey()
        WeatherReferenceCatalog.byKeyOrNull(key)?.let { return it }
        if (prefs.getString("custom_key", null) == key) {
            val latitude = prefs.getString("custom_latitude", null)?.toDoubleOrNull()
            val longitude = prefs.getString("custom_longitude", null)?.toDoubleOrNull()
            val stationId = prefs.getString("custom_station_id", null)
            val stationName = prefs.getString("custom_station_name", null)
            val city = prefs.getString("custom_city", null)
            val departmentId = prefs.getString("custom_department_id", null).orEmpty()
            if (latitude != null && longitude != null && !stationId.isNullOrBlank() && !stationName.isNullOrBlank()) {
                return WeatherReference(
                    key = key,
                    city = city?.takeIf { it.isNotBlank() } ?: stationName,
                    stationName = stationName,
                    stationId = stationId,
                    latitude = latitude,
                    longitude = longitude,
                    departmentId = departmentId
                )
            }
        }
        return WeatherReferenceCatalog.byKey(null)
    }

    fun select(key: String) = select(WeatherReferenceCatalog.byKey(key))

    fun select(reference: WeatherReference) {
        val editor = prefs.edit().putString("selected_key", reference.key)
        if (WeatherReferenceCatalog.byKeyOrNull(reference.key) != null) {
            editor.remove("custom_key")
                .remove("custom_city")
                .remove("custom_station_name")
                .remove("custom_station_id")
                .remove("custom_latitude")
                .remove("custom_longitude")
                .remove("custom_department_id")
        } else {
            editor.putString("custom_key", reference.key)
                .putString("custom_city", reference.city)
                .putString("custom_station_name", reference.stationName)
                .putString("custom_station_id", reference.stationId)
                .putString("custom_latitude", reference.latitude.toString())
                .putString("custom_longitude", reference.longitude.toString())
                .putString("custom_department_id", reference.departmentId)
        }
        editor.apply()
    }

    fun autoProtection(): Boolean = prefs.getBoolean("station_auto_protection", false)
    fun setAutoProtection(enabled: Boolean) = prefs.edit().putBoolean("station_auto_protection", enabled).apply()
}''',
    "Référence météo dynamique persistante",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }\n    val reference = WeatherReferenceCatalog.byKey(selectedKey)\n    var menuOpen by remember { mutableStateOf(false) }\n    var busy by remember { mutableStateOf(false) }',
    '    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }\n    val reference = remember(selectedKey) { prefs.selectedReference() }\n    var menuOpen by remember { mutableStateOf(false) }\n    var stationDiscoveryOpen by remember { mutableStateOf(false) }\n    var busy by remember { mutableStateOf(false) }',
    "ThermalUi référence dynamique",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '                "Lyon reste la référence par défaut. Une seule station charge ses séries à la fois.",',
    '                "Lyon reste le secours par défaut. Auto protection peut choisir la station historiquement la plus chaude du secteur ; une seule station charge ses séries à la fois.",',
    "ThermalUi texte protection",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '                    Text("ID ${reference.stationId}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)',
    '                    Text("ID ${reference.stationId} · ${if (prefs.autoProtection()) "★ Auto protection" else "choix manuel"}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)',
    "ThermalUi mode station",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                                onClick = {
                                    prefs.select(station.key)
                                    selectedKey = station.key
                                    menuOpen = false
                                }''',
    '''                                onClick = {
                                    prefs.setAutoProtection(false)
                                    prefs.select(station.key)
                                    selectedKey = station.key
                                    menuOpen = false
                                }''',
    "ThermalUi menu manuel",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''            }

            Text(info, style = MaterialTheme.typography.bodySmall)''',
    '''            }

            OutlinedButton(
                onClick = { stationDiscoveryOpen = true },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Sondes proches · Auto protection") }

            Text(info, style = MaterialTheme.typography.bodySmall)''',
    "ThermalUi bouton découverte",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''    if (profileDialog) {
        ThermalProfileDialog(''',
    '''    if (stationDiscoveryOpen) {
        StationDiscoveryDialog(
            currentReference = reference,
            credentials = credentials,
            onDismiss = { stationDiscoveryOpen = false },
            onSelect = { station, auto ->
                prefs.setAutoProtection(auto)
                prefs.select(station)
                selectedKey = station.key
                stationDiscoveryOpen = false
            }
        )
    }

    if (profileDialog) {
        ThermalProfileDialog(''',
    "ThermalUi dialogue découverte",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '    val visualReference = WeatherReferenceCatalog.byKey(WeatherReferencePrefs(context).selectedKey())',
    '    val visualReference = WeatherReferencePrefs(context).selectedReference()',
    "MainActivity référence dynamique",
)

print("v0.13.0 station protection patch complete")
