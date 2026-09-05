from pathlib import Path

MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
GRADLE = Path('app/build.gradle.kts')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, got {count}')
    return text.replace(old, new, 1)


text = MAIN.read_text()

text = replace_once(
    text,
    'import androidx.compose.foundation.gestures.detectTapGestures\n',
    'import androidx.compose.foundation.gestures.detectTapGestures\nimport androidx.compose.foundation.gestures.detectDragGestures\n',
    'drag import'
)

text = replace_once(
    text,
    '    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }\n',
    '    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }\n'
    '    val thermalTrainingMaskStore = remember { ThermalTrainingMaskStore(db) }\n',
    'training mask store'
)

text = replace_once(
    text,
    '    var windowCenterTimestamp by remember { mutableStateOf<Long?>(null) }\n',
    '    var windowCenterTimestamp by remember { mutableStateOf<Long?>(null) }\n'
    '    var customViewSpanMs by remember { mutableStateOf<Long?>(null) }\n',
    'custom zoom state'
)

text = replace_once(
    text,
    '    LaunchedEffect(reloadToken, preset, windowCenterTimestamp) {\n',
    '    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs) {\n',
    'loader keys'
)

text = replace_once(
    text,
    '                val requested = minOf(preset.spanMs, fullSpan)\n',
    '                val requested = minOf(customViewSpanMs ?: preset.spanMs, fullSpan)\n',
    'custom requested span'
)

old_call = '''                    HistoryOverviewCard(
                        sensors = chartSensors,
                        sampleMap = chartOverviewSampleMap,
                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        selectedTimestamp = selectedTimestamp,
                        onSelectTimestamp = { ts ->
                            // v0.17 : une sélection depuis le bandeau place la visée
                            // au centre de la fenêtre détaillée tout en gardant son zoom.
                            selectedTimestamp = ts
                            windowCenterTimestamp = ts
                            selectedAnnotation = null
                        },
                        onNavigate = { ts ->
                            // Le double-tap recentre le graphe principal autour du point
                            // en conservant le preset/zoom temporel actuellement choisi.
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        }
                    )'''
new_call = '''                    HistoryOverviewCard(
                        sensors = chartSensors,
                        sampleMap = chartOverviewSampleMap,
                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        selectedTimestamp = selectedTimestamp,
                        onSelectTimestamp = { ts ->
                            // v0.17 : une sélection depuis le bandeau place la visée
                            // au centre de la fenêtre détaillée tout en gardant son zoom.
                            selectedTimestamp = ts
                            windowCenterTimestamp = ts
                            selectedAnnotation = null
                        },
                        onNavigate = { ts ->
                            // Le double-tap recentre le graphe principal autour du point
                            // en conservant le preset/zoom temporel actuellement choisi.
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        },
                        onUseForInertia = { range ->
                            val sensorId = inertiaEstimate?.diagnostics?.sourceSensorId
                            if (sensorId == null) {
                                scope.launch { snackbar.showSnackbar("Modèle d'inertie indisponible : aucune sonde physique active") }
                            } else {
                                scope.launch {
                                    busy = true
                                    val changed = withContext(Dispatchers.IO) {
                                        thermalTrainingMaskStore.includeRange(sensorId, range.first, range.last)
                                    }
                                    reloadToken++
                                    busy = false
                                    snackbar.showSnackbar(
                                        if (changed > 0) "Zone réintégrée à l'entraînement inertiel"
                                        else "Zone déjà utilisée pour l'entraînement inertiel"
                                    )
                                }
                            }
                        },
                        onExcludeFromInertia = { range ->
                            val sensorId = inertiaEstimate?.diagnostics?.sourceSensorId
                            if (sensorId == null) {
                                scope.launch { snackbar.showSnackbar("Modèle d'inertie indisponible : aucune sonde physique active") }
                            } else {
                                scope.launch {
                                    busy = true
                                    withContext(Dispatchers.IO) {
                                        thermalTrainingMaskStore.addMerged(
                                            sensorId,
                                            range.first,
                                            range.last,
                                            "Sélection bandeau global"
                                        )
                                    }
                                    reloadToken++
                                    busy = false
                                    snackbar.showSnackbar("Zone exclue de l'entraînement inertiel · RAW conservées")
                                }
                            }
                        },
                        onZoomRange = { range ->
                            val span = (range.last - range.first).coerceAtLeast(60L * 60L * 1000L)
                            val center = range.first + span / 2L
                            customViewSpanMs = span
                            windowCenterTimestamp = center
                            selectedTimestamp = center
                            selectedAnnotation = null
                        }
                    )'''
text = replace_once(text, old_call, new_call, 'overview caller')

text = replace_once(
    text,
    '''                item {
                    TimeTabs(preset = preset, onSelect = {
                        preset = it
                        windowCenterTimestamp = selectedTimestamp''',
    '''                item {
                    TimeTabs(preset = preset, onSelect = {
                        customViewSpanMs = null
                        preset = it
                        windowCenterTimestamp = selectedTimestamp''',
    'preset clears custom zoom'
)

text = replace_once(
    text,
    '''                        onRequestZoom = { ts ->
                            preset = TimePreset.TWO_DAYS''',
    '''                        onRequestZoom = { ts ->
                            customViewSpanMs = null
                            preset = TimePreset.TWO_DAYS''',
    'long press preserves 48h contract'
)

old_signature = '''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,
    viewBounds: LongRange?,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit,
    onNavigate: (Long) -> Unit
) {'''
new_signature = '''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,
    viewBounds: LongRange?,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit,
    onNavigate: (Long) -> Unit,
    onUseForInertia: (LongRange) -> Unit,
    onExcludeFromInertia: (LongRange) -> Unit,
    onZoomRange: (LongRange) -> Unit
) {'''
text = replace_once(text, old_signature, new_signature, 'overview signature')

text = replace_once(
    text,
    '                "Tap = sélectionner · double tap = ouvrir · glisse = déplacer la prévisu · pince = élargir/rétrécir",\n',
    '                "Tap = viser · double tap = ouvrir · Sélection = choisir une période · pince/glisse = prévisu",\n',
    'overview help text'
)

old_preview_state = '''                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
'''
new_preview_state = old_preview_state + '''                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }
                var rangeStart by remember { mutableStateOf<Long?>(null) }
                var rangeEnd by remember { mutableStateOf<Long?>(null) }
                var rangeMenuOpen by remember { mutableStateOf(false) }
'''
text = replace_once(text, old_preview_state, new_preview_state, 'range states')

old_preset_row_end = '''                    }
                }

                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)
'''
new_preset_row_end = '''                    }
                }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    AssistChip(
                        onClick = {
                            rangeSelectionMode = !rangeSelectionMode
                            rangeMenuOpen = false
                            rangeStart = null
                            rangeEnd = null
                        },
                        label = {
                            Text(if (rangeSelectionMode) "✓ Sélection active" else "Sélectionner une période")
                        }
                    )
                }
                if (rangeSelectionMode) {
                    Text(
                        "Glisse horizontalement dans le bandeau puis choisis l'action. Tu peux recommencer pour plusieurs zones.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }

                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)
'''
text = replace_once(text, old_preset_row_end, new_preset_row_end, 'selection chip')

text = replace_once(
    text,
    '''                        .pointerInput(bounds, previewPreset) {
                            detectTransformGestures { centroid, pan, zoomChange, _ ->''',
    '''                        .pointerInput(bounds, previewPreset, rangeSelectionMode) {
                            if (!rangeSelectionMode) detectTransformGestures { centroid, pan, zoomChange, _ ->''',
    'gate preview transform'
)

old_tap_block = '''                        .pointerInput(previewFrom, previewTo) {
                            detectTapGestures(
                                onDoubleTap = { p ->
                                    val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                    val ts = previewFrom + (previewSpan * frac).toLong()
                                    onSelectTimestamp(ts)
                                    onNavigate(ts)
                                },
                                onTap = { p ->
                                    val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                    onSelectTimestamp(previewFrom + (previewSpan * frac).toLong())
                                }
                            )
                        }
'''
new_tap_block = '''                        .pointerInput(previewFrom, previewTo, rangeSelectionMode) {
                            if (!rangeSelectionMode) {
                                detectTapGestures(
                                    onDoubleTap = { p ->
                                        val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        val ts = previewFrom + (previewSpan * frac).toLong()
                                        onSelectTimestamp(ts)
                                        onNavigate(ts)
                                    },
                                    onTap = { p ->
                                        val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        onSelectTimestamp(previewFrom + (previewSpan * frac).toLong())
                                    }
                                )
                            }
                        }
                        .pointerInput(previewFrom, previewTo, rangeSelectionMode) {
                            if (rangeSelectionMode) {
                                detectDragGestures(
                                    onDragStart = { p ->
                                        val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        val ts = previewFrom + (previewSpan * frac).toLong()
                                        rangeStart = ts
                                        rangeEnd = ts
                                        rangeMenuOpen = false
                                    },
                                    onDrag = { change, _ ->
                                        val frac = (change.position.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                        rangeEnd = previewFrom + (previewSpan * frac).toLong()
                                        change.consume()
                                    },
                                    onDragEnd = {
                                        val a = rangeStart
                                        val b = rangeEnd
                                        if (a != null && b != null && kotlin.math.abs(b - a) >= 60L * 60L * 1000L) {
                                            rangeMenuOpen = true
                                        } else {
                                            rangeStart = null
                                            rangeEnd = null
                                        }
                                    },
                                    onDragCancel = {
                                        rangeStart = null
                                        rangeEnd = null
                                        rangeMenuOpen = false
                                    }
                                )
                            }
                        }
'''
text = replace_once(text, old_tap_block, new_tap_block, 'range drag gesture')

old_selected_marker = '''                    selectedTimestamp?.takeIf { it in previewWindow }?.let { selected ->
'''
new_selected_marker = '''                    if (rangeSelectionMode) {
                        val a = rangeStart
                        val b = rangeEnd
                        if (a != null && b != null) {
                            val start = maxOf(minOf(a, b), previewFrom)
                            val end = minOf(maxOf(a, b), previewTo)
                            if (end > start) {
                                val left = (((start - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                    .coerceIn(0f, size.width)
                                val right = (((end - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                    .coerceIn(0f, size.width)
                                drawRect(
                                    selectionColor.copy(alpha = 0.24f),
                                    topLeft = Offset(left, 0f),
                                    size = androidx.compose.ui.geometry.Size(right - left, size.height)
                                )
                                drawLine(selectionColor, Offset(left, 0f), Offset(left, size.height), 2.dp.toPx())
                                drawLine(selectionColor, Offset(right, 0f), Offset(right, size.height), 2.dp.toPx())
                                drawCircle(selectionColor, 5.dp.toPx(), Offset(left, size.height / 2f))
                                drawCircle(selectionColor, 5.dp.toPx(), Offset(right, size.height / 2f))
                            }
                        }
                    }

                    selectedTimestamp?.takeIf { it in previewWindow }?.let { selected ->
'''
text = replace_once(text, old_selected_marker, new_selected_marker, 'range drawing')

old_after_canvas = '''                }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
'''
new_after_canvas = '''                }

                val pendingRange = rangeStart?.let { a ->
                    rangeEnd?.let { b -> minOf(a, b)..maxOf(a, b) }
                }
                Box(Modifier.fillMaxWidth()) {
                    Box(Modifier.align(Alignment.TopEnd)) {
                        DropdownMenu(
                            expanded = rangeMenuOpen && pendingRange != null,
                            onDismissRequest = {
                                rangeMenuOpen = false
                                rangeStart = null
                                rangeEnd = null
                            }
                        ) {
                            pendingRange?.let { selectedRange ->
                                DropdownMenuItem(
                                    text = { Text("Utiliser cette zone pour entraîner l'inertie") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onUseForInertia(selectedRange)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Exclure cette zone du modèle d'inertie") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onExcludeFromInertia(selectedRange)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Utiliser cette zone comme nouveau zoom") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        rangeSelectionMode = false
                                        onZoomRange(selectedRange)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Annuler") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                            }
                        }
                    }
                }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
'''
# This pattern can occur elsewhere; anchor it to the unique HistoryOverview region by replacing the first
# occurrence after the range drawing marker.
marker = '                    if (rangeSelectionMode) {'
pos = text.find(marker)
if pos < 0:
    raise SystemExit('menu insertion marker missing')
sub = text[pos:]
count = sub.count(old_after_canvas)
if count < 1:
    raise SystemExit('menu insertion target missing')
sub = sub.replace(old_after_canvas, new_after_canvas, 1)
text = text[:pos] + sub

MAIN.write_text(text)

gradle = GRADLE.read_text()
gradle = replace_once(gradle, '        versionCode = 36\n        versionName = "0.19.0"\n',
                      '        versionCode = 37\n        versionName = "0.19.1"\n', 'version bump')
GRADLE.write_text(gradle)

print('FabData v0.19.1 overview range selection applied')
