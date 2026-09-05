from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rep(path: Path, old: str, new: str, label: str, count: int = 1):
    text = path.read_text()
    n = text.count(old)
    if n == 0:
        if new in text:
            return
        raise SystemExit(f"missing anchor {label} in {path}")
    if n != count:
        raise SystemExit(f"anchor {label} expected {count}, found {n} in {path}")
    path.write_text(text.replace(old, new, count))


# ---- version ----
gradle = ROOT / "app/build.gradle.kts"
rep(gradle, 'versionCode = 33', 'versionCode = 34', 'versionCode')
rep(gradle, 'versionName = "0.17.1"', 'versionName = "0.18.0"', 'versionName')


# ---- weather history: 48 months + one-month archive chunks + explicit range prep ----
weather = ROOT / "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt"
rep(weather, 'val days = requestedDays.coerceIn(1, 1098)', 'val days = requestedDays.coerceIn(1, 1464)', 'weather max history')
rep(
    weather,
    '''        return WeatherReferencePreparation(sync, coverage, days)\n    }\n\n    fun coverage(referenceKey: String, from: Long, to: Long): WeatherReferenceCoverage {''',
    '''        return WeatherReferencePreparation(sync, coverage, days)\n    }\n\n    /** Prépare un seul morceau historique, toujours du plus ancien vers le plus récent. */\n    fun prepareHistoryRange(reference: WeatherReference, from: Long, to: Long): WeatherReferencePreparation {\n        require(to >= from) { "Période historique invalide" }\n        val loadFrom = from - 18L * hourMs\n        val sync = refreshSelected(reference, loadFrom, to)\n        val coverage = coverage(reference.key, loadFrom, to)\n        val days = (((to - from).coerceAtLeast(0L) / (24L * hourMs)) + 1L).toInt().coerceAtLeast(1)\n        return WeatherReferencePreparation(sync, coverage, days)\n    }\n\n    fun coverage(referenceKey: String, from: Long, to: Long): WeatherReferenceCoverage {''',
    'prepareHistoryRange'
)
rep(
    weather,
    '''        // v0.14 : 36 mois représentent ~26 000 points horaires. On découpe volontairement\n        // l'archive en fenêtres de 180 jours : moins de mémoire, moins de risque de timeout,\n        // et exactement la même série finale après déduplication.\n        val out = mutableListOf<WeatherReferencePoint>()\n        var cursor = startDate\n        while (!cursor.isAfter(endDate)) {\n            val chunkEnd = minOf(cursor.plusDays(179L), endDate)''',
    '''        // v0.18 : les historiques longs sont volontairement découpés en morceaux\n        // d'environ un mois. Même logique partout : ancien -> récent, reprise plus simple,\n        // moins de mémoire et aucune grosse requête monolithique.\n        val out = mutableListOf<WeatherReferencePoint>()\n        var cursor = startDate\n        while (!cursor.isAfter(endDate)) {\n            val chunkEnd = minOf(cursor.plusDays(30L), endDate)''',
    'monthly weather chunks'
)
rep(weather, 'appelé au focus puis toutes les 60 s', 'appelé au focus puis selon la cadence premier-plan', 'refreshRecent comment')


# ---- point-source targeted invalidation: measured remains impossible to delete ----
point = ROOT / "app/src/main/java/com/fabdata/app/PointSourceLayer.kt"
rep(
    point,
    '''    fun reconstructedBounds(db: FabDataDb, sensorId: Long): LongRange? =\n        sourceBounds(db, sensorId, PointSource.RECONSTRUCTED)\n''',
    '''    /** Supprime une plage d'une couche calculée uniquement. MEASURED reste interdit. */\n    fun deleteBySourceRange(\n        db: FabDataDb,\n        sensorId: Long,\n        source: PointSource,\n        from: Long,\n        to: Long\n    ): Int {\n        require(source != PointSource.MEASURED) { "Une mesure réelle ne peut jamais être invalidée" }\n        if (to < from) return 0\n        ensure(db.writableDatabase)\n        val timestamps = mutableListOf<Long>()\n        db.readableDatabase.rawQuery(\n            "SELECT timestamp FROM point_sources WHERE sensor_id=? AND source=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",\n            arrayOf(sensorId.toString(), source.dbValue, from.toString(), to.toString())\n        ).use { c -> while (c.moveToNext()) timestamps += c.getLong(0) }\n        if (timestamps.isEmpty()) return 0\n        db.inTransaction {\n            timestamps.forEach { ts ->\n                db.writableDatabase.delete(\n                    "samples", "sensor_id=? AND timestamp=?",\n                    arrayOf(sensorId.toString(), ts.toString())\n                )\n                db.writableDatabase.delete(\n                    "point_sources", "sensor_id=? AND timestamp=? AND source=?",\n                    arrayOf(sensorId.toString(), ts.toString(), source.dbValue)\n                )\n            }\n        }\n        return timestamps.size\n    }\n\n    fun reconstructedBounds(db: FabDataDb, sensorId: Long): LongRange? =\n        sourceBounds(db, sensorId, PointSource.RECONSTRUCTED)\n''',
    'targeted calculated delete'
)


# ---- thermal engine: 48 months available, automatic callers can cap history ----
engine = ROOT / "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
rep(engine, 'private const val MAX_HISTORY_DAYS = 1098', 'private const val MAX_HISTORY_DAYS = 1464', 'thermal max history')
rep(
    engine,
    '''    fun refreshExistingReconstructions(\n        reference: WeatherReference,\n        profile: ThermalBuildingProfile = ThermalBuildingProfile(),\n        sensorId: Long? = null\n    ): ThermalWriteSummary {''',
    '''    fun refreshExistingReconstructions(\n        reference: WeatherReference,\n        profile: ThermalBuildingProfile = ThermalBuildingProfile(),\n        sensorId: Long? = null,\n        maxHistoryDays: Int? = null\n    ): ThermalWriteSummary {''',
    'refresh cap signature'
)
rep(
    engine,
    '''                val days = ((span + THERMAL_DAY_MS - 1L) / THERMAL_DAY_MS).toInt().coerceIn(1, MAX_HISTORY_DAYS)\n                val r = reconstructHistory(reference, days, sensor.id, profile)''',
    '''                val fullDays = ((span + THERMAL_DAY_MS - 1L) / THERMAL_DAY_MS).toInt().coerceIn(1, MAX_HISTORY_DAYS)\n                val days = maxHistoryDays?.let { min(fullDays, it.coerceAtLeast(1)) } ?: fullDays\n                val r = reconstructHistory(reference, days, sensor.id, profile)''',
    'refresh cap body'
)


# ---- live coordinator: automatic recalculation limited to last 12 months, debt persisted ----
live = ROOT / "app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt"
rep(
    live,
    '''    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, credentials) }\n\n    var foreground''',
    '''    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, credentials) }\n    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }\n    val coherenceStore = remember { ThermalCoherenceStore(db) }\n\n    var foreground''',
    'live debt stores'
)
rep(
    live,
    '''                if (rebuildFromMeasured) {\n                    engine.refreshExistingReconstructions(reference, profile, selectedSensorId)\n                }''',
    '''                if (rebuildFromMeasured) {\n                    selectedSensorId?.let { id ->\n                        val firstReal = coherenceStore.firstMeasuredTimestamp(id)\n                        val existing = PointSourceStore.reconstructedBounds(db, id)\n                        if (firstReal != null && existing != null) {\n                            val recentStart = firstReal - 366L * 24L * 60L * 60L * 1000L\n                            if (existing.first < recentStart) {\n                                historyDebtStore.recordDebt(\n                                    reference.key, id, existing.first, recentStart,\n                                    "Nouvelle mesure réelle : historique antérieur aux 12 derniers mois à remettre à jour"\n                                )\n                            }\n                        }\n                    }\n                    engine.refreshExistingReconstructions(reference, profile, selectedSensorId, maxHistoryDays = 366)\n                }''',
    'live 12-month cap'
)


# ---- Main UI: coherent weather curves, one curve list, styling from the same place ----
main = ROOT / "app/src/main/java/com/fabdata/app/MainActivity.kt"
rep(
    main,
    '''private const val LYON_RECONSTRUCTED_SENSOR_ID = -6902900103L\nprivate const val LYON_RECONSTRUCTED_STABLE_KEY = "lyon-reconstructed"''',
    '''private const val WEATHER_OFFICIAL_SENSOR_ID = -6902900102L\nprivate const val WEATHER_OFFICIAL_STABLE_KEY = "weather-reference-official"\nprivate const val LYON_RECONSTRUCTED_SENSOR_ID = -6902900103L\nprivate const val LYON_RECONSTRUCTED_STABLE_KEY = "lyon-reconstructed"''',
    'weather official pseudo id'
)
rep(
    main,
    '''    val weatherReferenceStore = remember { WeatherReferenceStore(db) }\n    val inertiaEstimator''',
    '''    val weatherReferenceStore = remember { WeatherReferenceStore(db) }\n    val weatherReferenceManager = remember { WeatherReferenceManager(context, db, lyonLab, meteoCredentials) }\n    val inertiaEstimator''',
    'main weather manager'
)
rep(
    main,
    '''            sensors.forEach { sensor -> put(sensor.id, curveStyleStore.load("sensor:${sensor.stableKey}")) }\n            put(LYON_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("lyon:reconstructed"))''',
    '''            sensors.forEach { sensor -> put(sensor.id, curveStyleStore.load("sensor:${sensor.stableKey}")) }\n            put(WEATHER_OFFICIAL_SENSOR_ID, curveStyleStore.load("weather:official"))\n            put(LYON_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("lyon:reconstructed"))\n            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))''',
    'pseudo styles'
)
rep(main, 'à l\'ouverture, au retour au focus et ensuite toutes les 60 secondes.', 'à l\'ouverture, au retour au focus et ensuite toutes les 5 minutes au premier plan.', 'main live comment')
rep(
    main,
    '''        if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {\n            // Always checked: if data arrives later the curve appears without another user action.\n            showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = true\n        }''',
    '''        if (!showTemp.containsKey(WEATHER_OFFICIAL_SENSOR_ID)) showTemp[WEATHER_OFFICIAL_SENSOR_ID] = true\n        if (!showHumidity.containsKey(WEATHER_OFFICIAL_SENSOR_ID)) showHumidity[WEATHER_OFFICIAL_SENSOR_ID] = false\n        if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {\n            // Always checked: if data arrives later the curve appears without another user action.\n            showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = true\n        }''',
    'official visibility'
)
rep(
    main,
    '''    val visualReference = WeatherReferencePrefs(context).selectedReference()\n    val lyonReconstructedSensor = Sensor(\n        id = LYON_RECONSTRUCTED_SENSOR_ID,\n        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,\n        name = "${visualReference.city} reconstruit",\n        room = "${visualReference.city} reconstruit",\n        colorIndex = 3,\n        latestTimestamp = lyonReconstructedSamples.lastOrNull()?.timestamp\n    )\n    // v0.10.2 : Lyon reconstruit redevient une couche visuelle comparative.\n    // Il ne crée PAS une deuxième référence météo ni une deuxième série persistée :\n    // le pseudo-capteur n'existe que pour Superposition / graphique / inspecteur.\n    val inertiaVisible''',
    '''    val visualReference = WeatherReferencePrefs(context).selectedReference()\n    val weatherOfficialSamples = lyonReconstructedSamples\n        .filter { it.source == PointSource.MEASURED }\n        .map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }\n    val weatherReconstructedSamples = lyonReconstructedSamples\n        .filter { it.source == PointSource.RECONSTRUCTED }\n        .map { it.copy(sensorId = LYON_RECONSTRUCTED_SENSOR_ID) }\n    val weatherOfficialSensor = Sensor(\n        id = WEATHER_OFFICIAL_SENSOR_ID,\n        stableKey = WEATHER_OFFICIAL_STABLE_KEY,\n        name = "Station météo officielle",\n        room = visualReference.label,\n        colorIndex = 2,\n        latestTimestamp = weatherOfficialSamples.lastOrNull()?.timestamp\n    )\n    val lyonReconstructedSensor = Sensor(\n        id = LYON_RECONSTRUCTED_SENSOR_ID,\n        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,\n        name = "Station météo reconstruite",\n        room = visualReference.label,\n        colorIndex = 3,\n        latestTimestamp = weatherReconstructedSamples.lastOrNull()?.timestamp\n    )\n    // Les deux pseudo-capteurs météo sont uniquement des vues de la référence sélectionnée.\n    // Aucun doublon n'est persisté et les anciennes clés internes restent compatibles.\n    val inertiaVisible''',
    'split selected weather curves'
)
rep(
    main,
    '''    val chartSensors = sensors + lyonReconstructedSensor + inertiaSensor\n    val chartSampleMap = sampleMap +\n        (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)\n    val chartOverviewSampleMap = overviewSampleMap + (THERMAL_INERTIA_SENSOR_ID to inertiaOverview)''',
    '''    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }\n    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + inertiaSensor\n    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +\n        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)\n    val overviewReference = overviewSampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()\n    val chartOverviewSampleMap = overviewSampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (WEATHER_OFFICIAL_SENSOR_ID to overviewReference.filter { it.source == PointSource.MEASURED }.map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +\n        (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference.filter { it.source == PointSource.RECONSTRUCTED }) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaOverview)''',
    'chart pseudo split'
)
# toolbar refresh selected weather rather than always Lyon
rep(
    main,
    '''                            val result = runCatching { syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }\n                            busy = false\n                            reloadToken++\n                            snackbar.showSnackbar(\n                                result.fold(\n                                    onSuccess = { "${it.label} : ${it.received} reçue(s) · ${it.stored} stockée(s)" },\n                                    onFailure = { "Lyon non actualisé : ${it.message ?: "réseau ou source indisponible"}" }\n                                )\n                            )''',
    '''                            val selected = WeatherReferencePrefs(context).selectedReference()\n                            val result = withContext(Dispatchers.IO) {\n                                runCatching {\n                                    if (selected.key == WeatherReferenceCatalog.DEFAULT_KEY) {\n                                        syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials)\n                                    }\n                                    weatherReferenceManager.refreshRecent(selected)\n                                }\n                            }\n                            busy = false\n                            reloadToken++\n                            snackbar.showSnackbar(\n                                result.fold(\n                                    onSuccess = { "${it.label} · ${it.measured} réel(s) · ${it.reconstructed} reconstruit(s)" },\n                                    onFailure = { "Station météo non actualisée : ${it.message ?: "réseau ou source indisponible"}" }\n                                )\n                            )''',
    'toolbar selected weather refresh'
)
# source card gets generic wording and knows if Lyon-specific tools are applicable
rep(
    main,
    '''                    SensorSourcesCard(\n                        sensors = sensors,\n                        remoteConfigs = remoteConfigs,''',
    '''                    SensorSourcesCard(\n                        sensors = sensors,\n                        remoteConfigs = remoteConfigs,\n                        showLyonSpecificTools = visualReference.key == WeatherReferenceCatalog.DEFAULT_KEY,''',
    'source card flag'
)
# source sync callback selected reference
rep(
    main,
    '''                                val result = runCatching { syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }\n                                busy = false\n                                reloadToken++\n                                snackbar.showSnackbar(\n                                    result.fold(\n                                        onSuccess = { "${it.label} : ${it.received} reçue(s) · ${it.stored} stockée(s)" },\n                                        onFailure = { "Lyon : ${it.message ?: "source indisponible"}" }\n                                    )\n                                )''',
    '''                                val selected = WeatherReferencePrefs(context).selectedReference()\n                                val result = withContext(Dispatchers.IO) {\n                                    runCatching {\n                                        if (selected.key == WeatherReferenceCatalog.DEFAULT_KEY) {\n                                            syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials)\n                                        }\n                                        weatherReferenceManager.refreshRecent(selected)\n                                    }\n                                }\n                                busy = false\n                                reloadToken++\n                                snackbar.showSnackbar(\n                                    result.fold(\n                                        onSuccess = { "${it.label} · ${it.measured} réel(s) · ${it.reconstructed} reconstruit(s)" },\n                                        onFailure = { "Station météo : ${it.message ?: "source indisponible"}" }\n                                    )\n                                )''',
    'source selected weather refresh'
)
# Series selector centralizes names + style controls
rep(
    main,
    '''                    SeriesSelector(\n                        sensors = chartSensors,\n                        showTemp = showTemp,\n                        showHumidity = showHumidity,\n                        onEdit = { if (it.id != LYON_RECONSTRUCTED_SENSOR_ID) editSensor = it }\n                    )''',
    '''                    SeriesSelector(\n                        sensors = chartSensors,\n                        showTemp = showTemp,\n                        showHumidity = showHumidity,\n                        onEditSensor = { sensor -> if (sensor.id >= 0L) editSensor = sensor },\n                        onStyleEdit = { sensor ->\n                            val key = when (sensor.id) {\n                                WEATHER_OFFICIAL_SENSOR_ID -> "weather:official"\n                                LYON_RECONSTRUCTED_SENSOR_ID -> "lyon:reconstructed"\n                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"\n                                else -> "sensor:${sensor.stableKey}"\n                            }\n                            styleEditKey = key to sensor.name\n                        }\n                    )''',
    'selector callbacks'
)
rep(
    main,
    '''                item {\n                    CurvePersonalizationCard(\n                        sensors = chartSensors.filter { it.id != THERMAL_INERTIA_SENSOR_ID },\n                        onEdit = { key, label -> styleEditKey = key to label }\n                    )\n                }\n\n''',
    '',
    'remove duplicate personalization card'
)
rep(
    main,
    '''private fun SensorSourcesCard(\n    sensors: List<Sensor>,\n    remoteConfigs: List<RemoteSensorConfig>,''',
    '''private fun SensorSourcesCard(\n    sensors: List<Sensor>,\n    remoteConfigs: List<RemoteSensorConfig>,\n    showLyonSpecificTools: Boolean,''',
    'source card signature'
)
rep(
    main,
    '''            Text("Sondes / stations météo", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)\n            Text(\n                "Lyon-Bron permanent : officiel 6 min prioritaire, secours auto sans token. Reconstruit reste toujours disponible.",''',
    '''            Text("Sources & synchronisation", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)\n            Text(\n                "La station météo active est choisie dans Référence météo & moteur thermique. Ici on synchronise les sources sans dupliquer les noms des courbes.",''',
    'source generic title'
)
rep(
    main,
    '''                    Text("Lyon", fontWeight = FontWeight.SemiBold)\n                    Text(\n                        if (lyon?.latestTimestamp != null) "Station météo · active" else "Station météo · en attente de mesure",''',
    '''                    Text("Source météo", fontWeight = FontWeight.SemiBold)\n                    Text(\n                        if (lyon?.latestTimestamp != null) "Synchronisation disponible" else "En attente de données",''',
    'source no duplicated name'
)
rep(
    main,
    '''                TextButton(onClick = onOpenLyon) { Text("Détail") }\n                TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }\n                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }''',
    '''                if (showLyonSpecificTools) {\n                    TextButton(onClick = onOpenLyon) { Text("Détail") }\n                    TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }\n                }\n                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }''',
    'hide Lyon-only tools for other station'
)
rep(
    main,
    '''private fun SeriesSelector(\n    sensors: List<Sensor>,\n    showTemp: MutableMap<Long, Boolean>,\n    showHumidity: MutableMap<Long, Boolean>,\n    onEdit: (Sensor) -> Unit\n) {''',
    '''private fun SeriesSelector(\n    sensors: List<Sensor>,\n    showTemp: MutableMap<Long, Boolean>,\n    showHumidity: MutableMap<Long, Boolean>,\n    onEditSensor: (Sensor) -> Unit,\n    onStyleEdit: (Sensor) -> Unit\n) {''',
    'selector signature'
)
rep(
    main,
    '''                        val displayRoom = when {\n                            sensor.id == LYON_RECONSTRUCTED_SENSOR_ID -> "Lyon reconstruit"\n                            sensor.id == THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"\n                            sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon brut · officiel/secours"\n                            else -> sensor.room\n                        }\n                        Text(displayRoom, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)\n                        if (sensor.name != sensor.room && sensor.id != LYON_RECONSTRUCTED_SENSOR_ID) {\n                            Text(\n                                sensor.name,''',
    '''                        val displayRoom = when (sensor.id) {\n                            WEATHER_OFFICIAL_SENSOR_ID -> "Station météo officielle"\n                            LYON_RECONSTRUCTED_SENSOR_ID -> "Station météo reconstruite"\n                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"\n                            else -> sensor.room\n                        }\n                        Text(displayRoom, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)\n                        if (sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) {\n                            Text(sensor.room, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)\n                        } else if (sensor.name != sensor.room && sensor.id != THERMAL_INERTIA_SENSOR_ID) {\n                            Text(\n                                sensor.name,''',
    'selector labels'
)
rep(
    main,
    '''                    if (sensor.id != LYON_RECONSTRUCTED_SENSOR_ID && sensor.id != THERMAL_INERTIA_SENSOR_ID) {\n                        IconButton(onClick = { onEdit(sensor) }) {\n                            Icon(Icons.Default.Edit, contentDescription = "Modifier la pièce")\n                        }\n                    } else {\n                        Spacer(Modifier.size(48.dp))\n                    }''',
    '''                    IconButton(onClick = { onStyleEdit(sensor) }) {\n                        Icon(Icons.Default.Settings, contentDescription = "Personnaliser la courbe")\n                    }\n                    if (sensor.id >= 0L) {\n                        IconButton(onClick = { onEditSensor(sensor) }) {\n                            Icon(Icons.Default.Edit, contentDescription = "Modifier la sonde")\n                        }\n                    }''',
    'selector style controls'
)


# ---- curve style dialog gets a real reset ----
lyon = ROOT / "app/src/main/java/com/fabdata/app/LyonLabLayer.kt"
rep(
    lyon,
    '''        confirmButton = { Button(onClick = { onSave(value) }) { Text("Enregistrer") } },\n        dismissButton = { TextButton(onClick = onDismiss) { Text("Annuler") } }''',
    '''        confirmButton = { Button(onClick = { onSave(value) }) { Text("Enregistrer") } },\n        dismissButton = {\n            Row {\n                TextButton(onClick = { onSave(CurveVisualPrefs()) }) { Text("Réinitialiser") }\n                TextButton(onClick = onDismiss) { Text("Annuler") }\n            }\n        }''',
    'curve style reset'
)


# ---- Thermal UI: 48 months, persistent debt, monthly continuation/pause/cancel, 12-month auto cap ----
thermal = ROOT / "app/src/main/java/com/fabdata/app/ThermalUi.kt"
rep(
    thermal,
    '''    ThermalHistoryChoice("24 mois", 732),\n    ThermalHistoryChoice("36 mois", 1098)''',
    '''    ThermalHistoryChoice("24 mois", 732),\n    ThermalHistoryChoice("36 mois", 1098),\n    ThermalHistoryChoice("48 mois", 1464)''',
    '48 month choice'
)
rep(
    thermal,
    '''    val profileStore = remember { ThermalProfileStore(context) }\n    val modelSensorPrefs''',
    '''    val profileStore = remember { ThermalProfileStore(context) }\n    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }\n    val modelSensorPrefs''',
    'thermal debt store'
)
rep(
    thermal,
    '''    var observedReferenceKey by remember { mutableStateOf(selectedKey) }\n    var observedDataVersion by remember { mutableIntStateOf(dataVersion) }\n''',
    '''    var observedReferenceKey by remember { mutableStateOf(selectedKey) }\n    var observedDataVersion by remember { mutableIntStateOf(dataVersion) }\n    var debtSnapshot by remember { mutableStateOf(historyDebtStore.loadDebt()) }\n    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }\n\n    fun refreshDebtState() { debtSnapshot = historyDebtStore.loadDebt() }\n\n    suspend fun processNextHistoryChunk() {\n        val work = historyDebtStore.loadWork() ?: return\n        historyDebtStore.resumeWork()\n        val range = work.nextRange() ?: return\n        busy = true\n        info = "Historique · mois ${work.nextChunk + 1}/${work.totalChunks} · préparation météo…"\n        val result = withContext(Dispatchers.IO) {\n            runCatching {\n                val prepared = manager.prepareHistoryRange(reference, range.first, range.last)\n                if (!prepared.coverage.ready) {\n                    error("${reference.city} incomplet sur ce mois : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")\n                }\n                val advanced = historyDebtStore.advanceWork() ?: error("Session historique perdue")\n                if (advanced.nextChunk >= advanced.totalChunks) {\n                    val checked = engine.status(reference, advanced.sensorId, profile)\n                    if (!checked.canReconstruct) error(checked.message)\n                    val activeModel = checked.preferred?.model?.takeIf { it.sensorId == advanced.sensorId }\n                    val summary = engine.reconstructHistory(\n                        reference = reference,\n                        requestedDays = advanced.requestedDays,\n                        sensorId = advanced.sensorId,\n                        profile = profile,\n                        precalibratedModel = activeModel\n                    ) { p ->\n                        scope.launch {\n                            info = if (p.total > 0) {\n                                val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)\n                                "${p.stage} · $percent % · ${p.changed} point(s)"\n                            } else p.stage\n                            if (p.total > 0 && p.processed > 0) {\n                                suppressNextAuto = true\n                                onDataChanged()\n                            }\n                        }\n                    }\n                    historyDebtStore.clearWork()\n                    historyDebtStore.clearDebt()\n                    Triple(prepared, summary, null)\n                } else {\n                    Triple(prepared, null, advanced)\n                }\n            }\n        }\n        busy = false\n        result.fold(\n            onSuccess = { (_, summary, next) ->\n                refreshDebtState()\n                if (summary != null) {\n                    continuationWork = null\n                    val detail = summary.diagnostic?.let { " · $it" }.orEmpty()\n                    info = "Historique terminé · ${summary.reconstructed} point(s) · ${summary.raccords} raccord(s)$detail"\n                    suppressNextAuto = true\n                    onDataChanged()\n                } else if (next != null) {\n                    continuationWork = next\n                    info = "Mois ${next.nextChunk}/${next.totalChunks} validé · choisir Continuer, Pause ou Annuler"\n                }\n            },\n            onFailure = { error ->\n                historyDebtStore.pauseWork()\n                historyDebtStore.setDebtState(HistoricalDebtState.PAUSED)\n                refreshDebtState()\n                continuationWork = null\n                info = error.message ?: "Morceau historique impossible · session mise en pause"\n            }\n        )\n    }\n\n    suspend fun beginHistoryWork(days: Int, reason: String) {\n        val checked = withContext(Dispatchers.IO) { engine.status(reference, selectedSensorId, profile) }\n        if (!checked.canReconstruct) { info = checked.message; return }\n        val activeId = selectedSensorId ?: checked.preferred?.sensor?.id ?: run { info = "Aucune sonde modèle"; return }\n        val firstReal = withContext(Dispatchers.IO) { coherenceStore.firstMeasuredTimestamp(activeId) }\n            ?: run { info = "Aucune vraie mesure pour initialiser l'historique"; return }\n        val boundedDays = days.coerceIn(1, 1464)\n        historyDebtStore.beginWork(reference.key, activeId, boundedDays, firstReal, reason)\n        historyDebtStore.recordDebt(\n            reference.key, activeId,\n            firstReal - boundedDays.toLong() * 24L * 60L * 60L * 1000L,\n            firstReal, reason, HistoricalDebtState.PENDING\n        )\n        refreshDebtState()\n        processNextHistoryChunk()\n    }\n''',
    'history work helpers'
)
# replace auto rationalization depth preparation block
rep(
    thermal,
    '''                val maxHistoryDays = staleRecon.mapNotNull { state ->\n                    val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId) ?: return@mapNotNull null\n                    if (state.bounds.first >= firstReal) 0\n                    else (((firstReal - state.bounds.first) + dayMs - 1L) / dayMs).toInt().coerceIn(1, 1098)\n                }.maxOrNull() ?: 0\n                if (maxHistoryDays > 0) {\n                    info = "Rationalisation · préparation météo ${thermalHistoryLabel(maxHistoryDays)}…"\n                    val prepared = manager.prepareHistory(reference, maxHistoryDays)''',
    '''                val fullHistoryDays = staleRecon.mapNotNull { state ->\n                    val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId) ?: return@mapNotNull null\n                    if (state.bounds.first >= firstReal) 0\n                    else (((firstReal - state.bounds.first) + dayMs - 1L) / dayMs).toInt().coerceIn(1, 1464)\n                }.maxOrNull() ?: 0\n                val maxHistoryDays = minOf(fullHistoryDays, 366)\n                if (fullHistoryDays > 366) {\n                    staleRecon.forEach { state ->\n                        val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId) ?: return@forEach\n                        val recentStart = firstReal - 366L * dayMs\n                        if (state.bounds.first < recentStart) {\n                            historyDebtStore.recordDebt(\n                                reference.key, state.sensorId, state.bounds.first, recentStart, reason,\n                                HistoricalDebtState.PENDING\n                            )\n                        }\n                    }\n                }\n                if (maxHistoryDays > 0) {\n                    info = "Rationalisation · 12 mois max automatiques · préparation ${thermalHistoryLabel(maxHistoryDays)}…"\n                    val prepared = manager.prepareHistory(reference, maxHistoryDays)''',
    'auto 12 month preparation'
)
rep(
    thermal,
    '''                staleRecon.forEach { state ->\n                    val previousBounds = state.bounds\n                    removed += PointSourceStore.deleteBySource(db, state.sensorId, PointSource.RECONSTRUCTED)\n                    val rebuilt = engine.rebuildCalculatedExtent(\n                        reference, targetProfile, state.sensorId, previousBounds, progressCallback\n                    )''',
    '''                staleRecon.forEach { state ->\n                    val previousBounds = state.bounds\n                    val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId)\n                    val recentStart = firstReal?.let { maxOf(previousBounds.first, it - 366L * dayMs) } ?: previousBounds.first\n                    removed += PointSourceStore.deleteBySourceRange(\n                        db, state.sensorId, PointSource.RECONSTRUCTED, recentStart, previousBounds.last\n                    )\n                    val rebuilt = engine.rebuildCalculatedExtent(\n                        reference, targetProfile, state.sensorId, recentStart..previousBounds.last, progressCallback\n                    )''',
    'auto targeted rebuild'
)
rep(
    thermal,
    '''                suppressNextAuto = true\n                onDataChanged()\n            },''',
    '''                refreshDebtState()\n                suppressNextAuto = true\n                onDataChanged()\n            },''',
    'refresh debt after rationalize',
    count=1
)
# reset station + debt status/buttons after station discovery button
rep(
    thermal,
    '''            OutlinedButton(\n                onClick = { stationDiscoveryOpen = true },\n                enabled = !busy,\n                modifier = Modifier.fillMaxWidth()\n            ) { Text("Sondes proches · Auto protection") }\n\n            Text(info, style = MaterialTheme.typography.bodySmall)''',
    '''            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {\n                OutlinedButton(\n                    onClick = { stationDiscoveryOpen = true },\n                    enabled = !busy,\n                    modifier = Modifier.weight(1f)\n                ) { Text("Sondes proches · Auto") }\n                TextButton(\n                    onClick = {\n                        prefs.setAutoProtection(false)\n                        prefs.select(WeatherReferenceCatalog.DEFAULT_KEY)\n                        selectedKey = WeatherReferenceCatalog.DEFAULT_KEY\n                    },\n                    enabled = !busy\n                ) { Text("Réinitialiser") }\n            }\n\n            debtSnapshot?.let { debt ->\n                Text(\n                    "◐ Historique ancien en attente · ~${debt.pendingDays} j · ${debt.reason}",\n                    style = MaterialTheme.typography.bodySmall,\n                    color = MaterialTheme.colorScheme.tertiary\n                )\n                val savedWork = historyDebtStore.loadWork()\n                Button(\n                    onClick = {\n                        scope.launch {\n                            if (savedWork != null) {\n                                historyDebtStore.resumeWork()\n                                continuationWork = null\n                                processNextHistoryChunk()\n                            } else {\n                                val firstReal = coherenceStore.firstMeasuredTimestamp(debt.sensorId)\n                                val days = firstReal?.let { (((it - debt.from).coerceAtLeast(24L * 60L * 60L * 1000L)) / (24L * 60L * 60L * 1000L)).toInt() }\n                                    ?: debt.pendingDays\n                                beginHistoryWork(days, debt.reason)\n                            }\n                        }\n                    },\n                    enabled = !busy,\n                    modifier = Modifier.fillMaxWidth()\n                ) { Text(if (savedWork != null) "Reprendre l'historique" else "Mettre à jour l'historique ancien") }\n            }\n\n            Text(info, style = MaterialTheme.typography.bodySmall)''',
    'debt UI and station reset'
)
# replace both long history confirm handlers with beginHistoryWork
old_weather_handler = '''                    scope.launch {\n                        busy = true\n                        info = "Historique météo · préparation ${thermalHistoryLabel(weatherHistoryDays)}…"\n                        val result = withContext(Dispatchers.IO) {\n                            runCatching {\n                                val prepared = manager.prepareHistory(reference, weatherHistoryDays)\n                                if (!prepared.coverage.ready) {\n                                    error("${reference.city} incomplet : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")\n                                }\n                                val checked = engine.status(reference, selectedSensorId, profile)\n                                if (!checked.canReconstruct) error(checked.message)\n                                val activeId = selectedSensorId ?: checked.preferred?.sensor?.id\n                                val activeModel = checked.preferred?.model?.takeIf { it.sensorId == activeId }\n                                val summary = engine.reconstructHistory(\n                                    reference = reference,\n                                    requestedDays = weatherHistoryDays,\n                                    sensorId = activeId,\n                                    profile = profile,\n                                    precalibratedModel = activeModel\n                                ) { p ->\n                                    scope.launch {\n                                        info = if (p.total > 0) {\n                                            val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)\n                                            "${p.stage} · $percent % · ${p.changed} point(s) écrit(s)"\n                                        } else p.stage\n                                        if (p.total > 0 && p.processed > 0) {\n                                            suppressNextAuto = true\n                                            onDataChanged()\n                                        }\n                                    }\n                                }\n                                prepared to summary\n                            }\n                        }\n                        busy = false\n                        result.fold(\n                            onSuccess = { (prepared, summary) ->\n                                val c = prepared.coverage\n                                val detail = summary.diagnostic?.let { d -> " · $d" }.orEmpty()\n                                info = "Deux petits loups prêts · météo ${prepared.days} j ${(c.coverage * 100).toInt()} % · bâtiment ${summary.reconstructed} point(s) · ${summary.raccords} raccord(s)$detail"\n                                suppressNextAuto = true\n                                onDataChanged()\n                            },\n                            onFailure = { info = it.message ?: "Extension météo + bâtiment impossible" }\n                        )\n                    }'''
rep(
    thermal,
    old_weather_handler,
    '''                    scope.launch { beginHistoryWork(weatherHistoryDays, "Extension historique demandée") }''',
    'weather history monthly handler'
)
old_history_handler = '''                    scope.launch {\n                        busy = true\n                        info = "Reconstruction · préparation météo…"\n                        val result = withContext(Dispatchers.IO) {\n                            runCatching {\n                                // Ordre strict v0.10.3 : la référence visible/RC est préparée AVANT tout.\n                                val prepared = manager.prepareHistory(reference, historyDays)\n                                if (!prepared.coverage.ready) {\n                                    error("${reference.city} incomplet : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")\n                                }\n                                val checked = engine.status(reference, selectedSensorId, profile)\n                                if (!checked.canReconstruct) error(checked.message)\n                                val activeId = selectedSensorId ?: checked.preferred?.sensor?.id\n                                val activeModel = checked.preferred?.model?.takeIf { it.sensorId == activeId }\n                                engine.reconstructHistory(\n                                    reference = reference,\n                                    requestedDays = historyDays,\n                                    sensorId = activeId,\n                                    profile = profile,\n                                    precalibratedModel = activeModel\n                                ) { p ->\n                                    scope.launch {\n                                        info = if (p.total > 0) {\n                                            val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)\n                                            "${p.stage} · $percent % · ${p.changed} point(s) écrit(s)"\n                                        } else p.stage\n                                        // Le callback arrive après un commit SQLite de 256 points :\n                                        // la courbe peut donc montrer la reconstruction sans attendre la fin.\n                                        if (p.total > 0 && p.processed > 0) {\n                                            suppressNextAuto = true\n                                            onDataChanged()\n                                        }\n                                    }\n                                }\n                            }\n                        }\n                        busy = false\n                        result.fold(\n                            onSuccess = {\n                                // v0.10.2 : préserver le diagnostic de reconstruction pendant\n                                // le rechargement du graphique au lieu de le remplacer aussitôt.\n                                val detail = it.diagnostic?.let { d -> " · $d" }.orEmpty()\n                                info = "Historique : ${it.reconstructed} point(s) · ${it.raccords} raccord(s) · dérive max ${fmt(it.maxRaccordDrift)} °C · ${it.skippedSensors} refus$detail"\n                                suppressNextAuto = true\n                                onDataChanged()\n                            },\n                            onFailure = { info = it.message ?: "Reconstruction refusée" }\n                        )\n                    }'''
rep(
    thermal,
    old_history_handler,
    '''                    scope.launch { beginHistoryWork(historyDays, "Reconstruction historique demandée") }''',
    'history monthly handler'
)
rep(thermal, 'maximum 36 mois.', 'maximum 48 mois.', 'history max label')
# append continuation dialog before function closes (before historyDialog block end marker)
rep(
    thermal,
    '''    if (historyDialog) {\n        AlertDialog(''',
    '''    continuationWork?.let { work ->\n        AlertDialog(\n            onDismissRequest = {},\n            title = { Text("Morceau historique terminé") },\n            text = {\n                Text("${work.nextChunk}/${work.totalChunks} mois préparé(s). La suite reste strictement du plus ancien vers le présent.")\n            },\n            confirmButton = {\n                Button(onClick = {\n                    continuationWork = null\n                    scope.launch { processNextHistoryChunk() }\n                }) { Text("Continuer") }\n            },\n            dismissButton = {\n                Row {\n                    TextButton(onClick = {\n                        historyDebtStore.pauseWork()\n                        historyDebtStore.setDebtState(HistoricalDebtState.PAUSED)\n                        refreshDebtState()\n                        continuationWork = null\n                        info = "Historique mis en pause · reprise mémorisée"\n                    }) { Text("Mettre en pause") }\n                    TextButton(onClick = {\n                        historyDebtStore.clearWork()\n                        historyDebtStore.setDebtState(HistoricalDebtState.CANCELLED)\n                        refreshDebtState()\n                        continuationWork = null\n                        info = "Traitement annulé · historique non traité conservé dans la liste des mises à jour"\n                    }) { Text("Annuler") }\n                }\n            }\n        )\n    }\n\n    if (historyDialog) {\n        AlertDialog(''',
    'continuation dialog'
)

print('FabData v0.18 history coherence patch applied')
