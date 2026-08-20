from pathlib import Path

# 1) Keep configured/virtual sensors visible even before they have samples.
data_path = Path("app/src/main/java/com/fabdata/app/DataLayer.kt")
data = data_path.read_text(encoding="utf-8")
old_join = "            JOIN samples p ON p.sensor_id = s.id\n"
new_join = "            LEFT JOIN samples p ON p.sensor_id = s.id\n"
if old_join in data:
    data = data.replace(old_join, new_join, 1)
    data_path.write_text(data, encoding="utf-8")
    print("v0.8.1: sensors without samples are now visible")
elif new_join in data:
    print("v0.8.1: LEFT JOIN already applied")
else:
    raise SystemExit("v0.8.1: sensors query anchor not found")

# 2) Create Lyon before the network request, and use a browser-like UA.
lyon_path = Path("app/src/main/java/com/fabdata/app/LyonWeatherSync.kt")
lyon = lyon_path.read_text(encoding="utf-8")
old_start = '''    fun syncToday(): LyonWeatherSyncResult {
        val now = ZonedDateTime.now(LYON_ZONE)
        val date = now.toLocalDate()
        val html = downloadHtml()
'''
new_start = '''    fun syncToday(): LyonWeatherSyncResult {
        // Create the virtual sensor first so FabData can show it even if the
        // remote weather source is temporarily unavailable.
        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)
        val now = ZonedDateTime.now(LYON_ZONE)
        val date = now.toLocalDate()
        val html = downloadHtml()
'''
if old_start in lyon:
    lyon = lyon.replace(old_start, new_start, 1)
elif "val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)\n        val now = ZonedDateTime.now" not in lyon:
    raise SystemExit("v0.8.1: Lyon sync start anchor not found")

old_late_sensor = '''        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)
        var added = 0
'''
new_late_sensor = '''        var added = 0
'''
if old_late_sensor in lyon:
    lyon = lyon.replace(old_late_sensor, new_late_sensor, 1)

old_ua = '            setRequestProperty("User-Agent", "FabData/0.8 (Android; weather observation import)")\n'
new_ua = '            setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/139.0 Mobile Safari/537.36 FabData/0.8")\n'
if old_ua in lyon:
    lyon = lyon.replace(old_ua, new_ua, 1)

lyon_path.write_text(lyon, encoding="utf-8")
print("v0.8.1: Lyon is created before network sync and browser UA is enabled")

# 3) Always reload after automatic sync, including failures, and surface the error.
main_path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
main = main_path.read_text(encoding="utf-8")
old_effect = '''    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
        if (result.isSuccess) reloadToken++
    }
'''
new_effect = '''    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
        // Reload even on failure: Lyon has already been created and must remain
        // visible so the user can distinguish "no data" from "no sensor".
        reloadToken++
        result.exceptionOrNull()?.let { error ->
            snackbar.showSnackbar("Lyon non actualisé : ${error.message ?: "réseau ou source indisponible"}")
        }
    }
'''
if old_effect in main:
    main = main.replace(old_effect, new_effect, 1)
elif "Reload even on failure: Lyon has already been created" not in main:
    raise SystemExit("v0.8.1: Lyon startup effect anchor not found")

main_path.write_text(main, encoding="utf-8")
print("v0.8.1: automatic Lyon sync failures are now visible")
