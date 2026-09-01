from pathlib import Path

MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
text = MAIN.read_text(encoding='utf-8')

legacy_duplicate = '''    // Synchronise silencieusement les observations mesurées du jour à Lyon-Bron.
    // Une absence de réseau ne bloque jamais l'ouverture ni les imports CSV.
    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
        // Reload even on failure: Lyon has already been created and must remain
        // visible so the user can distinguish "no data" from "no sensor".
        reloadToken++
        result.exceptionOrNull()?.let { error ->
            snackbar.showSnackbar("Lyon non actualisé : ${error.message ?: "réseau ou source indisponible"}")
        }
    }

'''

if legacy_duplicate in text:
    text = text.replace(legacy_duplicate, '', 1)
elif 'v0.9.2 : Lyon est une sonde système permanente.' not in text:
    raise SystemExit('v0.9.2 cleanup: hybrid startup block missing')

MAIN.write_text(text, encoding='utf-8')
print('FabData v0.9.2 duplicate legacy Lyon startup sync removed')
