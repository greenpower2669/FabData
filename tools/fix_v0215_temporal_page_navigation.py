from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


main = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
t = main.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Temporal page direction.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """private enum class PreviewPreset(val label: String, val spanMs: Long) {
    W1("1 sem.", 7L * 24L * 60L * 60L * 1000L),
    M1("1 mois", 31L * 24L * 60L * 60L * 1000L),
    M3("3 mois", 92L * 24L * 60L * 60L * 1000L),
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}

""",
    """private enum class PreviewPreset(val label: String, val spanMs: Long) {
    W1("1 sem.", 7L * 24L * 60L * 60L * 1000L),
    M1("1 mois", 31L * 24L * 60L * 60L * 1000L),
    M3("3 mois", 92L * 24L * 60L * 60L * 1000L),
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}

private enum class TemporalPageDirection {
    PREVIOUS,
    NEXT
}

""",
    "temporal page enum",
)

# ---------------------------------------------------------------------------
# Parent-level sync state. This is only used when paging starts from the lower
# levels so the two weather navigators can follow without any user interaction.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """    var lowerCascadeVeil by remember { mutableStateOf(false) }
    var lowerCascadeAwaitingReload by remember { mutableStateOf(false) }
    var lowerCascadeFlashToken by remember { mutableIntStateOf(0) }
""",
    """    var lowerCascadeVeil by remember { mutableStateOf(false) }
    var lowerCascadeAwaitingReload by remember { mutableStateOf(false) }
    var lowerCascadeFlashToken by remember { mutableIntStateOf(0) }
    var temporalPageSyncToken by remember { mutableIntStateOf(0) }
    var temporalPageSyncCenter by remember { mutableStateOf<Long?>(null) }
""",
    "page sync state",
)

# ---------------------------------------------------------------------------
# Central paging function. Page size = current level-3 calculated window.
# The detailed window lands at the beginning of the next page or at the end of
# the previous page, exactly like turning a temporal page.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """    val chartGigaOverviewSampleMap = chartLodMap(gigaOverviewSampleMap)
    val chartNavigatorOverviewSampleMap = chartLodMap(navigatorOverviewSampleMap)
    val chartExplorationOverviewSampleMap = chartLodMap(explorationOverviewSampleMap)

    val activeProcessCount = FabOperationRegistry.operations.count { it.active }
""",
    """    val chartGigaOverviewSampleMap = chartLodMap(gigaOverviewSampleMap)
    val chartNavigatorOverviewSampleMap = chartLodMap(navigatorOverviewSampleMap)
    val chartExplorationOverviewSampleMap = chartLodMap(explorationOverviewSampleMap)

    fun centeredTemporalRange(center: Long, requestedSpan: Long, outer: LongRange): LongRange {
        val outerSpan = (outer.last - outer.first).coerceAtLeast(1L)
        val span = minOf(requestedSpan.coerceAtLeast(1L), outerSpan)
        if (span >= outerSpan) return outer
        val half = span / 2L
        var start = center - half
        var end = start + span
        if (start < outer.first) {
            start = outer.first
            end = start + span
        }
        if (end > outer.last) {
            end = outer.last
            start = end - span
        }
        return start..end
    }

    fun requestTemporalPage(direction: TemporalPageDirection, currentPage: LongRange) {
        if (lowerCascadeVeil) return
        val history = globalBounds ?: return
        val historySpan = (history.last - history.first).coerceAtLeast(1L)
        val pageSpan = (currentPage.last - currentPage.first).coerceAtLeast(1L)
            .coerceAtMost(historySpan)
        if (pageSpan >= historySpan) return

        val desiredCenter = when (direction) {
            TemporalPageDirection.NEXT -> {
                if (currentPage.last >= history.last) return
                currentPage.last + pageSpan / 2L
            }
            TemporalPageDirection.PREVIOUS -> {
                if (currentPage.first <= history.first) return
                currentPage.first - pageSpan / 2L
            }
        }
        val nextPage = centeredTemporalRange(desiredCenter, pageSpan, history)
        if (nextPage.first == currentPage.first && nextPage.last == currentPage.last) return

        val nextPageSpan = (nextPage.last - nextPage.first).coerceAtLeast(1L)
        val nextCenter = nextPage.first + nextPageSpan / 2L
        val currentWideSpan = wideOverviewRange
            ?.let { (it.last - it.first).coerceAtLeast(nextPageSpan) }
            ?: minOf(historySpan, maxOf(nextPageSpan * 2L, PreviewPreset.M1.spanMs))
        val nextWide = centeredTemporalRange(nextCenter, currentWideSpan, history)

        val requestedDetailSpan = (customViewSpanMs ?: preset.spanMs)
            .coerceAtLeast(60L * 60L * 1000L)
        val detailSpan = minOf(requestedDetailSpan, nextPageSpan)
        val detailCenter = when (direction) {
            TemporalPageDirection.NEXT -> nextPage.first + detailSpan / 2L
            TemporalPageDirection.PREVIOUS -> nextPage.last - detailSpan / 2L
        }
        val landingTimestamp = when (direction) {
            TemporalPageDirection.NEXT -> nextPage.first
            TemporalPageDirection.PREVIOUS -> nextPage.last
        }

        // One commit only. Smoke freezes levels 3+4 until this single reload ends.
        lowerCascadeAwaitingReload = true
        lowerCascadeVeil = true
        wideOverviewRange = nextWide
        explorationOverviewRange = nextPage
        temporalPageSyncCenter = nextCenter
        temporalPageSyncToken++
        windowCenterTimestamp = detailCenter
        selectedTimestamp = landingTimestamp
        selectedAnnotation = null
    }

    val temporalPageRange = explorationOverviewRange
    val temporalDetailRange = viewBounds
    val temporalHistoryRange = globalBounds
    val temporalEdgeTolerance = temporalDetailRange?.let {
        maxOf(
            60L * 60L * 1000L,
            minOf(12L * 60L * 60L * 1000L, (it.last - it.first).coerceAtLeast(1L) / 20L)
        )
    } ?: (60L * 60L * 1000L)
    val detailCanPageBackward = !lowerCascadeVeil && temporalPageRange != null &&
        temporalDetailRange != null && temporalHistoryRange != null &&
        temporalDetailRange.first <= temporalPageRange.first + temporalEdgeTolerance &&
        temporalPageRange.first > temporalHistoryRange.first
    val detailCanPageForward = !lowerCascadeVeil && temporalPageRange != null &&
        temporalDetailRange != null && temporalHistoryRange != null &&
        temporalDetailRange.last >= temporalPageRange.last - temporalEdgeTolerance &&
        temporalPageRange.last < temporalHistoryRange.last

    val activeProcessCount = FabOperationRegistry.operations.count { it.active }
""",
    "central temporal paging",
)

# ---------------------------------------------------------------------------
# Wire paging + automatic top navigator sync into the overview card.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """                        selectedTimestamp = selectedTimestamp,
                        lowerZonesPending = lowerCascadeVeil,
                        lowerZonesFlashToken = lowerCascadeFlashToken,
""",
    """                        selectedTimestamp = selectedTimestamp,
                        lowerZonesPending = lowerCascadeVeil,
                        lowerZonesFlashToken = lowerCascadeFlashToken,
                        temporalPageSyncToken = temporalPageSyncToken,
                        temporalPageSyncCenter = temporalPageSyncCenter,
""",
    "overview sync args",
)

t = replace_once(
    t,
    """                        onLowerZonesCommit = {
                            lowerCascadeAwaitingReload = true
                            lowerCascadeVeil = true
                        },
                        onCascadeRangesChanged = { wide, exploration ->
""",
    """                        onLowerZonesCommit = {
                            lowerCascadeAwaitingReload = true
                            lowerCascadeVeil = true
                        },
                        onTemporalPageRequest = { direction, page ->
                            requestTemporalPage(direction, page)
                        },
                        onCascadeRangesChanged = { wide, exploration ->
""",
    "overview page callback",
)

# ---------------------------------------------------------------------------
# Wire page navigation into the detailed chart. Arrows only appear when the
# detailed RAW window actually touches the corresponding edge of level 3.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """                        styleTick = styleTick,
                        selectedTimestamp = selectedTimestamp,
                        onSelectTimestamp = {
""",
    """                        styleTick = styleTick,
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
""",
    "chart page callbacks",
)

# ---------------------------------------------------------------------------
# Reusable page arrows. They intentionally stay explicit: merely reaching the
# edge never changes page. The second trigger is the push threshold in the chart.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """@Composable
private fun PendingCascadeOverlay(
""",
    """@Composable
private fun TemporalPageArrows(
    showPrevious: Boolean,
    showNext: Boolean,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier
) {
    Box(modifier) {
        if (showPrevious) {
            Surface(
                onClick = onPrevious,
                modifier = Modifier.align(Alignment.CenterStart).padding(4.dp),
                shape = RoundedCornerShape(22.dp),
                color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.92f),
                shadowElevation = 5.dp
            ) {
                Text(
                    "←",
                    modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    fontWeight = FontWeight.Bold
                )
            }
        }
        if (showNext) {
            Surface(
                onClick = onNext,
                modifier = Modifier.align(Alignment.CenterEnd).padding(4.dp),
                shape = RoundedCornerShape(22.dp),
                color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.92f),
                shadowElevation = 5.dp
            ) {
                Text(
                    "→",
                    modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    fontWeight = FontWeight.Bold
                )
            }
        }
    }
}

@Composable
private fun PendingCascadeOverlay(
""",
    "temporal page arrows component",
)

# ---------------------------------------------------------------------------
# Extend overview signature.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """    selectedTimestamp: Long?,
    lowerZonesPending: Boolean,
    lowerZonesFlashToken: Int,
    onLowerZonesInteractionStart: () -> Unit,
""",
    """    selectedTimestamp: Long?,
    lowerZonesPending: Boolean,
    lowerZonesFlashToken: Int,
    temporalPageSyncToken: Int,
    temporalPageSyncCenter: Long?,
    onLowerZonesInteractionStart: () -> Unit,
""",
    "overview sync signature",
)

t = replace_once(
    t,
    """    onLowerZonesInteractionCancel: () -> Unit,
    onLowerZonesCommit: () -> Unit,
    onCascadeRangesChanged: (LongRange, LongRange) -> Unit,
""",
    """    onLowerZonesInteractionCancel: () -> Unit,
    onLowerZonesCommit: () -> Unit,
    onTemporalPageRequest: (TemporalPageDirection, LongRange) -> Unit,
    onCascadeRangesChanged: (LongRange, LongRange) -> Unit,
""",
    "overview page signature",
)

# ---------------------------------------------------------------------------
# When paging comes from level 3/4, reposition the two upper selector centers.
# This effect runs before the delayed range propagation can fire on stale bounds.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """                val previewFrom = if (previewSpan >= wideSpan) wideFrom else effectiveCenter - previewSpan / 2L
                val previewTo = if (previewSpan >= wideSpan) wideTo else previewFrom + previewSpan
                val previewWindow = previewFrom..previewTo

                // Les déplacements sont très fréquents au doigt : on attend un bref repos avant
""",
    """                val previewFrom = if (previewSpan >= wideSpan) wideFrom else effectiveCenter - previewSpan / 2L
                val previewTo = if (previewSpan >= wideSpan) wideTo else previewFrom + previewSpan
                val previewWindow = previewFrom..previewTo

                LaunchedEffect(temporalPageSyncToken, temporalPageSyncCenter) {
                    if (temporalPageSyncToken > 0) {
                        temporalPageSyncCenter?.let { target ->
                            secondBandDraftCenter = null
                            val syncedWideCenter = clampCenter(target, wideSpan)
                            wideCenter = syncedWideCenter
                            val syncedWideFrom = if (wideSpan >= fullSpan) bounds.first
                                else syncedWideCenter - wideSpan / 2L
                            val syncedWideTo = if (wideSpan >= fullSpan) bounds.last
                                else syncedWideFrom + wideSpan
                            previewCenter = clampCenterToRange(
                                target,
                                previewSpan,
                                syncedWideFrom..syncedWideTo
                            )
                        }
                    }
                }

                // Les déplacements sont très fréquents au doigt : on attend un bref repos avant
""",
    "top navigators follow lower page",
)

# ---------------------------------------------------------------------------
# Compute page availability for level 3. A page arrow is shown only when the
# detailed RAW window has actually reached the corresponding edge of level 3.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """                val navigatorDim = MaterialTheme.colorScheme.scrim.copy(alpha = 0.07f)

                // v0.21.4 : navigation = température extérieure uniquement.
""",
    """                val navigatorDim = MaterialTheme.colorScheme.scrim.copy(alpha = 0.07f)
                val thirdLevelEdgeTolerance = viewBounds?.let {
                    maxOf(
                        60L * 60L * 1000L,
                        minOf(12L * 60L * 60L * 1000L, (it.last - it.first).coerceAtLeast(1L) / 20L)
                    )
                } ?: (60L * 60L * 1000L)
                val thirdLevelCanPagePrevious = !lowerZonesPending && viewBounds != null &&
                    viewBounds.first <= previewFrom + thirdLevelEdgeTolerance &&
                    previewFrom > bounds.first
                val thirdLevelCanPageNext = !lowerZonesPending && viewBounds != null &&
                    viewBounds.last >= previewTo - thirdLevelEdgeTolerance &&
                    previewTo < bounds.last

                // v0.21.4 : navigation = température extérieure uniquement.
""",
    "level 3 edge availability",
)

# ---------------------------------------------------------------------------
# Put explicit arrows on level 3, above the frozen/flash layer only while idle.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """                PendingCascadeOverlay(
                    pending = lowerZonesPending,
                    flashToken = lowerZonesFlashToken,
                    modifier = Modifier.fillMaxSize()
                )
                }

                val pendingRange = rangeStart?.let { a ->
""",
    """                PendingCascadeOverlay(
                    pending = lowerZonesPending,
                    flashToken = lowerZonesFlashToken,
                    modifier = Modifier.fillMaxSize()
                )
                if (!lowerZonesPending) {
                    TemporalPageArrows(
                        showPrevious = thirdLevelCanPagePrevious,
                        showNext = thirdLevelCanPageNext,
                        onPrevious = {
                            onTemporalPageRequest(TemporalPageDirection.PREVIOUS, previewWindow)
                        },
                        onNext = {
                            onTemporalPageRequest(TemporalPageDirection.NEXT, previewWindow)
                        },
                        modifier = Modifier.fillMaxSize()
                    )
                }
                }

                val pendingRange = rangeStart?.let { a ->
""",
    "level 3 page arrows",
)

# ---------------------------------------------------------------------------
# Extend ChartCard + wrap chart with arrows.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """    styleTick: Long,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit,
""",
    """    styleTick: Long,
    selectedTimestamp: Long?,
    canPageBackward: Boolean,
    canPageForward: Boolean,
    onPageBackward: () -> Unit,
    onPageForward: () -> Unit,
    onSelectTimestamp: (Long) -> Unit,
""",
    "chart card signature",
)

t = replace_once(
    t,
    """            } else {
                InteractiveChart(
                    modifier = Modifier.fillMaxWidth().height(390.dp),
                    sensors = sensors,
""",
    """            } else {
                Box(Modifier.fillMaxWidth().height(390.dp)) {
                InteractiveChart(
                    modifier = Modifier.fillMaxSize(),
                    sensors = sensors,
""",
    "chart box open",
)

t = replace_once(
    t,
    """                    selectedTimestamp = selectedTimestamp,
                    resetKey = resetKey,
                    onSelectTimestamp = onSelectTimestamp,
""",
    """                    selectedTimestamp = selectedTimestamp,
                    resetKey = resetKey,
                    canPageBackward = canPageBackward,
                    canPageForward = canPageForward,
                    onPageBackward = onPageBackward,
                    onPageForward = onPageForward,
                    onSelectTimestamp = onSelectTimestamp,
""",
    "interactive chart paging args",
)

t = replace_once(
    t,
    """                    onRequestAnnotation = onRequestAnnotation,
                    onRequestZoom = onRequestZoom
                )
            }
        }
""",
    """                    onRequestAnnotation = onRequestAnnotation,
                    onRequestZoom = onRequestZoom
                )
                TemporalPageArrows(
                    showPrevious = canPageBackward,
                    showNext = canPageForward,
                    onPrevious = onPageBackward,
                    onNext = onPageForward,
                    modifier = Modifier.fillMaxSize()
                )
                }
            }
        }
""",
    "chart box arrows",
)

# ---------------------------------------------------------------------------
# Interactive chart gets a deliberate edge-push trigger. Reaching the stop only
# shows the arrow; paging requires click OR ~46dp continued push beyond the stop.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """    selectedTimestamp: Long?,
    resetKey: Int,
    onSelectTimestamp: (Long) -> Unit,
""",
    """    selectedTimestamp: Long?,
    resetKey: Int,
    canPageBackward: Boolean,
    canPageForward: Boolean,
    onPageBackward: () -> Unit,
    onPageForward: () -> Unit,
    onSelectTimestamp: (Long) -> Unit,
""",
    "interactive chart signature",
)

t = replace_once(
    t,
    """    var zoom by remember(resetKey, from, to) { mutableFloatStateOf(1f) }
    var center by remember(resetKey, from, to) { mutableFloatStateOf(0.5f) }
    var sightTemperature by remember(resetKey, from, to) { mutableStateOf<Double?>(null) }
""",
    """    var zoom by remember(resetKey, from, to) { mutableFloatStateOf(1f) }
    var center by remember(resetKey, from, to) { mutableFloatStateOf(0.5f) }
    var sightTemperature by remember(resetKey, from, to) { mutableStateOf<Double?>(null) }
    var edgePushDistancePx by remember(resetKey, from, to) { mutableFloatStateOf(0f) }
    var edgePushDirection by remember(resetKey, from, to) { mutableIntStateOf(0) }
    var edgePushTriggered by remember(resetKey, from, to) { mutableStateOf(false) }
""",
    "chart edge push state",
)

old_pan = """                    } else {
                        val oldVisible = 1f / zoom
                        val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)
                        zoom = newZoom
                        val visible = 1f / zoom
                        center = (center - (pan.x / size.width.toFloat()) * oldVisible)
                            .coerceIn(visible / 2f, 1f - visible / 2f)
                    }
"""
new_pan = """                    } else {
                        val oldVisible = 1f / zoom
                        val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)
                        zoom = newZoom
                        val visible = 1f / zoom
                        val minimumCenter = visible / 2f
                        val maximumCenter = 1f - visible / 2f
                        val requestedCenter = center - (pan.x / size.width.toFloat()) * oldVisible
                        val clampedCenter = requestedCenter.coerceIn(minimumCenter, maximumCenter)

                        val deliberatePan = zoomChange in 0.985f..1.015f
                        val pushDirection = when {
                            deliberatePan && requestedCenter < minimumCenter && pan.x > 0f && canPageBackward -> -1
                            deliberatePan && requestedCenter > maximumCenter && pan.x < 0f && canPageForward -> 1
                            else -> 0
                        }
                        if (pushDirection != 0) {
                            if (edgePushDirection != pushDirection) {
                                edgePushDirection = pushDirection
                                edgePushDistancePx = 0f
                                edgePushTriggered = false
                            }
                            edgePushDistancePx += kotlin.math.abs(pan.x)
                            if (!edgePushTriggered && edgePushDistancePx >= 46.dp.toPx()) {
                                edgePushTriggered = true
                                if (pushDirection < 0) onPageBackward() else onPageForward()
                            }
                        } else if (kotlin.math.abs(pan.x) > 0.5f) {
                            edgePushDirection = 0
                            edgePushDistancePx = 0f
                            edgePushTriggered = false
                        }
                        center = clampedCenter
                    }
"""
t = replace_once(t, old_pan, new_pan, "deliberate edge push")

main.write_text(t, encoding="utf-8")

# Version bump.
gradle = Path("app/build.gradle.kts")
g = gradle.read_text(encoding="utf-8")ng = replace_once(
    g,
    '        versionCode = 50\n        versionName = "0.21.4"\n',
    '        versionCode = 51\n        versionName = "0.21.5"\n',
    "version bump",
)
gradle.write_text(g, encoding="utf-8")

print("FabData v0.21.5 temporal page navigation patch applied")
