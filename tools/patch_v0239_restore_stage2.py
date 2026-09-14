from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"pattern not found: {label}")
    return text.replace(old, new, 1)


# Stage 2: the RAW path is now fast. Avoid schema/store setup inside the huge
# transaction and make the tiny extended-state phase observable row-by-row.
backup_path = Path("app/src/main/java/com/fabdata/app/BackupLayer.kt")
backup = backup_path.read_text(encoding="utf-8")

backup = replace_once(
    backup,
    '''            PointSourceStore.ensure(db.writableDatabase)\n            val v3Support = FabDataBackupV3Support(context, db)\n\n            db.inTransaction {\n''',
    '''            PointSourceStore.ensure(db.writableDatabase)\n            val v3Support = FabDataBackupV3Support(context, db)\n            // Prépare une seule fois les tables/index/stores AVANT la grosse transaction.\n            // Cela évite des CREATE TABLE/INDEX répétés pendant la restauration et les\n            // attentes de verrou de schéma face aux lecteurs UI/overlay.\n            FabOperationRegistry.update(\n                operationId,\n                "Préparation des structures de restauration…",\n                0,\n                totalRecords\n            )\n            v3Support.prepareRestore()\n\n            db.inTransaction {\n''',
    "prepare extended restore before transaction",
)

backup = replace_once(
    backup,
    '''            fun stageFor(record: String): String = when {\n                record == "SAMPLE" -> "Mesures RAW $doneSamples/$totalSamples"\n                record == "WEATHER" -> "Météo $doneWeather/$totalWeather"\n                record == "UI_PREFERENCES" -> "Personnalisation $donePreferences/$totalPreferences"\n                record in archiveTypes -> "Archives $doneArchives/$totalArchives"\n                record == "SENSOR" -> "Capteurs"\n                record == "EVENT" -> "Événements"\n                record == "BACKUP_END" -> "Finalisation"\n                else -> "État FabData"\n            }\n''',
    '''            fun stageFor(record: String): String = when {\n                record == "SAMPLE" -> "Mesures RAW $doneSamples/$totalSamples"\n                record == "WEATHER" -> "Météo $doneWeather/$totalWeather"\n                record == "UI_PREFERENCES" -> "Personnalisation $donePreferences/$totalPreferences"\n                record == "WEATHER_META" -> "Référence météo"\n                record == "WEATHER_REFERENCE_META" -> "Métadonnées station météo"\n                record == "THERMAL_PROFILE" -> "Profil thermique"\n                record == "TRAINED_MODEL" -> "Modèle thermique entraîné"\n                record == "WALL" -> "Configuration des murs"\n                record == "SENSOR_THERMAL" -> "Rôles thermiques des sondes"\n                record == "WALL_SOLAR_MODEL" -> "Modèle solaire des murs"\n                record == "TRAINING_POLICY" -> "Sélections d’apprentissage"\n                record == "TRAINING_EXCLUSION" -> "Exclusions d’apprentissage"\n                record in archiveTypes -> "Archives $doneArchives/$totalArchives"\n                record == "SENSOR" -> "Capteurs"\n                record == "EVENT" -> "Événements"\n                record == "BACKUP_END" -> "Finalisation"\n                else -> "État FabData"\n            }\n''',
    "specific extended-state progress labels",
)

backup = replace_once(
    backup,
    '''                            else -> {\n                                if (record == "WEATHER") doneWeather++\n                                if (record == "UI_PREFERENCES") donePreferences++\n                                if (record in archiveTypes) doneArchives++\n                                val rowMap = header.mapIndexed { i, name ->\n''',
    '''                            else -> {\n                                // Pour les petites lignes d’état, annonce la ligne AVANT son\n                                // traitement. Si un store attend un verrou, l’écran nomme donc\n                                // exactement l’étape courante au lieu d’afficher la ligne précédente.\n                                if (record != "WEATHER" && record !in archiveTypes && operationId != null) {\n                                    FabOperationRegistry.update(\n                                        operationId,\n                                        "Traitement · ${stageFor(record)} · ligne ${rowIndex + 1}/$totalRecords",\n                                        rowIndex,\n                                        totalRecords\n                                    )\n                                }\n                                if (record == "WEATHER") doneWeather++\n                                if (record == "UI_PREFERENCES") donePreferences++\n                                if (record in archiveTypes) doneArchives++\n                                val rowMap = header.mapIndexed { i, name ->\n''',
    "pre-row extended-state diagnostics",
)

backup_path.write_text(backup, encoding="utf-8")


support_path = Path("app/src/main/java/com/fabdata/app/BackupV3Support.kt")
support = support_path.read_text(encoding="utf-8")

support = replace_once(
    support,
    '''    }\n\n    fun writeExtraRows(writer: Writer) {\n''',
    '''    }\n\n    // Import restore stores are cached for the whole backup. Constructing e.g.\n    // WeatherReferenceStore for every WEATHER row re-ran schema checks thousands\n    // of times and could contend with the forecast overlay reader.\n    private val restoreWeatherStore by lazy(LazyThreadSafetyMode.NONE) { WeatherReferenceStore(db) }\n    private val restoreWallStore by lazy(LazyThreadSafetyMode.NONE) { ThermalWallConfigStore(db) }\n    private val restoreWallSolarStore by lazy(LazyThreadSafetyMode.NONE) { ThermalWallSolarModelStore(db) }\n    private val restoreTrainingPolicyStore by lazy(LazyThreadSafetyMode.NONE) { ThermalTrainingPolicyStore(db) }\n    private var restorePrepared = false\n\n    /** Prepare every additive schema once, outside the bulk restore transaction. */\n    fun prepareRestore() {\n        if (restorePrepared) return\n        val sql = db.writableDatabase\n        ThermalTrainingPolicyStore.ensure(sql)\n        ThermalWallConfigStore.ensure(sql)\n        ThermalWallSolarModelStore.ensure(sql)\n        WeatherReferenceStore.ensure(sql)\n        ForecastMemoryStore.ensure(sql)\n        ForecastLocalSnapshotStore.ensure(sql)\n        ForecastPastArchiveStore.ensure(sql)\n        ForecastCurve10mStore.ensure(sql)\n        ForecastAdaptiveStore.ensure(sql)\n        // Force the cached constructors now too; subsequent rows perform data writes only.\n        restoreWeatherStore\n        restoreWallStore\n        restoreWallSolarStore\n        restoreTrainingPolicyStore\n        restorePrepared = true\n    }\n\n    private fun sensorIdByStableKey(stableKey: String): Long? {\n        if (stableKey.isBlank()) return null\n        return db.readableDatabase.rawQuery(\n            "SELECT id FROM sensors WHERE stable_key=? LIMIT 1",\n            arrayOf(stableKey)\n        ).use { c -> if (c.moveToFirst()) c.getLong(0) else null }\n    }\n\n    fun writeExtraRows(writer: Writer) {\n''',
    "cached restore stores and prepareRestore",
)

support = replace_once(
    support,
    '''    fun importRecord(record: String, values: Map<String, String>): Boolean {\n        return runCatching {\n''',
    '''    fun importRecord(record: String, values: Map<String, String>): Boolean {\n        if (!restorePrepared) prepareRestore()\n        return runCatching {\n''',
    "prepare restore fallback",
)

support = support.replace(
    'WeatherReferenceStore(db).rememberReference(',
    'restoreWeatherStore.rememberReference(',
)
support = support.replace(
    'ThermalWallConfigStore(db).upsertWall(',
    'restoreWallStore.upsertWall(',
)
support = support.replace(
    'ThermalWallConfigStore(db).setSensorConfig(',
    'restoreWallStore.setSensorConfig(',
)
support = support.replace(
    'ThermalWallSolarModelStore(db).save(',
    'restoreWallSolarStore.save(',
)
support = support.replace(
    'ThermalTrainingPolicyStore(db).apply(',
    'restoreTrainingPolicyStore.apply(',
)
support = support.replace(
    'WeatherReferenceStore(db).upsert(',
    'restoreWeatherStore.upsert(',
)

support = replace_once(
    support,
    '''        val stableKey = o.optString("sensorStableKey", "")\n        val sensorId = db.sensors().firstOrNull { it.stableKey == stableKey }?.id\n            ?: o.optLong("sensorId", -1L)\n''',
    '''        val stableKey = o.optString("sensorStableKey", "")\n        val sensorId = sensorIdByStableKey(stableKey) ?: o.optLong("sensorId", -1L)\n''',
    "trained model direct sensor id",
)

support = replace_once(
    support,
    '''    private fun restoreSensorThermal(o: JSONObject) {\n        val sensor = db.sensors().firstOrNull { it.stableKey == o.optString("stableKey") } ?: return\n        restoreWallStore.setSensorConfig(\n            SensorThermalConfig(\n                sensorId = sensor.id,\n''',
    '''    private fun restoreSensorThermal(o: JSONObject) {\n        val sensorId = sensorIdByStableKey(o.optString("stableKey")) ?: return\n        restoreWallStore.setSensorConfig(\n            SensorThermalConfig(\n                sensorId = sensorId,\n''',
    "sensor thermal direct sensor id",
)

support = replace_once(
    support,
    '''    private fun restoreTrainingExclusion(o: JSONObject) {\n        if (!o.optBoolean("enabled", true)) return\n        val sensor = db.sensors().firstOrNull { it.stableKey == o.optString("stableKey") } ?: return\n        ThermalTrainingMaskStore(db).addMerged(\n            sensor.id,\n''',
    '''    private fun restoreTrainingExclusion(o: JSONObject) {\n        if (!o.optBoolean("enabled", true)) return\n        val sensorId = sensorIdByStableKey(o.optString("stableKey")) ?: return\n        ThermalTrainingMaskStore(db).addMerged(\n            sensorId,\n''',
    "training exclusion direct sensor id",
)

support = replace_once(
    support,
    '''    private fun restoreForecastArchive(o: JSONObject) {\n        ForecastMemoryStore.ensure(db.writableDatabase)\n''',
    '''    private fun restoreForecastArchive(o: JSONObject) {\n''',
    "forecast memory already prepared",
)

support_path.write_text(support, encoding="utf-8")
print("stage-2 restore optimization applied")
