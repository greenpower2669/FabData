from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = path.read_text(encoding="utf-8")
original = text

# Remember stores/sync.
anchor = "    val lyonWeather = remember { LyonWeatherSync(db) }\n"
insert = anchor + "    val remoteSensorStore = remember { RemoteSensorStore(context) }\n    val remoteSensorSync = remember { RemoteSensorHttpSync(db) }\n"
if "val remoteSensorStore = remember" not in text:
    if anchor not in text:
        raise SystemExit("v0.8.2: lyonWeather remember anchor not found")
    text = text.replace(anchor, insert, 1)

# UI state.
state_anchor = "    var settingsOpen by remember { mutableStateOf(false) }\n"
state_insert = state_anchor + "    var remoteSensorDialogOpen by remember { mutableStateOf(false) }\n    var remoteConfigs by remember { mutableStateOf(remoteSensorStore.load()) }\n"
if "remoteSensorDialogOpen" not in text:
    if state_anchor not in text:
        raise SystemExit("v0.8.2: settings state anchor not found")
    text = text.replace(state_anchor, state_insert, 1)

# Auto sync configured remote sensors after Lyon startup sync.
lyon_effect = '''    LaunchedEffect(Unit) {
        val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
        // Reload even on failure: Lyon has already been created and must remain
        // visible so the user can distinguish "no data" from "no sensor".
        reloadToken++
        result.exceptionOrNull()?.let { error ->
            snackbar.showSnackbar("Lyon non actualisé : ${error.message ?: "réseau ou source indisponible"}")
        }
    }
'''
remote_effect = lyon_effect + '''
    // Les sondes HTTP ajoutées une fois restent automatiques ensuite.
    LaunchedEffect(Unit) {
        val configs = remoteSensorStore.load()
        if (configs.isNotEmpty()) {
            withContext(Dispatchers.IO) {
                configs.forEach { config -> runCatching { remoteSensorSync.sync(config) } }
            }
            reloadToken++
        }
    }
'''
if "Les sondes HTTP ajoutées une fois restent automatiques ensuite" not in text:
    if lyon_effect not in text:
        raise SystemExit("v0.8.2: Lyon effect anchor not found")
    text = text.replace(lyon_effect, remote_effect, 1)

# Insert station card before SeriesSelector.
series_anchor = '''                item {
                    SeriesSelector(
                        sensors = sensors,
                        showTemp = showTemp,
                        showHumidity = showHumidity,
                        onEdit = { editSensor = it }
                    )
                }
'''
station_block = '''                item {
                    SensorSourcesCard(
                        sensors = sensors,
                        remoteConfigs = remoteConfigs,
                        onSyncLyon = {
                            scope.launch {
                                busy = true
                                val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "Lyon : ${it.added} nouvelle(s) mesure(s)" },
                                        onFailure = { "Lyon : ${it.message ?: "source indisponible"}" }
                                    )
                                )
                            }
                        },
                        onAddRemote = { remoteSensorDialogOpen = true },
                        onSyncRemote = { config ->
                            scope.launch {
                                busy = true
                                val result = withContext(Dispatchers.IO) { runCatching { remoteSensorSync.sync(config) } }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "${config.name} : ${if (it.added) "mesure ajoutée" else "déjà à jour"}" },
                                        onFailure = { "${config.name} : ${it.message ?: "GET impossible"}" }
                                    )
                                )
                            }
                        },
                        onDeleteRemote = { config ->
                            remoteSensorStore.delete(config.id)
                            remoteConfigs = remoteSensorStore.load()
                        }
                    )
                }

''' + series_anchor
if "SensorSourcesCard(" not in text:
    if series_anchor not in text:
        raise SystemExit("v0.8.2: SeriesSelector anchor not found")
    text = text.replace(series_anchor, station_block, 1)

# Add remote sensor dialog before annotation dialog.
dialog_anchor = "    annotationTimestamp?.let { ts ->\n"
dialog_block = '''    if (remoteSensorDialogOpen) {
        RemoteSensorDialog(
            onDismiss = { remoteSensorDialogOpen = false },
            onSave = { name, url, tempKey, humidityKey, timestampKey ->
                val config = remoteSensorStore.add(name, url, tempKey, humidityKey, timestampKey)
                remoteConfigs = remoteSensorStore.load()
                remoteSensorDialogOpen = false
                scope.launch {
                    busy = true
                    val result = withContext(Dispatchers.IO) { runCatching { remoteSensorSync.sync(config) } }
                    busy = false
                    reloadToken++
                    snackbar.showSnackbar(
                        result.fold(
                            onSuccess = { "${config.name} initialisée · synchro automatique activée" },
                            onFailure = { "${config.name} enregistrée · GET initial : ${it.message ?: "échec"}" }
                        )
                    )
                }
            }
        )
    }

'''
if "RemoteSensorDialog(" not in text:
    if dialog_anchor not in text:
        raise SystemExit("v0.8.2: annotation dialog anchor not found")
    text = text.replace(dialog_anchor, dialog_block + dialog_anchor, 1)

# Append composables before TimeTabs.
composable_anchor = "@Composable\nprivate fun TimeTabs"
composables = '''@Composable
private fun SensorSourcesCard(
    sensors: List<Sensor>,
    remoteConfigs: List<RemoteSensorConfig>,
    onSyncLyon: () -> Unit,
    onAddRemote: () -> Unit,
    onSyncRemote: (RemoteSensorConfig) -> Unit,
    onDeleteRemote: (RemoteSensorConfig) -> Unit
) {
    val lyon = sensors.firstOrNull { it.stableKey == LyonWeatherSync.STABLE_KEY }
    Card(shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Sondes / stations météo", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "Lyon est préconfigurée par défaut. Une sonde HTTP ajoutée une fois reste ensuite automatique.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Lyon", fontWeight = FontWeight.SemiBold)
                    Text(
                        if (lyon?.latestTimestamp != null) "Station météo · active" else "Station météo · en attente de mesure",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
            }

            remoteConfigs.forEach { config ->
                HorizontalDivider()
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(config.name, fontWeight = FontWeight.SemiBold)
                        Text(
                            "HTTP GET · automatique",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    TextButton(onClick = { onSyncRemote(config) }) { Text("Actualiser") }
                    IconButton(onClick = { onDeleteRemote(config) }) {
                        Icon(Icons.Default.Delete, contentDescription = "Supprimer la sonde HTTP")
                    }
                }
            }

            OutlinedButton(onClick = onAddRemote, modifier = Modifier.fillMaxWidth()) {
                Text("+ Ajouter une sonde HTTP GET")
            }
        }
    }
}

@Composable
private fun RemoteSensorDialog(
    onDismiss: () -> Unit,
    onSave: (String, String, String, String, String) -> Unit
) {
    var name by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var temperatureKey by remember { mutableStateOf("temperature") }
    var humidityKey by remember { mutableStateOf("humidity") }
    var timestampKey by remember { mutableStateOf("timestamp") }
    var error by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Ajouter une sonde HTTP GET") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text("À faire une seule fois : ensuite FabData synchronise cette sonde automatiquement.")
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Nom de la sonde") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it; error = false },
                    label = { Text("URL GET (http:// ou https://)") },
                    isError = error,
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Text("Réponse JSON ou texte : temperature=23.4&humidity=51", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(
                    value = temperatureKey,
                    onValueChange = { temperatureKey = it },
                    label = { Text("Champ température") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = humidityKey,
                    onValueChange = { humidityKey = it },
                    label = { Text("Champ humidité") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                OutlinedTextField(
                    value = timestampKey,
                    onValueChange = { timestampKey = it },
                    label = { Text("Champ date/heure (optionnel)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(onClick = {
                if (!url.trim().startsWith("http://") && !url.trim().startsWith("https://")) {
                    error = true
                } else {
                    onSave(name, url, temperatureKey, humidityKey, timestampKey)
                }
            }) { Text("Initialiser") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }
    )
}

'''
if "private fun SensorSourcesCard(" not in text:
    if composable_anchor not in text:
        raise SystemExit("v0.8.2: TimeTabs composable anchor not found")
    text = text.replace(composable_anchor, composables + composable_anchor, 1)

if text != original:
    path.write_text(text, encoding="utf-8")
    print("v0.8.2: station/weather and HTTP sensor UI applied")
else:
    print("v0.8.2: station/weather and HTTP sensor UI already applied")
