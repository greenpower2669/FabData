from pathlib import Path


def once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


def patch_weather_reference():
    p = Path('app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt')
    t = p.read_text()

    t = once(
        t,
        '''data class WeatherReferencePoint(\n    val timestamp: Long,\n    val temperature: Double,\n    val humidity: Double,\n    val source: PointSource,\n    val confidence: Double = 1.0\n)\n\nclass WeatherReferenceStore(private val db: FabDataDb) {\n''',
        '''data class WeatherReferencePoint(\n    val timestamp: Long,\n    val temperature: Double,\n    val humidity: Double,\n    val source: PointSource,\n    val confidence: Double = 1.0\n)\n\ndata class WeatherReferenceMetadata(\n    val key: String,\n    val city: String,\n    val stationName: String,\n    val stationId: String,\n    val latitude: Double,\n    val longitude: Double,\n    val departmentId: String\n) {\n    fun asReference() = WeatherReference(key, city, stationName, stationId, latitude, longitude, departmentId)\n}\n\nclass WeatherReferenceStore(private val db: FabDataDb) {\n''',
        'weather metadata data class'
    )

    t = once(
        t,
        '''            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_weather_reference_time ON weather_reference_samples(reference_key, timestamp)")\n        }\n    }\n\n    /** Une seule référence temporelle reste en cache, conformément au choix utilisateur. */\n    fun keepOnly(referenceKey: String) {\n        db.writableDatabase.delete("weather_reference_samples", "reference_key<>?", arrayOf(referenceKey))\n    }\n''',
        '''            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_weather_reference_time ON weather_reference_samples(reference_key, timestamp)")\n            sql.execSQL(\n                """\n                CREATE TABLE IF NOT EXISTS weather_reference_meta (\n                    reference_key TEXT PRIMARY KEY,\n                    city TEXT NOT NULL,\n                    station_name TEXT NOT NULL,\n                    station_id TEXT NOT NULL,\n                    latitude REAL NOT NULL,\n                    longitude REAL NOT NULL,\n                    department_id TEXT NOT NULL DEFAULT '',\n                    updated_at INTEGER NOT NULL\n                )\n                """.trimIndent()\n            )\n        }\n    }\n\n    /**\n     * v0.20.5 regression invariant: switching weather reference MUST NOT erase another\n     * station's history. Kept for source compatibility with older callers, intentionally no-op.\n     */\n    @Suppress("UNUSED_PARAMETER")\n    fun keepOnly(referenceKey: String) = Unit\n\n    fun rememberReference(reference: WeatherReference) {\n        val v = ContentValues().apply {\n            put("reference_key", reference.key)\n            put("city", reference.city)\n            put("station_name", reference.stationName)\n            put("station_id", reference.stationId)\n            put("latitude", reference.latitude)\n            put("longitude", reference.longitude)\n            put("department_id", reference.departmentId)\n            put("updated_at", System.currentTimeMillis())\n        }\n        db.writableDatabase.insertWithOnConflict(\n            "weather_reference_meta", null, v, SQLiteDatabase.CONFLICT_REPLACE\n        )\n    }\n\n    fun referenceMetadata(referenceKey: String): WeatherReferenceMetadata? {\n        db.readableDatabase.rawQuery(\n            """\n            SELECT city, station_name, station_id, latitude, longitude, department_id\n            FROM weather_reference_meta WHERE reference_key=? LIMIT 1\n            """.trimIndent(), arrayOf(referenceKey)\n        ).use { c ->\n            if (!c.moveToFirst()) return null\n            return WeatherReferenceMetadata(\n                referenceKey, c.getString(0), c.getString(1), c.getString(2),\n                c.getDouble(3), c.getDouble(4), c.getString(5)\n            )\n        }\n    }\n\n    fun allReferenceMetadata(): List<WeatherReferenceMetadata> {\n        val out = mutableListOf<WeatherReferenceMetadata>()\n        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, city, station_name, station_id, latitude, longitude, department_id\n            FROM weather_reference_meta ORDER BY updated_at DESC\n            """.trimIndent(), null\n        ).use { c ->\n            while (c.moveToNext()) {\n                out += WeatherReferenceMetadata(\n                    c.getString(0), c.getString(1), c.getString(2), c.getString(3),\n                    c.getDouble(4), c.getDouble(5), c.getString(6)\n                )\n            }\n        }\n        return out\n    }\n''',
        'weather metadata table and keep-only invariant'
    )

    t = once(
        t,
        '''    fun refreshSelected(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {\n        store.keepOnly(reference.key)\n''',
        '''    fun refreshSelected(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {\n        store.rememberReference(reference)\n        store.keepOnly(reference.key)\n''',
        'remember reference on full refresh'
    )

    t = once(
        t,
        '''    fun refreshRecent(reference: WeatherReference): WeatherReferenceSyncResult {\n        store.keepOnly(reference.key)\n''',
        '''    fun refreshRecent(reference: WeatherReference): WeatherReferenceSyncResult {\n        store.rememberReference(reference)\n        store.keepOnly(reference.key)\n''',
        'remember reference on recent refresh'
    )

    t = once(
        t,
        '''    fun ensureLocalCache(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {\n        store.keepOnly(reference.key)\n''',
        '''    fun ensureLocalCache(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {\n        store.rememberReference(reference)\n        store.keepOnly(reference.key)\n''',
        'remember reference on cache ensure'
    )

    t = once(
        t,
        '''    fun prepareHistoryRange(reference: WeatherReference, from: Long, to: Long): WeatherReferencePreparation {\n        require(to >= from) { "Période historique invalide" }\n        val loadFrom = from - 18L * hourMs\n        val sync = refreshSelected(reference, loadFrom, to)\n        val coverage = coverage(reference.key, loadFrom, to)\n        val days = (((to - from).coerceAtLeast(0L) / (24L * hourMs)) + 1L).toInt().coerceAtLeast(1)\n        return WeatherReferencePreparation(sync, coverage, days)\n    }\n''',
        '''    fun prepareHistoryRange(reference: WeatherReference, from: Long, to: Long): WeatherReferencePreparation {\n        require(to >= from) { "Période historique invalide" }\n        val loadFrom = from - 18L * hourMs\n        val sync = refreshSelected(reference, loadFrom, to)\n        val coverage = coverage(reference.key, loadFrom, to)\n        val days = (((to - from).coerceAtLeast(0L) / (24L * hourMs)) + 1L).toInt().coerceAtLeast(1)\n        return WeatherReferencePreparation(sync, coverage, days)\n    }\n\n    /**\n     * Manual weather-history extension. Direction is intentionally PRESENT -> PAST.\n     * Each call adds at most 90 older days and NEVER triggers indoor reconstruction.\n     * Indoor thermal curves keep their opposite invariant: PAST -> PRESENT.\n     */\n    fun extendHistoryBackward(\n        reference: WeatherReference,\n        alreadyLoadedDays: Int,\n        requestedStepDays: Int = 90\n    ): WeatherReferencePreparation {\n        val depth = alreadyLoadedDays.coerceAtLeast(0)\n        val step = requestedStepDays.coerceIn(1, 90)\n        val dayMs = 24L * hourMs\n        val now = roundHour(System.currentTimeMillis())\n        val to = now - depth.toLong() * dayMs\n        val from = to - step.toLong() * dayMs\n        return prepareHistoryRange(reference, from, to)\n    }\n''',
        'manual backward weather history method'
    )

    p.write_text(t)


def patch_backup_v3():
    p = Path('app/src/main/java/com/fabdata/app/BackupV3Support.kt')
    t = p.read_text()

    t = once(
        t,
        '''        writeJson(writer, "WEATHER_META", weatherMetaJson())\n        writeJson(writer, "THERMAL_PROFILE", profileJson())\n''',
        '''        writeJson(writer, "WEATHER_META", weatherMetaJson())\n        WeatherReferenceStore(db).allReferenceMetadata().forEach { meta ->\n            writeJson(writer, "WEATHER_REFERENCE_META", JSONObject().apply {\n                put("key", meta.key)\n                put("city", meta.city)\n                put("stationName", meta.stationName)\n                put("stationId", meta.stationId)\n                put("latitude", meta.latitude)\n                put("longitude", meta.longitude)\n                put("departmentId", meta.departmentId)\n            })\n        }\n        writeJson(writer, "THERMAL_PROFILE", profileJson())\n''',
        'backup all weather reference metadata'
    )

    t = once(
        t,
        '''                "WEATHER_META" -> restoreWeatherMeta(json(values))\n                "THERMAL_PROFILE" -> restoreProfile(json(values))\n''',
        '''                "WEATHER_META" -> restoreWeatherMeta(json(values))\n                "WEATHER_REFERENCE_META" -> restoreWeatherReferenceMeta(json(values))\n                "THERMAL_PROFILE" -> restoreProfile(json(values))\n''',
        'restore weather reference metadata record'
    )

    t = once(
        t,
        '''    private fun restoreProfile(o: JSONObject) {\n''',
        '''    private fun restoreWeatherReferenceMeta(o: JSONObject) {\n        WeatherReferenceStore(db).rememberReference(\n            WeatherReference(\n                key = o.getString("key"),\n                city = o.getString("city"),\n                stationName = o.getString("stationName"),\n                stationId = o.getString("stationId"),\n                latitude = o.getDouble("latitude"),\n                longitude = o.getDouble("longitude"),\n                departmentId = o.optString("departmentId", "")\n            )\n        )\n    }\n\n    private fun restoreProfile(o: JSONObject) {\n''',
        'restore weather metadata function'
    )

    p.write_text(t)


def patch_thermal_ui():
    p = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')
    t = p.read_text()

    t = once(
        t,
        '''    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }\n    val trainedModelStore = remember { ThermalTrainedModelStore(context) }\n''',
        '''    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }\n    val weatherMigrationStore = remember { WeatherReferenceMigrationStore(context) }\n    val trainedModelStore = remember { ThermalTrainedModelStore(context) }\n''',
        'remember migration store'
    )

    t = once(
        t,
        '''    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }\n    val reference = remember(selectedKey) { prefs.selectedReference() }\n    var trainedModel by remember { mutableStateOf<ThermalModel?>(null) }\n''',
        '''    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }\n    val reference = remember(selectedKey) { prefs.selectedReference() }\n    var weatherMigration by remember { mutableStateOf(weatherMigrationStore.load()) }\n    var trainedModel by remember { mutableStateOf<ThermalModel?>(null) }\n''',
        'migration compose state'
    )

    t = once(
        t,
        '''    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }\n\n    LaunchedEffect(selectedKey, selectedSensorId, dataVersion) {\n''',
        '''    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }\n\n    fun switchWeatherReference(next: WeatherReference, auto: Boolean) {\n        val previous = reference\n        if (previous.key != next.key) {\n            weatherMigrationStore.recordSwitch(previous, next)\n        }\n        prefs.setAutoProtection(auto)\n        prefs.select(next)\n        selectedKey = next.key\n        weatherMigration = weatherMigrationStore.load()\n    }\n\n    LaunchedEffect(selectedKey, selectedSensorId, dataVersion) {\n''',
        'switch reference helper'
    )

    t = once(
        t,
        '''    fun refreshDebtState() { debtSnapshot = historyDebtStore.loadDebt() }\n\n    suspend fun processNextHistoryChunk() {\n''',
        '''    fun refreshDebtState() { debtSnapshot = historyDebtStore.loadDebt() }\n\n    suspend fun extendWeatherBackward90() {\n        val migration = weatherMigrationStore.load()?.takeIf { it.newKey == reference.key }\n            ?: run { info = "Aucun changement de station météo à traiter"; return }\n        if (busy) return\n        busy = true\n        info = "${reference.label} · météo : +90 j vers le passé…"\n        val result = withContext(Dispatchers.IO) {\n            runCatching {\n                manager.extendHistoryBackward(\n                    reference = reference,\n                    alreadyLoadedDays = migration.reconstructedDepthDays,\n                    requestedStepDays = 90\n                )\n            }\n        }\n        busy = false\n        result.fold(\n            onSuccess = { prepared ->\n                weatherMigrationStore.addReconstructedDepth(90)\n                weatherMigration = weatherMigrationStore.load()\n                val depth = weatherMigration?.reconstructedDepthDays ?: 90\n                info = "${reference.label} · météo étendue à ~$depth j vers le passé · couverture ${(prepared.coverage.coverage * 100).toInt()} %"\n                suppressNextAuto = true\n                onDataChanged()\n            },\n            onFailure = { error ->\n                info = error.message ?: "Extension météo 90 j impossible"\n            }\n        )\n    }\n\n    suspend fun processNextHistoryChunk() {\n''',
        'manual weather history helper'
    )

    t = once(
        t,
        '''                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()\n                    ?: error("Aucune donnée intérieure")\n                val from = if (allHistory) bounds.first - 90L * 24L * 60L * 60L * 1000L else bounds.first - 18L * 60L * 60L * 1000L\n                val to = maxOf(bounds.last, System.currentTimeMillis() + (forecastMode.maxHours + 2L) * 60L * 60L * 1000L)\n''',
        '''                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()\n                    ?: error("Aucune donnée intérieure")\n                val now = System.currentTimeMillis()\n                // v0.20.5: "Actualiser météo" no longer dives to the oldest indoor point.\n                // A full click means at most the latest 90 weather days. Older weather is\n                // added only with the explicit +90 j migration action (present -> past).\n                val from = if (allHistory) now - 90L * 24L * 60L * 60L * 1000L\n                    else bounds.first - 18L * 60L * 60L * 1000L\n                val to = maxOf(bounds.last, now + (forecastMode.maxHours + 2L) * 60L * 60L * 1000L)\n''',
        'limit ordinary weather refresh to latest 90 days'
    )

    t = once(
        t,
        '''                                onClick = {\n                                    prefs.setAutoProtection(false)\n                                    prefs.select(station.key)\n                                    selectedKey = station.key\n                                    menuOpen = false\n                                }\n''',
        '''                                onClick = {\n                                    switchWeatherReference(station, auto = false)\n                                    menuOpen = false\n                                }\n''',
        'dropdown reference switch'
    )

    t = once(
        t,
        '''                    onClick = {\n                        prefs.setAutoProtection(false)\n                        prefs.select(WeatherReferenceCatalog.DEFAULT_KEY)\n                        selectedKey = WeatherReferenceCatalog.DEFAULT_KEY\n                    },\n''',
        '''                    onClick = {\n                        switchWeatherReference(\n                            WeatherReferenceCatalog.byKey(WeatherReferenceCatalog.DEFAULT_KEY),\n                            auto = false\n                        )\n                    },\n''',
        'reset reference switch'
    )

    station_anchor = '''            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {\n                OutlinedButton(\n                    onClick = { stationDiscoveryOpen = true },\n                    enabled = !busy,\n                    modifier = Modifier.weight(1f)\n                ) { Text("Sondes proches · Auto") }\n                TextButton(\n                    onClick = {\n                        switchWeatherReference(\n                            WeatherReferenceCatalog.byKey(WeatherReferenceCatalog.DEFAULT_KEY),\n                            auto = false\n                        )\n                    },\n                    enabled = !busy\n                ) { Text("Réinitialiser") }\n            }\n'''
    station_panel = station_anchor + '''\n            weatherMigration?.takeIf { it.newKey == reference.key }?.let { migration ->\n                Card(shape = RoundedCornerShape(14.dp)) {\n                    Column(\n                        Modifier.fillMaxWidth().padding(12.dp),\n                        verticalArrangement = Arrangement.spacedBy(7.dp)\n                    ) {\n                        Text("Changement de station météo", fontWeight = FontWeight.SemiBold)\n                        Text(\n                            "${migration.oldLabel} → ${migration.newLabel}",\n                            style = MaterialTheme.typography.bodySmall\n                        )\n                        Text(\n                            "Les 3 actions restent disponibles ici, même après redémarrage. " +\n                                "Aucune courbe intérieure n'est recalculée automatiquement.",\n                            style = MaterialTheme.typography.labelSmall,\n                            color = MaterialTheme.colorScheme.onSurfaceVariant\n                        )\n                        Text(\n                            "⚠ Invariant anti-régression : météo = présent → passé par +90 j ; " +\n                                "thermique intérieur = passé → présent uniquement.",\n                            style = MaterialTheme.typography.labelSmall,\n                            color = MaterialTheme.colorScheme.tertiary\n                        )\n                        OutlinedButton(\n                            onClick = {\n                                weatherMigrationStore.markKeepOld()\n                                weatherMigration = weatherMigrationStore.load()\n                                info = "Ancien historique météo conservé · nouvelle station utilisée en live"\n                            },\n                            enabled = !busy && !migration.oldHistoryDeleted,\n                            modifier = Modifier.fillMaxWidth()\n                        ) {\n                            Text(if (migration.keepOldChosen) "✓ Conserver l'ancien historique" else "Conserver l'ancien historique")\n                        }\n                        OutlinedButton(\n                            onClick = {\n                                scope.launch {\n                                    busy = true\n                                    val result = withContext(Dispatchers.IO) {\n                                        runCatching { manager.store().clear(migration.oldKey) }\n                                    }\n                                    busy = false\n                                    result.fold(\n                                        onSuccess = {\n                                            weatherMigrationStore.markOldDeleted()\n                                            weatherMigration = weatherMigrationStore.load()\n                                            info = "${migration.oldLabel} · ancien historique météo effacé"\n                                            suppressNextAuto = true\n                                            onDataChanged()\n                                        },\n                                        onFailure = { info = it.message ?: "Suppression météo impossible" }\n                                    )\n                                }\n                            },\n                            enabled = !busy && !migration.oldHistoryDeleted,\n                            modifier = Modifier.fillMaxWidth()\n                        ) {\n                            Text(if (migration.oldHistoryDeleted) "✓ Ancien historique effacé" else "Effacer l'ancien historique")\n                        }\n                        Button(\n                            onClick = { scope.launch { extendWeatherBackward90() } },\n                            enabled = !busy,\n                            modifier = Modifier.fillMaxWidth()\n                        ) {\n                            Text("Reconstruire nouvelle météo · +90 j")\n                        }\n                        Text(\n                            "Profondeur nouvelle station : ~${migration.reconstructedDepthDays} j. " +\n                                "Les courbes intérieures existantes gardent leur station/provenance d'origine tant que tu ne demandes pas leur recalcul.",\n                            style = MaterialTheme.typography.labelSmall,\n                            color = MaterialTheme.colorScheme.onSurfaceVariant\n                        )\n                    }\n                }\n            }\n'''
    t = once(t, station_anchor, station_panel, 'persistent three weather actions panel')

    t = once(
        t,
        '''                ) { Text(if (busy) "Chargement…" else "Actualiser référence") }\n''',
        '''                ) { Text(if (busy) "Chargement…" else "Actualiser météo · 90 j") }\n''',
        'weather refresh label'
    )

    t = once(
        t,
        '''            onSelect = { station, auto ->\n                prefs.setAutoProtection(auto)\n                prefs.select(station)\n                selectedKey = station.key\n                stationDiscoveryOpen = false\n            }\n''',
        '''            onSelect = { station, auto ->\n                switchWeatherReference(station, auto)\n                stationDiscoveryOpen = false\n            }\n''',
        'station discovery switch'
    )

    p.write_text(t)


def patch_engine_invariant():
    p = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt')
    t = p.read_text()
    t = once(
        t,
        '''            val requestedStart = first.timestamp - days.toLong() * THERMAL_DAY_MS\n            val startAt = max(requestedStart, refBounds.first)\n            if (startAt >= first.timestamp) {\n''',
        '''            val requestedStart = first.timestamp - days.toLong() * THERMAL_DAY_MS\n            val startAt = max(requestedStart, refBounds.first)\n            // v0.20.5 anti-régression : une courbe intérieure dépend d'un état thermique\n            // antérieur. Toute reconstruction intérieure est donc FORWARD, passé -> présent.\n            if (startAt >= first.timestamp) {\n''',
        'indoor forward invariant comment'
    )
    p.write_text(t)


def regression_guard():
    weather = Path('app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt').read_text()
    ui = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt').read_text()
    engine = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt').read_text()

    keep_start = weather.index('fun keepOnly(referenceKey: String)')
    keep_slice = weather[keep_start:keep_start + 220]
    if 'delete(' in keep_slice or 'weather_reference_samples' in keep_slice:
        raise SystemExit('REGRESSION: keepOnly deletes another weather reference')
    required = [
        'Reconstruire nouvelle météo · +90 j',
        'Conserver l\'ancien historique',
        'Effacer l\'ancien historique',
        'météo = présent → passé',
        'thermique intérieur = passé → présent'
    ]
    for token in required:
        if token not in ui:
            raise SystemExit(f'REGRESSION: missing persistent weather action/invariant: {token}')
    if 'Toute reconstruction intérieure est donc FORWARD, passé -> présent.' not in engine:
        raise SystemExit('REGRESSION: indoor forward-only invariant missing')


if __name__ == '__main__':
    patch_weather_reference()
    patch_backup_v3()
    patch_thermal_ui()
    patch_engine_invariant()
    regression_guard()
    print('v0.20.5 weather migration patch applied')
