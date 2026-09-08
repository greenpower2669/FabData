from pathlib import Path


def once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


def all_required(text: str, old: str, new: str, label: str, minimum: int = 1) -> str:
    count = text.count(old)
    if count < minimum:
        if new in text:
            return text
        raise SystemExit(f"missing anchor: {label}, found {count}")
    return text.replace(old, new)


def patch_history_store():
    p = Path('app/src/main/java/com/fabdata/app/ThermalHistoryDebt.kt')
    t = p.read_text()

    t = once(
        t,
        '''    val requestedDays: Int,\n    val firstMeasuredTimestamp: Long,\n    val nextChunk: Int,\n''',
        '''    val requestedDays: Int,\n    val firstMeasuredTimestamp: Long,\n    // Profondeur déjà reconstruite au démarrage de CE bloc. Les nouveaux travaux\n    // v0.20.4 ajoutent au maximum 90 jours sans retraiter la préparation météo déjà faite.\n    val existingDepthDays: Int,\n    val stepDays: Int,\n    val nextChunk: Int,\n''',
        'history work incremental fields'
    )

    t = once(
        t,
        '''    fun nextRange(): LongRange? {\n        if (nextChunk !in 0 until totalChunks) return null\n        val start = oldestRequestedTimestamp + nextChunk.toLong() * HISTORY_MONTH_DAYS * HISTORY_DAY_MS\n        val endExclusive = minOf(\n            firstMeasuredTimestamp,\n            start + HISTORY_MONTH_DAYS.toLong() * HISTORY_DAY_MS\n        )\n''',
        '''    val newestStepExclusiveTimestamp: Long\n        get() = firstMeasuredTimestamp - existingDepthDays.toLong() * HISTORY_DAY_MS\n\n    fun nextRange(): LongRange? {\n        if (nextChunk !in 0 until totalChunks) return null\n        val start = oldestRequestedTimestamp + nextChunk.toLong() * HISTORY_MONTH_DAYS * HISTORY_DAY_MS\n        val endExclusive = minOf(\n            newestStepExclusiveTimestamp,\n            start + HISTORY_MONTH_DAYS.toLong() * HISTORY_DAY_MS\n        )\n''',
        'history next range incremental boundary'
    )

    old_begin = '''    fun beginWork(\n        referenceKey: String,\n        sensorId: Long,\n        requestedDays: Int,\n        firstMeasuredTimestamp: Long,\n        reason: String\n    ): ThermalHistoryWork {\n        val days = requestedDays.coerceAtLeast(1)\n        val chunks = ceil(days.toDouble() / HISTORY_MONTH_DAYS.toDouble()).toInt().coerceAtLeast(1)\n        val work = ThermalHistoryWork(\n            referenceKey = referenceKey,\n            sensorId = sensorId,\n            requestedDays = days,\n            firstMeasuredTimestamp = firstMeasuredTimestamp,\n            nextChunk = 0,\n            totalChunks = chunks,\n            reason = reason,\n            paused = false\n        )\n'''
    new_begin = '''    fun beginWork(\n        referenceKey: String,\n        sensorId: Long,\n        requestedDays: Int,\n        firstMeasuredTimestamp: Long,\n        reason: String,\n        existingDepthDays: Int = 0\n    ): ThermalHistoryWork {\n        val days = requestedDays.coerceAtLeast(1)\n        val existing = existingDepthDays.coerceIn(0, (days - 1).coerceAtLeast(0))\n        val step = (days - existing).coerceAtLeast(1)\n        val chunks = ceil(step.toDouble() / HISTORY_MONTH_DAYS.toDouble()).toInt().coerceAtLeast(1)\n        val work = ThermalHistoryWork(\n            referenceKey = referenceKey,\n            sensorId = sensorId,\n            requestedDays = days,\n            firstMeasuredTimestamp = firstMeasuredTimestamp,\n            existingDepthDays = existing,\n            stepDays = step,\n            nextChunk = 0,\n            totalChunks = chunks,\n            reason = reason,\n            paused = false\n        )\n'''
    t = once(t, old_begin, new_begin, 'begin incremental work')

    t = once(
        t,
        '''        return ThermalHistoryWork(\n            referenceKey = referenceKey,\n            sensorId = prefs.getLong("work_sensor", -1L),\n            requestedDays = requestedDays,\n            firstMeasuredTimestamp = first,\n            nextChunk = prefs.getInt("work_next_chunk", 0).coerceIn(0, total),\n''',
        '''        val existingDepth = prefs.getInt("work_existing_depth_days", 0)\n            .coerceIn(0, (requestedDays - 1).coerceAtLeast(0))\n        val stepDays = prefs.getInt("work_step_days", (requestedDays - existingDepth).coerceAtLeast(1))\n            .coerceAtLeast(1)\n        return ThermalHistoryWork(\n            referenceKey = referenceKey,\n            sensorId = prefs.getLong("work_sensor", -1L),\n            requestedDays = requestedDays,\n            firstMeasuredTimestamp = first,\n            existingDepthDays = existingDepth,\n            stepDays = stepDays,\n            nextChunk = prefs.getInt("work_next_chunk", 0).coerceIn(0, total),\n''',
        'load incremental fields'
    )

    t = once(
        t,
        '''            .remove("work_first_measured")\n            .remove("work_next_chunk")\n''',
        '''            .remove("work_first_measured")\n            .remove("work_existing_depth_days")\n            .remove("work_step_days")\n            .remove("work_next_chunk")\n''',
        'clear incremental fields'
    )

    t = once(
        t,
        '''            .putLong("work_first_measured", work.firstMeasuredTimestamp)\n            .putInt("work_next_chunk", work.nextChunk)\n''',
        '''            .putLong("work_first_measured", work.firstMeasuredTimestamp)\n            .putInt("work_existing_depth_days", work.existingDepthDays)\n            .putInt("work_step_days", work.stepDays)\n            .putInt("work_next_chunk", work.nextChunk)\n''',
        'save incremental fields'
    )

    p.write_text(t)


def patch_point_source():
    p = Path('app/src/main/java/com/fabdata/app/PointSourceLayer.kt')
    t = p.read_text()

    t = once(
        t,
        '''    val profileHash: String? = null,\n    val dependencyHash: String? = null\n)\n''',
        '''    val profileHash: String? = null,\n    val dependencyHash: String? = null,\n    // Présent lors d'un réimport FabData : empêche un ancien export calculé\n    // de remplacer silencieusement une reconstruction plus récente.\n    val sourceUpdatedAt: Long? = null\n)\n''',
        'provenance updated at'
    )

    t = once(
        t,
        '''enum class PriorityWriteResult { INSERTED, REPLACED, UNCHANGED, REJECTED }\n\ndata class PriorityPointWrite(\n''',
        '''enum class PriorityWriteResult { INSERTED, REPLACED, UNCHANGED, REJECTED }\n\nprivate data class ExistingPriorityPoint(\n    val temperature: Double,\n    val humidity: Double,\n    val source: PointSource,\n    val sourceUpdatedAt: Long?\n)\n\ndata class PriorityPointWrite(\n''',
        'existing priority point data class'
    )

    t = once(
        t,
        '''                   profile_hash, dependency_hash\n            FROM point_sources\n''',
        '''                   profile_hash, dependency_hash, updated_at\n            FROM point_sources\n''',
        'provenance select updated at'
    )
    t = once(
        t,
        '''                profileHash = if (c.isNull(10)) null else c.getString(10),\n                dependencyHash = if (c.isNull(11)) null else c.getString(11)\n            )\n''',
        '''                profileHash = if (c.isNull(10)) null else c.getString(10),\n                dependencyHash = if (c.isNull(11)) null else c.getString(11),\n                sourceUpdatedAt = if (c.isNull(12)) null else c.getLong(12)\n            )\n''',
        'provenance map updated at'
    )

    t = once(
        t,
        '''            put("updated_at", System.currentTimeMillis())\n        }\n''',
        '''            put("updated_at", provenance.sourceUpdatedAt ?: System.currentTimeMillis())\n        }\n''',
        'persist source timestamp'
    )

    t = once(
        t,
        '''            SELECT p.temperature, p.humidity, ps.source\n            FROM samples p\n''',
        '''            SELECT p.temperature, p.humidity, ps.source, ps.updated_at\n            FROM samples p\n''',
        'priority existing select timestamp'
    )
    t = once(
        t,
        '''            if (!c.moveToFirst()) null\n            else Triple(c.getDouble(0), c.getDouble(1), PointSource.fromDb(if (c.isNull(2)) null else c.getString(2)))\n        }\n''',
        '''            if (!c.moveToFirst()) null\n            else ExistingPriorityPoint(\n                temperature = c.getDouble(0),\n                humidity = c.getDouble(1),\n                source = PointSource.fromDb(if (c.isNull(2)) null else c.getString(2)),\n                sourceUpdatedAt = if (c.isNull(3)) null else c.getLong(3)\n            )\n        }\n''',
        'priority existing map'
    )
    t = once(t, '        val existingSource = existing.third\n', '        val existingSource = existing.source\n', 'existing source access')
    t = once(
        t,
        '''        if (provenance.source.priority < existingSource.priority) {\n            return PriorityWriteResult.REJECTED\n        }\n\n        val sameValues = kotlin.math.abs(existing.first - temperature) < 0.001 &&\n            kotlin.math.abs(existing.second - humidity) < 0.001\n''',
        '''        if (provenance.source.priority < existingSource.priority) {\n            return PriorityWriteResult.REJECTED\n        }\n\n        // Un export ancien RECONSTRUCTED/FORECAST ne doit jamais faire régresser une\n        // courbe recalculée depuis. MEASURED garde de toute façon la priorité absolue.\n        if (provenance.source == existingSource && provenance.source != PointSource.MEASURED &&\n            provenance.sourceUpdatedAt != null && existing.sourceUpdatedAt != null &&\n            provenance.sourceUpdatedAt < existing.sourceUpdatedAt\n        ) {\n            return PriorityWriteResult.REJECTED\n        }\n\n        val sameValues = kotlin.math.abs(existing.temperature - temperature) < 0.001 &&\n            kotlin.math.abs(existing.humidity - humidity) < 0.001\n''',
        'stale calculated import guard'
    )

    p.write_text(t)


def patch_source_export():
    p = Path('app/src/main/java/com/fabdata/app/SourceExportLayer.kt')
    t = p.read_text()

    t = once(
        t,
        '''    fun export(uri: Uri, includeReconstructed: Boolean = false, includeForecast: Boolean = false): Result {\n''',
        '''    fun export(\n        uri: Uri,\n        includeReconstructed: Boolean = false,\n        includeForecast: Boolean = false,\n        sensorId: Long? = null\n    ): Result {\n''',
        'export optional sensor'
    )

    t = once(
        t,
        '''            writer.write(FabDataBackup.HEADER)\n            writer.write("\\n")\n\n            db.readableDatabase.rawQuery(\n                """\n                SELECT s.stable_key, s.name, s.room, s.color_index,\n                       p.timestamp, p.temperature, p.humidity,\n                       ps.source, ps.confidence, ps.reference_station_id, ps.reference_city,\n                       ps.calibration_from, ps.calibration_to, ps.model_version\n                FROM samples p\n                JOIN sensors s ON s.id=p.sensor_id\n                LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp\n                WHERE (ps.source IS NULL OR ps.source='measured')\n                   OR (?=1 AND ps.source='reconstructed')\n                   OR (?=1 AND ps.source='forecast')\n                ORDER BY p.timestamp, s.id\n                """.trimIndent(),\n                arrayOf(if (includeReconstructed) "1" else "0", if (includeForecast) "1" else "0")\n            ).use { c ->\n''',
        '''            // Extension compatible du CSV FabData v3. Les colonnes supplémentaires\n            // gardent l'identité/provenance et la date du calcul pour éviter qu'un ancien\n            // export ne remplace une reconstruction plus récente au réimport.\n            writer.write(\n                FabDataBackup.HEADER +\n                    ",Reference_Key,Sigma_C,Analog_Count,Profile_Hash,Dependency_Hash,Source_UpdatedAt_ms"\n            )\n            writer.write("\\n")\n\n            val sensorClause = if (sensorId == null) "" else " AND p.sensor_id=?"\n            val args = mutableListOf(\n                if (includeReconstructed) "1" else "0",\n                if (includeForecast) "1" else "0"\n            ).apply { if (sensorId != null) add(sensorId.toString()) }.toTypedArray()\n\n            db.readableDatabase.rawQuery(\n                """\n                SELECT s.stable_key, s.name, s.room, s.color_index,\n                       p.timestamp, p.temperature, p.humidity,\n                       ps.source, ps.confidence, ps.reference_station_id, ps.reference_city,\n                       ps.calibration_from, ps.calibration_to, ps.model_version,\n                       ps.reference_key, ps.sigma_c, ps.analog_count, ps.profile_hash,\n                       ps.dependency_hash, ps.updated_at\n                FROM samples p\n                JOIN sensors s ON s.id=p.sensor_id\n                LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp\n                WHERE (\n                    (ps.source IS NULL OR ps.source='measured')\n                    OR (?=1 AND ps.source='reconstructed')\n                    OR (?=1 AND ps.source='forecast')\n                )$sensorClause\n                ORDER BY p.timestamp, s.id\n                """.trimIndent(),\n                args\n            ).use { c ->\n''',
        'source export query'
    )

    t = once(
        t,
        '''                        if (c.isNull(11)) "" else c.getLong(11).toString(),\n                        if (c.isNull(12)) "" else c.getLong(12).toString(),\n                        if (c.isNull(13)) "" else c.getString(13)\n                    ).joinToString(",") { csvEscape(it) }\n''',
        '''                        if (c.isNull(11)) "" else c.getLong(11).toString(),\n                        if (c.isNull(12)) "" else c.getLong(12).toString(),\n                        if (c.isNull(13)) "" else c.getString(13),\n                        if (c.isNull(14)) "" else c.getString(14),\n                        if (c.isNull(15)) "" else c.getDouble(15).toString(),\n                        if (c.isNull(16)) "" else c.getInt(16).toString(),\n                        if (c.isNull(17)) "" else c.getString(17),\n                        if (c.isNull(18)) "" else c.getString(18),\n                        if (c.isNull(19)) "" else c.getLong(19).toString()\n                    ).joinToString(",") { csvEscape(it) }\n''',
        'source export provenance columns'
    )

    t = once(
        t,
        '''        return Result(count, reconstructed, forecast)\n    }\n\n    private fun csvEscape(value: String): String {\n''',
        '''        return Result(count, reconstructed, forecast)\n    }\n\n    /** Exporte une seule courbe, réelle + reconstruite, sous l'identité de la sonde d'origine. */\n    fun exportSensorHistory(uri: Uri, sensorId: Long): Result =\n        export(uri, includeReconstructed = true, includeForecast = false, sensorId = sensorId)\n\n    private fun csvEscape(value: String): String {\n''',
        'targeted sensor export helper'
    )

    p.write_text(t)


def patch_backup_import():
    p = Path('app/src/main/java/com/fabdata/app/BackupLayer.kt')
    t = p.read_text()

    t = once(
        t,
        '''                                        modelVersion = col(fields, "Model_Version").trim().ifBlank { null }\n                                    )\n''',
        '''                                        modelVersion = col(fields, "Model_Version").trim().ifBlank { null },\n                                        referenceKey = col(fields, "Reference_Key").trim().ifBlank { null },\n                                        sigmaC = parseNumber(col(fields, "Sigma_C")),\n                                        analogCount = col(fields, "Analog_Count").trim().toIntOrNull(),\n                                        profileHash = col(fields, "Profile_Hash").trim().ifBlank { null },\n                                        dependencyHash = col(fields, "Dependency_Hash").trim().ifBlank { null },\n                                        sourceUpdatedAt = col(fields, "Source_UpdatedAt_ms").trim().toLongOrNull()\n                                    )\n''',
        'backup import extended provenance'
    )

    p.write_text(t)


def patch_thermal_ui():
    p = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')
    t = p.read_text()

    t = once(
        t,
        '''import androidx.compose.animation.core.tween\n''',
        '''import androidx.compose.animation.core.tween\nimport androidx.activity.compose.rememberLauncherForActivityResult\nimport androidx.activity.result.contract.ActivityResultContracts\n''',
        'activity result imports'
    )

    # Add exporter state after info/busy states, where both scope and context already exist.
    t = once(
        t,
        '''    var status by remember { mutableStateOf<ThermalStatus?>(null) }\n    var info by remember { mutableStateOf("État thermique prêt") }\n    var trainingFeedback by remember { mutableStateOf<String?>(null) }\n''',
        '''    var status by remember { mutableStateOf<ThermalStatus?>(null) }\n    var info by remember { mutableStateOf("État thermique prêt") }\n    var trainingFeedback by remember { mutableStateOf<String?>(null) }\n    val sensorHistoryExporter = remember { FabDataSourceExporter(context, db) }\n    var pendingHistoryExportSensor by remember { mutableStateOf<Sensor?>(null) }\n    val historyExportLauncher = rememberLauncherForActivityResult(\n        ActivityResultContracts.CreateDocument("text/csv")\n    ) { uri ->\n        val sensor = pendingHistoryExportSensor\n        pendingHistoryExportSensor = null\n        if (uri != null && sensor != null) {\n            scope.launch {\n                busy = true\n                info = "${sensor.name} · export réel + reconstruit…"\n                val result = withContext(Dispatchers.IO) {\n                    runCatching { sensorHistoryExporter.exportSensorHistory(uri, sensor.id) }\n                }\n                busy = false\n                info = result.fold(\n                    onSuccess = {\n                        "${sensor.name} · exporté : ${it.rows} point(s), dont ${it.reconstructed} reconstruit(s)"\n                    },\n                    onFailure = { "Export impossible : ${it.message ?: "erreur inconnue"}" }\n                )\n            }\n        }\n    }\n''',
        'sensor export launcher'
    )

    # Make new <=90 day blocks auto-continue between their ~31-day preparation chunks.
    t = once(
        t,
        '''                } else if (next != null) {\n                    continuationWork = next\n                    info = "Mois ${next.nextChunk}/${next.totalChunks} validé · choisir Continuer, Pause ou Annuler"\n                }\n''',
        '''                } else if (next != null) {\n                    if (next.stepDays <= 90) {\n                        continuationWork = null\n                        info = "Bloc +${next.stepDays} j · étape ${next.nextChunk}/${next.totalChunks} préparée · suite automatique…"\n                        // Une action utilisateur = au plus 90 jours. Les ~3 sous-morceaux\n                        // ne demandent plus trois confirmations ; le texte de progression\n                        // montre néanmoins clairement que FabData travaille.\n                        scope.launch { processNextHistoryChunk() }\n                    } else {\n                        continuationWork = next\n                        info = "Mois ${next.nextChunk}/${next.totalChunks} validé · choisir Continuer, Pause ou Annuler"\n                    }\n                }\n''',
        'auto progress 90-day block'
    )

    # Extend beginHistoryWork with existing-depth parameter and pending debt only for new slice.
    old_begin = '''    suspend fun beginHistoryWork(days: Int, reason: String) {\n        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)\n            ?: run { info = "Modèle vide ou à réentraîner"; return }\n        val activeId = activeModel.sensorId\n        val firstReal = withContext(Dispatchers.IO) { coherenceStore.firstMeasuredTimestamp(activeId) }\n            ?: run { info = "Aucune vraie mesure pour initialiser l'historique"; return }\n        val boundedDays = days.coerceIn(1, 1464)\n        historyDebtStore.beginWork(reference.key, activeId, boundedDays, firstReal, reason)\n        historyDebtStore.recordDebt(\n            reference.key, activeId,\n            firstReal - boundedDays.toLong() * 24L * 60L * 60L * 1000L,\n            firstReal, reason, HistoricalDebtState.PENDING\n        )\n        refreshDebtState()\n        processNextHistoryChunk()\n    }\n'''
    new_begin = '''    suspend fun beginHistoryWork(days: Int, reason: String, existingDepthDays: Int = 0) {\n        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)\n            ?: run { info = "Modèle vide ou à réentraîner"; return }\n        val activeId = activeModel.sensorId\n        val firstReal = withContext(Dispatchers.IO) { coherenceStore.firstMeasuredTimestamp(activeId) }\n            ?: run { info = "Aucune vraie mesure pour initialiser l'historique"; return }\n        val boundedDays = days.coerceIn(1, 1464)\n        val existing = existingDepthDays.coerceIn(0, (boundedDays - 1).coerceAtLeast(0))\n        historyDebtStore.beginWork(\n            reference.key, activeId, boundedDays, firstReal, reason, existingDepthDays = existing\n        )\n        val dayMs = 24L * 60L * 60L * 1000L\n        historyDebtStore.recordDebt(\n            reference.key, activeId,\n            firstReal - boundedDays.toLong() * dayMs,\n            firstReal - existing.toLong() * dayMs,\n            reason, HistoricalDebtState.PENDING\n        )\n        refreshDebtState()\n        processNextHistoryChunk()\n    }\n\n    /**\n     * L'utilisateur n'engage jamais plus de 90 jours à la fois. Si une tranche\n     * RECONSTRUCTED existe déjà avant la première mesure réelle, on ajoute 90 jours\n     * plus anciens ; sinon on crée la première tranche de 90 jours.\n     */\n    suspend fun beginNext90DayHistory(reason: String) {\n        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)\n            ?: run { info = "Modèle vide ou à réentraîner"; return }\n        val firstReal = withContext(Dispatchers.IO) {\n            coherenceStore.firstMeasuredTimestamp(activeModel.sensorId)\n        } ?: run {\n            info = "Aucune vraie mesure pour initialiser l'historique"\n            return\n        }\n        val dayMs = 24L * 60L * 60L * 1000L\n        val existingDepth = withContext(Dispatchers.IO) {\n            val bounds = PointSourceStore.reconstructedBounds(db, activeModel.sensorId)\n            val oldest = bounds?.first?.takeIf { it < firstReal } ?: return@withContext 0\n            (((firstReal - oldest) + dayMs - 1L) / dayMs).toInt().coerceIn(0, 1464)\n        }\n        if (existingDepth >= 1464) {\n            info = "Historique déjà au maximum de 48 mois"\n            return\n        }\n        val added = minOf(90, 1464 - existingDepth)\n        val targetDepth = existingDepth + added\n        info = if (existingDepth == 0) {\n            "Première reconstruction · $added jours · 3 étapes maximum"\n        } else {\n            "Extension de $added jours · profondeur cible ~$targetDepth jours · 3 étapes maximum"\n        }\n        beginHistoryWork(targetDepth, reason, existingDepthDays = existingDepth)\n    }\n'''
    t = once(t, old_begin, new_begin, '90 day history helper')

    # Button wording. Both legacy entry points now do one 90-day increment only.
    t = all_required(t, 'onClick = { weatherHistoryDialog = true }', 'onClick = { weatherHistoryDialog = true }', 'noop weather button')
    t = once(t, ') { Text("Étendre historique") }', ') { Text("Étendre historique +90 j") }', 'history button label')
    t = once(t, ') { Text("Estimer historique") }', ') { Text("Reconstruire +90 j") }', 'estimate button label')

    # Add per-sensor export below history actions and above guardrail text.
    anchor = '''            Text(\n                "Garde-fou : apprentissage uniquement sur MEASURED propres. Clim probable, fenêtre, saut brutal ou donnée douteuse restent visibles mais sont exclues de l’apprentissage. Météo + inertie sont obligatoires pour prolonger le passé.",\n'''
    export_block = '''            val exportSensor = status?.preferred?.sensor\n            OutlinedButton(\n                onClick = {\n                    exportSensor?.let { sensor ->\n                        pendingHistoryExportSensor = sensor\n                        val safe = sensor.name\n                            .replace(Regex("[^A-Za-z0-9._-]+"), "_")\n                            .trim('_')\n                            .ifBlank { sensor.stableKey }\n                            .take(72)\n                        historyExportLauncher.launch("FabData_${safe}_historique.csv")\n                    }\n                },\n                enabled = !busy && exportSensor != null,\n                modifier = Modifier.fillMaxWidth()\n            ) { Text("Exporter cette sonde · réel + reconstruit") }\n            Text(\n                "Le CSV garde le nom ET l'identifiant stable de la sonde d'origine. Les points calculés restent RECONSTRUCTED : une vraie mesure importée plus tard les écrase automatiquement, et un ancien export calculé ne peut pas remplacer une reconstruction plus récente.",\n                style = MaterialTheme.typography.labelSmall,\n                color = MaterialTheme.colorScheme.onSurfaceVariant\n            )\n\n''' + anchor
    t = once(t, anchor, export_block, 'sensor history export UI')

    # Simplify both indoor history dialogs: fixed 90-day increment, automatic internal chunks.
    old_weather = '''                    Text("FabData prépare automatiquement les deux petits loups : météo extérieure + inertie bâtiment, puis reconstruit l’air intérieur sur la même profondeur. Pas de courbe historique intérieure sans inertie.")\n                    Row(\n                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),\n                        horizontalArrangement = Arrangement.spacedBy(6.dp)\n                    ) {\n                        THERMAL_HISTORY_CHOICES.forEach { choice ->\n                            FilterChip(\n                                selected = weatherHistoryDays == choice.days,\n                                onClick = { weatherHistoryDays = choice.days },\n                                label = { Text(choice.label) }\n                            )\n                        }\n                    }\n                    Text("Sélection : ${thermalHistoryLabel(weatherHistoryDays)} avant la première vraie mesure intérieure.", style = MaterialTheme.typography.bodySmall)\n'''
    new_weather = '''                    Text("FabData ajoute au maximum 90 jours avant la partie déjà reconstruite. La météo est préparée en trois morceaux d’environ un mois avec progression visible, puis l’app s’arrête. Tu relances +90 j seulement si tu en as envie.")\n                    Text("Les points créés restent RECONSTRUCTED et pourront être raffinés ou remplacés par de vraies mesures.", style = MaterialTheme.typography.bodySmall)\n'''
    t = once(t, old_weather, new_weather, 'fixed 90 weather history dialog')
    t = once(
        t,
        'scope.launch { beginHistoryWork(weatherHistoryDays, "Extension historique demandée") }',
        'scope.launch { beginNext90DayHistory("Extension historique +90 j demandée") }',
        'weather dialog confirm 90'
    )
    t = once(t, ') { Text("Étendre") }', ') { Text("Ajouter +90 j") }', 'weather dialog button 90')

    old_history = '''                    Text("FabData prolonge ensemble la météo, l’état inertiel du bâtiment puis l’air intérieur. Les paramètres sont appris uniquement sur les mesures réelles propres.")\n                    Text("Choisis une limite maximale :")\n                    Row(\n                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),\n                        horizontalArrangement = Arrangement.spacedBy(6.dp)\n                    ) {\n                        THERMAL_HISTORY_CHOICES.forEach { choice ->\n                            FilterChip(\n                                selected = historyDays == choice.days,\n                                onClick = { historyDays = choice.days },\n                                label = { Text(choice.label) }\n                            )\n                        }\n                    }\n                    Text("Sélection : ${thermalHistoryLabel(historyDays)} · maximum 48 mois.", style = MaterialTheme.typography.bodySmall)\n'''
    new_history = '''                    Text("FabData reconstruit une seule sonde intérieure à la fois. Une action ajoute au maximum 90 jours, préparés en trois morceaux d’environ un mois pour rendre la progression visible.")\n                    Text("Après ces 90 jours, rien ne continue tout seul : utilise à nouveau +90 j si tu veux remonter plus loin.", style = MaterialTheme.typography.bodySmall)\n'''
    t = once(t, old_history, new_history, 'fixed 90 estimate dialog')
    t = once(
        t,
        'scope.launch { beginHistoryWork(historyDays, "Reconstruction historique demandée") }',
        'scope.launch { beginNext90DayHistory("Reconstruction historique +90 j demandée") }',
        'estimate dialog confirm 90'
    )
    t = once(t, ') { Text("Estimer") }', ') { Text("Reconstruire +90 j") }', 'estimate dialog button 90')

    p.write_text(t)


def main():
    patch_history_store()
    patch_point_source()
    patch_source_export()
    patch_backup_import()
    patch_thermal_ui()
    print('v0.20.4 90-day history + stable sensor export patch applied')


if __name__ == '__main__':
    main()
