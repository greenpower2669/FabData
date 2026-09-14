from pathlib import Path

p = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
s = p.read_text(encoding='utf-8')
if 'reloadPendingTrigger' in s:
    print('ui queue already patched')
    raise SystemExit(0)

def once(old, new):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'expected one match, got {n}: {old[:100]}')
    s = s.replace(old, new, 1)

once(
'''    var reloadRequestGeneration by remember { mutableIntStateOf(1) }
    var reloadPendingPriority by remember { mutableIntStateOf(UiReloadPriority.DATA.rank) }
    fun queueUiReload(priority: UiReloadPriority) {
        reloadPendingPriority = maxOf(reloadPendingPriority, priority.rank)
        reloadRequestGeneration++
    }
''',
'''    var reloadRequestGeneration by remember { mutableIntStateOf(1) }
    var reloadPendingPriority by remember { mutableIntStateOf(UiReloadPriority.DATA.rank) }
    var reloadPendingTrigger by remember { mutableStateOf("démarrage") }
    var reloadMergedRequests by remember { mutableIntStateOf(0) }
    var viewIntentGeneration by remember { mutableIntStateOf(0) }
    fun queueUiReload(priority: UiReloadPriority, trigger: String) {
        reloadPendingPriority = maxOf(reloadPendingPriority, priority.rank)
        reloadPendingTrigger = trigger
        reloadMergedRequests++
        reloadRequestGeneration++
    }
''')

once(
'''    var reloadToken by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }''',
'''    var reloadToken by remember { mutableIntStateOf(0) }
    fun notifyDataChanged(trigger: String, priority: UiReloadPriority = UiReloadPriority.DATA) {
        __TOKEN_INC__
        queueUiReload(priority, trigger)
    }
    var busy by remember { mutableStateOf(false) }''')

once(
'''        dataVersion = reloadToken,
        onDataChanged = {
            reloadToken++
            queueUiReload(UiReloadPriority.DATA)
        }
''',
'''        dataVersion = reloadToken,
        onDataChanged = { trigger ->
            notifyDataChanged(trigger, UiReloadPriority.DATA)
        }
''')

once(
'''                reloadToken++
                FabOperationRegistry.update(importOperation, "Données importées · affichage prioritaire en file", uris.size, uris.size)
                queueUiReload(UiReloadPriority.CRITICAL)''',
'''                notifyDataChanged("import terminé", UiReloadPriority.CRITICAL)
                FabOperationRegistry.update(importOperation, "Données importées · affichage prioritaire en file", uris.size, uris.size)''')

once(
'''            reloadToken++
            queueUiReload(UiReloadPriority.BACKGROUND_DATA)''',
'''            notifyDataChanged("sondes HTTP automatiques", UiReloadPriority.BACKGROUND_DATA)''')

once(
'''            reloadToken++
            queueUiReload(UiReloadPriority.CRITICAL)
            result.fold(''',
'''            notifyDataChanged("import initial terminé", UiReloadPriority.CRITICAL)
            result.fold(''')

once(
'''    LaunchedEffect(preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {
        // UI-only movement is low priority. It is buffered and merged; it never cancels
        // a reload already in progress.
        delay(180L)
        queueUiReload(UiReloadPriority.NAVIGATION)
    }
''',
'''    LaunchedEffect(preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {
        // Mark the intent immediately. Older reads are forbidden from applying afterward.
        viewIntentGeneration++
        delay(180L)
        queueUiReload(UiReloadPriority.NAVIGATION, "navigation / zoom / sélection")
    }
''')

once(
'''                val priorityRank = reloadPendingPriority
                reloadPendingPriority = 0
                if (FabDataWorkArbiter.criticalImportPending()) {''',
'''                val priorityRank = reloadPendingPriority
                val trigger = reloadPendingTrigger
                val mergedRequests = (reloadMergedRequests.coerceAtLeast(1) - 1)
                val generation = reloadRequestGeneration
                val viewGenerationAtStart = viewIntentGeneration
                reloadPendingPriority = 0
                reloadMergedRequests = 0
                if (FabDataWorkArbiter.criticalImportPending()) {''')

once(
'''                    reloadPendingPriority = maxOf(reloadPendingPriority, priorityRank)
                    return@collect''',
'''                    reloadPendingPriority = maxOf(reloadPendingPriority, priorityRank)
                    reloadPendingTrigger = trigger
                    reloadMergedRequests += mergedRequests + 1
                    return@collect''')

once(
'''                if (priorityRank >= UiReloadPriority.CRITICAL.rank) "Priorité critique · lecture des courbes…"
                else "Données mises à jour · lecture des courbes…",
                cancellable = true
            )''',
'''                if (priorityRank >= UiReloadPriority.CRITICAL.rank) "Priorité critique · lecture des courbes…"
                else "Données mises à jour · lecture des courbes…",
                cancellable = true,
                trigger = trigger,
                priority = UiReloadPriority.entries.firstOrNull { it.rank == priorityRank }?.name ?: "MERGED",
                network = false,
                generation = generation,
                mergedRequests = mergedRequests
            )''')

once(
'''        FabOperationRegistry.ensureNotCancelled(reloadOperation)
        sensors = loaded.sensors
''',
'''        FabOperationRegistry.ensureNotCancelled(reloadOperation)
        if (viewGenerationAtStart != viewIntentGeneration) {
            FabOperationRegistry.discard(reloadOperation)
            queueUiReload(UiReloadPriority.NAVIGATION, "interaction utilisateur plus récente")
            return@withLock
        }
        sensors = loaded.sensors
''')

once(
'''        loaded.viewBounds?.let { bounds ->
            val current = selectedTimestamp
            if (current == null || current !in bounds) {
                selectedTimestamp = bounds.first + (bounds.last - bounds.first) / 2L
            }
        }
''',
'''        loaded.viewBounds?.let { bounds ->
            // A background/data refresh never moves an explicit user cursor.
            if (selectedTimestamp == null) {
                selectedTimestamp = bounds.first + (bounds.last - bounds.first) / 2L
            }
        }
''')

# Centralize remaining data mutations. The helper placeholder protects its own increment.
s = s.replace('reloadToken++', 'notifyDataChanged("modification locale")')
s = s.replace('__TOKEN_INC__', 'reloadToken++')

# Imports are visible and diagnostic.
s = s.replace(
'''                    detail = "Préparation · priorité maximale",
                    cancellable = false''',
'''                    detail = "Préparation · priorité maximale",
                    cancellable = false,
                    trigger = "sélection utilisateur",
                    priority = "CRITICAL",
                    network = false''')
s = s.replace(
'''                detail = "Ouverture du fichier · priorité maximale",
                cancellable = false''',
'''                detail = "Ouverture du fichier · priorité maximale",
                cancellable = false,
                trigger = "ouverture fichier externe",
                priority = "CRITICAL",
                network = false''')

p.write_text(s, encoding='utf-8')
print('ui queue patched')
