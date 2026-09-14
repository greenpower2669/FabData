from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


main = MAIN.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 1) Global navigation terrain: keep one month of empty/future runway after NOW.
#    The anchor only advances on app start and on the explicit refresh button.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    'private const val FORECAST_DISPLAY_FUTURE_MS = 48L * 60L * 60L * 1000L\n',
    'private const val FORECAST_DISPLAY_FUTURE_MS = 48L * 60L * 60L * 1000L\n'
    'private const val OVERVIEW_FUTURE_MONTH_MS = 31L * 24L * 60L * 60L * 1000L\n',
    "future month constant",
)

main = replace_once(
    main,
    '    var reloadToken by remember { mutableIntStateOf(0) }\n'
    '    fun notifyDataChanged(trigger: String, priority: UiReloadPriority = UiReloadPriority.DATA) {\n',
    '    var reloadToken by remember { mutableIntStateOf(0) }\n'
    '    // Stable present anchor for the overview. It advances only at startup or explicit refresh,\n'
    '    // so normal recompositions do not make the selectors drift by a few milliseconds.\n'
    '    var overviewPresentAnchor by remember { mutableStateOf(System.currentTimeMillis()) }\n'
    '    fun notifyDataChanged(trigger: String, priority: UiReloadPriority = UiReloadPriority.DATA) {\n',
    "overview present anchor state",
)

main = replace_once(
    main,
    '    // Navigation is allowed to continue beyond the last terrain point up to NOW + 48 h.\n'
    '    // The terrain curve simply stops at its last real/reconstructed point while forecast curves continue.\n'
    '    val overviewDisplayBounds = globalBounds?.let { historical ->\n'
    '        val now = System.currentTimeMillis()\n'
    '        historical.first..maxOf(historical.last, now + FORECAST_DISPLAY_FUTURE_MS)\n'
    '    }\n',
    '    // The giga overview always keeps one month of temporal runway after the anchored present.\n'
    '    // RAW/terrain data still stops where it really stops; only the navigable/display terrain extends.\n'
    '    val overviewDisplayBounds = globalBounds?.let { historical ->\n'
    '        historical.first..maxOf(historical.last, overviewPresentAnchor + OVERVIEW_FUTURE_MONTH_MS)\n'
    '    }\n',
    "overview month future bounds",
)

main = replace_once(
    main,
    '                    IconButton(onClick = {\n'
    '                        val selected = WeatherReferencePrefs(context).selectedReference()\n',
    '                    IconButton(onClick = {\n'
    '                        // Refresh also advances the visual future runway to NOW + 1 month.\n'
    '                        // History is untouched; this only enlarges the allowed navigation terrain.\n'
    '                        overviewPresentAnchor = System.currentTimeMillis()\n'
    '                        val selected = WeatherReferencePrefs(context).selectedReference()\n',
    "refresh advances future runway",
)

# Pass the stable present anchor into the compact cascade.
main = replace_once(
    main,
    '                        historyBounds = overviewDisplayBounds,\n'
    '                        viewBounds = viewBounds,\n',
    '                        historyBounds = overviewDisplayBounds,\n'
    '                        presentAnchorTimestamp = overviewPresentAnchor,\n'
    '                        viewBounds = viewBounds,\n',
    "history overview present anchor call",
)
main = replace_once(
    main,
    '    historyBounds: LongRange?,\n'
    '    viewBounds: LongRange?,\n',
    '    historyBounds: LongRange?,\n'
    '    presentAnchorTimestamp: Long,\n'
    '    viewBounds: LongRange?,\n',
    "history overview present anchor signature",
)

# ---------------------------------------------------------------------------
# 2) Exploration context selector: x3..x9 of the detailed graph.
#    x6 is the default. Pinch may still zoom inward from that context width.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    '                val bandPrefs = remember {\n'
    '                    helpContext.getSharedPreferences("fabdata_overview_band_curves", Context.MODE_PRIVATE)\n'
    '                }\n'
    '                val availableBandSensors = remember(sensors, gigaSampleMap, navigatorSampleMap, sampleMap) {\n',
    '                val bandPrefs = remember {\n'
    '                    helpContext.getSharedPreferences("fabdata_overview_band_curves", Context.MODE_PRIVATE)\n'
    '                }\n'
    '                var explorationContextMultiplier by rememberSaveable {\n'
    '                    mutableIntStateOf(bandPrefs.getInt("exploration_context_multiplier", 6).coerceIn(3, 9))\n'
    '                }\n'
    '                LaunchedEffect(explorationContextMultiplier) {\n'
    '                    bandPrefs.edit().putInt("exploration_context_multiplier", explorationContextMultiplier).apply()\n'
    '                }\n'
    '                var appliedRightAnchor by remember { mutableStateOf<Long?>(null) }\n'
    '                val availableBandSensors = remember(sensors, gigaSampleMap, navigatorSampleMap, sampleMap) {\n',
    "exploration multiplier state",
)

main = replace_once(
    main,
    '                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)\n'
    '                val maxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)\n'
    '                val mainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }\n'
    '                    ?: (24L * 60L * 60L * 1000L)\n'
    '                val minSpan = minOf(maxSpan, maxOf(6L * 60L * 60L * 1000L, mainSpan))\n'
    '                val maxZoom = (maxSpan.toDouble() / minSpan.toDouble()).toFloat().coerceAtLeast(1f)\n'
    '                val effectiveZoom = previewZoom.coerceIn(1f, maxZoom)\n'
    '                val previewSpan = (maxSpan.toDouble() / effectiveZoom.toDouble()).toLong()\n'
    '                    .coerceIn(minSpan, maxSpan)\n',
    '                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)\n'
    '                val mainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }\n'
    '                    ?: (24L * 60L * 60L * 1000L)\n'
    '                // Exploration starts at an explicit multiple of the detailed graph.\n'
    '                // This gives the middle band enough context to spot hot/cold zones before opening detail.\n'
    '                val requestedContextSpan = mainSpan * explorationContextMultiplier.toLong()\n'
    '                val maxSpan = minOf(requestedContextSpan, fullSpan).coerceAtLeast(1L)\n'
    '                val minSpan = minOf(maxSpan, maxOf(6L * 60L * 60L * 1000L, mainSpan))\n'
    '                val maxZoom = (maxSpan.toDouble() / minSpan.toDouble()).toFloat().coerceAtLeast(1f)\n'
    '                val effectiveZoom = previewZoom.coerceIn(1f, maxZoom)\n'
    '                val previewSpan = (maxSpan.toDouble() / effectiveZoom.toDouble()).toLong()\n'
    '                    .coerceIn(minSpan, maxSpan)\n',
    "exploration span relative to detail",
)

# Gesture math must use the same x3..x9 context instead of the old fixed preview preset.
main = replace_once(
    main,
    '                        .pointerInput(bounds, previewPreset, rangeSelectionMode) {\n'
    '                            if (!rangeSelectionMode) detectTransformGestures { centroid, pan, zoomChange, _ ->\n'
    '                                val oldMaxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)\n'
    '                                val oldMainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }\n'
    '                                    ?: (24L * 60L * 60L * 1000L)\n',
    '                        .pointerInput(bounds, explorationContextMultiplier, rangeSelectionMode) {\n'
    '                            if (!rangeSelectionMode) detectTransformGestures { centroid, pan, zoomChange, _ ->\n'
    '                                val oldMainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }\n'
    '                                    ?: (24L * 60L * 60L * 1000L)\n'
    '                                val oldMaxSpan = minOf(\n'
    '                                    oldMainSpan * explorationContextMultiplier.toLong(),\n'
    '                                    fullSpan\n'
    '                                ).coerceAtLeast(1L)\n',
    "exploration gesture span relative to detail",
)

# Add the x3..x9 selector directly between band 2 and band 3 where it has meaning.
selector_marker = '''\n                HorizontalDivider()\n                Text(\n                    "Sélection / exploration · LOD 6 h · limitée par le bandeau du milieu",\n'''
selector_insert = '''\n                Row(\n                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),\n                    horizontalArrangement = Arrangement.spacedBy(4.dp),\n                    verticalAlignment = Alignment.CenterVertically\n                ) {\n                    Text(\n                        "Contexte du détail",\n                        style = MaterialTheme.typography.labelSmall,\n                        color = MaterialTheme.colorScheme.onSurfaceVariant\n                    )\n                    (3..9).forEach { factor ->\n                        Surface(\n                            onClick = {\n                                explorationContextMultiplier = factor\n                                previewZoom = 1f\n                            },\n                            color = if (factor == explorationContextMultiplier)\n                                MaterialTheme.colorScheme.secondaryContainer else Color.Transparent,\n                            shape = RoundedCornerShape(12.dp)\n                        ) {\n                            Text(\n                                "×$factor",\n                                Modifier.padding(horizontal = 8.dp, vertical = 5.dp),\n                                fontWeight = if (factor == explorationContextMultiplier) FontWeight.Bold else FontWeight.Normal\n                            )\n                        }\n                    }\n                }\n\n                HorizontalDivider()\n                Text(\n                    "Sélection / exploration · LOD 6 h · limitée par le bandeau du milieu",\n'''
main = replace_once(main, selector_marker, selector_insert, "exploration x3-x9 selector")

main = replace_once(
    main,
    '                        "fenêtre ${previewPreset.label} → détail RAW",\n',
    '                        "contexte ×$explorationContextMultiplier → détail RAW",\n',
    "exploration footer label",
)

# The old 1 week / 1 month / ... row used to define exploration width. Replace it with a note,
# because x3..x9 is now the authoritative context selector.
old_tools_row = '''                Row(\n                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),\n                    horizontalArrangement = Arrangement.spacedBy(4.dp)\n                ) {\n                    PreviewPreset.entries.forEach { item ->\n                        Surface(\n                            onClick = {\n                                previewPreset = item\n                                previewZoom = 1f\n                                val targetCenter = (selectedTimestamp\n                                    ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }\n                                    ?: previewCenter).coerceIn(bounds.first, bounds.last)\n                                previewCenter = targetCenter\n                                wideCenter = targetCenter\n                            },\n                            color = if (item == previewPreset) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent,\n                            shape = RoundedCornerShape(14.dp)\n                        ) {\n                            Text(\n                                item.label,\n                                Modifier.padding(horizontal = 10.dp, vertical = 7.dp),\n                                fontWeight = if (item == previewPreset) FontWeight.Bold else FontWeight.Normal\n                            )\n                        }\n                    }\n                }\n\n'''
main = replace_once(
    main,
    old_tools_row,
    '                Text(\n'
    '                    "Largeur d’exploration pilotée par le sélecteur ×3…×9 placé entre les bandeaux 2 et 3.",\n'
    '                    style = MaterialTheme.typography.labelSmall,\n'
    '                    color = MaterialTheme.colorScheme.onSurfaceVariant\n'
    '                )\n\n',
    "remove obsolete preview preset row",
)

# ---------------------------------------------------------------------------
# 3) Right-edge cascade semantics.
#    Bands 1 and 2 keep their lower levels frozen while dragging, then align every child
#    on the newest/right edge only on release (already existing behavior).
#    Startup and explicit refresh also initialize band 2, band 3 and detail on the right edge
#    of the PRESENT, not on the +1 month empty runway.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    '                fun latestEdgeCenter(span: Long, outer: LongRange): Long {\n'
    '                    val outerSpan = (outer.last - outer.first).coerceAtLeast(1L)\n'
    '                    if (span >= outerSpan) return outer.first + outerSpan / 2L\n'
    '                    return clampCenterToRange(outer.last - span / 2L, span, outer)\n'
    '                }\n',
    '                fun latestEdgeCenter(span: Long, outer: LongRange): Long {\n'
    '                    val outerSpan = (outer.last - outer.first).coerceAtLeast(1L)\n'
    '                    if (span >= outerSpan) return outer.first + outerSpan / 2L\n'
    '                    return clampCenterToRange(outer.last - span / 2L, span, outer)\n'
    '                }\n'
    '                fun rightAlignedCenterAt(edge: Long, span: Long, outer: LongRange): Long {\n'
    '                    val outerSpan = (outer.last - outer.first).coerceAtLeast(1L)\n'
    '                    if (span >= outerSpan) return outer.first + outerSpan / 2L\n'
    '                    val safeEdge = edge.coerceIn(outer.first, outer.last)\n'
    '                    val start = (safeEdge - span).coerceIn(outer.first, outer.last - span)\n'
    '                    return clampCenterToRange(start + span / 2L, span, outer)\n'
    '                }\n',
    "right aligned center helper",
)

startup_marker = '''                val previewWindow = previewFrom..previewTo\n\n                LaunchedEffect(temporalPageSyncToken, temporalPageSyncCenter) {\n'''
startup_insert = '''                val previewWindow = previewFrom..previewTo\n\n                // Initial load and explicit refresh: align the complete lower cascade to the right\n                // edge of the PRESENT. The giga band may extend one month further, but we do not\n                // boot the useful views inside that intentionally empty future runway.\n                LaunchedEffect(presentAnchorTimestamp, viewBounds?.first, viewBounds?.last) {\n                    val detail = viewBounds ?: return@LaunchedEffect\n                    if (appliedRightAnchor == presentAnchorTimestamp) return@LaunchedEffect\n                    val present = presentAnchorTimestamp.coerceIn(bounds.first, bounds.last)\n                    val initialWideCenter = rightAlignedCenterAt(present, wideSpan, bounds)\n                    val initialWideRange = rangeForCenter(initialWideCenter, wideSpan, bounds)\n                    val initialPreviewCenter = rightAlignedCenterAt(present, previewSpan, initialWideRange)\n                    val initialPreviewRange = rangeForCenter(initialPreviewCenter, previewSpan, initialWideRange)\n                    val detailSpan = (detail.last - detail.first).coerceAtLeast(1L).coerceAtMost(previewSpan)\n                    val initialDetailCenter = rightAlignedCenterAt(present, detailSpan, initialPreviewRange)\n                    appliedRightAnchor = presentAnchorTimestamp\n                    wideCenter = initialWideCenter\n                    previewCenter = initialPreviewCenter\n                    onNavigate(initialDetailCenter)\n                    onSelectTimestamp(present.coerceIn(initialPreviewRange.first, initialPreviewRange.last))\n                }\n\n                LaunchedEffect(temporalPageSyncToken, temporalPageSyncCenter) {\n'''
main = replace_once(main, startup_marker, startup_insert, "startup refresh right-edge cascade")

# Band 3 is the training-range workspace: moving it must NOT auto-cascade the detailed graph.
old_detail_constraint = '''                // v0.21.3 : le détail est le quatrième étage de la cascade.\n                // Il ne peut jamais rester hors de la sélection du bandeau 6 h.\n                LaunchedEffect(previewFrom, previewTo, viewBounds?.first, viewBounds?.last) {\n                    val detail = viewBounds ?: return@LaunchedEffect\n                    if (detail.first < previewFrom || detail.last > previewTo) {\n                        val detailSpan = (detail.last - detail.first).coerceAtLeast(1L)\n                            .coerceAtMost(previewSpan)\n                        val currentDetailCenter = detail.first + (detail.last - detail.first) / 2L\n                        val constrainedCenter = clampCenterToRange(\n                            currentDetailCenter,\n                            detailSpan,\n                            previewWindow\n                        )\n                        onNavigate(constrainedCenter)\n                    }\n                }\n'''
main = replace_once(
    main,
    old_detail_constraint,
    '                // Band 3 is intentionally independent while exploring/selecting training ranges.\n'
    '                // It never drags the detailed graph automatically. Detail moves only after an\n'
    '                // upper-band release, explicit navigation/double-tap, startup, or refresh.\n',
    "band3 no automatic cascade",
)

MAIN.write_text(main, encoding="utf-8")
print("Applied right-edge cascade, +1 month runway and x3..x9 exploration context patch")
