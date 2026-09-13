from pathlib import Path


def replace_once(path: str, old: str, new: str):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"pattern not found in {path}: {old[:160]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

# Version
replace_once(
    "app/build.gradle.kts",
    '        versionCode = 61\n        versionName = "0.23.4"',
    '        versionCode = 62\n        versionName = "0.23.5"',
)

main = "app/src/main/java/com/fabdata/app/MainActivity.kt"

# Flow imports for a serial conflated buffer: state changes never cancel a running reload.
replace_once(
    main,
    'import androidx.compose.runtime.rememberUpdatedState\n',
    'import androidx.compose.runtime.rememberUpdatedState\nimport androidx.compose.runtime.snapshotFlow\n',
)
replace_once(
    main,
    'import kotlinx.coroutines.Dispatchers\n',
    'import kotlinx.coroutines.Dispatchers\nimport kotlinx.coroutines.flow.conflate\n',
)

# Explicit priority classes. Higher work waits in the same buffer; it never interrupts safe work already running.
replace_once(
    main,
    '''private enum class TemporalPageDirection {\n    PREVIOUS,\n    NEXT\n}\n''',
    '''private enum class TemporalPageDirection {\n    PREVIOUS,\n    NEXT\n}\n\nprivate enum class UiReloadPriority(val rank: Int) {\n    NAVIGATION(10),\n    BACKGROUND_DATA(40),\n    DATA(70),\n    CRITICAL(100)\n}\n''',
)

# Queue state + helper. The pending priority is max-merged, while generation only wakes the consumer.
replace_once(
    main,
    '''    val scope = rememberCoroutineScope()\n    val reloadMutex = remember { Mutex() }\n    val snackbar = remember { SnackbarHostState() }\n''',
    '''    val scope = rememberCoroutineScope()\n    val reloadMutex = remember { Mutex() }\n    val snackbar = remember { SnackbarHostState() }\n    var reloadRequestGeneration by remember { mutableIntStateOf(1) }\n    var reloadPendingPriority by remember { mutableIntStateOf(UiReloadPriority.DATA.rank) }\n    fun queueUiReload(priority: UiReloadPriority) {\n        reloadPendingPriority = maxOf(reloadPendingPriority, priority.rank)\n        reloadRequestGeneration++\n    }\n''',
)

# Data-source changes enqueue instead of directly retriggering a keyed LaunchedEffect.
replace_once(
    main,
    '        onDataChanged = { reloadToken++ }\n',
    '''        onDataChanged = {\n            reloadToken++\n            queueUiReload(UiReloadPriority.DATA)\n        }\n''',
)

# Imports/restores are critical. Remote sensor startup sync is background data.
replace_once(
    main,
    '''                busy = false\n                reloadToken++\n                snackbar.showSnackbar(\n                    "Import : $measuresAdded mesure(s) ajoutée(s)''',
    '''                busy = false\n                reloadToken++\n                queueUiReload(UiReloadPriority.CRITICAL)\n                snackbar.showSnackbar(\n                    "Import : $measuresAdded mesure(s) ajoutée(s)''',
)
replace_once(
    main,
    '''            reloadToken++\n        }\n    }\n\n    LaunchedEffect(initialImport, initialHandled)''',
    '''            reloadToken++\n            queueUiReload(UiReloadPriority.BACKGROUND_DATA)\n        }\n    }\n\n    LaunchedEffect(initialImport, initialHandled)''',
)
replace_once(
    main,
    '''            busy = false\n            reloadToken++\n            snackbar.showSnackbar(\n                result.fold(''',
    '''            busy = false\n            reloadToken++\n            queueUiReload(UiReloadPriority.CRITICAL)\n            snackbar.showSnackbar(\n                result.fold(''',
)

# Navigation changes are low priority: debounce them into one pending request.
old_header = '''    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {\n        // Startup/preferences can settle through several Compose states in a few milliseconds.\n        // Debounce before registering work so Activity FabData shows one meaningful refresh,\n        // not a TERMINÉ/ANNULÉ/TERMINÉ burst.\n        delay(350L)\n        reloadMutex.withLock {\n'''
new_header = '''    LaunchedEffect(preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {\n        // UI-only movement is low priority. It is buffered and merged; it never cancels\n        // a reload already in progress.\n        delay(180L)\n        queueUiReload(UiReloadPriority.NAVIGATION)\n    }\n\n    LaunchedEffect(Unit) {\n        // One serial consumer for all redraw work. Startup gets a short settle window, then\n        // conflate() keeps only the newest pending generation while work is running.\n        // Priority is max-merged by queueUiReload: CRITICAL > DATA > BACKGROUND > NAVIGATION.\n        delay(320L)\n        snapshotFlow { reloadRequestGeneration }\n            .conflate()\n            .collect {\n                val priorityRank = reloadPendingPriority\n                reloadPendingPriority = 0\n                reloadMutex.withLock {\n'''
replace_once(main, old_header, new_header)

# Only meaningful data work is listed in Activity FabData. Navigation redraws remain silent.
replace_once(
    main,
    '''        val reloadOperation = FabOperationRegistry.tryStart(\n            "ui-reload", "Actualisation affichage", "Lecture des courbes…", cancellable = true\n        )\n''',
    '''        val reloadOperation = if (priorityRank >= UiReloadPriority.DATA.rank) {\n            FabOperationRegistry.tryStart(\n                "ui-reload",\n                "Actualisation affichage",\n                if (priorityRank >= UiReloadPriority.CRITICAL.rank) "Priorité critique · lecture des courbes…"\n                else "Données mises à jour · lecture des courbes…",\n                cancellable = true\n            )\n        } else null\n''',
)

# In the new long-lived consumer, only a true composition cancellation is rethrown.
# Explicit user cancellation ends the current batch but leaves the scheduler alive.
replace_once(
    main,
    '''        } catch (cancel: CancellationException) {\n            if (FabOperationRegistry.cancelRequested(reloadOperation)) {\n                FabOperationRegistry.cancelled(reloadOperation, "Actualisation affichage annulée")\n            } else {\n                FabOperationRegistry.discard(reloadOperation)\n            }\n            throw cancel\n''',
    '''        } catch (cancel: CancellationException) {\n            if (FabOperationRegistry.cancelRequested(reloadOperation)) {\n                FabOperationRegistry.cancelled(reloadOperation, "Actualisation affichage annulée par l’utilisateur")\n            } else {\n                FabOperationRegistry.discard(reloadOperation)\n                throw cancel\n            }\n''',
)

# Close collect + long-lived LaunchedEffect (old code only closed mutex + keyed effect).
needle = '''        }\n        }\n    }\n\n    fun requestTemporalPage'''
replacement = '''        }\n                }\n            }\n    }\n\n    fun requestTemporalPage'''
replace_once(main, needle, replacement)

# Update the in-app help so the behaviour is understandable if Activity is opened.
replace_once(
    main,
    '''                Text("Aide · cadrans flottants", fontWeight = FontWeight.Bold)\n''',
    '''                Text("Aide · activité et cadrans", fontWeight = FontWeight.Bold)\n                Text(\n                    "Les actualisations d’affichage sont mises en file avec priorités : import/restauration, données, puis navigation. " +\n                        "Une tâche déjà lancée n’est plus annulée par un simple changement d’écran ; les demandes suivantes sont fusionnées dans le buffer.",\n                    style = MaterialTheme.typography.bodySmall\n                )\n''',
)
replace_once(
    main,
    'Text("Politique de confidentialité · FabData v0.23.4", fontWeight = FontWeight.Bold)',
    'Text("Politique de confidentialité · FabData v0.23.5", fontWeight = FontWeight.Bold)',
)

print("v0.23.5 priority reload buffer patch applied")
