from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


p = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
t = p.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Animation / soft veil imports.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    "import androidx.activity.result.contract.ActivityResultContracts\n",
    "import androidx.activity.result.contract.ActivityResultContracts\n"
    "import androidx.compose.animation.core.Animatable\n"
    "import androidx.compose.animation.core.animateFloatAsState\n"
    "import androidx.compose.animation.core.tween\n",
    "animation imports",
)
t = replace_once(
    t,
    "import androidx.compose.ui.graphics.Color\n",
    "import androidx.compose.ui.graphics.Brush\nimport androidx.compose.ui.graphics.Color\n",
    "brush import",
)

# ---------------------------------------------------------------------------
# Top navigation levels become weather-only at the data layer.
# Global = daily reference weather, wide zoom = 6h reference weather.
# No physical sensor / inertia SQL is executed for levels 1 and 2 anymore.
# ---------------------------------------------------------------------------
old = """                // V0.21.1 : vraie cascade. Seul le giga touche tout l'historique.
                // Le niveau jour ne lit que la fenêtre large ; le niveau 6 h uniquement
                // la fenêtre d'exploration. Le graphe détaillé reste limité à chosen.
                FabOperationRegistry.update(reloadOperation, "Global · LOD mois…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val gigaOverview = physicalLod(OVERVIEW_LOD_MONTH_MS, all) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_MONTH_MS, all))

                FabOperationRegistry.update(reloadOperation, "Zoom large · LOD jour…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val navigatorOverview = physicalLod(OVERVIEW_LOD_DAY_MS, navigatorScope) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS, navigatorScope))

                FabOperationRegistry.update(reloadOperation, "Sélection · LOD 6 h…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS, explorationScope) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS, explorationScope))
"""
new = """                // v0.21.4 : les deux étages de navigation du haut sont météo pure.
                // Ils ne chargent ni thermomètres physiques ni sol inertiel : leur seule
                // mission est de répondre à « où regarder dans le temps ? ».
                FabOperationRegistry.update(reloadOperation, "Global météo · LOD jour…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val gigaOverview = mapOf(
                    LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS, all)
                )

                FabOperationRegistry.update(reloadOperation, "Zoom large météo · LOD 6 h…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val navigatorOverview = mapOf(
                    LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS, navigatorScope)
                )

                // A partir du troisième niveau seulement, on réintroduit toutes les
                // courbes d'analyse et le sol inertiel.
                FabOperationRegistry.update(reloadOperation, "Analyse · LOD 6 h…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS, explorationScope) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS, explorationScope))
"""
t = replace_once(t, old, new, "weather-only upper data levels")

t = replace_once(
    t,
    """                    withInertiaLod(gigaOverview, OVERVIEW_LOD_MONTH_MS, all),
                    withInertiaLod(navigatorOverview, OVERVIEW_LOD_DAY_MS, navigatorScope),
                    withInertiaLod(explorationOverview, OVERVIEW_LOD_6H_MS, explorationScope),
""",
    """                    gigaOverview,
                    navigatorOverview,
                    withInertiaLod(explorationOverview, OVERVIEW_LOD_6H_MS, explorationScope),
""",
    "no inertia in upper nav maps",
)

# ---------------------------------------------------------------------------
# Parent state keeps the two lower zones veiled from drag start until the one
# post-release reload has actually completed. Flash starts only after fresh data.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    "    var busy by remember { mutableStateOf(false) }\n",
    """    var busy by remember { mutableStateOf(false) }
    var lowerCascadeVeil by remember { mutableStateOf(false) }
    var lowerCascadeAwaitingReload by remember { mutableStateOf(false) }
    var lowerCascadeFlashToken by remember { mutableIntStateOf(0) }
""",
    "cascade transition state",
)

t = replace_once(
    t,
    """        allAnnotations = loaded.allAnnotations

        loaded.viewBounds?.let { bounds ->
""",
    """        allAnnotations = loaded.allAnnotations

        // Le voile ne disparaît qu'une fois LE rechargement déclenché au relâchement
        // réellement terminé. Le flash doux révèle alors les nouvelles courbes.
        if (lowerCascadeAwaitingReload) {
            lowerCascadeAwaitingReload = false
            lowerCascadeVeil = false
            lowerCascadeFlashToken++
        }

        loaded.viewBounds?.let { bounds ->
""",
    "finish lower-zone transition after reload",
)

# ---------------------------------------------------------------------------
# Reusable helpers: outside-weather merge, temperature-coded selector, explicit
# missing-weather ranges, and grey smoke/light sweep overlay.
# ---------------------------------------------------------------------------
helper_anchor = "@Composable\nprivate fun HistoryOverviewCard(\n"
if helper_anchor not in t:
    raise SystemExit("missing patch anchor: HistoryOverviewCard helper insertion")
helpers = r'''private fun navigationWeatherPoints(sampleMap: Map<Long, List<SamplePoint>>): List<SamplePoint> =
    (sampleMap[WEATHER_OFFICIAL_SENSOR_ID].orEmpty() +
        sampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty())
        .groupBy { it.timestamp }
        .mapNotNull { (_, values) -> values.maxByOrNull { it.source.priority } }
        .sortedBy { it.timestamp }

private fun weatherTemperatureColor(temperature: Double?): Color {
    if (temperature == null || !temperature.isFinite()) return Color(0xFF73777F)
    val normalized = ((temperature + 10.0) / 45.0).coerceIn(0.0, 1.0).toFloat()
    val hue = 220f * (1f - normalized)
    return Color.hsv(hue, 0.72f, 0.88f)
}

private fun nearestWeatherTemperature(
    points: List<SamplePoint>,
    timestamp: Long,
    toleranceMs: Long
): Double? = points.minByOrNull { kotlin.math.abs(it.timestamp - timestamp) }
    ?.takeIf { kotlin.math.abs(it.timestamp - timestamp) <= toleranceMs }
    ?.temperature

private fun weatherMissingRanges(
    points: List<SamplePoint>,
    from: Long,
    to: Long,
    gapThresholdMs: Long
): List<LongRange> {
    if (to <= from) return emptyList()
    if (points.isEmpty()) return listOf(from..to)
    val sorted = points.filter { it.timestamp in from..to }.sortedBy { it.timestamp }
    if (sorted.isEmpty()) return listOf(from..to)
    val out = mutableListOf<LongRange>()
    if (sorted.first().timestamp - from > gapThresholdMs) {
        out += from..sorted.first().timestamp
    }
    sorted.zipWithNext().forEach { (a, b) ->
        if (b.timestamp - a.timestamp > gapThresholdMs) {
            val margin = gapThresholdMs / 3L
            val start = (a.timestamp + margin).coerceAtMost(b.timestamp)
            val end = (b.timestamp - margin).coerceAtLeast(start)
            if (end > start) out += start..end
        }
    }
    if (to - sorted.last().timestamp > gapThresholdMs) {
        out += sorted.last().timestamp..to
    }
    return out
}

@Composable
private fun PendingCascadeOverlay(
    pending: Boolean,
    flashToken: Int,
    modifier: Modifier = Modifier
) {
    val smokeAlpha by animateFloatAsState(
        targetValue = if (pending) 0.34f else 0f,
        animationSpec = tween(durationMillis = if (pending) 180 else 430),
        label = "cascade-smoke"
    )
    val flash = remember { Animatable(1.35f) }
    LaunchedEffect(flashToken) {
        if (flashToken > 0) {
            flash.snapTo(-0.28f)
            flash.animateTo(1.28f, animationSpec = tween(420))
        }
    }
    Canvas(modifier) {
        if (smokeAlpha > 0.002f) {
            drawRect(Color(0xFF6D727A).copy(alpha = smokeAlpha))
            val mist = Color.White.copy(alpha = smokeAlpha * 0.12f)
            drawCircle(mist, size.width * 0.24f, Offset(size.width * 0.18f, size.height * 0.38f))
            drawCircle(mist, size.width * 0.28f, Offset(size.width * 0.56f, size.height * 0.62f))
            drawCircle(mist, size.width * 0.20f, Offset(size.width * 0.88f, size.height * 0.32f))
        }
        val progress = flash.value
        if (flashToken > 0 && progress in -0.30f..1.30f) {
            val centerX = size.width * progress
            val half = maxOf(34.dp.toPx(), size.width * 0.09f)
            drawRect(
                brush = Brush.horizontalGradient(
                    colors = listOf(
                        Color.Transparent,
                        Color.White.copy(alpha = 0.08f),
                        Color.White.copy(alpha = 0.42f),
                        Color.White.copy(alpha = 0.08f),
                        Color.Transparent
                    ),
                    startX = centerX - half,
                    endX = centerX + half
                ),
                topLeft = Offset(centerX - half, 0f),
                size = androidx.compose.ui.geometry.Size(half * 2f, size.height)
            )
        }
    }
}

'''
t = t.replace(helper_anchor, helpers + helper_anchor, 1)

# ---------------------------------------------------------------------------
# HistoryOverviewCard receives the lower-zone transition state/callbacks.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """    selectedTimestamp: Long?,
    onCascadeRangesChanged: (LongRange, LongRange) -> Unit,
""",
    """    selectedTimestamp: Long?,
    lowerZonesPending: Boolean,
    lowerZonesFlashToken: Int,
    onLowerZonesInteractionStart: () -> Unit,
    onLowerZonesInteractionCancel: () -> Unit,
    onLowerZonesCommit: () -> Unit,
    onCascadeRangesChanged: (LongRange, LongRange) -> Unit,
""",
    "HistoryOverview transition parameters",
)

t = replace_once(
    t,
    """                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
""",
    """                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                // Position provisoire du sélecteur du bandeau 2. Tant qu'elle existe,
                // elle ne sort jamais du composable et ne déclenche aucune requête.
                var secondBandDraftCenter by remember { mutableStateOf<Long?>(null) }
""",
    "second band draft center",
)

# ---------------------------------------------------------------------------
# Move the whole work UI (period presets / curve choice / selection / help/tip)
# from above the navigator to immediately above level 3.
# ---------------------------------------------------------------------------
demo_marker = "                LaunchedEffect(demoOpen, demoReplayToken) {"
demo_pos = t.index(demo_marker)
controls_start = t.index(
    "                Row(\n                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),\n                    horizontalArrangement = Arrangement.spacedBy(4.dp)\n                ) {\n                    PreviewPreset.entries.forEach { item ->",
    demo_pos,
)
controls_end_marker = "                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)\n"
controls_end = t.index(controls_end_marker, controls_start)
controls_block = t[controls_start:controls_end]
t = t[:controls_start] + t[controls_end:]

# Rename chooser / alert while moving it.
controls_block = controls_block.replace(
    'Text("Courbes des bandeaux · ${bandSensorIds.size} sélectionnée(s)")',
    'Text("Courbes du bandeau d’analyse · ${bandSensorIds.size} sélectionnée(s)")',
)
controls_block = controls_block.replace(') { Text("! Astuce") }', ') { Text("! Alertes / astuce") }')
controls_block = (
    "                HorizontalDivider()\n"
    "                Text(\n"
    "                    \"Outils d’analyse de la période\",\n"
    "                    fontWeight = FontWeight.Bold,\n"
    "                    color = MaterialTheme.colorScheme.primary\n"
    "                )\n"
    "                Text(\n"
    "                    \"À partir d’ici : périodes, courbes, sélections, aide et alertes.\",\n"
    "                    style = MaterialTheme.typography.labelSmall,\n"
    "                    color = MaterialTheme.colorScheme.onSurfaceVariant\n"
    "                )\n" + controls_block +
    "                HorizontalDivider()\n"
)
third_level_marker = "                Text(\n                    \"Sélection / exploration · LOD 6 h · limitée par le bandeau du milieu\","
third_pos = t.index(third_level_marker)
t = t[:third_pos] + controls_block + t[third_pos:]

# ---------------------------------------------------------------------------
# Navigation data inside the card: upper two bands are ALWAYS reference weather.
# Level 3 keeps the user's curve chooser.
# ---------------------------------------------------------------------------
old = """                // Bandeau d'exploration DU bandeau d'exploration.
                // Il représente tout l'historique avec des points déjà décimés par la couche overview.
                // La fenêtre colorée se comporte comme un vrai curseur : on la glisse au doigt/souris,
                // et seul ce morceau alimente ensuite le bandeau principal + ses MIN/MAX.
                val navigatorSensorPoints = remember(navigatorSampleMap, sensors, bandSensorIds, wideFrom, wideTo) {
                    sensors.filter { it.id in bandSensorIds }.associate { sensor ->
                        sensor.id to navigatorSampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in wideWindow }
                            .sortedBy { it.timestamp }
                    }
                }
                val navigatorAllPoints = remember(navigatorSensorPoints) {
                    navigatorSensorPoints.values.flatten()
                }
                val navigatorMin = navigatorAllPoints.minOfOrNull { it.temperature } ?: 0.0
                val navigatorMax = navigatorAllPoints.maxOfOrNull { it.temperature } ?: 1.0
                val navigatorTempRange = (navigatorMax - navigatorMin).takeIf { it > 0.01 } ?: 1.0

                val gigaSensorPoints = remember(gigaSampleMap, sensors, bandSensorIds, bounds.first, bounds.last) {
                    sensors.filter { it.id in bandSensorIds }.associate { sensor ->
                        sensor.id to gigaSampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in bounds }
                            .sortedBy { it.timestamp }
                    }
                }
                val gigaAllPoints = remember(gigaSensorPoints) { gigaSensorPoints.values.flatten() }
                val gigaMin = gigaAllPoints.minOfOrNull { it.temperature } ?: 0.0
                val gigaMax = gigaAllPoints.maxOfOrNull { it.temperature } ?: 1.0
                val gigaTempRange = (gigaMax - gigaMin).takeIf { it > 0.01 } ?: 1.0
"""
new = """                // v0.21.4 : navigation = température extérieure uniquement.
                val navigatorWeatherPoints = remember(navigatorSampleMap, wideFrom, wideTo) {
                    navigationWeatherPoints(navigatorSampleMap)
                        .filter { it.timestamp in wideWindow }
                }
                val gigaWeatherPoints = remember(gigaSampleMap, bounds.first, bounds.last) {
                    navigationWeatherPoints(gigaSampleMap)
                        .filter { it.timestamp in bounds }
                }
                val navigatorMin = navigatorWeatherPoints.minOfOrNull { it.temperature } ?: 0.0
                val navigatorMax = navigatorWeatherPoints.maxOfOrNull { it.temperature } ?: 1.0
                val navigatorTempRange = (navigatorMax - navigatorMin).takeIf { it > 0.01 } ?: 1.0
                val gigaMin = gigaWeatherPoints.minOfOrNull { it.temperature } ?: 0.0
                val gigaMax = gigaWeatherPoints.maxOfOrNull { it.temperature } ?: 1.0
                val gigaTempRange = (gigaMax - gigaMin).takeIf { it > 0.01 } ?: 1.0

                // Le niveau 2 possède une visée locale pendant le glisser. Le niveau 3
                // continue d'utiliser previewFrom/previewTo (la dernière valeur validée).
                val displayPreviewCenter = secondBandDraftCenter ?: effectiveCenter
                val displayPreviewFrom = if (previewSpan >= wideSpan) wideFrom
                    else displayPreviewCenter - previewSpan / 2L
                val displayPreviewTo = if (previewSpan >= wideSpan) wideTo
                    else displayPreviewFrom + previewSpan

                val gigaSelectionCenter = wideFrom + (wideTo - wideFrom) / 2L
                val gigaSelectionTemp = nearestWeatherTemperature(
                    gigaWeatherPoints, gigaSelectionCenter, 40L * 60L * 60L * 1000L
                )
                val wideSelectionTemp = nearestWeatherTemperature(
                    navigatorWeatherPoints, displayPreviewCenter, 14L * 60L * 60L * 1000L
                )
                val gigaSelectorColor = weatherTemperatureColor(gigaSelectionTemp)
                val wideSelectorColor = weatherTemperatureColor(wideSelectionTemp)
                val missingWeatherColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.18f)
                val gigaMissingRanges = remember(gigaWeatherPoints, bounds.first, bounds.last) {
                    weatherMissingRanges(
                        gigaWeatherPoints, bounds.first, bounds.last,
                        42L * 60L * 60L * 1000L
                    )
                }
                val navigatorMissingRanges = remember(navigatorWeatherPoints, wideFrom, wideTo) {
                    weatherMissingRanges(
                        navigatorWeatherPoints, wideFrom, wideTo,
                        14L * 60L * 60L * 1000L
                    )
                }
"""
t = replace_once(t, old, new, "weather-only upper visual datasets")

# Labels.
t = t.replace(
    '"Navigation giga · LOD mois · TOTALITÉ de l’historique"',
    '"Navigation giga · météo extérieure · historique complet"',
    1,
)
t = t.replace(
    '"Zoom large · LOD jour · uniquement la sélection du bandeau du haut"',
    '"Zoom large · météo extérieure · uniquement la sélection du haut"',
    1,
)

# ---------------------------------------------------------------------------
# Global band: draw explicit weather gaps, a temperature-coloured weather curve,
# and a temperature-coloured selection window/handle.
# ---------------------------------------------------------------------------
old = """                    gigaSensorPoints.forEach { (sensorId, points) ->
                        if (points.size >= 2) {
                            val sensor = sensors.firstOrNull { it.id == sensorId } ?: return@forEach
                            val path = Path()
                            var previous: SamplePoint? = null
                            val gapLimit = maxOf(62L * 24L * 60L * 60L * 1000L, fullSpan / 80L)
                            points.forEach { point ->
                                val x = (((point.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                                    .coerceIn(0f, size.width)
                                val y = size.height - (((point.temperature - gigaMin) / gigaTempRange).toFloat() * size.height)
                                val breakHere = previous?.let { point.timestamp - it.timestamp > gapLimit } == true
                                if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                                previous = point
                            }
                            drawPath(
                                path,
                                palette[sensor.colorIndex % palette.size].copy(alpha = 0.34f),
                                style = Stroke(width = 0.8.dp.toPx())
                            )
                        }
                    }
                    val left = (((wideFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((wideTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
                    drawRect(
                        highlight.copy(alpha = 0.12f),
                        topLeft = Offset(left, 0f),
                        size = androidx.compose.ui.geometry.Size((right - left).coerceAtLeast(1f), size.height)
                    )
                    drawLine(highlight, Offset(left, 0f), Offset(left, size.height), 1.5.dp.toPx())
                    drawLine(highlight, Offset(right, 0f), Offset(right, size.height), 1.5.dp.toPx())
"""
new = """                    gigaMissingRanges.forEach { gap ->
                        val leftGap = (((gap.first - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        val rightGap = (((gap.last - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                            .coerceIn(leftGap, size.width)
                        drawRect(
                            missingWeatherColor,
                            topLeft = Offset(leftGap, 0f),
                            size = androidx.compose.ui.geometry.Size((rightGap - leftGap).coerceAtLeast(1f), size.height)
                        )
                    }
                    val gapLimit = maxOf(42L * 60L * 60L * 1000L, fullSpan / 500L)
                    gigaWeatherPoints.zipWithNext().forEach { (a, b) ->
                        if (b.timestamp - a.timestamp <= gapLimit) {
                            val x1 = (((a.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            val x2 = (((b.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            val y1 = size.height - (((a.temperature - gigaMin) / gigaTempRange).toFloat() * size.height)
                            val y2 = size.height - (((b.temperature - gigaMin) / gigaTempRange).toFloat() * size.height)
                            drawLine(
                                weatherTemperatureColor((a.temperature + b.temperature) / 2.0).copy(alpha = 0.72f),
                                Offset(x1, y1), Offset(x2, y2), 1.25.dp.toPx()
                            )
                        }
                    }
                    val left = (((wideFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((wideTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
                    drawRect(
                        gigaSelectorColor.copy(alpha = 0.16f),
                        topLeft = Offset(left, 0f),
                        size = androidx.compose.ui.geometry.Size((right - left).coerceAtLeast(1f), size.height)
                    )
                    drawLine(gigaSelectorColor, Offset(left, 0f), Offset(left, size.height), 1.7.dp.toPx())
                    drawLine(gigaSelectorColor, Offset(right, 0f), Offset(right, size.height), 1.7.dp.toPx())
                    drawCircle(gigaSelectorColor, 3.6.dp.toPx(), Offset((left + right) / 2f, size.height / 2f))
"""
t = replace_once(t, old, new, "global weather band drawing")

t = replace_once(
    t,
    """                    Text("ultra simplifié", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
""",
    """                    Text(
                        gigaSelectionTemp?.let { String.format(Locale.FRANCE, "%.1f° ext.", it) } ?: "météo absente",
                        style = MaterialTheme.typography.labelSmall,
                        color = gigaSelectorColor,
                        fontWeight = FontWeight.Bold
                    )
""",
    "global selection temperature label",
)

# ---------------------------------------------------------------------------
# Second band: draft selector moves locally; lower levels and DB stay frozen.
# ---------------------------------------------------------------------------
old = """                        .pointerInput(wideFrom, wideTo, previewSpan) {
                            detectDragGestures { change, dragAmount ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val deltaTs = ((dragAmount.x / width) * wideSpan.toDouble()).toLong()
                                previewCenter = clampCenterToRange(previewCenter + deltaTs, previewSpan, wideWindow)
                                change.consume()
                            }
                        }
                        .pointerInput(wideFrom, wideTo, previewSpan) {
                            detectTapGestures(onTap = { p ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val fraction = (p.x / width).coerceIn(0f, 1f)
                                val target = wideFrom + (wideSpan * fraction).toLong()
                                previewCenter = clampCenterToRange(target, previewSpan, wideWindow)
                            })
                        }
"""
new = """                        .pointerInput(wideFrom, wideTo, previewSpan, effectiveCenter) {
                            detectDragGestures(
                                onDragStart = {
                                    secondBandDraftCenter = effectiveCenter
                                    onLowerZonesInteractionStart()
                                },
                                onDrag = { change, dragAmount ->
                                    val width = size.width.toFloat().coerceAtLeast(1f)
                                    val deltaTs = ((dragAmount.x / width) * wideSpan.toDouble()).toLong()
                                    val current = secondBandDraftCenter ?: effectiveCenter
                                    secondBandDraftCenter = clampCenterToRange(
                                        current + deltaTs, previewSpan, wideWindow
                                    )
                                    change.consume()
                                },
                                onDragEnd = {
                                    val target = secondBandDraftCenter
                                    secondBandDraftCenter = null
                                    if (target != null && target != effectiveCenter) {
                                        previewCenter = target
                                        onLowerZonesCommit()
                                    } else {
                                        onLowerZonesInteractionCancel()
                                    }
                                },
                                onDragCancel = {
                                    secondBandDraftCenter = null
                                    onLowerZonesInteractionCancel()
                                }
                            )
                        }
                        .pointerInput(wideFrom, wideTo, previewSpan, effectiveCenter) {
                            detectTapGestures(onTap = { p ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val fraction = (p.x / width).coerceIn(0f, 1f)
                                val target = clampCenterToRange(
                                    wideFrom + (wideSpan * fraction).toLong(), previewSpan, wideWindow
                                )
                                if (target != effectiveCenter) {
                                    onLowerZonesInteractionStart()
                                    previewCenter = target
                                    onLowerZonesCommit()
                                }
                            })
                        }
"""
t = replace_once(t, old, new, "second band commit-on-release gestures")

old = """                    if (navigatorAllPoints.isNotEmpty()) {
                        navigatorSensorPoints.forEach { (sensorId, points) ->
                            if (points.size >= 2) {
                                val sensor = sensors.firstOrNull { it.id == sensorId } ?: return@forEach
                                val path = Path()
                                var previous: SamplePoint? = null
                                val navigatorGapLimit = maxOf(
                                    12L * 60L * 60L * 1000L,
                                    wideSpan / 120L
                                )
                                points.forEach { point ->
                                    val x = (((point.timestamp - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                                        .coerceIn(0f, size.width)
                                    val y = size.height - (((point.temperature - navigatorMin) / navigatorTempRange)
                                        .toFloat() * size.height)
                                    val breakHere = previous?.let {
                                        point.timestamp - it.timestamp > navigatorGapLimit
                                    } == true
                                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                                    previous = point
                                }
                                drawPath(
                                    path,
                                    palette[sensor.colorIndex % palette.size].copy(alpha = 0.42f),
                                    style = Stroke(width = 1.dp.toPx())
                                )
                            }
                        }
                    }

                    val left = (((previewFrom - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((previewTo - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
"""
new = """                    navigatorMissingRanges.forEach { gap ->
                        val leftGap = (((gap.first - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        val rightGap = (((gap.last - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                            .coerceIn(leftGap, size.width)
                        drawRect(
                            missingWeatherColor,
                            topLeft = Offset(leftGap, 0f),
                            size = androidx.compose.ui.geometry.Size((rightGap - leftGap).coerceAtLeast(1f), size.height)
                        )
                    }
                    val navigatorGapLimit = maxOf(14L * 60L * 60L * 1000L, wideSpan / 600L)
                    navigatorWeatherPoints.zipWithNext().forEach { (a, b) ->
                        if (b.timestamp - a.timestamp <= navigatorGapLimit) {
                            val x1 = (((a.timestamp - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            val x2 = (((b.timestamp - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            val y1 = size.height - (((a.temperature - navigatorMin) / navigatorTempRange).toFloat() * size.height)
                            val y2 = size.height - (((b.temperature - navigatorMin) / navigatorTempRange).toFloat() * size.height)
                            drawLine(
                                weatherTemperatureColor((a.temperature + b.temperature) / 2.0).copy(alpha = 0.82f),
                                Offset(x1, y1), Offset(x2, y2), 1.6.dp.toPx()
                            )
                        }
                    }

                    val left = (((displayPreviewFrom - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((displayPreviewTo - wideFrom).toDouble() / wideSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
"""
t = replace_once(t, old, new, "second weather band drawing and draft selector")

t = replace_once(
    t,
    """                        highlight.copy(alpha = 0.16f),
                        topLeft = Offset(left, 0f),
""",
    """                        wideSelectorColor.copy(alpha = 0.18f),
                        topLeft = Offset(left, 0f),
""",
    "second selector fill color",
)
t = replace_once(
    t,
    """                    drawLine(highlight, Offset(left, 0f), Offset(left, size.height), 2.dp.toPx())
                    drawLine(highlight, Offset(right, 0f), Offset(right, size.height), 2.dp.toPx())
                    val handleX = (left + right) / 2f
                    drawLine(highlight.copy(alpha = 0.9f), Offset(handleX - 5.dp.toPx(), size.height / 2f), Offset(handleX + 5.dp.toPx(), size.height / 2f), 2.dp.toPx())
                    drawCircle(highlight, 3.5.dp.toPx(), Offset(handleX, size.height / 2f))
""",
    """                    drawLine(wideSelectorColor, Offset(left, 0f), Offset(left, size.height), 2.dp.toPx())
                    drawLine(wideSelectorColor, Offset(right, 0f), Offset(right, size.height), 2.dp.toPx())
                    val handleX = (left + right) / 2f
                    drawLine(wideSelectorColor.copy(alpha = 0.92f), Offset(handleX - 6.dp.toPx(), size.height / 2f), Offset(handleX + 6.dp.toPx(), size.height / 2f), 2.2.dp.toPx())
                    drawCircle(wideSelectorColor, 4.dp.toPx(), Offset(handleX, size.height / 2f))
""",
    "second selector line color",
)
t = replace_once(
    t,
    """                    Text("zoom large", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
""",
    """                    Text(
                        wideSelectionTemp?.let { String.format(Locale.FRANCE, "%.1f° ext.", it) } ?: "météo absente",
                        style = MaterialTheme.typography.labelSmall,
                        color = wideSelectorColor,
                        fontWeight = FontWeight.Bold
                    )
""",
    "second selection temperature label",
)

# ---------------------------------------------------------------------------
# Level 3 graphical area gets the progressive veil and post-load light sweep.
# Wrap only the actual 92dp analysis band; MIN/MAX and controls remain readable.
# ---------------------------------------------------------------------------
canvas_anchor = """                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(92.dp)
"""
canvas_pos = t.index(canvas_anchor, t.index(third_level_marker))
t = t[:canvas_pos] + t[canvas_pos:].replace(
    canvas_anchor,
    """                Box(Modifier.fillMaxWidth().height(92.dp)) {
                Canvas(
                    modifier = Modifier
                        .fillMaxSize()
""",
    1,
)
# Find the known end of this exact Canvas and close the Box after the overlay.
end_anchor = """                }

                val pendingRange = rangeStart?.let { a ->
"""
end_pos = t.index(end_anchor, canvas_pos)
t = t[:end_pos] + t[end_pos:].replace(
    end_anchor,
    """                }
                PendingCascadeOverlay(
                    pending = lowerZonesPending,
                    flashToken = lowerZonesFlashToken,
                    modifier = Modifier.fillMaxSize()
                )
                }

                val pendingRange = rangeStart?.let { a ->
""",
    1,
)

# ---------------------------------------------------------------------------
# Wire parent transition callbacks into HistoryOverviewCard.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """                        selectedTimestamp = selectedTimestamp,
                        onCascadeRangesChanged = { wide, exploration ->
""",
    """                        selectedTimestamp = selectedTimestamp,
                        lowerZonesPending = lowerCascadeVeil,
                        lowerZonesFlashToken = lowerCascadeFlashToken,
                        onLowerZonesInteractionStart = {
                            lowerCascadeAwaitingReload = false
                            lowerCascadeVeil = true
                        },
                        onLowerZonesInteractionCancel = {
                            lowerCascadeAwaitingReload = false
                            lowerCascadeVeil = false
                        },
                        onLowerZonesCommit = {
                            lowerCascadeAwaitingReload = true
                            lowerCascadeVeil = true
                        },
                        onCascadeRangesChanged = { wide, exploration ->
""",
    "wire overview transition callbacks",
)

# ---------------------------------------------------------------------------
# Level 4 detailed chart gets the same veil / light sweep.
# ---------------------------------------------------------------------------
t = replace_once(
    t,
    """                item {
                    ChartCard(
""",
    """                item {
                    Box(Modifier.fillMaxWidth()) {
                    ChartCard(
""",
    "wrap detailed chart start",
)
t = replace_once(
    t,
    """                    )
                }

                item {
                    SensorSourcesCard(
""",
    """                    )
                    PendingCascadeOverlay(
                        pending = lowerCascadeVeil,
                        flashToken = lowerCascadeFlashToken,
                        modifier = Modifier.fillMaxSize()
                    )
                    }
                }

                item {
                    SensorSourcesCard(
""",
    "wrap detailed chart end",
)

# ---------------------------------------------------------------------------
# Version bump.
# ---------------------------------------------------------------------------
p.write_text(t, encoding="utf-8")

p = Path("app/build.gradle.kts")
g = p.read_text(encoding="utf-8")
g = replace_once(
    g,
    '        versionCode = 49\n        versionName = "0.21.3"\n',
    '        versionCode = 50\n        versionName = "0.21.4"\n',
    "version bump",
)
p.write_text(g, encoding="utf-8")

print("FabData v0.21.4 weather navigation UI patch applied")
