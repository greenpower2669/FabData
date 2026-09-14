from pathlib import Path
import re

MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
DIAL = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


main = MAIN.read_text(encoding="utf-8")
dial = DIAL.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 1) Forecast dials: always start compact for a fresh Activity session.
#    Expanded geometry is still persisted and restored when the user unfolds it.
# ---------------------------------------------------------------------------
dial = replace_once(
    dial,
    '        val params = FrameLayout.LayoutParams(dp(348f), dp(154f), Gravity.TOP or Gravity.START)\n',
    '        // Startup policy: the floating tangent cockpit begins compact, then the user may unfold it.\n'
    '        val params = FrameLayout.LayoutParams(dp(76f), dp(46f), Gravity.TOP or Gravity.START)\n',
    "dial startup size",
)
dial = replace_once(
    dial,
    '        compact = prefs.getBoolean(KEY_COMPACT, false)\n',
    '        // Explicit startup policy: each newly attached Activity starts with reduced dials.\n'
    '        // The expanded size/position remain persisted for the next manual unfold.\n'
    '        compact = true\n'
    '        prefs.edit().putBoolean(KEY_COMPACT, true).apply()\n',
    "dial startup compact state",
)

# ---------------------------------------------------------------------------
# 2) Navigation/display horizon: the cascade can extend to NOW + 48 h.
#    Historical RAW stays where it ends; prediction series can naturally continue it.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    '    val chartExplorationOverviewSampleMap = chartLodMap(explorationOverviewSampleMap, OVERVIEW_LOD_6H_MS)\n\n'
    '    fun centeredTemporalRange(center: Long, requestedSpan: Long, outer: LongRange): LongRange {\n',
    '    val chartExplorationOverviewSampleMap = chartLodMap(explorationOverviewSampleMap, OVERVIEW_LOD_6H_MS)\n\n'
    '    // Navigation is allowed to continue beyond the last terrain point up to NOW + 48 h.\n'
    '    // The terrain curve simply stops at its last real/reconstructed point while forecast curves continue.\n'
    '    val overviewDisplayBounds = globalBounds?.let { historical ->\n'
    '        val now = System.currentTimeMillis()\n'
    '        historical.first..maxOf(historical.last, now + FORECAST_DISPLAY_FUTURE_MS)\n'
    '    }\n\n'
    '    fun centeredTemporalRange(center: Long, requestedSpan: Long, outer: LongRange): LongRange {\n',
    "overview display bounds",
)
main = replace_once(
    main,
    '    fun requestTemporalPage(direction: TemporalPageDirection, currentPage: LongRange) {\n'
    '        if (lowerCascadeVeil) return\n'
    '        val history = globalBounds ?: return\n',
    '    fun requestTemporalPage(direction: TemporalPageDirection, currentPage: LongRange) {\n'
    '        if (lowerCascadeVeil) return\n'
    '        val history = overviewDisplayBounds ?: return\n',
    "temporal page future bounds",
)
main = replace_once(
    main,
    '    val temporalHistoryRange = globalBounds\n',
    '    val temporalHistoryRange = overviewDisplayBounds\n',
    "temporal history future bounds",
)
main = replace_once(
    main,
    '                        historyBounds = globalBounds,\n',
    '                        historyBounds = overviewDisplayBounds,\n',
    "history overview future bounds",
)

# ---------------------------------------------------------------------------
# 3) HistoryOverview receives the detail graph and its time tabs as slots.
#    This keeps bands 1/2/3 + detail together in one compact top block.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    '    onTrainingPolicy: (LongRange, ThermalTrainingTarget, ThermalTrainingRangeMode) -> Unit,\n'
    '    onZoomRange: (LongRange) -> Unit\n'
    ') {\n',
    '    onTrainingPolicy: (LongRange, ThermalTrainingTarget, ThermalTrainingRangeMode) -> Unit,\n'
    '    onZoomRange: (LongRange) -> Unit,\n'
    '    detailContent: @Composable () -> Unit,\n'
    '    detailPeriodContent: @Composable () -> Unit\n'
    ') {\n',
    "history overview detail slots",
)

call_start = main.index('                    HistoryOverviewCard(')
replay_marker = '\n\n                item {\n                    ForecastReplayCard('
call_end = main.index(replay_marker, call_start)
call_segment = main[call_start:call_end]
closing = '\n                    )\n                }'
close_idx = call_segment.rfind(closing)
if close_idx < 0:
    raise SystemExit("HistoryOverviewCard call closing marker not found")
call_prefix = call_segment[:close_idx].rstrip()
if not call_prefix.endswith('}'):
    raise SystemExit("HistoryOverviewCard call does not end with onZoomRange lambda")

slot_args = r''',
                        detailContent = {
                            Box(Modifier.fillMaxWidth()) {
                                ChartCard(
                                    sensors = chartSensors,
                                    sampleMap = chartSampleMap,
                                    showTemp = showTemp,
                                    showHumidity = showHumidity,
                                    annotations = annotations,
                                    bounds = viewBounds,
                                    prefs = prefs,
                                    curveStyles = activeCurveStyles,
                                    styleTick = styleTick,
                                    selectedTimestamp = selectedTimestamp,
                                    canPageBackward = detailCanPageBackward,
                                    canPageForward = detailCanPageForward,
                                    onPageBackward = {
                                        temporalPageRange?.let { requestTemporalPage(TemporalPageDirection.PREVIOUS, it) }
                                    },
                                    onPageForward = {
                                        temporalPageRange?.let { requestTemporalPage(TemporalPageDirection.NEXT, it) }
                                    },
                                    onSelectTimestamp = {
                                        selectedTimestamp = it
                                        selectedAnnotation = null
                                    },
                                    onAnnotationClick = {
                                        selectedAnnotation = it
                                        selectedTimestamp = it.timestamp
                                    },
                                    onAnnotationDoubleClick = {
                                        detailAnnotation = it
                                        selectedAnnotation = it
                                    },
                                    onRequestAnnotation = { ts ->
                                        editingAnnotation = null
                                        annotationTimestamp = ts
                                        selectedTimestamp = ts
                                    },
                                    onRequestZoom = { _ ->
                                        // Reserved gesture hook. Long press currently performs no action.
                                    }
                                )
                                PendingCascadeOverlay(
                                    pending = lowerCascadeVeil,
                                    flashToken = lowerCascadeFlashToken,
                                    modifier = Modifier.fillMaxSize()
                                )
                            }
                        },
                        detailPeriodContent = {
                            TimeTabs(preset = preset, onSelect = {
                                customViewSpanMs = null
                                preset = it
                                windowCenterTimestamp = selectedTimestamp
                                    ?: viewBounds?.let { b -> b.first + (b.last - b.first) / 2L }
                                selectedAnnotation = null
                            })
                        }'''
call_segment_new = call_prefix + slot_args + call_segment[close_idx:]
main = main[:call_start] + call_segment_new + main[call_end:]

# Remove the old standalone TimeTabs + ChartCard items. They now live in the compact cascade block.
standalone_start = main.index('\n                item {\n                    TimeTabs(preset = preset, onSelect = {', main.index(replay_marker, call_start))
sensor_sources_marker = '\n                item {\n                    SensorSourcesCard('
standalone_end = main.index(sensor_sources_marker, standalone_start)
main = main[:standalone_start] + main[standalone_end:]

# ---------------------------------------------------------------------------
# 4) Inside HistoryOverview: move analysis controls below band 3 + detail.
#    Order becomes: global -> wide -> exploration -> detail -> range controls -> detail presets -> analysis tools.
# ---------------------------------------------------------------------------
hist_start = main.index('@Composable\nprivate fun HistoryOverviewCard(')
hist_end = main.index('\n@Composable\nprivate fun RangeSelectionHelpDemo(', hist_start)
hist = main[hist_start:hist_end]

tools_start_marker = '\n                HorizontalDivider()\n                Text(\n                    "Outils d’analyse de la période",'
band_start_marker = '\n                HorizontalDivider()\n                Text(\n                    "Sélection / exploration · LOD 6 h · limitée par le bandeau du milieu",'
tools_start = hist.index(tools_start_marker)
band_start = hist.index(band_start_marker, tools_start)
assist_idx = hist.index('                    AssistChip(', tools_start, band_start)
controls_start = hist.rfind('\n                Row(', tools_start, assist_idx)
if controls_start < 0:
    raise SystemExit("range-selection controls start not found")
close_marker = '\n            }\n        }\n    }\n}'
close_idx = hist.rfind(close_marker)
if close_idx < band_start:
    raise SystemExit("HistoryOverviewCard closing marker not found")

tools_prefix = hist[tools_start:controls_start]
controls_block = hist[controls_start:band_start]
band_block = hist[band_start:close_idx]

hist_new = (
    hist[:tools_start]
    + band_block
    + '\n\n                // Fourth level: detailed RAW/forecast graph immediately below exploration.\n'
      '                detailContent()\n'
    + controls_block
    + '\n\n                // Detail time presets are outside the detail card and below the range controls.\n'
      '                detailPeriodContent()\n'
    + tools_prefix
    + hist[close_idx:]
)
main = main[:hist_start] + hist_new + main[hist_end:]

# ---------------------------------------------------------------------------
# 5) Continue-drag paging on exploration band, in addition to arrow buttons.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    '                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }\n'
    '                var rangeStart by remember { mutableStateOf<Long?>(null) }\n',
    '                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }\n'
    '                var explorationEdgePushDistancePx by remember { mutableFloatStateOf(0f) }\n'
    '                var explorationEdgePushDirection by remember { mutableIntStateOf(0) }\n'
    '                var explorationEdgePushTriggered by remember { mutableStateOf(false) }\n'
    '                var rangeStart by remember { mutableStateOf<Long?>(null) }\n',
    "exploration edge push state",
)
main = replace_once(
    main,
    '                                val panShift = (-(pan.x / width) * newSpan.toDouble()).toLong()\n\n'
    '                                previewZoom = newZoom\n'
    '                                previewCenter = clampCenterToRange(zoomAnchoredCenter + panShift, newSpan, wideWindow)\n',
    '                                val panShift = (-(pan.x / width) * newSpan.toDouble()).toLong()\n'
    '                                val requestedCenter = zoomAnchoredCenter + panShift\n'
    '                                val clampedCenter = clampCenterToRange(requestedCenter, newSpan, wideWindow)\n\n'
    '                                // Keep dragging beyond the exploration edge to page the cascade.\n'
    '                                // Arrow buttons remain available and call exactly the same page action.\n'
    '                                val deliberatePan = zoomChange in 0.985f..1.015f\n'
    '                                val pushDirection = when {\n'
    '                                    deliberatePan && requestedCenter < clampedCenter && pan.x > 0f && thirdLevelCanPagePrevious -> -1\n'
    '                                    deliberatePan && requestedCenter > clampedCenter && pan.x < 0f && thirdLevelCanPageNext -> 1\n'
    '                                    else -> 0\n'
    '                                }\n'
    '                                if (pushDirection != 0) {\n'
    '                                    if (explorationEdgePushDirection != pushDirection) {\n'
    '                                        explorationEdgePushDirection = pushDirection\n'
    '                                        explorationEdgePushDistancePx = 0f\n'
    '                                        explorationEdgePushTriggered = false\n'
    '                                    }\n'
    '                                    explorationEdgePushDistancePx += kotlin.math.abs(pan.x)\n'
    '                                    if (!explorationEdgePushTriggered && explorationEdgePushDistancePx >= 42.dp.toPx()) {\n'
    '                                        explorationEdgePushTriggered = true\n'
    '                                        onTemporalPageRequest(\n'
    '                                            if (pushDirection < 0) TemporalPageDirection.PREVIOUS else TemporalPageDirection.NEXT,\n'
    '                                            previewWindow\n'
    '                                        )\n'
    '                                    }\n'
    '                                } else if (kotlin.math.abs(pan.x) > 0.5f) {\n'
    '                                    explorationEdgePushDirection = 0\n'
    '                                    explorationEdgePushDistancePx = 0f\n'
    '                                    explorationEdgePushTriggered = false\n'
    '                                }\n\n'
    '                                previewZoom = newZoom\n'
    '                                previewCenter = clampedCenter\n',
    "exploration continue-drag paging",
)

# ---------------------------------------------------------------------------
# 6) Detailed graph long press: keep the event hook but intentionally do nothing.
# ---------------------------------------------------------------------------
long_press_pattern = re.compile(
    r'                    onLongPress = \{ p ->\n'
    r'.*?'
    r'                    \},\n'
    r'                    onDoubleTap = \{ p ->',
    re.S,
)
match = long_press_pattern.search(main)
if not match:
    raise SystemExit("detailed chart long-press block not found")
replacement = (
    '                    onLongPress = { _ ->\n'
    '                        // Reserved for a future action: event detected, no visible effect today.\n'
    '                    },\n'
    '                    onDoubleTap = { p ->'
)
main = main[:match.start()] + replacement + main[match.end():]

main = replace_once(
    main,
    '            "Tap = curseur · double tap = événement · appui long = zoom 48 h · pince/glisse = ajuster",\n',
    '            "Tap = curseur · double tap = événement · pince/glisse = ajuster",\n',
    "detail gesture helper text",
)
main = replace_once(
    main,
    '                                "Le graphe principal ne change pas : son appui long reste réservé au zoom 48 h.",\n',
    '                                "Le graphe principal conserve l’appui long comme événement réservé, sans action pour l’instant.",\n',
    "range help long-press text",
)

# Small explanatory text: the four-stage cascade is now deliberately contiguous.
main = replace_once(
    main,
    '                "1. totalité · 2. sélection du haut · 3. sélection du milieu · 4. détail RAW",\n',
    '                "1. totalité · 2. sélection du haut · 3. exploration · 4. détail RAW / prévisions",\n',
    "cascade header",
)

MAIN.write_text(main, encoding="utf-8")
DIAL.write_text(dial, encoding="utf-8")
print("Applied v0.23.9 compact cascade UI patch")
