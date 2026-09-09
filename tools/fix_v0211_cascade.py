from pathlib import Path

p = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
s = p.read_text(encoding='utf-8')

def once(old, new, label):
    global s
    if old not in s:
        raise SystemExit(f'missing marker: {label}')
    s = s.replace(old, new, 1)

# Lift the two navigation windows to FabDataApp so SQL queries can truly cascade.
once(
'''    var globalBounds by remember { mutableStateOf<LongRange?>(null) }
    var viewBounds by remember { mutableStateOf<LongRange?>(null) }
    var preset by rememberSaveable { mutableStateOf(TimePreset.TWO_DAYS) }
''',
'''    var globalBounds by remember { mutableStateOf<LongRange?>(null) }
    var viewBounds by remember { mutableStateOf<LongRange?>(null) }
    // v0.21.1: two independent windows above the RAW detail.
    // wide = window selected in the global giga overview.
    // explore = window selected inside wide and rendered by the selection band.
    var wideCenterTimestamp by remember { mutableStateOf<Long?>(null) }
    var wideSpanMs by rememberSaveable { mutableStateOf(24L * 31L * 24L * 60L * 60L * 1000L) }
    var exploreCenterTimestamp by remember { mutableStateOf<Long?>(null) }
    var exploreSpanMs by rememberSaveable { mutableStateOf(6L * 31L * 24L * 60L * 60L * 1000L) }
    var preset by rememberSaveable { mutableStateOf(TimePreset.TWO_DAYS) }
''',
'lift cascade state')

# Reload whenever either upstream window changes.
once(
'''    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs) {
''',
'''    LaunchedEffect(
        reloadToken, preset, windowCenterTimestamp, customViewSpanMs,
        wideCenterTimestamp, wideSpanMs, exploreCenterTimestamp, exploreSpanMs
    ) {
''',
'reload keys')

# Replace all-history LOD block with scoped ranges.
old = '''                fun physicalLod(bucketMs: Long): Map<Long, List<SamplePoint>> =
                    s.associate { sensor ->
                        sensor.id to db.querySamplesLod(sensor.id, all.first, all.last, bucketMs)
                    }
                fun weatherLod(bucketMs: Long): List<SamplePoint> =
                    weatherReferenceStore.queryLod(
                        selectedWeatherReference.key, all.first, all.last, bucketMs
                    ).map {
                        SamplePoint(
                            LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity,
                            it.source, it.confidence
                        )
                    }

                // Pyramide LOD : les RAW restent dans SQLite. Chaque bandeau ne reçoit
                // que sa résolution dédiée, au lieu de charger tout l'historique puis réduire.
                val gigaOverview = physicalLod(OVERVIEW_LOD_MONTH_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_MONTH_MS))
                val navigatorOverview = physicalLod(OVERVIEW_LOD_DAY_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS))
                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS))
'''
new = '''                fun clampWindow(centerWanted: Long?, spanWanted: Long, parent: LongRange): LongRange {
                    val parentSpan = (parent.last - parent.first).coerceAtLeast(1L)
                    val span = spanWanted.coerceIn(1L, parentSpan)
                    val defaultCenter = parent.last - span / 2L
                    val center = (centerWanted ?: defaultCenter).coerceIn(parent.first, parent.last)
                    var start = center - span / 2L
                    var end = start + span
                    if (start < parent.first) { start = parent.first; end = start + span }
                    if (end > parent.last) { end = parent.last; start = end - span }
                    return start..end
                }
                val wideRange = clampWindow(wideCenterTimestamp, wideSpanMs, all)
                val exploreRange = clampWindow(exploreCenterTimestamp ?: wideRange.last - exploreSpanMs / 2L, exploreSpanMs, wideRange)

                fun physicalLod(range: LongRange, bucketMs: Long): Map<Long, List<SamplePoint>> =
                    s.associate { sensor ->
                        sensor.id to db.querySamplesLod(sensor.id, range.first, range.last, bucketMs)
                    }
                fun weatherLod(range: LongRange, bucketMs: Long): List<SamplePoint> =
                    weatherReferenceStore.queryLod(
                        selectedWeatherReference.key, range.first, range.last, bucketMs
                    ).map {
                        SamplePoint(
                            LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity,
                            it.source, it.confidence
                        )
                    }

                // True cascade: ONLY the giga band touches the complete history.
                // Wide navigation reads the giga-selected range, exploration reads only
                // the wide-selected range, and RAW stays restricted to `chosen` above.
                val gigaOverview = physicalLod(all, OVERVIEW_LOD_MONTH_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(all, OVERVIEW_LOD_MONTH_MS))
                val navigatorOverview = physicalLod(wideRange, OVERVIEW_LOD_DAY_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(wideRange, OVERVIEW_LOD_DAY_MS))
                val explorationOverview = physicalLod(exploreRange, OVERVIEW_LOD_6H_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(exploreRange, OVERVIEW_LOD_6H_MS))
'''
once(old, new, 'scoped LOD queries')

# Scope inertia LOD too; currently it still queries all.
once(
'''                fun withInertiaLod(
                    base: Map<Long, List<SamplePoint>>,
                    bucketMs: Long
                ): Map<Long, List<SamplePoint>> {
''',
'''                fun withInertiaLod(
                    base: Map<Long, List<SamplePoint>>,
                    range: LongRange,
                    bucketMs: Long
                ): Map<Long, List<SamplePoint>> {
''',
'inertia signature')
once(
'''                        all.first,
                        all.last,
                        bucketMs
''',
'''                        range.first,
                        range.last,
                        bucketMs
''',
'inertia range')
once(
'''                    withInertiaLod(gigaOverview, OVERVIEW_LOD_MONTH_MS),
                    withInertiaLod(navigatorOverview, OVERVIEW_LOD_DAY_MS),
                    withInertiaLod(explorationOverview, OVERVIEW_LOD_6H_MS),
''',
'''                    withInertiaLod(gigaOverview, all, OVERVIEW_LOD_MONTH_MS),
                    withInertiaLod(navigatorOverview, wideRange, OVERVIEW_LOD_DAY_MS),
                    withInertiaLod(explorationOverview, exploreRange, OVERVIEW_LOD_6H_MS),
''',
'inertia calls')

# Initialize lifted window centers after loading bounds, but don't overwrite user choices.
once(
'''        globalBounds = loaded.globalBounds
        viewBounds = loaded.viewBounds
''',
'''        globalBounds = loaded.globalBounds
        viewBounds = loaded.viewBounds
        loaded.globalBounds?.let { b ->
            if (wideCenterTimestamp == null) {
                val span = wideSpanMs.coerceAtMost((b.last - b.first).coerceAtLeast(1L))
                wideCenterTimestamp = b.last - span / 2L
            }
        }
        if (exploreCenterTimestamp == null) {
            exploreCenterTimestamp = loaded.viewBounds?.let { it.first + (it.last - it.first) / 2L }
                ?: wideCenterTimestamp
        }
''',
'initialize centers')

# Add lifted state/callbacks to HistoryOverviewCard call.
once(
'''                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        selectedTimestamp = selectedTimestamp,
''',
'''                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        wideCenterTimestamp = wideCenterTimestamp,
                        wideSpanMs = wideSpanMs,
                        exploreCenterTimestamp = exploreCenterTimestamp,
                        exploreSpanMs = exploreSpanMs,
                        onWideWindowChanged = { center, span ->
                            wideCenterTimestamp = center
                            wideSpanMs = span
                            val wideHalf = span / 2L
                            exploreCenterTimestamp = (exploreCenterTimestamp ?: center)
                                .coerceIn(center - wideHalf, center + wideHalf)
                        },
                        onExploreWindowChanged = { center, span ->
                            exploreCenterTimestamp = center
                            exploreSpanMs = span
                        },
                        selectedTimestamp = selectedTimestamp,
''',
'card args')

# Extend HistoryOverviewCard signature.
once(
'''    historyBounds: LongRange?,
    viewBounds: LongRange?,
    selectedTimestamp: Long?,
''',
'''    historyBounds: LongRange?,
    viewBounds: LongRange?,
    wideCenterTimestamp: Long?,
    wideSpanMs: Long,
    exploreCenterTimestamp: Long?,
    exploreSpanMs: Long,
    onWideWindowChanged: (Long, Long) -> Unit,
    onExploreWindowChanged: (Long, Long) -> Unit,
    selectedTimestamp: Long?,
''',
'card signature')

# Replace local preview center and preset coupling with explore state while keeping preset UI.
once(
'''                var previewPreset by rememberSaveable { mutableStateOf(PreviewPreset.M6) }
                var previewZoom by rememberSaveable { mutableFloatStateOf(1f) }
                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
''',
'''                var previewPreset by rememberSaveable { mutableStateOf(PreviewPreset.M6) }
                var previewZoom by rememberSaveable { mutableFloatStateOf(1f) }
                var previewCenter by remember(exploreCenterTimestamp, bounds.first, bounds.last) {
                    mutableStateOf(
                        exploreCenterTimestamp
                            ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
''',
'preview center source')

# When preset changes, inform parent of the exploration span.
once(
'''                                previewPreset = item
                                previewZoom = 1f
                                previewCenter = (selectedTimestamp
                                    ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                                    ?: previewCenter).coerceIn(bounds.first, bounds.last)
''',
'''                                previewPreset = item
                                previewZoom = 1f
                                previewCenter = (selectedTimestamp
                                    ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                                    ?: previewCenter).coerceIn(bounds.first, bounds.last)
                                onExploreWindowChanged(previewCenter, item.spanMs)
''',
'preset callback')

# Need real independent wide range inside card.
# Insert before giga points calculations, at stable navigatorTempRange marker.
once(
'''                val navigatorTempRange = (navigatorMax - navigatorMin).takeIf { it > 0.01 } ?: 1.0

                val gigaSensorPoints = remember(gigaSampleMap, sensors, bandSensorIds, bounds.first, bounds.last) {
''',
'''                val navigatorTempRange = (navigatorMax - navigatorMin).takeIf { it > 0.01 } ?: 1.0

                val globalSpanForWide = (bounds.last - bounds.first).coerceAtLeast(1L)
                val effectiveWideSpan = wideSpanMs.coerceIn(1L, globalSpanForWide)
                val effectiveWideCenter = (wideCenterTimestamp ?: bounds.last - effectiveWideSpan / 2L)
                    .coerceIn(bounds.first, bounds.last)
                var wideFrom = effectiveWideCenter - effectiveWideSpan / 2L
                var wideTo = wideFrom + effectiveWideSpan
                if (wideFrom < bounds.first) { wideFrom = bounds.first; wideTo = wideFrom + effectiveWideSpan }
                if (wideTo > bounds.last) { wideTo = bounds.last; wideFrom = wideTo - effectiveWideSpan }
                val wideRangeForUi = wideFrom..wideTo

                val gigaSensorPoints = remember(gigaSampleMap, sensors, bandSensorIds, bounds.first, bounds.last) {
''',
'wide ui range')

# Giga drag/tap should move WIDE, not preview/explore.
once(
'''                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()
                                previewCenter = clampCenter(previewCenter + deltaTs, previewSpan)
                                change.consume()
''',
'''                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()
                                val center = clampCenter(effectiveWideCenter + deltaTs, effectiveWideSpan)
                                onWideWindowChanged(center, effectiveWideSpan)
                                change.consume()
''',
'giga drag')
once(
'''                                previewCenter = clampCenter(
                                    bounds.first + (fullSpan * fraction).toLong(),
                                    previewSpan
                                )
''',
'''                                val center = clampCenter(
                                    bounds.first + (fullSpan * fraction).toLong(),
                                    effectiveWideSpan
                                )
                                onWideWindowChanged(center, effectiveWideSpan)
''',
'giga tap')

# Giga window rectangle = wide window, not exploration.
once(
'''                    val left = (((previewFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((previewTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
''',
'''                    val left = (((wideFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((wideTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
''',
'giga window')

# Navigator should display only wide range and move exploration window inside it.
# First occurrence after navigator label: pointer mapping uses full global; scope it.
# We make drag/tap operate on exploration center and span within wide.
once(
'''                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()
                                previewCenter = clampCenter(previewCenter + deltaTs, previewSpan)
                                change.consume()
''',
'''                                val wideSpan = (wideTo - wideFrom).coerceAtLeast(1L)
                                val deltaTs = ((dragAmount.x / width) * wideSpan.toDouble()).toLong()
                                val targetSpan = exploreSpanMs.coerceAtMost(wideSpan)
                                val minCenter = wideFrom + targetSpan / 2L
                                val maxCenter = wideTo - targetSpan / 2L
                                val next = (previewCenter + deltaTs).coerceIn(minCenter, maxCenter)
                                previewCenter = next
                                onExploreWindowChanged(next, targetSpan)
                                change.consume()
''',
'navigator drag')
once(
'''                                val target = bounds.first + (fullSpan * fraction).toLong()
                                previewCenter = clampCenter(target, previewSpan)
''',
'''                                val wideSpan = (wideTo - wideFrom).coerceAtLeast(1L)
                                val target = wideFrom + (wideSpan * fraction).toLong()
                                val targetSpan = exploreSpanMs.coerceAtMost(wideSpan)
                                val minCenter = wideFrom + targetSpan / 2L
                                val maxCenter = wideTo - targetSpan / 2L
                                previewCenter = target.coerceIn(minCenter, maxCenter)
                                onExploreWindowChanged(previewCenter, targetSpan)
''',
'navigator tap')

# Navigator plot x mapping and mask must be relative to wide, and labels wide dates.
s = s.replace(
'''                                val navigatorGapLimit = maxOf(
                                    12L * 60L * 60L * 1000L,
                                    fullSpan / 120L
                                )
                                points.forEach { point ->
                                    val x = (((point.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
''',
'''                                val navigatorGapLimit = maxOf(
                                    12L * 60L * 60L * 1000L,
                                    (wideTo - wideFrom).coerceAtLeast(1L) / 120L
                                )
                                val widePlotSpan = (wideTo - wideFrom).coerceAtLeast(1L)
                                points.filter { it.timestamp in wideRangeForUi }.forEach { point ->
                                    val x = (((point.timestamp - wideFrom).toDouble() / widePlotSpan.toDouble()).toFloat() * size.width)
''',1)
# Replace second matching preview window rect (navigator) with exploration relative to wide.
needle = '''                    val left = (((previewFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((previewTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
'''
if needle not in s:
    raise SystemExit('missing navigator window rect')
s = s.replace(needle,
'''                    val widePlotSpan = (wideTo - wideFrom).coerceAtLeast(1L)
                    val clippedPreviewFrom = maxOf(previewFrom, wideFrom)
                    val clippedPreviewTo = minOf(previewTo, wideTo)
                    val left = (((clippedPreviewFrom - wideFrom).toDouble() / widePlotSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((clippedPreviewTo - wideFrom).toDouble() / widePlotSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
''',1)
once(
'''                    Text(formatDateTime(bounds.first), style = MaterialTheme.typography.labelSmall)
                    Text("historique complet", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(formatDateTime(bounds.last), style = MaterialTheme.typography.labelSmall)
''',
'''                    Text(formatDateTime(wideFrom), style = MaterialTheme.typography.labelSmall)
                    Text("zoom large", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(formatDateTime(wideTo), style = MaterialTheme.typography.labelSmall)
''',
'navigator labels')

# Keep parent in sync after transform gestures on exploration band.
once(
'''                                previewZoom = newZoom
                                previewCenter = clampCenter(zoomAnchoredCenter + panShift, newSpan)
''',
'''                                previewZoom = newZoom
                                previewCenter = clampCenter(zoomAnchoredCenter + panShift, newSpan)
                                onExploreWindowChanged(previewCenter, newSpan)
''',
'explore transform callback')

# Clarify header.
once(
'''                "Giga = mois · navigation = jours · exploration = 6 h · détail = RAW",
''',
'''                "Giga global → zoom large → sélection → détail RAW",
''',
'header text')

p.write_text(s, encoding='utf-8')
print('v0.21.1 cascade patch applied')
