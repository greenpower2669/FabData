from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def write(rel, text):
    (ROOT / rel).write_text(text, encoding='utf-8')


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f'anchor missing: {label}')
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# MainActivity: central activity button, single-flight manual refresh,
# overview min/max, weather overview decimation, visible reload diagnostics.
# ---------------------------------------------------------------------------
rel = 'app/src/main/java/com/fabdata/app/MainActivity.kt'
s = read(rel)

s = replace_once(
    s,
    '    var settingsOpen by remember { mutableStateOf(false) }\n',
    '    var settingsOpen by remember { mutableStateOf(false) }\n'
    '    var processActivityOpen by remember { mutableStateOf(false) }\n',
    'process activity state'
)

s = replace_once(
    s,
    '    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs) {\n'
    '        busy = true\n',
    '    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs) {\n'
    '        val reloadStarted = System.currentTimeMillis()\n'
    '        val reloadOperation = FabOperationRegistry.tryStart(\n'
    '            "ui-reload", "Actualisation affichage", "Lecture des courbes…", cancellable = false\n'
    '        )\n'
    '        try {\n'
    '        busy = true\n',
    'reload operation begin'
)

s = replace_once(
    s,
    '        busy = false\n'
    '    }\n\n'
    '    val visualReference = WeatherReferencePrefs(context).selectedReference()\n',
    '        busy = false\n'
    '        } finally {\n'
    '            busy = false\n'
    '            FabOperationRegistry.finish(\n'
    '                reloadOperation,\n'
    '                "Affichage prêt · ${System.currentTimeMillis() - reloadStarted} ms"\n'
    '            )\n'
    '        }\n'
    '    }\n\n'
    '    val visualReference = WeatherReferencePrefs(context).selectedReference()\n',
    'reload operation finally'
)

old_weather_preview = '''                val overviewReference = weatherReferenceStore.query(
                    selectedWeatherReference.key, all.first, all.last
                ).filter { it.source != PointSource.FORECAST }.map {
                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, it.source, it.confidence)
                }
                val overviewWithReference = overview + (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference)
'''
new_weather_preview = '''                val overviewReferenceRaw = weatherReferenceStore.query(
                    selectedWeatherReference.key, all.first, all.last
                ).filter { it.source != PointSource.FORECAST }.map {
                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, it.source, it.confidence)
                }
                // v0.20.7 performance: le bandeau n'a pas besoin de dizaines de milliers
                // de points météo. On garde les extrémités et ~1200 points réguliers.
                val overviewReference = if (overviewReferenceRaw.size <= 1200) overviewReferenceRaw else {
                    val step = ((overviewReferenceRaw.size + 1199) / 1200).coerceAtLeast(1)
                    val sampled = overviewReferenceRaw.filterIndexed { index, _ -> index % step == 0 }.toMutableList()
                    overviewReferenceRaw.lastOrNull()?.let { last ->
                        if (sampled.lastOrNull()?.timestamp != last.timestamp) sampled += last
                    }
                    sampled
                }
                val overviewWithReference = overview + (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference)
'''
s = replace_once(s, old_weather_preview, new_weather_preview, 'weather overview decimation')

s = replace_once(
    s,
    '    Scaffold(\n',
    '    val activeProcessCount = FabOperationRegistry.operations.count { it.active }\n\n'
    '    Scaffold(\n',
    'active process count'
)

s = replace_once(
    s,
    '                            if (busy) "Mise à jour…" else "Courbes & événements",\n',
    '                            if (busy || thermalBusy || activeProcessCount > 0) {\n'
    '                                if (activeProcessCount > 0) "Mise à jour… · $activeProcessCount tâche(s)" else "Mise à jour…"\n'
    '                            } else "Courbes & événements",\n',
    'top subtitle processes'
)

s = replace_once(
    s,
    '                actions = {\n'
    '                    IconButton(onClick = {\n'
    '                        picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel"))\n'
    '                    }) { Icon(Icons.Default.FileOpen, contentDescription = "Importer des CSV") }\n',
    '                actions = {\n'
    '                    IconButton(onClick = { processActivityOpen = true }) {\n'
    '                        Text(\n'
    '                            if (activeProcessCount > 0) "↕$activeProcessCount" else "↕",\n'
    '                            fontWeight = FontWeight.Bold\n'
    '                        )\n'
    '                    }\n'
    '                    IconButton(onClick = {\n'
    '                        picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel"))\n'
    '                    }) { Icon(Icons.Default.FileOpen, contentDescription = "Importer des CSV") }\n',
    'top activity button'
)

old_refresh = '''                    IconButton(onClick = {
                        scope.launch {
                            busy = true
                            val selected = WeatherReferencePrefs(context).selectedReference()
                            val result = withContext(Dispatchers.IO) {
                                runCatching {
                                    if (selected.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                                        syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials)
                                    }
                                    weatherReferenceManager.refreshRecent(selected)
                                }
                            }
                            busy = false
                            reloadToken++
                            snackbar.showSnackbar(
                                result.fold(
                                    onSuccess = { "${it.label} · ${it.measured} réel(s) · ${it.reconstructed} reconstruit(s)" },
                                    onFailure = { "Station météo non actualisée : ${it.message ?: "réseau ou source indisponible"}" }
                                )
                            )
                        }
                    }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Actualiser Lyon et les courbes")
                    }
'''
new_refresh = '''                    IconButton(onClick = {
                        val selected = WeatherReferencePrefs(context).selectedReference()
                        val operationId = FabOperationRegistry.tryStart(
                            "weather:${selected.key}",
                            "Actualisation météo",
                            "${selected.label} · démarrage…"
                        )
                        if (operationId == null) {
                            processActivityOpen = true
                            scope.launch { snackbar.showSnackbar("Une routine météo est déjà en cours") }
                        } else scope.launch {
                            busy = true
                            FabOperationRegistry.update(operationId, "${selected.label} · téléchargement récent…")
                            val result = withContext(Dispatchers.IO) {
                                runCatching {
                                    if (selected.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                                        syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials)
                                    }
                                    weatherReferenceManager.refreshRecent(selected)
                                }
                            }
                            busy = false
                            if (FabOperationRegistry.cancelRequested(operationId)) {
                                FabOperationRegistry.cancelled(operationId, "Arrêt demandé · bloc réseau terminé")
                            } else {
                                reloadToken++
                            }
                            snackbar.showSnackbar(
                                result.fold(
                                    onSuccess = {
                                        FabOperationRegistry.finish(operationId, "${it.label} · ${it.measured} réel(s) · ${it.reconstructed} reconstruit(s)")
                                        "${it.label} · ${it.measured} réel(s) · ${it.reconstructed} reconstruit(s)"
                                    },
                                    onFailure = {
                                        val message = it.message ?: "réseau ou source indisponible"
                                        FabOperationRegistry.fail(operationId, message)
                                        "Station météo non actualisée : $message"
                                    }
                                )
                            )
                        }
                    }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Actualiser Lyon et les courbes")
                    }
'''
s = replace_once(s, old_refresh, new_refresh, 'manual refresh registry')

s = replace_once(
    s,
    '\n    if (settingsOpen) {\n',
    '\n    if (processActivityOpen) {\n'
    '        FabProcessActivityDialog(onDismiss = { processActivityOpen = false })\n'
    '    }\n\n'
    '    if (settingsOpen) {\n',
    'process dialog'
)

# Meta-band inside HistoryOverviewCard, calculated strictly on previewWindow.
s = replace_once(
    s,
    '                val minTemp = visiblePoints.minOfOrNull { it.temperature } ?: 0.0\n'
    '                val maxTemp = visiblePoints.maxOfOrNull { it.temperature } ?: 1.0\n'
    '                val tempRange = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0\n',
    '                val minPoint = visiblePoints.minByOrNull { it.temperature }\n'
    '                val maxPoint = visiblePoints.maxByOrNull { it.temperature }\n'
    '                val minTemp = minPoint?.temperature ?: 0.0\n'
    '                val maxTemp = maxPoint?.temperature ?: 1.0\n'
    '                val tempRange = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0\n',
    'overview extrema points'
)

meta_anchor = '''                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)

                Canvas(
'''
meta_new = '''                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)

                if (minPoint != null && maxPoint != null) {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.42f)
                    ) {
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 8.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text("MIN ${String.format(Locale.getDefault(), "%.1f°", minPoint.temperature)}", fontWeight = FontWeight.SemiBold)
                                Text(formatDateTime(minPoint.timestamp), style = MaterialTheme.typography.labelSmall)
                            }
                            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                                Text(
                                    "MAX ${String.format(Locale.getDefault(), "%.1f°", maxPoint.temperature)}",
                                    fontWeight = FontWeight.Bold,
                                    color = overviewMaximumColor(maxPoint.temperature)
                                )
                                Text(formatDateTime(maxPoint.timestamp), style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }

                Canvas(
'''
s = replace_once(s, meta_anchor, meta_new, 'overview min max band')

s = replace_once(
    s,
    'private fun formatDateTime(epoch: Long): String =\n',
    'private fun overviewMaximumColor(value: Double): Color = when {\n'
    '    value >= 40.0 -> Color(0xFF7B1FA2) // violet : chaleur extrême\n'
    '    value >= 35.0 -> Color(0xFFC62828)\n'
    '    value >= 30.0 -> Color(0xFFD1495B)\n'
    '    value >= 25.0 -> Color(0xFFE08E0B)\n'
    '    else -> Color(0xFF2A9D8F)\n'
    '}\n\n'
    'private fun formatDateTime(epoch: Long): String =\n',
    'overview maximum color helper'
)

write(rel, s)


# ---------------------------------------------------------------------------
# ThermalUi: operation history, cooperative cancellation, no full reload on
# every SQLite batch, visible training / weather process diagnostics.
# ---------------------------------------------------------------------------
rel = 'app/src/main/java/com/fabdata/app/ThermalUi.kt'
s = read(rel)

s = replace_once(
    s,
    '    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }\n',
    '    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }\n'
    '    var historyOperationId by remember { mutableStateOf<Long?>(null) }\n'
    '    var inertiaOperationId by remember { mutableStateOf<Long?>(null) }\n',
    'thermal operation ids'
)

# Weather +90 migration becomes visible and single-flight.
old = '''    suspend fun extendWeatherBackward90() {
        val migration = weatherMigrationStore.load()?.takeIf { it.newKey == reference.key }
            ?: run { info = "Aucun changement de station météo à traiter"; return }
        if (busy) return
        busy = true
        info = "${reference.label} · météo : +90 j vers le passé…"
'''
new = '''    suspend fun extendWeatherBackward90() {
        val migration = weatherMigrationStore.load()?.takeIf { it.newKey == reference.key }
            ?: run { info = "Aucun changement de station météo à traiter"; return }
        if (busy) return
        val operationId = FabOperationRegistry.tryStart(
            "weather:${reference.key}",
            "Historique météo +90 j",
            "${reference.label} · présent → passé"
        ) ?: run {
            info = "Une routine météo est déjà en cours · ouvre ↕ Activité"
            return
        }
        busy = true
        info = "${reference.label} · météo : +90 j vers le passé…"
        FabOperationRegistry.update(operationId, info)
'''
s = replace_once(s, old, new, 'weather history operation begin')

s = replace_once(
    s,
    '                suppressNextAuto = true\n'
    '                onDataChanged()\n'
    '            },\n'
    '            onFailure = { error ->\n'
    '                info = error.message ?: "Extension météo 90 j impossible"\n'
    '            }\n'
    '        )\n'
    '    }\n\n'
    '    suspend fun processNextHistoryChunk() {\n',
    '                suppressNextAuto = true\n'
    '                onDataChanged()\n'
    '                FabOperationRegistry.finish(operationId, info)\n'
    '            },\n'
    '            onFailure = { error ->\n'
    '                info = error.message ?: "Extension météo 90 j impossible"\n'
    '                FabOperationRegistry.fail(operationId, info)\n'
    '            }\n'
    '        )\n'
    '    }\n\n'
    '    suspend fun processNextHistoryChunk() {\n',
    'weather history operation end'
)

# Start/recover one process entry for a persisted history work.
s = replace_once(
    s,
    '    suspend fun processNextHistoryChunk() {\n'
    '        val work = historyDebtStore.loadWork() ?: return\n'
    '        historyDebtStore.resumeWork()\n',
    '    suspend fun processNextHistoryChunk() {\n'
    '        val work = historyDebtStore.loadWork() ?: run {\n'
    '            FabOperationRegistry.finish(historyOperationId, "Historique intérieur terminé")\n'
    '            historyOperationId = null\n'
    '            return\n'
    '        }\n'
    '        if (historyOperationId == null) {\n'
    '            historyOperationId = FabOperationRegistry.tryStart(\n'
    '                "thermal-history:${work.sensorId}",\n'
    '                "Historique intérieur",\n'
    '                "Reprise · passé → présent"\n'
    '            )\n'
    '        }\n'
    '        val operationId = historyOperationId\n'
    '        if (FabOperationRegistry.cancelRequested(operationId)) {\n'
    '            historyDebtStore.pauseWork()\n'
    '            historyDebtStore.setDebtState(HistoricalDebtState.PAUSED)\n'
    '            info = "Historique intérieur annulé · session conservée en pause"\n'
    '            FabOperationRegistry.cancelled(operationId, info)\n'
    '            historyOperationId = null\n'
    '            busy = false\n'
    '            refreshDebtState()\n'
    '            return\n'
    '        }\n'
    '        historyDebtStore.resumeWork()\n',
    'history operation recover and cancel'
)

s = replace_once(
    s,
    '        busy = true\n'
    '        info = "Historique · mois ${work.nextChunk + 1}/${work.totalChunks} · préparation météo…"\n'
    '        val result = withContext(Dispatchers.IO) {\n',
    '        busy = true\n'
    '        info = "Historique · mois ${work.nextChunk + 1}/${work.totalChunks} · préparation météo…"\n'
    '        FabOperationRegistry.update(operationId, info)\n'
    '        val result = withContext(Dispatchers.IO) {\n',
    'history operation update'
)

# Cancellation checkpoint after weather preparation and remove reload storm.
s = replace_once(
    s,
    '                if (!prepared.coverage.ready) {\n'
    '                    error("${reference.city} incomplet sur ce mois : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")\n'
    '                }\n'
    '                val advanced = historyDebtStore.advanceWork() ?: error("Session historique perdue")\n',
    '                if (!prepared.coverage.ready) {\n'
    '                    error("${reference.city} incomplet sur ce mois : couverture ${(prepared.coverage.coverage * 100).toInt()} % · trou max ${prepared.coverage.maxGapHours} h")\n'
    '                }\n'
    '                if (FabOperationRegistry.cancelRequested(operationId)) error("__FAB_CANCELLED__")\n'
    '                val advanced = historyDebtStore.advanceWork() ?: error("Session historique perdue")\n',
    'history cancellation checkpoint'
)

old_progress = '''                        scope.launch {
                            info = if (p.total > 0) {
                                val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                                "${p.stage} · $percent % · ${p.changed} point(s)"
                            } else p.stage
                            if (p.total > 0 && p.processed > 0) {
                                suppressNextAuto = true
                                onDataChanged()
                            }
                        }
'''
new_progress = '''                        scope.launch {
                            info = if (p.total > 0) {
                                val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                                "${p.stage} · $percent % · ${p.changed} point(s)"
                            } else p.stage
                            // v0.20.7: progression UI seulement. Recharger toutes les courbes
                            // à chaque batch SQLite de 256 points provoquait une tempête de reads.
                            FabOperationRegistry.update(operationId, info, p.processed, p.total)
                        }
'''
s = replace_once(s, old_progress, new_progress, 'remove progress reload storm')

s = replace_once(
    s,
    '                    suppressNextAuto = true\n'
    '                    onDataChanged()\n'
    '                } else if (next != null) {\n',
    '                    suppressNextAuto = true\n'
    '                    onDataChanged()\n'
    '                    FabOperationRegistry.finish(operationId, info)\n'
    '                    historyOperationId = null\n'
    '                } else if (next != null) {\n',
    'history operation success end'
)

s = replace_once(
    s,
    '            onFailure = { error ->\n'
    '                historyDebtStore.pauseWork()\n'
    '                historyDebtStore.setDebtState(HistoricalDebtState.PAUSED)\n'
    '                refreshDebtState()\n'
    '                continuationWork = null\n'
    '                info = error.message ?: "Morceau historique impossible · session mise en pause"\n'
    '            }\n',
    '            onFailure = { error ->\n'
    '                historyDebtStore.pauseWork()\n'
    '                historyDebtStore.setDebtState(HistoricalDebtState.PAUSED)\n'
    '                refreshDebtState()\n'
    '                continuationWork = null\n'
    '                if (error.message == "__FAB_CANCELLED__" || FabOperationRegistry.cancelRequested(operationId)) {\n'
    '                    info = "Historique intérieur annulé · session conservée en pause"\n'
    '                    FabOperationRegistry.cancelled(operationId, info)\n'
    '                } else {\n'
    '                    info = error.message ?: "Morceau historique impossible · session mise en pause"\n'
    '                    FabOperationRegistry.fail(operationId, info)\n'
    '                }\n'
    '                historyOperationId = null\n'
    '            }\n',
    'history operation failure end'
)

# Claim single-flight synchronously before first suspend in +90 action.
s = replace_once(
    s,
    '    suspend fun beginNext90DayHistory(reason: String) {\n'
    '        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)\n'
    '            ?: run { info = "Modèle vide ou à réentraîner"; return }\n'
    '        val firstReal = withContext(Dispatchers.IO) {\n',
    '    suspend fun beginNext90DayHistory(reason: String) {\n'
    '        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)\n'
    '            ?: run { info = "Modèle vide ou à réentraîner"; return }\n'
    '        if (historyOperationId != null || FabOperationRegistry.activeId("thermal-history:${activeModel.sensorId}") != null) {\n'
    '            info = "Historique intérieur déjà en cours · ouvre ↕ Activité"\n'
    '            return\n'
    '        }\n'
    '        historyOperationId = FabOperationRegistry.tryStart(\n'
    '            "thermal-history:${activeModel.sensorId}",\n'
    '            "Historique intérieur +90 j",\n'
    '            "${activeModel.sensorName} · préparation · passé → présent"\n'
    '        )\n'
    '        val operationId = historyOperationId\n'
    '        if (operationId == null) {\n'
    '            info = "Historique intérieur déjà en cours · ouvre ↕ Activité"\n'
    '            return\n'
    '        }\n'
    '        val firstReal = withContext(Dispatchers.IO) {\n',
    'history single-flight before suspend'
)

s = replace_once(
    s,
    '        } ?: run {\n'
    '            info = "Aucune vraie mesure pour initialiser l\'historique"\n'
    '            return\n'
    '        }\n'
    '        val dayMs = 24L * 60L * 60L * 1000L\n',
    '        } ?: run {\n'
    '            info = "Aucune vraie mesure pour initialiser l\'historique"\n'
    '            FabOperationRegistry.fail(operationId, info)\n'
    '            historyOperationId = null\n'
    '            return\n'
    '        }\n'
    '        val dayMs = 24L * 60L * 60L * 1000L\n',
    'history first real failure cleanup'
)

s = replace_once(
    s,
    '        if (existingDepth >= 1464) {\n'
    '            info = "Historique déjà au maximum de 48 mois"\n'
    '            return\n'
    '        }\n',
    '        if (existingDepth >= 1464) {\n'
    '            info = "Historique déjà au maximum de 48 mois"\n'
    '            FabOperationRegistry.finish(operationId, info)\n'
    '            historyOperationId = null\n'
    '            return\n'
    '        }\n',
    'history max cleanup'
)

s = replace_once(
    s,
    '        beginHistoryWork(targetDepth, reason, existingDepthDays = existingDepth)\n'
    '    }\n\n\n'
    '    suspend fun processNextInertiaChunk() {\n',
    '        FabOperationRegistry.update(operationId, info)\n'
    '        beginHistoryWork(targetDepth, reason, existingDepthDays = existingDepth)\n'
    '    }\n\n\n'
    '    suspend fun processNextInertiaChunk() {\n',
    'history target update'
)

# Inertia operation tracking (calculation may wait for user validation; remains visible).
s = replace_once(
    s,
    '    suspend fun processNextInertiaChunk() {\n'
    '        val work = inertiaHistoryStore.loadWork() ?: return\n',
    '    suspend fun processNextInertiaChunk() {\n'
    '        val work = inertiaHistoryStore.loadWork() ?: run {\n'
    '            FabOperationRegistry.finish(inertiaOperationId, "Sol inertiel terminé")\n'
    '            inertiaOperationId = null\n'
    '            return\n'
    '        }\n'
    '        if (inertiaOperationId == null) {\n'
    '            inertiaOperationId = FabOperationRegistry.tryStart(\n'
    '                "inertia-history:${work.sensorId}", "Calcul sol inertiel", "Préparation du prochain mois"\n'
    '            )\n'
    '        }\n'
    '        val inertiaOp = inertiaOperationId\n'
    '        if (FabOperationRegistry.cancelRequested(inertiaOp)) {\n'
    '            inertiaHistoryStore.pauseWork()\n'
    '            info = "Sol inertiel annulé · session conservée en pause"\n'
    '            FabOperationRegistry.cancelled(inertiaOp, info)\n'
    '            inertiaOperationId = null\n'
    '            return\n'
    '        }\n',
    'inertia operation begin'
)

s = replace_once(
    s,
    '        busy = true\n'
    '        info = "Sol inertiel · mois ${work.nextChunk + 1}/${work.totalChunks} · contrôle des prérequis…"\n',
    '        busy = true\n'
    '        info = "Sol inertiel · mois ${work.nextChunk + 1}/${work.totalChunks} · contrôle des prérequis…"\n'
    '        FabOperationRegistry.update(inertiaOp, info)\n',
    'inertia operation update'
)

s = replace_once(
    s,
    '                inertiaPending = ThermalInertiaPendingChunk(work, range, chunk)\n'
    '                info = "Sol inertiel · mois ${work.nextChunk + 1}/${work.totalChunks} calculé · validation utilisateur requise"\n',
    '                inertiaPending = ThermalInertiaPendingChunk(work, range, chunk)\n'
    '                info = "Sol inertiel · mois ${work.nextChunk + 1}/${work.totalChunks} calculé · validation utilisateur requise"\n'
    '                FabOperationRegistry.update(inertiaOp, info)\n',
    'inertia waiting validation'
)

s = replace_once(
    s,
    '                inertiaHistoryStore.pauseWork()\n'
    '                inertiaPending = null\n'
    '                info = error.message ?: "Sol inertiel impossible · session mise en pause"\n'
    '            }\n'
    '        )\n'
    '    }\n\n'
    '    suspend fun beginInertiaHistoryWork(days: Int) {\n',
    '                inertiaHistoryStore.pauseWork()\n'
    '                inertiaPending = null\n'
    '                info = error.message ?: "Sol inertiel impossible · session mise en pause"\n'
    '                FabOperationRegistry.fail(inertiaOp, info)\n'
    '                inertiaOperationId = null\n'
    '            }\n'
    '        )\n'
    '    }\n\n'
    '    suspend fun beginInertiaHistoryWork(days: Int) {\n',
    'inertia failure end'
)

s = replace_once(
    s,
    '        if (advanced == null || advanced.nextChunk >= advanced.totalChunks) {\n'
    '            inertiaHistoryStore.clearWork()\n'
    '            info = "Sol inertiel historique terminé · tous les mois validés sont conservés"\n',
    '        if (advanced == null || advanced.nextChunk >= advanced.totalChunks) {\n'
    '            inertiaHistoryStore.clearWork()\n'
    '            info = "Sol inertiel historique terminé · tous les mois validés sont conservés"\n'
    '            FabOperationRegistry.finish(inertiaOperationId, info)\n'
    '            inertiaOperationId = null\n',
    'inertia final finish'
)

# Training processes visible in ↕ panel.
s = replace_once(
    s,
    '    suspend fun trainPersistedModel() {\n'
    '        if (busy) return\n'
    '        busy = true\n',
    '    suspend fun trainPersistedModel() {\n'
    '        if (busy) return\n'
    '        val operationId = FabOperationRegistry.tryStart(\n'
    '            "training-inertia:${selectedSensorId ?: -1L}", "Entraînement sol / inertie", "Préparation des mesures réelles…"\n'
    '        ) ?: run { info = "Entraînement déjà en cours · ouvre ↕ Activité"; return }\n'
    '        busy = true\n',
    'training operation begin'
)

s = replace_once(
    s,
    '                suppressNextAuto = true\n'
    '                onDataChanged()\n'
    '            },\n'
    '            onFailure = { error ->\n'
    '                val message = error.message ?: "Entraînement impossible"\n'
    '                info = message\n'
    '                trainingFeedback = "⚠ $message"\n'
    '            }\n'
    '        )\n'
    '        busy = false\n'
    '    }\n\n'
    '    suspend fun trainSelectedWallSolar(wallId: String) {\n',
    '                suppressNextAuto = true\n'
    '                onDataChanged()\n'
    '                FabOperationRegistry.finish(operationId, trainingFeedback ?: info)\n'
    '            },\n'
    '            onFailure = { error ->\n'
    '                val message = error.message ?: "Entraînement impossible"\n'
    '                info = message\n'
    '                trainingFeedback = "⚠ $message"\n'
    '                FabOperationRegistry.fail(operationId, message)\n'
    '            }\n'
    '        )\n'
    '        busy = false\n'
    '    }\n\n'
    '    suspend fun trainSelectedWallSolar(wallId: String) {\n',
    'training operation end'
)

s = replace_once(
    s,
    '    suspend fun trainSelectedWallSolar(wallId: String) {\n'
    '        if (busy) return\n'
    '        busy = true\n',
    '    suspend fun trainSelectedWallSolar(wallId: String) {\n'
    '        if (busy) return\n'
    '        val operationId = FabOperationRegistry.tryStart(\n'
    '            "training-wall:$wallId", "Entraînement mur / solaire", "Pan $wallId · préparation…"\n'
    '        ) ?: run { info = "Entraînement mur déjà en cours · ouvre ↕ Activité"; return }\n'
    '        busy = true\n',
    'wall training operation begin'
)

s = replace_once(
    s,
    '                trainingTopologyVersion++\n'
    '                onDataChanged()\n'
    '            },\n'
    '            onFailure = { error ->\n'
    '                val message = error.message ?: "Apprentissage solaire impossible"\n'
    '                trainingFeedback = "⚠ $message"\n'
    '                info = message\n'
    '            }\n'
    '        )\n'
    '        busy = false\n'
    '    }\n',
    '                trainingTopologyVersion++\n'
    '                onDataChanged()\n'
    '                FabOperationRegistry.finish(operationId, trainingFeedback ?: info)\n'
    '            },\n'
    '            onFailure = { error ->\n'
    '                val message = error.message ?: "Apprentissage solaire impossible"\n'
    '                trainingFeedback = "⚠ $message"\n'
    '                info = message\n'
    '                FabOperationRegistry.fail(operationId, message)\n'
    '            }\n'
    '        )\n'
    '        busy = false\n'
    '    }\n',
    'wall training operation end'
)

write(rel, s)


# ---------------------------------------------------------------------------
# LiveUpdateCoordinator: make startup/focus routine observable and avoid
# silently overlapping a manual weather operation.
# ---------------------------------------------------------------------------
rel = 'app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt'
s = read(rel)

old = '''    suspend fun updateLive(): Boolean {
        if (!foreground || working) return false
        working = true
        return try {
            withContext(Dispatchers.IO) {
                // Important : le focus ne choisit jamais une autre station.
                // La référence ne peut changer que depuis l'écran de choix explicite.
                val reference = weatherPrefs.selectedReference()
'''
new = '''    suspend fun updateLive(): Boolean {
        if (!foreground || working) return false
        val referenceForOperation = weatherPrefs.selectedReference()
        val operationId = FabOperationRegistry.tryStart(
            "weather:${referenceForOperation.key}",
            "Mise à jour automatique",
            "${referenceForOperation.label} · ouverture / focus"
        ) ?: return false
        working = true
        return try {
            withContext(Dispatchers.IO) {
                // Important : le focus ne choisit jamais une autre station.
                // La référence ne peut changer que depuis l'écran de choix explicite.
                val reference = referenceForOperation
                FabOperationRegistry.update(operationId, "${reference.label} · météo récente…")
'''
s = replace_once(s, old, new, 'live operation begin')

s = replace_once(
    s,
    '                PointSourceStore.reconcileMeasuredDominance(db)\n'
    '                manager.refreshRecent(reference)\n\n'
    '                val profile = profileStore.load()\n',
    '                PointSourceStore.reconcileMeasuredDominance(db)\n'
    '                manager.refreshRecent(reference)\n'
    '                if (FabOperationRegistry.cancelRequested(operationId)) return@withContext\n\n'
    '                FabOperationRegistry.update(operationId, "${reference.label} · prévision / cohérence…")\n'
    '                val profile = profileStore.load()\n',
    'live cancellation checkpoint'
)

s = replace_once(
    s,
    '            onDataChanged()\n'
    '            true\n'
    '        } finally {\n'
    '            working = false\n'
    '        }\n'
    '    }\n',
    '            if (FabOperationRegistry.cancelRequested(operationId)) {\n'
    '                FabOperationRegistry.cancelled(operationId, "Mise à jour automatique arrêtée")\n'
    '            } else {\n'
    '                onDataChanged()\n'
    '                FabOperationRegistry.finish(operationId, "Météo et prévision à jour")\n'
    '            }\n'
    '            true\n'
    '        } catch (error: Throwable) {\n'
    '            FabOperationRegistry.fail(operationId, error.message ?: "Mise à jour automatique impossible")\n'
    '            false\n'
    '        } finally {\n'
    '            working = false\n'
    '        }\n'
    '    }\n',
    'live operation end'
)

write(rel, s)

print('v0.20.7 integration applied')
