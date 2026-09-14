from pathlib import Path

MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


main = MAIN.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 1) Keep the last timestamp from the user's physical probes separate from
#    weather/global bounds. This becomes the visual centre reference.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    "    val lyonReconstructedSamples: List<SamplePoint>,\n"
    "    val inertiaEstimate: ThermalInertiaEstimate?\n"
    ")\n",
    "    val lyonReconstructedSamples: List<SamplePoint>,\n"
    "    val inertiaEstimate: ThermalInertiaEstimate?,\n"
    "    val latestUserDataTimestamp: Long?\n"
    ")\n",
    "LoadedData latest user timestamp field",
)

main = replace_once(
    main,
    "    var globalBounds by remember { mutableStateOf<LongRange?>(null) }\n"
    "    var viewBounds by remember { mutableStateOf<LongRange?>(null) }\n",
    "    var globalBounds by remember { mutableStateOf<LongRange?>(null) }\n"
    "    var latestUserDataTimestamp by remember { mutableStateOf<Long?>(null) }\n"
    "    var viewBounds by remember { mutableStateOf<LongRange?>(null) }\n",
    "latest user timestamp compose state",
)

main = replace_once(
    main,
    "            val physicalBounds = db.physicalSensorBounds() ?: db.globalTimeBounds()\n",
    "            val userPhysicalBounds = db.physicalSensorBounds()\n"
    "            val physicalBounds = userPhysicalBounds ?: db.globalTimeBounds()\n",
    "preserve physical user bounds",
)

main = replace_once(
    main,
    "                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null)\n",
    "                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null, userPhysicalBounds?.last)\n",
    "empty LoadedData latest timestamp",
)

main = replace_once(
    main,
    "                    stat,\n"
    "                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed, inertia\n"
    "                )\n",
    "                    stat,\n"
    "                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed, inertia,\n"
    "                    userPhysicalBounds?.last\n"
    "                )\n",
    "full LoadedData latest timestamp",
)

main = replace_once(
    main,
    "        globalBounds = loaded.globalBounds\n"
    "        viewBounds = loaded.viewBounds\n",
    "        globalBounds = loaded.globalBounds\n"
    "        latestUserDataTimestamp = loaded.latestUserDataTimestamp\n"
    "        viewBounds = loaded.viewBounds\n",
    "apply latest user timestamp",
)

main = replace_once(
    main,
    "                        historyBounds = overviewDisplayBounds,\n"
    "                        presentAnchorTimestamp = overviewPresentAnchor,\n"
    "                        viewBounds = viewBounds,\n",
    "                        historyBounds = overviewDisplayBounds,\n"
    "                        presentAnchorTimestamp = overviewPresentAnchor,\n"
    "                        latestUserDataTimestamp = latestUserDataTimestamp ?: overviewPresentAnchor,\n"
    "                        viewBounds = viewBounds,\n",
    "pass latest user timestamp",
)

main = replace_once(
    main,
    "    historyBounds: LongRange?,\n"
    "    presentAnchorTimestamp: Long,\n"
    "    viewBounds: LongRange?,\n",
    "    historyBounds: LongRange?,\n"
    "    presentAnchorTimestamp: Long,\n"
    "    latestUserDataTimestamp: Long,\n"
    "    viewBounds: LongRange?,\n",
    "HistoryOverview latest timestamp parameter",
)

# ---------------------------------------------------------------------------
# 2) Cascade geometry: band 3 is exactly half of band 2. The x3..x9 selector
#    remains authoritative relative to the detailed graph. Cap band 3 to half
#    of the global terrain so its parent can always remain exactly 2x wider.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    "                val maxSpan = minOf(requestedContextSpan, fullSpan).coerceAtLeast(1L)\n",
    "                val maxSpan = minOf(requestedContextSpan, maxOf(1L, fullSpan / 2L)).coerceAtLeast(1L)\n",
    "band3 max span half global",
)

main = replace_once(
    main,
    "                // Niveau 1 : le giga est le seul historique complet.\n"
    "                // Sa sélection doit rester un VRAI niveau intermédiaire et non retomber\n"
    "                // automatiquement sur tout l'historique. Le milieu vaut environ 2x\n"
    "                // l'exploration, avec un plancher d'un mois pour les petits presets.\n"
    "                val minimumWideSpan = minOf(fullSpan, maxOf(PreviewPreset.M1.spanMs, previewSpan))\n"
    "                val desiredWideSpan = maxOf(previewSpan * 2L, minimumWideSpan)\n"
    "                val wideSpan = minOf(fullSpan, desiredWideSpan).coerceAtLeast(previewSpan)\n",
    "                // Cascade geometry: band 2 is always exactly twice band 3.\n"
    "                // The x3..x9 selector still chooses band 3 from the detailed graph.\n"
    "                val wideSpan = minOf(fullSpan, previewSpan * 2L).coerceAtLeast(previewSpan)\n",
    "band2 exactly double band3",
)

main = replace_once(
    main,
    "                                val oldMaxSpan = minOf(\n"
    "                                    oldMainSpan * explorationContextMultiplier.toLong(),\n"
    "                                    fullSpan\n"
    "                                ).coerceAtLeast(1L)\n",
    "                                val oldMaxSpan = minOf(\n"
    "                                    oldMainSpan * explorationContextMultiplier.toLong(),\n"
    "                                    maxOf(1L, fullSpan / 2L)\n"
    "                                ).coerceAtLeast(1L)\n",
    "band3 gesture max span half global",
)

# ---------------------------------------------------------------------------
# 3) Startup / refresh: the centre reference is the newest REAL user-probe
#    timestamp. The upper-band release cascade remains right-edge aligned.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    "                // Initial load and explicit refresh: align the complete lower cascade to the right\n"
    "                // edge of the PRESENT. The giga band may extend one month further, but we do not\n"
    "                // boot the useful views inside that intentionally empty future runway.\n"
    "                LaunchedEffect(presentAnchorTimestamp, viewBounds?.first, viewBounds?.last) {\n"
    "                    val detail = viewBounds ?: return@LaunchedEffect\n"
    "                    if (appliedRightAnchor == presentAnchorTimestamp) return@LaunchedEffect\n"
    "                    val present = presentAnchorTimestamp.coerceIn(bounds.first, bounds.last)\n"
    "                    val initialWideCenter = rightAlignedCenterAt(present, wideSpan, bounds)\n"
    "                    val initialWideRange = rangeForCenter(initialWideCenter, wideSpan, bounds)\n"
    "                    val initialPreviewCenter = rightAlignedCenterAt(present, previewSpan, initialWideRange)\n"
    "                    val initialPreviewRange = rangeForCenter(initialPreviewCenter, previewSpan, initialWideRange)\n"
    "                    val detailSpan = (detail.last - detail.first).coerceAtLeast(1L).coerceAtMost(previewSpan)\n"
    "                    val initialDetailCenter = rightAlignedCenterAt(present, detailSpan, initialPreviewRange)\n"
    "                    appliedRightAnchor = presentAnchorTimestamp\n"
    "                    wideCenter = initialWideCenter\n"
    "                    previewCenter = initialPreviewCenter\n"
    "                    onNavigate(initialDetailCenter)\n"
    "                    onSelectTimestamp(present.coerceIn(initialPreviewRange.first, initialPreviewRange.last))\n"
    "                }\n",
    "                // Initial load and explicit refresh: the temporal midpoint is the newest\n"
    "                // real timestamp from the user's physical probes. This keeps recent RAW on\n"
    "                // the left and leaves symmetric room for forecasts on the right.\n"
    "                // Upper-band drag/tap releases still cascade their children to the right edge.\n"
    "                LaunchedEffect(presentAnchorTimestamp, latestUserDataTimestamp, viewBounds?.first, viewBounds?.last) {\n"
    "                    val detail = viewBounds ?: return@LaunchedEffect\n"
    "                    if (appliedRightAnchor == presentAnchorTimestamp) return@LaunchedEffect\n"
    "                    val latestData = latestUserDataTimestamp.coerceIn(bounds.first, bounds.last)\n"
    "                    val initialWideCenter = clampCenter(latestData, wideSpan)\n"
    "                    val initialWideRange = rangeForCenter(initialWideCenter, wideSpan, bounds)\n"
    "                    val initialPreviewCenter = clampCenterToRange(latestData, previewSpan, initialWideRange)\n"
    "                    val initialPreviewRange = rangeForCenter(initialPreviewCenter, previewSpan, initialWideRange)\n"
    "                    val detailSpan = (detail.last - detail.first).coerceAtLeast(1L).coerceAtMost(previewSpan)\n"
    "                    val initialDetailCenter = clampCenterToRange(latestData, detailSpan, initialPreviewRange)\n"
    "                    appliedRightAnchor = presentAnchorTimestamp\n"
    "                    wideCenter = initialWideCenter\n"
    "                    previewCenter = initialPreviewCenter\n"
    "                    onNavigate(initialDetailCenter)\n"
    "                    onSelectTimestamp(latestData.coerceIn(initialPreviewRange.first, initialPreviewRange.last))\n"
    "                }\n",
    "centre cascade on latest user data",
)

# ---------------------------------------------------------------------------
# 4) Band 3 weather: same temperature-colour gradient as bands 1 and 2.
#    User-probe MIN/MAX labels remain user-probe labels; weather participates
#    only in the shared vertical temperature scale and its own coloured curve.
# ---------------------------------------------------------------------------
main = replace_once(
    main,
    "                val visiblePoints = remember(previewSensorPoints) {\n"
    "                    previewSensorPoints.values.flatten()\n"
    "                }\n"
    "                val minPoint = visiblePoints.minByOrNull { it.temperature }\n"
    "                val maxPoint = visiblePoints.maxByOrNull { it.temperature }\n"
    "                val minTemp = minPoint?.temperature ?: 0.0\n"
    "                val maxTemp = maxPoint?.temperature ?: 1.0\n"
    "                val tempRange = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0\n",
    "                val visiblePoints = remember(previewSensorPoints) {\n"
    "                    previewSensorPoints.values.flatten()\n"
    "                }\n"
    "                val explorationWeatherPoints = remember(sampleMap, previewFrom, previewTo) {\n"
    "                    navigationWeatherPoints(sampleMap)\n"
    "                        .filter { it.timestamp in previewWindow }\n"
    "                }\n"
    "                val minPoint = visiblePoints.minByOrNull { it.temperature }\n"
    "                val maxPoint = visiblePoints.maxByOrNull { it.temperature }\n"
    "                val scalePoints = remember(visiblePoints, explorationWeatherPoints) {\n"
    "                    visiblePoints + explorationWeatherPoints\n"
    "                }\n"
    "                val minTemp = scalePoints.minOfOrNull { it.temperature } ?: 0.0\n"
    "                val maxTemp = scalePoints.maxOfOrNull { it.temperature } ?: 1.0\n"
    "                val tempRange = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0\n",
    "band3 weather points and shared scale",
)

main = replace_once(
    main,
    "                Text(\n"
    "                    \"Sélection / exploration · LOD 6 h · limitée par le bandeau du milieu\",\n",
    "                Text(\n"
    "                    \"Sélection / exploration · LOD 6 h · météo colorée + sondes · 1/2 du bandeau 2\",\n",
    "band3 label weather half width",
)

weather_draw_marker = """                    // Fenêtre détaillée actuelle : fond grisé + deux limites.\n"""
weather_draw = """                    // Météo extérieure : même gradient température que les deux bandeaux supérieurs.\n                    val weatherGapLimit = maxOf(\n                        6L * 60L * 60L * 1000L,\n                        previewSpan / 150L\n                    )\n                    explorationWeatherPoints.zipWithNext().forEach { (a, b) ->\n                        if (b.timestamp - a.timestamp <= weatherGapLimit) {\n                            val x1 = (((a.timestamp - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)\n                                .coerceIn(0f, size.width)\n                            val x2 = (((b.timestamp - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)\n                                .coerceIn(0f, size.width)\n                            val y1 = size.height - (((a.temperature - minTemp) / tempRange).toFloat() * size.height)\n                            val y2 = size.height - (((b.temperature - minTemp) / tempRange).toFloat() * size.height)\n                            drawLine(\n                                weatherTemperatureColor((a.temperature + b.temperature) / 2.0).copy(alpha = 0.86f),\n                                Offset(x1, y1), Offset(x2, y2), 1.7.dp.toPx()\n                            )\n                        }\n                    }\n\n                    // Fenêtre détaillée actuelle : fond grisé + deux limites.\n"""
main = replace_once(main, weather_draw_marker, weather_draw, "draw coloured weather in band3")

MAIN.write_text(main, encoding="utf-8")
print("Patched v0.23.9 band 3 weather + half-width cascade + latest-user-data midpoint")
