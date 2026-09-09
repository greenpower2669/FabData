from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


p = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
t = p.read_text(encoding="utf-8")

# Hoist the two lower LOD query windows. Only the giga band is allowed to stay global.
t = replace_once(
    t,
    """    var globalBounds by remember { mutableStateOf<LongRange?>(null) }\n    var viewBounds by remember { mutableStateOf<LongRange?>(null) }\n    var preset by rememberSaveable { mutableStateOf(TimePreset.TWO_DAYS) }\n""",
    """    var globalBounds by remember { mutableStateOf<LongRange?>(null) }\n    var viewBounds by remember { mutableStateOf<LongRange?>(null) }\n    var wideOverviewRange by remember { mutableStateOf<LongRange?>(null) }\n    var explorationOverviewRange by remember { mutableStateOf<LongRange?>(null) }\n    var preset by rememberSaveable { mutableStateOf(TimePreset.TWO_DAYS) }\n""",
    "cascade state",
)

t = replace_once(
    t,
    "LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs) {",
    "LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {",
    "reload keys",
)

# Compute safe default nested windows before the UI has emitted its first cursor positions.
t = replace_once(
    t,
    """            } else {\n                val samples = s.associate { sensor ->\n""",
    """            } else {\n                fun centeredRange(center: Long, requestedSpan: Long, outer: LongRange): LongRange {\n                    val outerSpan = (outer.last - outer.first).coerceAtLeast(1L)\n                    val span = minOf(requestedSpan.coerceAtLeast(1L), outerSpan)\n                    if (span >= outerSpan) return outer\n                    val half = span / 2L\n                    var start = center - half\n                    var end = start + span\n                    if (start < outer.first) {\n                        start = outer.first\n                        end = start + span\n                    }\n                    if (end > outer.last) {\n                        end = outer.last\n                        start = end - span\n                    }\n                    return start..end\n                }\n                fun clipRange(candidate: LongRange, outer: LongRange): LongRange {\n                    val start = maxOf(candidate.first, outer.first)\n                    val end = minOf(candidate.last, outer.last)\n                    return if (end > start) start..end else outer\n                }\n                val allSpan = (all.last - all.first).coerceAtLeast(1L)\n                val detailCenter = chosen.first + (chosen.last - chosen.first) / 2L\n                val defaultExplorationSpan = minOf(PreviewPreset.M6.spanMs, allSpan)\n                val defaultExploration = centeredRange(detailCenter, defaultExplorationSpan, all)\n                val defaultWideSpan = minOf(\n                    allSpan,\n                    maxOf(defaultExplorationSpan * 6L, PreviewPreset.M6.spanMs)\n                )\n                val defaultWide = centeredRange(detailCenter, defaultWideSpan, all)\n                val navigatorScope = clipRange(wideOverviewRange ?: defaultWide, all)\n                val explorationScope = clipRange(explorationOverviewRange ?: defaultExploration, navigatorScope)\n\n                val samples = s.associate { sensor ->\n""",
    "default cascade ranges",
)

old_lod = """                fun physicalLod(bucketMs: Long): Map<Long, List<SamplePoint>> =\n                    s.associate { sensor ->\n                        sensor.id to db.querySamplesLod(sensor.id, all.first, all.last, bucketMs)\n                    }\n                fun weatherLod(bucketMs: Long): List<SamplePoint> =\n                    weatherReferenceStore.queryLod(\n                        selectedWeatherReference.key, all.first, all.last, bucketMs\n                    ).map {\n                        SamplePoint(\n                            LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity,\n                            it.source, it.confidence\n                        )\n                    }\n\n                // Pyramide LOD : les RAW restent dans SQLite. Chaque bandeau ne reçoit\n                // que sa résolution dédiée, au lieu de charger tout l'historique puis réduire.\n                val gigaOverview = physicalLod(OVERVIEW_LOD_MONTH_MS) +\n                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_MONTH_MS))\n                val navigatorOverview = physicalLod(OVERVIEW_LOD_DAY_MS) +\n                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS))\n                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS) +\n                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS))\n"""
new_lod = """                fun physicalLod(bucketMs: Long, range: LongRange): Map<Long, List<SamplePoint>> =\n                    s.associate { sensor ->\n                        sensor.id to db.querySamplesLod(sensor.id, range.first, range.last, bucketMs)\n                    }\n                fun weatherLod(bucketMs: Long, range: LongRange): List<SamplePoint> =\n                    weatherReferenceStore.queryLod(\n                        selectedWeatherReference.key, range.first, range.last, bucketMs\n                    ).map {\n                        SamplePoint(\n                            LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity,\n                            it.source, it.confidence\n                        )\n                    }\n\n                // V0.21.1 : vraie cascade. Seul le giga touche tout l'historique.\n                // Le niveau jour ne lit que la fenêtre large ; le niveau 6 h uniquement\n                // la fenêtre d'exploration. Le graphe détaillé reste limité à chosen.\n                val gigaOverview = physicalLod(OVERVIEW_LOD_MONTH_MS, all) +\n                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_MONTH_MS, all))\n                val navigatorOverview = physicalLod(OVERVIEW_LOD_DAY_MS, navigatorScope) +\n                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS, navigatorScope))\n                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS, explorationScope) +\n                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS, explorationScope))\n"""
t = replace_once(t, old_lod, new_lod, "scoped LOD queries")

old_inertia = """                fun withInertiaLod(\n                    base: Map<Long, List<SamplePoint>>,\n                    bucketMs: Long\n                ): Map<Long, List<SamplePoint>> {\n                    val model = trainedModel ?: return base\n                    val stored = inertiaHistoryStore.queryLod(\n                        selectedWeatherReference.key,\n                        model.sensorId,\n                        model.stableSignature(),\n                        all.first,\n                        all.last,\n                        bucketMs\n                    )\n                    val recent = inertia?.surfacePoints.orEmpty()\n                        .groupBy { (it.timestamp / bucketMs) * bucketMs }\n"""
new_inertia = """                fun withInertiaLod(\n                    base: Map<Long, List<SamplePoint>>,\n                    bucketMs: Long,\n                    range: LongRange\n                ): Map<Long, List<SamplePoint>> {\n                    val model = trainedModel ?: return base\n                    val stored = inertiaHistoryStore.queryLod(\n                        selectedWeatherReference.key,\n                        model.sensorId,\n                        model.stableSignature(),\n                        range.first,\n                        range.last,\n                        bucketMs\n                    )\n                    val recent = inertia?.surfacePoints.orEmpty()\n                        .filter { it.timestamp in range }\n                        .groupBy { (it.timestamp / bucketMs) * bucketMs }\n"""
t = replace_once(t, old_inertia, new_inertia, "scoped inertia LOD")

t = replace_once(
    t,
    """                    withInertiaLod(gigaOverview, OVERVIEW_LOD_MONTH_MS),\n                    withInertiaLod(navigatorOverview, OVERVIEW_LOD_DAY_MS),\n                    withInertiaLod(explorationOverview, OVERVIEW_LOD_6H_MS),\n""",
    """                    withInertiaLod(gigaOverview, OVERVIEW_LOD_MONTH_MS, all),\n                    withInertiaLod(navigatorOverview, OVERVIEW_LOD_DAY_MS, navigatorScope),\n                    withInertiaLod(explorationOverview, OVERVIEW_LOD_6H_MS, explorationScope),\n""",
    "inertia calls",
)

# UI callback hoists the nested windows after a short debounce inside HistoryOverviewCard.
t = replace_once(
    t,
    """                        viewBounds = viewBounds,\n                        selectedTimestamp = selectedTimestamp,\n                        onSelectTimestamp = { ts ->\n""",
    """                        viewBounds = viewBounds,\n                        selectedTimestamp = selectedTimestamp,\n                        onCascadeRangesChanged = { wide, exploration ->\n                            if (wideOverviewRange != wide) wideOverviewRange = wide\n                            if (explorationOverviewRange != exploration) explorationOverviewRange = exploration\n                        },\n                        onSelectTimestamp = { ts ->\n""",
    "cascade callback call",
)

t = replace_once(
    t,
    """    viewBounds: LongRange?,\n    selectedTimestamp: Long?,\n    onSelectTimestamp: (Long) -> Unit,\n""",
    """    viewBounds: LongRange?,\n    selectedTimestamp: Long?,\n    onCascadeRangesChanged: (LongRange, LongRange) -> Unit,\n    onSelectTimestamp: (Long) -> Unit,\n""",
    "cascade callback signature",
)

t = replace_once(
    t,
    '"Giga = mois · navigation = jours · exploration = 6 h · détail = RAW",',
    '"Global = mois · zoom large = jours · sélection = 6 h · détail = RAW",',
    "overview title",
)

# Separate center for the giga window and the nested exploration window.
t = replace_once(
    t,
    """                var previewCenter by remember(bounds.first, bounds.last) {\n                    mutableStateOf(\n                        viewBounds?.let { it.first + (it.last - it.first) / 2L }\n                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)\n                    )\n                }\n                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }\n""",
    """                var previewCenter by remember(bounds.first, bounds.last) {\n                    mutableStateOf(\n                        viewBounds?.let { it.first + (it.last - it.first) / 2L }\n                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)\n                    )\n                }\n                var wideCenter by remember(bounds.first, bounds.last) {\n                    mutableStateOf(\n                        viewBounds?.let { it.first + (it.last - it.first) / 2L }\n                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)\n                    )\n                }\n                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }\n""",
    "wide center state",
)

# Curve chooser must not lose a curve just because the currently nested 6 h window has no point.
t = replace_once(
    t,
    """                val availableBandSensorIds = remember(sensors, sampleMap) {\n                    sensors.filter { sampleMap[it.id].orEmpty().isNotEmpty() }.map { it.id }.toSet()\n                }\n""",
    """                val availableBandSensorIds = remember(sensors, gigaSampleMap, navigatorSampleMap, sampleMap) {\n                    sensors.filter { sensor ->\n                        gigaSampleMap[sensor.id].orEmpty().isNotEmpty() ||\n                            navigatorSampleMap[sensor.id].orEmpty().isNotEmpty() ||\n                            sampleMap[sensor.id].orEmpty().isNotEmpty()\n                    }.map { it.id }.toSet()\n                }\n""",
    "band curve availability",
)

# Recenter both levels when the user explicitly changes the exploration period preset.
t = replace_once(
    t,
    """                                previewPreset = item\n                                previewZoom = 1f\n                                previewCenter = (selectedTimestamp\n                                    ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }\n                                    ?: previewCenter).coerceIn(bounds.first, bounds.last)\n""",
    """                                previewPreset = item\n                                previewZoom = 1f\n                                val targetCenter = (selectedTimestamp\n                                    ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }\n                                    ?: previewCenter).coerceIn(bounds.first, bounds.last)\n                                previewCenter = targetCenter\n                                wideCenter = targetCenter\n""",
    "preset recenter",
)

old_ranges = """                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)\n                val maxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)\n                val mainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }\n                    ?: (24L * 60L * 60L * 1000L)\n                val minSpan = minOf(maxSpan, maxOf(6L * 60L * 60L * 1000L, mainSpan))\n                val maxZoom = (maxSpan.toDouble() / minSpan.toDouble()).toFloat().coerceAtLeast(1f)\n                val effectiveZoom = previewZoom.coerceIn(1f, maxZoom)\n                val previewSpan = (maxSpan.toDouble() / effectiveZoom.toDouble()).toLong()\n                    .coerceIn(minSpan, maxSpan)\n\n                fun clampCenter(value: Long, span: Long): Long {\n                    if (span >= fullSpan) return bounds.first + fullSpan / 2L\n                    val half = span / 2L\n                    return value.coerceIn(bounds.first + half, bounds.last - (span - half))\n                }\n\n                val effectiveCenter = clampCenter(previewCenter, previewSpan)\n                val previewFrom = if (previewSpan >= fullSpan) bounds.first else effectiveCenter - previewSpan / 2L\n                val previewTo = if (previewSpan >= fullSpan) bounds.last else previewFrom + previewSpan\n                val previewWindow = previewFrom..previewTo\n"""
new_ranges = """                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)\n                val maxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)\n                val mainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }\n                    ?: (24L * 60L * 60L * 1000L)\n                val minSpan = minOf(maxSpan, maxOf(6L * 60L * 60L * 1000L, mainSpan))\n                val maxZoom = (maxSpan.toDouble() / minSpan.toDouble()).toFloat().coerceAtLeast(1f)\n                val effectiveZoom = previewZoom.coerceIn(1f, maxZoom)\n                val previewSpan = (maxSpan.toDouble() / effectiveZoom.toDouble()).toLong()\n                    .coerceIn(minSpan, maxSpan)\n\n                fun clampCenter(value: Long, span: Long): Long {\n                    if (span >= fullSpan) return bounds.first + fullSpan / 2L\n                    val half = span / 2L\n                    return value.coerceIn(bounds.first + half, bounds.last - (span - half))\n                }\n                fun clampCenterToRange(value: Long, span: Long, outer: LongRange): Long {\n                    val outerSpan = (outer.last - outer.first).coerceAtLeast(1L)\n                    if (span >= outerSpan) return outer.first + outerSpan / 2L\n                    val half = span / 2L\n                    return value.coerceIn(outer.first + half, outer.last - (span - half))\n                }\n\n                // Niveau 1 : le giga est le seul historique complet. Sa fenêtre large\n                // vaut environ 6 fois la fenêtre d'exploration (minimum 6 mois).\n                val minimumWideSpan = minOf(fullSpan, PreviewPreset.M6.spanMs)\n                val wideSpan = minOf(fullSpan, maxOf(previewSpan * 6L, minimumWideSpan))\n                    .coerceAtLeast(previewSpan)\n                val effectiveWideCenter = clampCenter(wideCenter, wideSpan)\n                val wideFrom = if (wideSpan >= fullSpan) bounds.first else effectiveWideCenter - wideSpan / 2L\n                val wideTo = if (wideSpan >= fullSpan) bounds.last else wideFrom + wideSpan\n                val wideWindow = wideFrom..wideTo\n\n                // Niveau 2 -> 3 : la fenêtre d'exploration est contrainte à la fenêtre large.\n                val effectiveCenter = clampCenterToRange(previewCenter, previewSpan, wideWindow)\n                val previewFrom = if (previewSpan >= wideSpan) wideFrom else effectiveCenter - previewSpan / 2L\n                val previewTo = if (previewSpan >= wideSpan) wideTo else previewFrom + previewSpan\n                val previewWindow = previewFrom..previewTo\n\n                // Les déplacements sont très fréquents au doigt : on attend un bref repos avant\n                // de lancer les requêtes SQLite du niveau inférieur.\n                LaunchedEffect(wideFrom, wideTo, previewFrom, previewTo) {\n                    delay(140L)\n                    onCascadeRangesChanged(wideWindow, previewWindow)\n                }\n                LaunchedEffect(wideFrom, wideTo, previewSpan) {\n                    val clamped = clampCenterToRange(previewCenter, previewSpan, wideWindow)\n                    if (previewCenter != clamped) previewCenter = clamped\n                }\n"""
t = replace_once(t, old_ranges, new_ranges, "nested window math")

# Navigator points are no longer global: they are the large window only.
t = replace_once(
    t,
    """                val navigatorSensorPoints = remember(navigatorSampleMap, sensors, bandSensorIds, bounds.first, bounds.last) {\n                    sensors.filter { it.id in bandSensorIds }.associate { sensor ->\n                        sensor.id to navigatorSampleMap[sensor.id].orEmpty()\n                            .filter { it.timestamp in bounds }\n                            .sortedBy { it.timestamp }\n                    }\n                }\n""",
    """                val navigatorSensorPoints = remember(navigatorSampleMap, sensors, bandSensorIds, wideFrom, wideTo) {\n                    sensors.filter { it.id in bandSensorIds }.associate { sensor ->\n                        sensor.id to navigatorSampleMap[sensor.id].orEmpty()\n                            .filter { it.timestamp in wideWindow }\n                            .sortedBy { it.timestamp }\n                    }\n                }\n""",
    "navigator scoped points",
)

# Giga interaction controls only the wide window.
t = replace_once(
    t,
    """                        .pointerInput(bounds.first, bounds.last, previewSpan) {\n                            detectDragGestures { change, dragAmount ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()\n                                previewCenter = clampCenter(previewCenter + deltaTs, previewSpan)\n                                change.consume()\n                            }\n                        }\n                        .pointerInput(bounds.first, bounds.last, previewSpan) {\n                            detectTapGestures(onTap = { p ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val fraction = (p.x / width).coerceIn(0f, 1f)\n                                previewCenter = clampCenter(\n                                    bounds.first + (fullSpan * fraction).toLong(),\n                                    previewSpan\n                                )\n                            })\n                        }\n""",
    """                        .pointerInput(bounds.first, bounds.last, wideSpan) {\n                            detectDragGestures { change, dragAmount ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()\n                                wideCenter = clampCenter(wideCenter + deltaTs, wideSpan)\n                                change.consume()\n                            }\n                        }\n                        .pointerInput(bounds.first, bounds.last, wideSpan) {\n                            detectTapGestures(onTap = { p ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val fraction = (p.x / width).coerceIn(0f, 1f)\n                                wideCenter = clampCenter(\n                                    bounds.first + (fullSpan * fraction).toLong(),\n                                    wideSpan\n                                )\n                            })\n                        }\n""",
    "giga controls wide cursor",
)

# First left/right rectangle after the giga paths is the wide window, not the exploration window.
t = replace_once(
    t,
    """                    val left = (((previewFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(0f, size.width)\n                    val right = (((previewTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(left, size.width)\n""",
    """                    val left = (((wideFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(0f, size.width)\n                    val right = (((wideTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(left, size.width)\n""",
    "giga highlighted window",
)

t = replace_once(
    t,
    '"Navigation globale · LOD jour · glisse la fenêtre",',
    '"Zoom large · LOD jour · glisse la fenêtre de sélection",',
    "navigator label",
)

# Navigator interaction is relative to the wide window and moves only the exploration cursor.
t = replace_once(
    t,
    """                        .pointerInput(bounds.first, bounds.last, previewSpan) {\n                            detectDragGestures { change, dragAmount ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()\n                                previewCenter = clampCenter(previewCenter + deltaTs, previewSpan)\n                                change.consume()\n                            }\n                        }\n                        .pointerInput(bounds.first, bounds.last, previewSpan) {\n                            detectTapGestures(onTap = { p ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val fraction = (p.x / width).coerceIn(0f, 1f)\n                                val target = bounds.first + (fullSpan * fraction).toLong()\n                                previewCenter = clampCenter(target, previewSpan)\n                            })\n                        }\n""",
    """                        .pointerInput(wideFrom, wideTo, previewSpan) {\n                            detectDragGestures { change, dragAmount ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val deltaTs = ((dragAmount.x / width) * wideSpan.toDouble()).toLong()\n                                previewCenter = clampCenterToRange(previewCenter + deltaTs, previewSpan, wideWindow)\n                                change.consume()\n                            }\n                        }\n                        .pointerInput(wideFrom, wideTo, previewSpan) {\n                            detectTapGestures(onTap = { p ->\n                                val width = size.width.toFloat().coerceAtLeast(1f)\n                                val fraction = (p.x / width).coerceIn(0f, 1f)\n                                val target = wideFrom + (wideSpan * fraction).toLong()\n                                previewCenter = clampCenterToRange(target, previewSpan, wideWindow)\n                            })\n                        }\n""",
    "navigator controls exploration cursor",
)

# Navigator plotting coordinates and hole threshold are local to the wide window.
t = replace_once(
    t,
    """                                val navigatorGapLimit = maxOf(\n                                    12L * 60L * 60L * 1000L,\n                                    fullSpan / 120L\n                                )\n                                points.forEach { point ->\n                                    val x = (((point.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)\n                                        .coerceIn(0f, size.width)\n""",
    """                                val navigatorGapLimit = maxOf(\n                                    12L * 60L * 60L * 1000L,\n                                    wideSpan / 120L\n                                )\n                                points.forEach { point ->\n                                    val x = (((point.timestamp - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)\n                                        .coerceIn(0f, size.width)\n""",
    "navigator local coordinates",
)

# The second left/right rectangle belongs to the navigator: map preview inside wide window.
t = replace_once(
    t,
    """                    val left = (((previewFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(0f, size.width)\n                    val right = (((previewTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(left, size.width)\n""",
    """                    val left = (((previewFrom - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(0f, size.width)\n                    val right = (((previewTo - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)\n                        .coerceIn(left, size.width)\n""",
    "navigator highlighted selection",
)

# Navigator date labels now describe only its own large window.
t = replace_once(
    t,
    """                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {\n                    Text(formatDateTime(bounds.first), style = MaterialTheme.typography.labelSmall)\n                    Text("historique complet", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)\n                    Text(formatDateTime(bounds.last), style = MaterialTheme.typography.labelSmall)\n                }\n""",
    """                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {\n                    Text(formatDateTime(wideFrom), style = MaterialTheme.typography.labelSmall)\n                    Text("zoom large", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)\n                    Text(formatDateTime(wideTo), style = MaterialTheme.typography.labelSmall)\n                }\n""",
    "navigator labels",
)

# Pinch/pan of the exploration band must remain inside its parent wide window.
t = replace_once(
    t,
    "val oldCenter = clampCenter(previewCenter, oldSpan)",
    "val oldCenter = clampCenterToRange(previewCenter, oldSpan, wideWindow)",
    "exploration old center clamp",
)
t = replace_once(
    t,
    "val oldFrom = if (oldSpan >= fullSpan) bounds.first else oldCenter - oldSpan / 2L",
    "val oldFrom = if (oldSpan >= wideSpan) wideFrom else oldCenter - oldSpan / 2L",
    "exploration old from",
)
t = replace_once(
    t,
    "previewCenter = clampCenter(zoomAnchoredCenter + panShift, newSpan)",
    "previewCenter = clampCenterToRange(zoomAnchoredCenter + panShift, newSpan, wideWindow)",
    "exploration new center clamp",
)

# Make the semantic role of the third level explicit in the UI.
t = replace_once(
    t,
    """                if (minPoint != null && maxPoint != null) {\n""",
    """                Text(\n                    "Sélection / exploration · LOD 6 h · seules ces données alimentent ce bandeau",\n                    style = MaterialTheme.typography.labelSmall,\n                    color = MaterialTheme.colorScheme.onSurfaceVariant\n                )\n\n                if (minPoint != null && maxPoint != null) {\n""",
    "exploration label",
)

p.write_text(t, encoding="utf-8")

# Version bump.
g = Path("app/build.gradle.kts")
s = g.read_text(encoding="utf-8")ns_old = '        versionCode = 46\n        versionName = "0.21.0"'
if ns_old not in s:
    raise SystemExit("missing version anchor")
s = s.replace(ns_old, '        versionCode = 47\n        versionName = "0.21.1"', 1)
g.write_text(s, encoding="utf-8")
