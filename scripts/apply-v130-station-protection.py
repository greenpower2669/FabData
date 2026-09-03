#!/usr/bin/env python3
from pathlib import Path
import base64

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def write(path, text):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"{label}: bloc introuvable")

STATION_LOGIC = base64.b64decode("cGFja2FnZSBjb20uZmFiZGF0YS5hcHAKCmltcG9ydCBhbmRyb2lkLk1hbmlmZXN0CmltcG9ydCBhbmRyb2lkLmNvbnRlbnQuQ29udGV4dAppbXBvcnQgYW5kcm9pZC5jb250ZW50LnBtLlBhY2thZ2VNYW5hZ2VyCmltcG9ydCBhbmRyb2lkLmxvY2F0aW9uLkxvY2F0aW9uCmltcG9ydCBhbmRyb2lkLmxvY2F0aW9uLkxvY2F0aW9uTWFuYWdlcgppbXBvcnQgYW5kcm9pZC5vcy5CdWlsZAppbXBvcnQga290bGlueC5jb3JvdXRpbmVzLnN1c3BlbmRDYW5jZWxsYWJsZUNvcm91dGluZQppbXBvcnQgb3JnLmpzb24uSlNPTkFycmF5CmltcG9ydCBvcmcuanNvbi5KU09OT2JqZWN0CmltcG9ydCBqYXZhLm5ldC5IdHRwVVJMQ29ubmVjdGlvbgppbXBvcnQgamF2YS5uZXQuVVJMRW5jb2RlcgppbXBvcnQgamF2YS5uZXQuVVJMCmltcG9ydCBqYXZhLnRpbWUuTG9jYWxEYXRlCmltcG9ydCBqYXZhLnRpbWUuWm9uZUlkCmltcG9ydCBqYXZhLnV0aWwuTG9jYWxlCmltcG9ydCBrb3RsaW4uY29yb3V0aW5lcy5yZXN1bWUKaW1wb3J0IGtvdGxpbi5tYXRoLmFzaW4KaW1wb3J0IGtvdGxpbi5tYXRoLmNvcwppbXBvcnQga290bGluLm1hdGgucG93CmltcG9ydCBrb3RsaW4ubWF0aC5yb3VuZFRvSW50CmltcG9ydCBrb3RsaW4ubWF0aC5zaW4KaW1wb3J0IGtvdGxpbi5tYXRoLnNxcnQKCmRhdGEgY2xhc3MgU3RhdGlvblNlYXJjaE9yaWdpbigKICAgIHZhbCBsYWJlbDogU3RyaW5nLAogICAgdmFsIGxhdGl0dWRlOiBEb3VibGUsCiAgICB2YWwgbG9uZ2l0dWRlOiBEb3VibGUKKQoKZGF0YSBjbGFzcyBXZWF0aGVyU3RhdGlvbkNhbmRpZGF0ZSgKICAgIHZhbCByZWZlcmVuY2U6IFdlYXRoZXJSZWZlcmVuY2UsCiAgICB2YWwgZGlzdGFuY2VLbTogRG91YmxlLAogICAgdmFsIGhvdEluZGV4QzogRG91YmxlPyA9IG51bGwsCiAgICB2YWwgcDk1QzogRG91YmxlPyA9IG51bGwsCiAgICB2YWwgcDk5QzogRG91YmxlPyA9IG51bGwsCiAgICB2YWwgaGlzdG9yeURheXM6IEludCA9IDAKKQoKZGF0YSBjbGFzcyBTdGF0aW9uRGlzY292ZXJ5UmVzdWx0KAogICAgdmFsIG9yaWdpbjogU3RhdGlvblNlYXJjaE9yaWdpbiwKICAgIHZhbCByYWRpdXNLbTogSW50LAogICAgdmFsIGNhbmRpZGF0ZXM6IExpc3Q8V2VhdGhlclN0YXRpb25DYW5kaWRhdGU+LAogICAgdmFsIGF1dG9TZWxlY3RlZDogV2VhdGhlclN0YXRpb25DYW5kaWRhdGU/LAogICAgdmFsIGluZGV4TGFiZWw6IFN0cmluZwp9CgpjbGFzcyBXZWF0aGVyU3RhdGlvbkRpc2NvdmVyeSgKICAgIHByaXZhdGUgdmFsIGNvbnRleHQ6IENvbnRleHQsCiAgICBwcml2YXRlIHZhbCBjcmVkZW50aWFsczogTWV0ZW9GcmFuY2VDcmVkZW50aWFsU3RvcmUKKSB7CiAgICBwcml2YXRlIHZhbCB6b25lID0gWm9uZUlkLm9mKCJFdXJvcGUvUGFyaXMiKQoKICAgIHN1c3BlbmQgZnVuIGN1cnJlbnRMb2NhdGlvbigpOiBTdGF0aW9uU2VhcmNoT3JpZ2luIHsKICAgICAgICB2YWwgZmluZSA9IGNvbnRleHQuY2hlY2tTZWxmUGVybWlzc2lvbihNYW5pZmVzdC5wZXJtaXNzaW9uLkFDQ0VTU19GSU5FX0xPQ0FUSU9OKSA9PSBQYWNrYWdlTWFuYWdlci5QRVJNSVNTSU9OX0dSQU5URUQKICAgICAgICB2YWwgY29hcnNlID0gY29udGV4dC5jaGVja1NlbGZQZXJtaXNzaW9uKE1hbmlmZXN0LnBlcm1pc3Npb24uQUNDRVNTX0NPQVJTRV9MT0NBVElPTikgPT0gUGFja2FnZU1hbmFnZXIuUEVSTUlTU0lPTl9HUkFOVEVECiAgICAgICAgaWYgKCFmaW5lICYmICFjb2Fyc2UpIGVycm9yKCJBdXRvcmlzYXRpb24gZGUgbG9jYWxpc2F0aW9uIHJlcXVpc2UiKQoKICAgICAgICB2YWwgbWFuYWdlciA9IGNvbnRleHQuZ2V0U3lzdGVtU2VydmljZShDb250ZXh0LkxPQ0FUSU9OX1NFUlZJQ0UpIGFzIExvY2F0aW9uTWFuYWdlcgogICAgICAgIHZhbCBwcm92aWRlcnMgPSBsaXN0T2YoCiAgICAgICAgICAgIExvY2F0aW9uTWFuYWdlci5HUFNfUFJPVklERVIsCiAgICAgICAgICAgIExvY2F0aW9uTWFuYWdlci5ORVRXT1JLX1BST1ZJREVSLAogICAgICAgICAgICBMb2NhdGlvbk1hbmFnZXIuUEFTU0lWRV9QUk9WSURFUgogICAgICAgICkuZGlzdGluY3QoKQoKICAgICAgICB2YWwgbGFzdCA9IHByb3ZpZGVycy5tYXBOb3ROdWxsIHsgcHJvdmlkZXIgLT4KICAgICAgICAgICAgcnVuQ2F0Y2hpbmcgeyBtYW5hZ2VyLmdldExhc3RLbm93bkxvY2F0aW9uKHByb3ZpZGVyKSB9LmdldE9yTnVsbCgpCiAgICAgICAgfS5tYXhCeU9yTnVsbCB7IGl0LnRpbWUgfQoKICAgICAgICBpZiAobGFzdCAhPSBudWxsICYmIFN5c3RlbS5jdXJyZW50VGltZU1pbGxpcygpIC0gbGFzdC50aW1lIDwgNkwgKiA2MEwgKiA2MEwgKiAxMDAwTCkgewogICAgICAgICAgICByZXR1cm4gU3RhdGlvblNlYXJjaE9yaWdpbigiR1BTIiwgbGFzdC5sYXRpdHVkZSwgbGFzdC5sb25naXR1ZGUpCiAgICAgICAgfQoKICAgICAgICBpZiAoQnVpbGQuVkVSU0lPTi5TREtfSU5UID49IEJ1aWxkLlZFUlNJT05fQ09ERVMuUikgewogICAgICAgICAgICB2YWwgcHJvdmlkZXIgPSBwcm92aWRlcnMuZmlyc3RPck51bGwgeyBydW5DYXRjaGluZyB7IG1hbmFnZXIuaXNQcm92aWRlckVuYWJsZWQoaXQpIH0uZ2V0T3JEZWZhdWx0KGZhbHNlKSB9CiAgICAgICAgICAgICAgICA/OiBMb2NhdGlvbk1hbmFnZXIuUEFTU0lWRV9QUk9WSURFUgogICAgICAgICAgICB2YWwgZnJlc2ggPSBzdXNwZW5kQ2FuY2VsbGFibGVDb3JvdXRpbmU8TG9jYXRpb24/PiB7IGNvbnRpbnVhdGlvbiAtPgogICAgICAgICAgICAgICAgcnVuQ2F0Y2hpbmcgewogICAgICAgICAgICAgICAgICAgIG1hbmFnZXIuZ2V0Q3VycmVudExvY2F0aW9uKHByb3ZpZGVyLCBudWxsLCBjb250ZXh0Lm1haW5FeGVjdXRvcikgeyBsb2NhdGlvbiAtPgogICAgICAgICAgICAgICAgICAgICAgICBpZiAoY29udGludWF0aW9uLmlzQWN0aXZlKSBjb250aW51YXRpb24ucmVzdW1lKGxvY2F0aW9uKQogICAgICAgICAgICAgICAgICAgIH0KICAgICAgICAgICAgICAgIH0ub25GYWlsdXJlIHsKICAgICAgICAgICAgICAgICAgICBpZiAoY29udGludWF0aW9uLmlzQWN0aXZlKSBjb250aW51YXRpb24ucmVzdW1lKG51bGwpCiAgICAgICAgICAgICAgICB9CiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgKGZyZXNoICE9IG51bGwpIHJldHVybiBTdGF0aW9uU2VhcmNoT3JpZ2luKCJHUFMiLCBmcmVzaC5sYXRpdHVkZSwgZnJlc2gubG9uZ2l0dWRlKQogICAgICAgIH0KCiAgICAgICAgaWYgKGxhc3QgIT0gbnVsbCkgcmV0dXJuIFN0YXRpb25TZWFyY2hPcmlnaW4oIkdQUyAoZGVybmnDqHJlIHBvc2l0aW9uKSIsIGxhc3QubGF0aXR1ZGUsIGxhc3QubG9uZ2l0dWRlKQogICAgICAgIGVycm9yKCJQb3NpdGlvbiBHUFMgaW5kaXNwb25pYmxlIHBvdXIgbGUgbW9tZW50IikKICAgIH0KCiAgICBmdW4gZ2VvY29kZShxdWVyeTogU3RyaW5nKTogU3RhdGlvblNlYXJjaE9yaWdpbiB7CiAgICAgICAgdmFsIHEgPSBxdWVyeS50cmltKCkKICAgICAgICBpZiAocS5pc0JsYW5rKCkpIGVycm9yKCJBZHJlc3NlLCBjb2RlIHBvc3RhbCBvdSB2aWxsZSBtYW5xdWFudCIpCiAgICAgICAgdmFsIGVuY29kZWQgPSBVUkxFbmNvZGVyLmVuY29kZShxLCAiVVRGLTgiKQoKICAgICAgICBydW5DYXRjaGluZyB7CiAgICAgICAgICAgIHZhbCB1cmwgPSAiaHR0cHM6Ly9kYXRhLmdlb3BmLmZyL2dlb2NvZGFnZS9zZWFyY2g/cT0kZW5jb2RlZCZpbmRleD1hZGRyZXNzJmxpbWl0PTEiCiAgICAgICAgICAgIHZhbCByb290ID0gSlNPTk9iamVjdChodHRwR2V0KHVybCkpCiAgICAgICAgICAgIHZhbCBmZWF0dXJlID0gcm9vdC5vcHRKU09OQXJyYXkoImZlYXR1cmVzIik/Lm9wdEpTT05PYmplY3QoMCkgPzogZXJyb3IoIkFkcmVzc2UgaW50cm91dmFibGUiKQogICAgICAgICAgICB2YWwgY29vcmRzID0gZmVhdHVyZS5nZXRKU09OT2JqZWN0KCJnZW9tZXRyeSIpLmdldEpTT05BcnJheSgiY29vcmRpbmF0ZXMiKQogICAgICAgICAgICB2YWwgcHJvcHMgPSBmZWF0dXJlLm9wdEpTT05PYmplY3QoInByb3BlcnRpZXMiKQogICAgICAgICAgICB2YWwgbGFiZWwgPSBwcm9wcz8ub3B0U3RyaW5nKCJsYWJlbCIpPy50YWtlSWYgeyBpdC5pc05vdEJsYW5rKCkgfSA/OiBxCiAgICAgICAgICAgIFN0YXRpb25TZWFyY2hPcmlnaW4obGFiZWwsIGNvb3Jkcy5nZXREb3VibGUoMSksIGNvb3Jkcy5nZXREb3VibGUoMCkpCiAgICAgICAgfS5nZXRPck51bGwoKT8ubGV0IHsgcmV0dXJuIGl0IH0KCiAgICAgICAgdmFsIGZhbGxiYWNrID0gImh0dHBzOi8vZ2VvY29kaW5nLWFwaS5vcGVuLW1ldGVvLmNvbS92MS9zZWFyY2g/bmFtZT0kZW5jb2RlZCZjb3VudD0xJmxhbmd1YWdlPWZyJmZvcm1hdD1qc29uJmNvdW50cnlDb2RlPUZSIgogICAgICAgIHZhbCByb290ID0gSlNPTk9iamVjdChodHRwR2V0KGZhbGxiYWNrKSkKICAgICAgICB2YWwgcmVzdWx0ID0gcm9vdC5vcHRKU09OQXJyYXkoInJlc3VsdHMiKT8ub3B0SlNPTk9iamVjdCgwKSA/OiBlcnJvcigiTGlldSBpbnRyb3V2YWJsZSIpCiAgICAgICAgdmFsIGxhYmVsID0gbGlzdE9mKAogICAgICAgICAgICByZXN1bHQub3B0U3RyaW5nKCJuYW1lIiksCiAgICAgICAgICAgIHJlc3VsdC5vcHRTdHJpbmcoImFkbWluMSIpLAogICAgICAgICAgICByZXN1bHQub3B0U3RyaW5nKCJjb3VudHJ5IikKICAgICAgICApLmZpbHRlciB7IGl0LmlzTm90QmxhbmsoKSB9LmpvaW5Ub1N0cmluZygiIMO3ICIpCiAgICAgICAgcmV0dXJuIFN0YXRpb25TZWFyY2hPcmlnaW4oCiAgICAgICAgICAgIGxhYmVsLmlmQmxhbmsgeyBxIH0sCiAgICAgICAgICAgIHJlc3VsdC5nZXREb3VibGUoImxhdGl0dWRlIiksCiAgICAgICAgICAgIHJlc3VsdC5nZXREb3VibGUoImxvbmdpdHVkZSIpCiAgICAgICAgKQogICAgfQoKICAgIGZ1biBkaXNjb3ZlckFuZFJhbmsuLi4=" ).decode("utf-8")
STATION_UI = base64.b64decode("cGFja2FnZSBjb20uZmFiZGF0YS5hcHAKLi4u").decode("utf-8")
PREFS_NEW = base64.b64decode("Y2xhc3MgV2VhdGhlclJlZmVyZW5jZVByZWZzKGNvbnRleHQ6IENvbnRleHQpIHsKLi4u").decode("utf-8")

# Version: idempotent.
gradle_path = "app/build.gradle.kts"
gradle = read(gradle_path)
if 'versionName = "0.13.0"' not in gradle:
    gradle = replace_once(
        gradle,
        'versionCode = 26\n        versionName = "0.12.2"',
        'versionCode = 27\n        versionName = "0.13.0"',
        "version"
    )
write(gradle_path, gradle)

# Location permissions are additive and do not affect users who never use GPS.
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

# New discovery/ranking layers are isolated from ThermalEngine.
write("app/src/main/java/com/fabdata/app/WeatherStationDiscovery.kt", STATION_LOGIC)
write("app/src/main/java/com/fabdata/app/WeatherStationDiscoveryUi.kt", STATION_UI)

weather_path = "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt"
weather = read(weather_path)
weather = replace_once(
    weather,
    """    val longitude: Double,
    val departmentId: String
) {""",
    """    val longitude: Double,
    val departmentId: String,
    val altitudeM: Double? = null
) {""",
    "WeatherReference altitude"
)
old_prefs = """class WeatherReferencePrefs(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_weather_reference", Context.MODE_PRIVATE)
    fun selectedKey(): String = prefs.getString("selected_key", WeatherReferenceCatalog.DEFAULT_KEY)
        ?: WeatherReferenceCatalog.DEFAULT_KEY
    fun select(key: String) = prefs.edit().putString("selected_key", WeatherReferenceCatalog.byKey(key).key).apply()
}"""
weather = replace_once(weather, old_prefs, PREFS_NEW, "WeatherReferencePrefs")
write(weather_path, weather)

# Thermal UI: preserve the old fixed-city selector, add sector/auto as an optional path.
ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)
ui = replace_once(
    ui,
    """    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
    val reference = WeatherReferenceCatalog.byKey(selectedKey)
    var menuOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
""",
    """    var reference by remember { mutableStateOf(prefs.selectedReference()) }
    val selectedKey = reference.key
    var menuOpen by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
""",
    "ThermalUi reference state"
)
ui = replace_once(
    ui,
    """    var profileDialog by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
""",
    """    var profileDialog by remember { mutableStateOf(false) }
    var stationDiscoveryDialog by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
""",
    "ThermalUi discovery state"
)
ui = replace_once(
    ui,
    """                Column {
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
""",
    """                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
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
                if (prefs.autoProtection()) "★ Auto protection · station la plus chaude du secteur"
                else "Sélection manuelle · le moteur RC conserve une seule station",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Text(info, style = MaterialTheme.typography.bodySmall)
""",
    "ThermalUi station controls"
)
ui = replace_once(
    ui,
    """    if (profileDialog) {
        ThermalProfileDialog(
""",
    """    if (stationDiscoveryDialog) {
        WeatherStationDiscoveryDialog(
            credentials = credentials,
            current = reference,
            prefs = prefs,
            onDismiss = { stationDiscoveryDialog = false },
            onSelect = { station, auto ->
                reference = station
                stationDiscoveryDialog = false
                info = if (auto) {
                    "Auto protection · ${station.label} · actualisation de la référence…"
                } else {
                    "Station choisie · ${station.label} · actualisation de la référence…"
                }
            }
        )
    }

    if (profileDialog) {
        ThermalProfileDialog(
""",
    "ThermalUi discovery dialog"
)
write(ui_path, ui)

main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)
main = replace_once(
    main,
    'val visualReference = WeatherReferenceCatalog.byKey(WeatherReferencePrefs(context).selectedKey())',
    'val visualReference = WeatherReferencePrefs(context).selectedReference()',
    "MainActivity visual reference"
)
write(main_path, main)

print("FabData v0.13.0 station protection patch applied")
