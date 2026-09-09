from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'app/src/main/java/com/fabdata/app/MainActivity.kt'
t = P.read_text(encoding='utf-8')

def one(old: str, new: str, label: str):
    global t
    if old not in t:
        raise SystemExit(f'missing MainActivity anchor: {label}')
    t = t.replace(old, new, 1)

# -----------------------------------------------------------------------------
# Short exploration presets.
# -----------------------------------------------------------------------------
one(
'''private enum class PreviewPreset(val label: String, val spanMs: Long) {
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}''',
'''private enum class PreviewPreset(val label: String, val spanMs: Long) {
    W1("1 sem.", 7L * 24L * 60L * 60L * 1000L),
    M1("1 mois", 31L * 24L * 60L * 60L * 1000L),
    M3("3 mois", 92L * 24L * 60L * 60L * 1000L),
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}''', 'PreviewPreset')

one(
'private const val LYON_DETAIL_GAP_MS = 90L * 60L * 1000L\n',
'''private const val OVERVIEW_LOD_6H_MS = 6L * 60L * 60L * 1000L
private const val OVERVIEW_LOD_DAY_MS = 24L * 60L * 60L * 1000L
private const val OVERVIEW_LOD_MONTH_MS = 30L * 24L * 60L * 60L * 1000L
private const val LYON_DETAIL_GAP_MS = 90L * 60L * 1000L
''', 'LOD constants')

# -----------------------------------------------------------------------------
# Three independent overview resolutions in LoadedData + state.
# -----------------------------------------------------------------------------
one(
'''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val overviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>,
    val lyonReconstructedSamples: List<SamplePoint>,
    val inertiaEstimate: ThermalInertiaEstimate?
)''',
'''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val gigaOverviewSamples: Map<Long, List<SamplePoint>>,
    val navigatorOverviewSamples: Map<Long, List<SamplePoint>>,
    val explorationOverviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>,
    val lyonReconstructedSamples: List<SamplePoint>,
    val inertiaEstimate: ThermalInertiaEstimate?
)''', 'LoadedData')

one(
'    var overviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }\n',
'''    var gigaOverviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var navigatorOverviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var explorationOverviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
''', 'overview state')

one(
'                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null)',
'                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null)',
'empty LoadedData')

# -----------------------------------------------------------------------------
# Replace the old full-history materialisation with SQL-side LOD maps.
# -----------------------------------------------------------------------------
old_overview = '''                val overview = s.associate { sensor ->
                    val value = if (sensor.stableKey == LyonWeatherSync.STABLE_KEY) {
                        val hourly = lyonLab.queryOfficial(LyonSeriesKind.HOURLY, all.first, all.last)
                            .map { SamplePoint(sensor.id, it.timestamp, it.temperature, it.humidity) }
                        hourly.ifEmpty { db.querySamples(sensor.id, all.first, all.last, maxPoints = 600) }
                    } else {
                        db.querySamples(sensor.id, all.first, all.last, maxPoints = 600)
                    }
                    sensor.id to value
                }
                val overviewReferenceRaw = weatherReferenceStore.query(
                    selectedWeatherReference.key, all.first, all.last
                ).filter { it.source != PointSource.FORECAST }.map {
                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity, it.source, it.confidence)
                }
                // v0.20.7 performance: le bandeau n'a pas besoin de dizaines de milliers
                // de points météo. On garde les extrémités et ~1200 points réguliers.
                val overviewReference = if (overviewReferenceRaw.size <= 1200) overviewReferenceRaw else {
                    val step = ((overviewReferenceRaw.size + 1199) / 1200).coerceAtLeast(1)
                    val sampled = overviewReferenceRaw.filterIndexed { index, _ -> index % step == 0 }.toMutableList()
                    overviewReferenceRaw.lastOrNull()?.let { last ->
                        if (sampled.lastOrNull()?.timestamp != last.timestamp) sampled += last
                    }
                    sampled
                }
                val overviewWithReference = overview + (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference)
'''
new_overview = '''                fun physicalLod(bucketMs: Long): Map<Long, List<SamplePoint>> =
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
one(old_overview, new_overview, 'old overview load')

# Limit full inertial materialisation to the detailed window and make separate LODs.
one(
'''                        val validatedHistory = inertiaHistoryStore.query(
                            selectedWeatherReference.key,
                            model.sensorId,
                            model.stableSignature(),
                            all.first,
                            all.last
                        )
                        measuredProjection.copy(
                            surfacePoints = (validatedHistory + measuredProjection.surfacePoints)
''',
'''                        val validatedHistory = inertiaHistoryStore.query(
                            selectedWeatherReference.key,
                            model.sensorId,
                            model.stableSignature(),
                            chosen.first,
                            chosen.last
                        )
                        measuredProjection.copy(
                            surfacePoints = (validatedHistory + measuredProjection.surfacePoints.filter { it.timestamp in chosen })
''', 'inertia detail range')

one(
'''                LoadedData(
                    s, all, chosen, samples, overviewWithReference, stat,
                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed, inertia
                )''',
'''                fun withInertiaLod(
                    base: Map<Long, List<SamplePoint>>,
                    bucketMs: Long
                ): Map<Long, List<SamplePoint>> {
                    val model = trainedModel ?: return base
                    val stored = inertiaHistoryStore.queryLod(
                        selectedWeatherReference.key,
                        model.sensorId,
                        model.stableSignature(),
                        all.first,
                        all.last,
                        bucketMs
                    )
                    val recent = inertia?.surfacePoints.orEmpty()
                        .groupBy { (it.timestamp / bucketMs) * bucketMs }
                        .map { (bucketStart, points) ->
                            SamplePoint(
                                THERMAL_INERTIA_SENSOR_ID,
                                bucketStart + bucketMs / 2L,
                                points.map { it.temperature }.average(),
                                points.map { it.humidity }.average(),
                                PointSource.RECONSTRUCTED,
                                points.mapNotNull { it.confidence }.takeIf { it.isNotEmpty() }?.average()
                            )
                        }
                    val merged = (stored + recent)
                        .associateBy { it.timestamp }
                        .values
                        .sortedBy { it.timestamp }
                    return base + (THERMAL_INERTIA_SENSOR_ID to merged)
                }

                LoadedData(
                    s, all, chosen, samples,
                    withInertiaLod(gigaOverview, OVERVIEW_LOD_MONTH_MS),
                    withInertiaLod(navigatorOverview, OVERVIEW_LOD_DAY_MS),
                    withInertiaLod(explorationOverview, OVERVIEW_LOD_6H_MS),
                    stat,
                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed, inertia
                )''', 'LoadedData populated')

one(
'''        overviewSampleMap = loaded.overviewSamples
        statsMap = loaded.stats''',
'''        gigaOverviewSampleMap = loaded.gigaOverviewSamples
        navigatorOverviewSampleMap = loaded.navigatorOverviewSamples
        explorationOverviewSampleMap = loaded.explorationOverviewSamples
        statsMap = loaded.stats''', 'overview assignments')

# -----------------------------------------------------------------------------
# Build chart-facing LOD maps without creating another all-history inertia list.
# -----------------------------------------------------------------------------
old_chart_overview = '''    val inertiaOverview = globalBounds?.let { b ->
        inertiaEstimate?.surfacePoints?.filter { it.timestamp in b }.orEmpty().let { selected ->
            if (selected.size <= 1200) selected else {
                val step = ((selected.size + 1199) / 1200).coerceAtLeast(1)
                selected.filterIndexed { index, _ -> index % step == 0 }
            }
        }
    }.orEmpty()
    val inertiaSensor = Sensor(
        id = THERMAL_INERTIA_SENSOR_ID,
        stableKey = THERMAL_INERTIA_STABLE_KEY,
        name = "Sol inertiel estimé",
        room = "Surface / sol équivalent · réel + historique validé",
        colorIndex = 4,
        latestTimestamp = inertiaEstimate?.surfacePoints?.lastOrNull()?.timestamp
    )
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + inertiaSensor
    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +
        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)
    val overviewReference = overviewSampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()
    val chartOverviewSampleMap = overviewSampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to overviewReference.filter { it.source == PointSource.MEASURED }.map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +
        (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference.filter { it.source == PointSource.RECONSTRUCTED }) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaOverview)
'''
new_chart_overview = '''    val inertiaSensor = Sensor(
        id = THERMAL_INERTIA_SENSOR_ID,
        stableKey = THERMAL_INERTIA_STABLE_KEY,
        name = "Sol inertiel estimé",
        room = "Surface / sol équivalent · réel + historique validé",
        colorIndex = 4,
        latestTimestamp = inertiaEstimate?.surfacePoints?.lastOrNull()?.timestamp
            ?: explorationOverviewSampleMap[THERMAL_INERTIA_SENSOR_ID]?.lastOrNull()?.timestamp
    )
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + inertiaSensor
    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +
        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)

    fun chartLodMap(source: Map<Long, List<SamplePoint>>): Map<Long, List<SamplePoint>> {
        val reference = source[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()
        return source.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
            (WEATHER_OFFICIAL_SENSOR_ID to reference.filter { it.source == PointSource.MEASURED }
                .map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +
            (LYON_RECONSTRUCTED_SENSOR_ID to reference.filter { it.source == PointSource.RECONSTRUCTED }
                .map { it.copy(sensorId = LYON_RECONSTRUCTED_SENSOR_ID) }) +
            (THERMAL_INERTIA_SENSOR_ID to source[THERMAL_INERTIA_SENSOR_ID].orEmpty())
    }
    val chartGigaOverviewSampleMap = chartLodMap(gigaOverviewSampleMap)
    val chartNavigatorOverviewSampleMap = chartLodMap(navigatorOverviewSampleMap)
    val chartExplorationOverviewSampleMap = chartLodMap(explorationOverviewSampleMap)
'''
one(old_chart_overview, new_chart_overview, 'chart overview maps')

one(
'''                    HistoryOverviewCard(
                        sensors = chartSensors,
                        sampleMap = chartOverviewSampleMap,
                        historyBounds = globalBounds,''',
'''                    HistoryOverviewCard(
                        sensors = chartSensors,
                        gigaSampleMap = chartGigaOverviewSampleMap,
                        navigatorSampleMap = chartNavigatorOverviewSampleMap,
                        sampleMap = chartExplorationOverviewSampleMap,
                        preferredIndoorSensorId = trainingTargetPrefs.indoorSensorId()
                            ?: inertiaEstimate?.diagnostics?.sourceSensorId,
                        historyBounds = globalBounds,''', 'HistoryOverviewCard call')

# -----------------------------------------------------------------------------
# Patch ONLY inside HistoryOverviewCard. The function bounds prevent accidental edits
# to the earlier detailed-window `fullSpan` calculation.
# -----------------------------------------------------------------------------
start = t.index('@Composable\nprivate fun HistoryOverviewCard(')
end = t.index('\n@Composable\nprivate fun RangeSelectionHelpDemo(', start)
f = t[start:end]

def f_one(old: str, new: str, label: str):
    global f
    if old not in f:
        raise SystemExit(f'missing HistoryOverviewCard anchor: {label}')
    f = f.replace(old, new, 1)

f_one(
'''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,''',
'''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    gigaSampleMap: Map<Long, List<SamplePoint>>,
    navigatorSampleMap: Map<Long, List<SamplePoint>>,
    sampleMap: Map<Long, List<SamplePoint>>,
    preferredIndoorSensorId: Long?,
    historyBounds: LongRange?,''', 'signature')

f_one(
'                "Bandeau fin = déplacer la fenêtre · bandeau principal = viser/sélectionner · pince = zoom de prévisu",',
'                "Giga = mois · navigation = jours · exploration = 6 h · détail = RAW",', 'hint')

# Add persistent sensor-level band selection. A physical sensor keeps its real/reconstructed
# source styling; selecting it never changes the underlying data.
f_one(
'''                val helpPrefs = remember {
                    helpContext.getSharedPreferences("fabdata_context_help", Context.MODE_PRIVATE)
                }
                var helpOpen''',
'''                val helpPrefs = remember {
                    helpContext.getSharedPreferences("fabdata_context_help", Context.MODE_PRIVATE)
                }
                val bandPrefs = remember {
                    helpContext.getSharedPreferences("fabdata_overview_band_curves", Context.MODE_PRIVATE)
                }
                val availableBandSensorIds = remember(sensors, sampleMap) {
                    sensors.filter { sampleMap[it.id].orEmpty().isNotEmpty() }.map { it.id }.toSet()
                }
                val bandSignature = remember(availableBandSensorIds) { availableBandSensorIds.sorted().joinToString(",") }
                var bandSensorIds by remember(bandSignature, preferredIndoorSensorId) {
                    val configured = bandPrefs.getBoolean("configured", false)
                    val stored = bandPrefs.getStringSet("sensor_ids", emptySet()).orEmpty()
                        .mapNotNull { it.toLongOrNull() }
                        .filter { it in availableBandSensorIds }
                        .toSet()
                    val defaults = linkedSetOf<Long>().apply {
                        preferredIndoorSensorId?.takeIf { it in availableBandSensorIds }?.let { add(it) }
                        THERMAL_INERTIA_SENSOR_ID.takeIf { it in availableBandSensorIds }?.let { add(it) }
                        if (isEmpty()) availableBandSensorIds.firstOrNull()?.let { add(it) }
                    }
                    mutableStateOf(if (configured) stored else defaults)
                }
                var bandChooserOpen by rememberSaveable { mutableStateOf(false) }
                fun saveBandSensors(next: Set<Long>) {
                    bandSensorIds = next
                    bandPrefs.edit()
                        .putBoolean("configured", true)
                        .putStringSet("sensor_ids", next.map { it.toString() }.toSet())
                        .apply()
                }
                var helpOpen''', 'band selection state')

# Add chooser immediately after preset row, before action row.
needle = '''                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    AssistChip('''
chooser = '''                OutlinedButton(
                    onClick = { bandChooserOpen = !bandChooserOpen },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Courbes des bandeaux · ${bandSensorIds.size} sélectionnée(s)")
                }
                if (bandChooserOpen) {
                    Card(
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.34f)
                        )
                    ) {
                        Column(
                            Modifier.fillMaxWidth().padding(8.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp)
                        ) {
                            Text(
                                "Même sélection, résolutions différentes. Les segments RECONSTRUCTED gardent leur style reconstruit.",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            sensors.filter { it.id in availableBandSensorIds }.forEach { sensor ->
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                    Checkbox(
                                        checked = sensor.id in bandSensorIds,
                                        onCheckedChange = { checked ->
                                            val next = bandSensorIds.toMutableSet()
                                            if (checked) next += sensor.id else next -= sensor.id
                                            saveBandSensors(next)
                                        }
                                    )
                                    Text(
                                        when (sensor.id) {
                                            THERMAL_INERTIA_SENSOR_ID -> "Sol inertiel"
                                            WEATHER_OFFICIAL_SENSOR_ID -> "Météo officielle"
                                            LYON_RECONSTRUCTED_SENSOR_ID -> "Météo reconstruite"
                                            else -> sensor.room
                                        },
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis
                                    )
                                }
                            }
                        }
                    }
                }

'''
f_one(needle, chooser + needle, 'band chooser')

# Main exploration only uses selected curves.
f_one(
'''                val previewSensorPoints = remember(sampleMap, sensors, previewFrom, previewTo) {
                    sensors.associate { sensor ->
                        sensor.id to sampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in previewWindow }
                            .sortedBy { it.timestamp }
                    }
                }''',
'''                val previewSensorPoints = remember(sampleMap, sensors, bandSensorIds, previewFrom, previewTo) {
                    sensors.filter { it.id in bandSensorIds }.associate { sensor ->
                        sensor.id to sampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in previewWindow }
                            .sortedBy { it.timestamp }
                    }
                }''', 'preview selected curves')

# Existing navigator becomes the daily LOD band and same user selection.
f_one(
'''                val navigatorSensorPoints = remember(sampleMap, sensors, bounds.first, bounds.last) {
                    sensors.associate { sensor ->
                        sensor.id to sampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in bounds }
                            .sortedBy { it.timestamp }
                    }
                }''',
'''                val navigatorSensorPoints = remember(navigatorSampleMap, sensors, bandSensorIds, bounds.first, bounds.last) {
                    sensors.filter { it.id in bandSensorIds }.associate { sensor ->
                        sensor.id to navigatorSampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in bounds }
                            .sortedBy { it.timestamp }
                    }
                }''', 'navigator LOD source')

f_one(
'                    "Navigation globale · glisse la fenêtre",',
'                    "Navigation globale · LOD jour · glisse la fenêtre",', 'navigator label')

# Insert the extra monthly giga layer immediately before the existing daily navigator label.
giga_anchor = '''                Text(
                    "Navigation globale · LOD jour · glisse la fenêtre",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )'''
giga = '''                val gigaSensorPoints = remember(gigaSampleMap, sensors, bandSensorIds, bounds.first, bounds.last) {
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

                Text(
                    "Navigation giga · LOD mois · historique complet",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(34.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.17f), RoundedCornerShape(10.dp))
                        .pointerInput(bounds.first, bounds.last, previewSpan) {
                            detectDragGestures { change, dragAmount ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()
                                previewCenter = clampCenter(previewCenter + deltaTs, previewSpan)
                                change.consume()
                            }
                        }
                        .pointerInput(bounds.first, bounds.last, previewSpan) {
                            detectTapGestures(onTap = { p ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val fraction = (p.x / width).coerceIn(0f, 1f)
                                previewCenter = clampCenter(
                                    bounds.first + (fullSpan * fraction).toLong(),
                                    previewSpan
                                )
                            })
                        }
                ) {
                    gigaSensorPoints.forEach { (sensorId, points) ->
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
                    val left = (((previewFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((previewTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
                    drawRect(
                        highlight.copy(alpha = 0.12f),
                        topLeft = Offset(left, 0f),
                        size = androidx.compose.ui.geometry.Size((right - left).coerceAtLeast(1f), size.height)
                    )
                    drawLine(highlight, Offset(left, 0f), Offset(left, size.height), 1.5.dp.toPx())
                    drawLine(highlight, Offset(right, 0f), Offset(right, size.height), 1.5.dp.toPx())
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDateTime(bounds.first), style = MaterialTheme.typography.labelSmall)
                    Text("ultra simplifié", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(formatDateTime(bounds.last), style = MaterialTheme.typography.labelSmall)
                }

'''
f_one(giga_anchor, giga + giga_anchor, 'giga layer')

# Gaps must remain gaps on all sensor types at overview levels.
f = f.replace(
'''                                    val weatherCurve = sensor.stableKey == LyonWeatherSync.STABLE_KEY ||
                                        sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID
                                    val breakHere = weatherCurve && previous?.let {
                                        point.timestamp - it.timestamp > navigatorGapLimit
                                    } == true''',
'''                                    val breakHere = previous?.let {
                                        point.timestamp - it.timestamp > navigatorGapLimit
                                    } == true''', 1)
f = f.replace(
'''                                    val weatherCurve = sensor.stableKey == LyonWeatherSync.STABLE_KEY ||
                                        sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID
                                    val breakHere = weatherCurve &&
                                        previous?.let { point.timestamp - it.timestamp > previewGapLimit } == true''',
'''                                    val breakHere = previous?.let {
                                        point.timestamp - it.timestamp > previewGapLimit
                                    } == true''', 1)

# The lower 1-week / 1-month preview must be allowed to go down to 6h or detailed span,
# rather than being forced to >=24h.
f = f.replace(
'maxOf(24L * 60L * 60L * 1000L, mainSpan)',
'maxOf(6L * 60L * 60L * 1000L, mainSpan)')

# Put the safely patched function back.
t = t[:start] + f + t[end:]

P.write_text(t, encoding='utf-8')
print('safe v0.21 MainActivity patch applied')
