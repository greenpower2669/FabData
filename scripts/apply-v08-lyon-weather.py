from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = path.read_text(encoding="utf-8")
original = text

remember_needle = "    val backup = remember { FabDataBackup(context, db) }\n"
remember_insert = remember_needle + "    val lyonWeather = remember { LyonWeatherSync(db) }\n"
if "val lyonWeather = remember { LyonWeatherSync(db) }" not in text:
    if remember_needle not in text:
        raise SystemExit("v0.8: FabDataBackup remember anchor not found")
    text = text.replace(remember_needle, remember_insert, 1)

initial_anchor = "    LaunchedEffect(initialImport, initialHandled) {\n"
initial_effect = '''    // Synchronise silencieusement les observations mesurées du jour à Lyon-Bron.
    // Une absence de réseau ne bloque jamais l'ouverture ni les imports CSV.
    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
        if (result.isSuccess) reloadToken++
    }

'''
if "Synchronise silencieusement les observations mesurées du jour à Lyon-Bron" not in text:
    if initial_anchor not in text:
        raise SystemExit("v0.8: initial import effect anchor not found")
    text = text.replace(initial_anchor, initial_effect + initial_anchor, 1)

refresh_old = '''                    IconButton(onClick = { reloadToken++ }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Actualiser")
                    }
'''
refresh_new = '''                    IconButton(onClick = {
                        scope.launch {
                            busy = true
                            val result = withContext(Dispatchers.IO) {
                                runCatching { lyonWeather.syncToday() }
                            }
                            busy = false
                            reloadToken++
                            snackbar.showSnackbar(
                                result.fold(
                                    onSuccess = {
                                        "Lyon : ${it.added} nouvelle(s) mesure(s) · ${it.duplicates} déjà présente(s)"
                                    },
                                    onFailure = {
                                        "Lyon non actualisé : ${it.message ?: "réseau ou source indisponible"}"
                                    }
                                )
                            )
                        }
                    }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Actualiser Lyon et les courbes")
                    }
'''
if "Actualiser Lyon et les courbes" not in text:
    if refresh_old not in text:
        raise SystemExit("v0.8: refresh button anchor not found")
    text = text.replace(refresh_old, refresh_new, 1)

text = text.replace(
    'Text("Politique de confidentialité · FabData v0.7", fontWeight = FontWeight.Bold)',
    'Text("Politique de confidentialité · FabData v0.8", fontWeight = FontWeight.Bold)',
    1,
)

privacy_old = '''                    "Les mesures, noms de pièces et événements sont traités localement sur cet appareil. " +
                        "FabData n'envoie aucune donnée utilisateur à un serveur, n'intègre ni publicité ni analytique " +
                        "et ne crée aucun compte utilisateur.",
'''
privacy_new = '''                    "Les mesures, noms de pièces et événements sont traités localement sur cet appareil. " +
                        "FabData n'envoie aucune donnée utilisateur à un serveur, n'intègre ni publicité ni analytique " +
                        "et ne crée aucun compte utilisateur. La sonde Lyon consulte uniquement une page publique " +
                        "d'observations météo Lyon-Bron afin d'importer température et humidité.",
'''
if privacy_old in text:
    text = text.replace(privacy_old, privacy_new, 1)

if text != original:
    path.write_text(text, encoding="utf-8")
    print("Applied FabData v0.8 Lyon weather UI patch")
else:
    print("FabData v0.8 Lyon weather UI patch already applied")
