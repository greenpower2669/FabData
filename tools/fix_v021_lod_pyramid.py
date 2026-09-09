from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

def write(rel, text):
    (ROOT / rel).write_text(text, encoding='utf-8')

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f'missing anchor: {label}')
    return text.replace(old, new, 1)

# -----------------------------------------------------------------------------
# DataLayer: SQL-side LOD. Never load the complete RAW set merely to draw a tiny band.
# -----------------------------------------------------------------------------
rel = 'app/src/main/java/com/fabdata/app/DataLayer.kt'
t = read(rel)
if 'fun querySamplesLod(' not in t:
    marker = '\n    fun stats(sensorId: Long, from: Long, to: Long): SensorStats? {'
    if marker not in t:
        raise SystemExit('DataLayer stats marker missing')
    method = r'''

    /**
     * Courbe LOD calculée directement par SQLite.
     *
     * Contrairement à querySamples(maxPoints), on ne matérialise jamais toutes les RAW
     * en mémoire avant de réduire la courbe. SQLite agrège les buckets et Kotlin ne reçoit
     * que quelques centaines / milliers de points selon le niveau de navigation.
     */
    fun querySamplesLod(
        sensorId: Long,
        from: Long,
        to: Long,
        bucketMs: Long,
        sourceFilter: PointSource? = null
    ): List<SamplePoint> {
        PointSourceStore.ensure(readableDatabase)
        val bucket = bucketMs.coerceAtLeast(60_000L)
        val args = mutableListOf(
            bucket.toString(), bucket.toString(), sensorId.toString(), from.toString(), to.toString()
        )
        val sourceClause = if (sourceFilter != null) {
            args += sourceFilter.dbValue
            " AND COALESCE(ps.source,'measured')=?"
        } else ""
        val out = ArrayList<SamplePoint>()
        readableDatabase.rawQuery(
            """
            SELECT ((p.timestamp / ?) * ?) AS bucket_start,
                   AVG(p.temperature), AVG(p.humidity),
                   COALESCE(ps.source,'measured') AS point_source,
                   AVG(COALESCE(ps.confidence,
                       CASE WHEN COALESCE(ps.source,'measured')='measured' THEN 1.0 ELSE 0.65 END))
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND p.timestamp BETWEEN ? AND ?
              AND COALESCE(ps.source,'measured')<>'forecast'
              $sourceClause
            GROUP BY bucket_start, COALESCE(ps.source,'measured')
            ORDER BY bucket_start
            """.trimIndent(),
            args.toTypedArray()
        ).use { c ->
            while (c.moveToNext()) {
                out += SamplePoint(
                    sensorId = sensorId,
                    timestamp = (c.getLong(0) + bucket / 2L).coerceIn(from, to),
                    temperature = c.getDouble(1),
                    humidity = c.getDouble(2),
                    source = PointSource.fromDb(c.getString(3)),
                    confidence = if (c.isNull(4)) null else c.getDouble(4)
                )
            }
        }
        return out
    }
'''
    t = t.replace(marker, method + marker, 1)
write(rel, t)

# -----------------------------------------------------------------------------
# WeatherReferenceStore: same LOD principle for the selected external reference.
# -----------------------------------------------------------------------------
rel = 'app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt'
t = read(rel)
if 'fun queryLod(' not in t:
    marker = '\n    fun bounds(referenceKey: String): LongRange? {'
    if marker not in t:
        raise SystemExit('WeatherReference bounds marker missing')
    method = r'''

    /** SQL-side overview: grouped before rows cross the SQLite/Kotlin boundary. */
    fun queryLod(
        referenceKey: String,
        from: Long,
        to: Long,
        bucketMs: Long
    ): List<WeatherReferencePoint> {
        val bucket = bucketMs.coerceAtLeast(60_000L)
        val out = mutableListOf<WeatherReferencePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT ((timestamp / ?) * ?) AS bucket_start,
                   AVG(temperature), AVG(humidity), source, AVG(confidence)
            FROM weather_reference_samples
            WHERE reference_key=? AND timestamp BETWEEN ? AND ? AND source<>'forecast'
            GROUP BY bucket_start, source
            ORDER BY bucket_start
            """.trimIndent(),
            arrayOf(bucket.toString(), bucket.toString(), referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += WeatherReferencePoint(
                    timestamp = (c.getLong(0) + bucket / 2L).coerceIn(from, to),
                    temperature = c.getDouble(1),
                    humidity = c.getDouble(2),
                    source = PointSource.fromDb(c.getString(3)),
                    confidence = c.getDouble(4)
                )
            }
        }
        return out
    }
'''
    t = t.replace(marker, method + marker, 1)
write(rel, t)

# -----------------------------------------------------------------------------
# Inertial surface history LOD.
# -----------------------------------------------------------------------------
rel = 'app/src/main/java/com/fabdata/app/ThermalInertiaHistory.kt'
t = read(rel)
if 'fun queryLod(' not in t:
    marker = '\n    fun replaceChunk('
    if marker not in t:
        raise SystemExit('ThermalInertiaHistory replaceChunk marker missing')
    method = r'''

    fun queryLod(
        referenceKey: String,
        sensorId: Long,
        modelSignature: String,
        from: Long,
        to: Long,
        bucketMs: Long
    ): List<SamplePoint> {
        ensure()
        val bucket = bucketMs.coerceAtLeast(60_000L)
        val out = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT ((timestamp / ?) * ?) AS bucket_start,
                   AVG(temperature), AVG(humidity), AVG(confidence)
            FROM thermal_inertia_history
            WHERE reference_key=? AND sensor_id=? AND model_signature=?
              AND timestamp BETWEEN ? AND ?
            GROUP BY bucket_start
            ORDER BY bucket_start
            """.trimIndent(),
            arrayOf(
                bucket.toString(), bucket.toString(), referenceKey, sensorId.toString(), modelSignature,
                from.toString(), to.toString()
            )
        ).use { c ->
            while (c.moveToNext()) {
                out += SamplePoint(
                    sensorId = THERMAL_INERTIA_SENSOR_ID,
                    timestamp = (c.getLong(0) + bucket / 2L).coerceIn(from, to),
                    temperature = c.getDouble(1),
                    humidity = c.getDouble(2),
                    source = PointSource.RECONSTRUCTED,
                    confidence = c.getDouble(3)
                )
            }
        }
        return out
    }
'''
    t = t.replace(marker, method + marker, 1)
write(rel, t)

# -----------------------------------------------------------------------------
# MainActivity: three overview LOD maps + an extra giga navigator + curve chooser.
# -----------------------------------------------------------------------------
rel = 'app/src/main/java/com/fabdata/app/MainActivity.kt'
t = read(rel)

# Preview periods: short windows now belong to the exploration band too.
old = '''private enum class PreviewPreset(val label: String, val spanMs: Long) {
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}'''
new = '''private enum class PreviewPreset(val label: String, val spanMs: Long) {
    W1("1 sem.", 7L * 24L * 60L * 60L * 1000L),
    M1("1 mois", 31L * 24L * 60L * 60L * 1000L),
    M3("3 mois", 92L * 24L * 60L * 60L * 1000L),
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}'''
t = replace_once(t, old, new, 'PreviewPreset')

# Constants / band option model.
anchor = 'private const val LYON_DETAIL_GAP_MS = 90L * 60L * 1000L\n'
insert = '''private const val OVERVIEW_LOD_6H_MS = 6L * 60L * 60L * 1000L
private const val OVERVIEW_LOD_DAY_MS = 24L * 60L * 60L * 1000L
private const val OVERVIEW_LOD_MONTH_MS = 30L * 24L * 60L * 60L * 1000L

private data class OverviewBandOption(
    val key: String,
    val label: String,
    val sensorId: Long,
    val source: PointSource?
)

'''
if 'OVERVIEW_LOD_6H_MS' not in t:
    t = replace_once(t, anchor, insert + anchor, 'LOD constants')

# Helper used for recent inertial projection, already small compared with RAW.
palette_end = '''private val palette = listOf(
    Color(0xFF1769AA), Color(0xFFD1495B), Color(0xFF2A9D8F), Color(0xFFE08E0B),
    Color(0xFF6A4C93), Color(0xFF0081A7), Color(0xFFB56576), Color(0xFF588157),
    Color(0xFF9C27B0), Color(0xFFE91E63), Color(0xFF00BFA5), Color(0xFFC0CA33),
    Color(0xFFFF7043), Color(0xFF3949AB), Color(0xFF8D6E63), Color(0xFF546E7A)
)'''
helper = r'''

private fun simplifySamplesForLod(points: List<SamplePoint>, bucketMs: Long): List<SamplePoint> {
    if (points.isEmpty()) return emptyList()
    val bucket = bucketMs.coerceAtLeast(60_000L)
    return points
        .asSequence()
        .filter { it.source != PointSource.FORECAST }
        .groupBy { (it.timestamp / bucket) * bucket }
        .toSortedMap()
        .map { (start, group) ->
            SamplePoint(
                sensorId = THERMAL_INERTIA_SENSOR_ID,
                timestamp = start + bucket / 2L,
                temperature = group.map { it.temperature }.average(),
                humidity = group.map { it.humidity }.average(),
                source = PointSource.RECONSTRUCTED,
                confidence = group.mapNotNull { it.confidence }.takeIf { it.isNotEmpty() }?.average()
            )
        }
}
'''
if 'private fun simplifySamplesForLod' not in t:
    t = replace_once(t, palette_end, palette_end + helper, 'palette helper')

# LoadedData now carries three independent resolutions.
old = '''private data class LoadedData(
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
)'''
new = '''private data class LoadedData(
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
)'''
t = replace_once(t, old, new, 'LoadedData')

# App state maps.
old = '    var overviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }\n'
new = '''    var gigaOverviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var navigatorOverviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
    var explorationOverviewSampleMap by remember { mutableStateOf<Map<Long, List<SamplePoint>>>(emptyMap()) }
'''
t = replace_once(t, old, new, 'overview states')

# Null-data constructor.
old = '                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null)'
new = '                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null)'
t = replace_once(t, old, new, 'LoadedData empty')

# Replace expensive full-history overview loading with SQL-side pyramid.
start = t.find('                val overview = s.associate { sensor ->')
end = t.find('                val stat = s.mapNotNull { sensor ->', start)
if start < 0 or end < 0:
    raise SystemExit('overview load block missing')
new_block = r'''                fun physicalLod(bucketMs: Long): Map<Long, List<SamplePoint>> =
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

                // Pyramide de résolution : 30 j -> 1 j -> 6 h. Chaque étage est agrégé
                // dans SQLite avant de franchir la frontière vers Kotlin.
                val gigaOverview = physicalLod(OVERVIEW_LOD_MONTH_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_MONTH_MS))
                val navigatorOverview = physicalLod(OVERVIEW_LOD_DAY_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS))
                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS))
'''
t = t[:start] + new_block + t[end:]

# Replace inertia full-history materialisation + LoadedData constructor.
start = t.find('                val inertia = trainedModel?.let { model ->')
end = t.find('            }\n        }\n        sensors = loaded.sensors', start)
if start < 0 or end < 0:
    raise SystemExit('inertia loaded block missing')
# Keep the closing of the withContext branch outside this replacement.
old_tail = t[start:end]
# Need only replace through LoadedData call, not the braces following.
loaded_pos = old_tail.find('                LoadedData(')
if loaded_pos < 0:
    raise SystemExit('LoadedData call missing in inertia block')
# Find end of LoadedData(...) statement by known final text.
call_end_marker = '                )\n'
call_end = old_tail.find(call_end_marker, loaded_pos)
if call_end < 0:
    raise SystemExit('LoadedData call end missing')
call_end += len(call_end_marker)
replace_segment = old_tail[:call_end]
new_segment = r'''                val measuredProjection = trainedModel?.let { model ->
                    runCatching { inertiaEstimator.projectTrained(selectedWeatherReference, model) }.getOrNull()
                }
                val inertia = if (trainedModel != null && measuredProjection != null) {
                    runCatching {
                        // Le graphe détaillé ne matérialise plus l'historique inertiel complet :
                        // seulement la fenêtre détaillée. Les bandeaux utilisent queryLod().
                        val validatedHistory = inertiaHistoryStore.query(
                            selectedWeatherReference.key,
                            trainedModel.sensorId,
                            trainedModel.stableSignature(),
                            chosen.first,
                            chosen.last
                        )
                        measuredProjection.copy(
                            surfacePoints = (validatedHistory + measuredProjection.surfacePoints.filter { it.timestamp in chosen })
                                .associateBy { it.timestamp }
                                .values
                                .sortedBy { it.timestamp }
                        )
                    }.getOrNull()
                } else null

                fun withInertiaLod(
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
                    val recent = simplifySamplesForLod(measuredProjection?.surfacePoints.orEmpty(), bucketMs)
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
                )
'''
old_tail = old_tail.replace(replace_segment, new_segment, 1)
t = t[:start] + old_tail + t[end:]

# Assign maps.
old = '''        overviewSampleMap = loaded.overviewSamples
        statsMap = loaded.stats'''
new = '''        gigaOverviewSampleMap = loaded.gigaOverviewSamples
        navigatorOverviewSampleMap = loaded.navigatorOverviewSamples
        explorationOverviewSampleMap = loaded.explorationOverviewSamples
        statsMap = loaded.stats'''
t = replace_once(t, old, new, 'LoadedData map assignments')

# Replace old in-memory overview/inertia downsampling with three already-LOD chart maps.
start = t.find('    val inertiaOverview = globalBounds?.let { b ->')
end = t.find('\n\n    val activeProcessCount =', start)
if start < 0 or end < 0:
    raise SystemExit('chart overview block missing')
new_block = r'''    val inertiaSensor = Sensor(
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
t = t[:start] + new_block + t[end:]

# HistoryOverviewCard call: three levels + preferred indoor target.
old = '''                    HistoryOverviewCard(
                        sensors = chartSensors,
                        sampleMap = chartOverviewSampleMap,
                        historyBounds = globalBounds,'''
new = '''                    HistoryOverviewCard(
                        sensors = chartSensors,
                        gigaSampleMap = chartGigaOverviewSampleMap,
                        navigatorSampleMap = chartNavigatorOverviewSampleMap,
                        sampleMap = chartExplorationOverviewSampleMap,
                        preferredIndoorSensorId = trainingTargetPrefs.indoorSensorId()
                            ?: inertiaEstimate?.diagnostics?.sourceSensorId,
                        historyBounds = globalBounds,'''
t = replace_once(t, old, new, 'HistoryOverviewCard call')

# Signature.
old = '''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,'''
new = '''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    gigaSampleMap: Map<Long, List<SamplePoint>>,
    navigatorSampleMap: Map<Long, List<SamplePoint>>,
    sampleMap: Map<Long, List<SamplePoint>>,
    preferredIndoorSensorId: Long?,
    historyBounds: LongRange?,'''
t = replace_once(t, old, new, 'HistoryOverviewCard signature')

# Navigator center state beside preview center.
old = '''                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                var rangeSelectionMode'''
new = '''                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                var navigatorCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }
                var rangeSelectionMode'''
t = replace_once(t, old, new, 'navigator center state')

# Add band options after help prefs are available.
anchor = '''                val helpPrefs = remember {
                    helpContext.getSharedPreferences("fabdata_context_help", Context.MODE_PRIVATE)
                }
'''
insert = r'''                val overviewPrefs = remember {
                    helpContext.getSharedPreferences("fabdata_overview_band_curves", Context.MODE_PRIVATE)
                }
                val bandOptions = remember(sensors, sampleMap) {
                    buildList {
                        sensors.forEach { sensor ->
                            val points = sampleMap[sensor.id].orEmpty()
                            if (points.isEmpty()) return@forEach
                            when (sensor.id) {
                                THERMAL_INERTIA_SENSOR_ID -> add(
                                    OverviewBandOption("inertia", "Sol inertiel", sensor.id, null)
                                )
                                WEATHER_OFFICIAL_SENSOR_ID -> add(
                                    OverviewBandOption("weather-real", "Météo officielle", sensor.id, null)
                                )
                                LYON_RECONSTRUCTED_SENSOR_ID -> add(
                                    OverviewBandOption("weather-recon", "Météo reconstruite", sensor.id, null)
                                )
                                else -> {
                                    if (points.any { it.source == PointSource.MEASURED }) {
                                        add(OverviewBandOption(
                                            "sensor:${sensor.id}:real", "${sensor.room} · réel",
                                            sensor.id, PointSource.MEASURED
                                        ))
                                    }
                                    if (points.any { it.source == PointSource.RECONSTRUCTED }) {
                                        add(OverviewBandOption(
                                            "sensor:${sensor.id}:recon", "${sensor.room} · reconstruit",
                                            sensor.id, PointSource.RECONSTRUCTED
                                        ))
                                    }
                                }
                            }
                        }
                    }
                }
                val bandOptionSignature = remember(bandOptions) { bandOptions.joinToString("|") { it.key } }
                var selectedBandKeys by remember(bandOptionSignature, preferredIndoorSensorId) {
                    val valid = bandOptions.map { it.key }.toSet()
                    val configured = overviewPrefs.getBoolean("configured", false)
                    val stored = overviewPrefs.getStringSet("keys", emptySet()).orEmpty().intersect(valid)
                    val preferredRecon = bandOptions.firstOrNull {
                        it.sensorId == preferredIndoorSensorId && it.source == PointSource.RECONSTRUCTED
                    }?.key
                    val inertia = bandOptions.firstOrNull { it.sensorId == THERMAL_INERTIA_SENSOR_ID }?.key
                    val fallbackRecon = bandOptions.firstOrNull {
                        it.source == PointSource.RECONSTRUCTED && it.sensorId >= 0L
                    }?.key
                    val defaults = linkedSetOf<String>().apply {
                        preferredRecon?.let { add(it) }
                        if (isEmpty()) fallbackRecon?.let { add(it) }
                        inertia?.let { add(it) }
                        if (isEmpty()) bandOptions.firstOrNull()?.key?.let { add(it) }
                    }
                    mutableStateOf(if (configured) stored else defaults)
                }
                var bandChooserOpen by rememberSaveable { mutableStateOf(false) }

                fun saveBandSelection(next: Set<String>) {
                    selectedBandKeys = next
                    overviewPrefs.edit()
                        .putBoolean("configured", true)
                        .putStringSet("keys", next)
                        .apply()
                }

                fun curvePoints(
                    sourceMap: Map<Long, List<SamplePoint>>,
                    option: OverviewBandOption,
                    range: LongRange
                ): List<SamplePoint> = sourceMap[option.sensorId].orEmpty()
                    .asSequence()
                    .filter { it.timestamp in range }
                    .filter { option.source == null || it.source == option.source }
                    .sortedBy { it.timestamp }
                    .toList()
'''
t = replace_once(t, anchor, anchor + insert, 'overview band options')

# Add chooser under preset row (before range action row).
needle = '''                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    AssistChip('''
chooser = r'''                OutlinedButton(
                    onClick = { bandChooserOpen = !bandChooserOpen },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Courbes du bandeau · ${selectedBandKeys.size} sélectionnée(s)")
                }
                if (bandChooserOpen) {
                    Card(
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.38f)
                        )
                    ) {
                        Column(
                            Modifier.fillMaxWidth().padding(8.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp)
                        ) {
                            Text(
                                "Chaque niveau utilise la même sélection, mais avec une résolution différente.",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            bandOptions.forEach { option ->
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                    Checkbox(
                                        checked = option.key in selectedBandKeys,
                                        onCheckedChange = { checked ->
                                            val next = selectedBandKeys.toMutableSet()
                                            if (checked) next += option.key else next -= option.key
                                            saveBandSelection(next)
                                        }
                                    )
                                    Text(option.label, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                            }
                        }
                    }
                }

'''
t = replace_once(t, needle, chooser + needle, 'band chooser UI')

# Replace span / preview point preparation up to navigator styling.
start = t.find('                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)')
end = t.find('                val highlight = MaterialTheme.colorScheme.primary', start)
if start < 0 or end < 0:
    raise SystemExit('span preparation block missing')
new = r'''                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)
                val maxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)
                val mainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }
                    ?: (24L * 60L * 60L * 1000L)
                val minSpan = minOf(maxSpan, maxOf(6L * 60L * 60L * 1000L, mainSpan))
                val maxZoom = (maxSpan.toDouble() / minSpan.toDouble()).toFloat().coerceAtLeast(1f)
                val effectiveZoom = previewZoom.coerceIn(1f, maxZoom)
                val previewSpan = (maxSpan.toDouble() / effectiveZoom.toDouble()).toLong()
                    .coerceIn(minSpan, maxSpan)

                fun clampCenterIn(range: LongRange, value: Long, span: Long): Long {
                    val rangeSpan = (range.last - range.first).coerceAtLeast(1L)
                    if (span >= rangeSpan) return range.first + rangeSpan / 2L
                    val half = span / 2L
                    return value.coerceIn(range.first + half, range.last - (span - half))
                }
                fun windowAround(range: LongRange, center: Long, span: Long): LongRange {
                    val rangeSpan = (range.last - range.first).coerceAtLeast(1L)
                    if (span >= rangeSpan) return range
                    val c = clampCenterIn(range, center, span)
                    val start = c - span / 2L
                    return start..(start + span)
                }

                // Niveau intermédiaire : au moins 12 mois pour garder de la marge autour
                // de 1 semaine / 1 mois, mais jamais plus petit que le bandeau exploré.
                val navigatorSpan = minOf(
                    fullSpan,
                    maxOf(previewPreset.spanMs, 366L * 24L * 60L * 60L * 1000L)
                ).coerceAtLeast(previewSpan)
                val navigatorWindow = windowAround(bounds, navigatorCenter, navigatorSpan)
                val effectiveCenter = clampCenterIn(navigatorWindow, previewCenter, previewSpan)
                val previewWindow = windowAround(navigatorWindow, effectiveCenter, previewSpan)
                val previewFrom = previewWindow.first
                val previewTo = previewWindow.last

                val selectedOptions = bandOptions.filter { it.key in selectedBandKeys }
                val previewCurves = remember(sampleMap, bandOptionSignature, selectedBandKeys, previewFrom, previewTo) {
                    selectedOptions.associate { option ->
                        option.key to curvePoints(sampleMap, option, previewWindow)
                    }
                }
                val visiblePoints = remember(previewCurves) { previewCurves.values.flatten() }
                val minPoint = visiblePoints.minByOrNull { it.temperature }
                val maxPoint = visiblePoints.maxByOrNull { it.temperature }
                val minTemp = minPoint?.temperature ?: 0.0
                val maxTemp = maxPoint?.temperature ?: 1.0
                val tempRange = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0
'''
t = t[:start] + new + t[end:]

# Replace navigator data preparation through label with GIGA + intermediate preparation.
start = t.find('                // Bandeau d\'exploration DU bandeau d\'exploration.')
end = t.find('                if (minPoint != null && maxPoint != null) {', start)
if start < 0 or end < 0:
    raise SystemExit('navigator section missing')
new = r'''                // Niveau 1 : GIGA. Environ un point / mois. Son seul rôle est de
                // déplacer la fenêtre du niveau intermédiaire, même sur 5-10 ans.
                val gigaCurves = remember(gigaSampleMap, bandOptionSignature, selectedBandKeys, bounds.first, bounds.last) {
                    selectedOptions.associate { option -> option.key to curvePoints(gigaSampleMap, option, bounds) }
                }
                val gigaAll = gigaCurves.values.flatten()
                val gigaMin = gigaAll.minOfOrNull { it.temperature } ?: 0.0
                val gigaMax = gigaAll.maxOfOrNull { it.temperature } ?: 1.0
                val gigaRange = (gigaMax - gigaMin).takeIf { it > 0.01 } ?: 1.0

                Text(
                    "Navigation giga · historique ultra simplifié",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(34.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.18f), RoundedCornerShape(10.dp))
                        .pointerInput(bounds.first, bounds.last, navigatorSpan) {
                            detectDragGestures { change, dragAmount ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()
                                navigatorCenter = clampCenterIn(bounds, navigatorCenter + deltaTs, navigatorSpan)
                                previewCenter = navigatorCenter
                                change.consume()
                            }
                        }
                        .pointerInput(bounds.first, bounds.last, navigatorSpan) {
                            detectTapGestures(onTap = { p ->
                                val fraction = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                val target = bounds.first + (fullSpan * fraction).toLong()
                                navigatorCenter = clampCenterIn(bounds, target, navigatorSpan)
                                previewCenter = navigatorCenter
                            })
                        }
                ) {
                    selectedOptions.forEach { option ->
                        val points = gigaCurves[option.key].orEmpty()
                        if (points.size >= 2) {
                            val sensor = sensors.firstOrNull { it.id == option.sensorId } ?: return@forEach
                            val path = Path()
                            var previous: SamplePoint? = null
                            val gapLimit = maxOf(60L * 24L * 60L * 60L * 1000L, fullSpan / 80L)
                            points.forEach { point ->
                                val x = (((point.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                                    .coerceIn(0f, size.width)
                                val y = size.height - (((point.temperature - gigaMin) / gigaRange).toFloat() * size.height)
                                if (previous == null || point.timestamp - previous!!.timestamp > gapLimit) path.moveTo(x, y)
                                else path.lineTo(x, y)
                                previous = point
                            }
                            drawPath(path, palette[sensor.colorIndex % palette.size].copy(alpha = 0.34f), style = Stroke(0.8.dp.toPx()))
                        }
                    }
                    val left = (((navigatorWindow.first - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((navigatorWindow.last - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
                    drawRect(highlight.copy(alpha = 0.12f), Offset(left, 0f), androidx.compose.ui.geometry.Size((right-left).coerceAtLeast(1f), size.height))
                    drawLine(highlight, Offset(left, 0f), Offset(left, size.height), 1.5.dp.toPx())
                    drawLine(highlight, Offset(right, 0f), Offset(right, size.height), 1.5.dp.toPx())
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDateTime(bounds.first), style = MaterialTheme.typography.labelSmall)
                    Text("LOD mois", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(formatDateTime(bounds.last), style = MaterialTheme.typography.labelSmall)
                }

                // Niveau 2 : navigation intermédiaire, un point environ par jour.
                val navigatorCurves = remember(
                    navigatorSampleMap, bandOptionSignature, selectedBandKeys,
                    navigatorWindow.first, navigatorWindow.last
                ) {
                    selectedOptions.associate { option ->
                        option.key to curvePoints(navigatorSampleMap, option, navigatorWindow)
                    }
                }
                val navigatorAllPoints = navigatorCurves.values.flatten()
                val navigatorMin = navigatorAllPoints.minOfOrNull { it.temperature } ?: 0.0
                val navigatorMax = navigatorAllPoints.maxOfOrNull { it.temperature } ?: 1.0
                val navigatorTempRange = (navigatorMax - navigatorMin).takeIf { it > 0.01 } ?: 1.0

                Text(
                    "Navigation intermédiaire · glisse la fenêtre",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(58.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.22f), RoundedCornerShape(12.dp))
                        .pointerInput(navigatorWindow.first, navigatorWindow.last, previewSpan) {
                            detectDragGestures { change, dragAmount ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val deltaTs = ((dragAmount.x / width) * navigatorSpan.toDouble()).toLong()
                                previewCenter = clampCenterIn(navigatorWindow, previewCenter + deltaTs, previewSpan)
                                change.consume()
                            }
                        }
                        .pointerInput(navigatorWindow.first, navigatorWindow.last, previewSpan) {
                            detectTapGestures(onTap = { p ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val fraction = (p.x / width).coerceIn(0f, 1f)
                                val target = navigatorWindow.first + (navigatorSpan * fraction).toLong()
                                previewCenter = clampCenterIn(navigatorWindow, target, previewSpan)
                            })
                        }
                ) {
                    selectedOptions.forEach { option ->
                        val points = navigatorCurves[option.key].orEmpty()
                        if (points.size >= 2) {
                            val sensor = sensors.firstOrNull { it.id == option.sensorId } ?: return@forEach
                            val path = Path()
                            var previous: SamplePoint? = null
                            val gapLimit = maxOf(3L * OVERVIEW_LOD_DAY_MS, navigatorSpan / 120L)
                            points.forEach { point ->
                                val x = (((point.timestamp - navigatorWindow.first).toDouble() / navigatorSpan.toDouble()).toFloat() * size.width)
                                    .coerceIn(0f, size.width)
                                val y = size.height - (((point.temperature - navigatorMin) / navigatorTempRange).toFloat() * size.height)
                                if (previous == null || point.timestamp - previous!!.timestamp > gapLimit) path.moveTo(x, y)
                                else path.lineTo(x, y)
                                previous = point
                            }
                            drawPath(path, palette[sensor.colorIndex % palette.size].copy(alpha = 0.42f), style = Stroke(width = 1.dp.toPx()))
                        }
                    }

                    val left = (((previewFrom - navigatorWindow.first).toDouble() / navigatorSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((previewTo - navigatorWindow.first).toDouble() / navigatorSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
                    if (left > 0f) drawRect(navigatorDim, Offset(0f, 0f), androidx.compose.ui.geometry.Size(left, size.height))
                    if (right < size.width) drawRect(navigatorDim, Offset(right, 0f), androidx.compose.ui.geometry.Size(size.width-right, size.height))
                    drawRect(highlight.copy(alpha = 0.16f), Offset(left, 0f), androidx.compose.ui.geometry.Size((right-left).coerceAtLeast(1f), size.height))
                    drawLine(highlight, Offset(left, 0f), Offset(left, size.height), 2.dp.toPx())
                    drawLine(highlight, Offset(right, 0f), Offset(right, size.height), 2.dp.toPx())
                    val handleX = (left + right) / 2f
                    drawLine(highlight.copy(alpha = 0.9f), Offset(handleX - 5.dp.toPx(), size.height/2f), Offset(handleX + 5.dp.toPx(), size.height/2f), 2.dp.toPx())
                    drawCircle(highlight, 3.5.dp.toPx(), Offset(handleX, size.height/2f))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDateTime(navigatorWindow.first), style = MaterialTheme.typography.labelSmall)
                    Text("LOD jour", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(formatDateTime(navigatorWindow.last), style = MaterialTheme.typography.labelSmall)
                }

'''
t = t[:start] + new + t[end:]

# Main preview drawing: use selected options/curves, not every series.
old_start = '''                    if (visiblePoints.isNotEmpty()) {
                        sensors.forEach { sensor ->
                            val points = previewSensorPoints[sensor.id].orEmpty()
                            if (points.size >= 2) {'''
new_start = '''                    if (visiblePoints.isNotEmpty()) {
                        selectedOptions.forEach { option ->
                            val sensor = sensors.firstOrNull { it.id == option.sensorId } ?: return@forEach
                            val points = previewCurves[option.key].orEmpty()
                            if (points.size >= 2) {'''
t = replace_once(t, old_start, new_start, 'preview selected curves')

# Generic curve gap break (not weather-only) for LOD preview. Replace the exact weather flag block.
old = '''                                    val weatherCurve = sensor.stableKey == LyonWeatherSync.STABLE_KEY ||
                                        sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID
                                    val breakHere = weatherCurve && previous?.let {
                                        point.timestamp - it.timestamp > previewGapLimit
                                    } == true'''
new = '''                                    val breakHere = previous?.let {
                                        point.timestamp - it.timestamp > previewGapLimit
                                    } == true'''
if old in t:
    t = t.replace(old, new, 1)

# Update card text to explain the pyramid.
old = '                "Bandeau fin = déplacer la fenêtre · bandeau principal = viser/sélectionner · pince = zoom de prévisu",'
new = '                "Giga = années · intermédiaire = grande fenêtre · bandeau principal = viser/sélectionner · chaque étage est simplifié",'
t = replace_once(t, old, new, 'overview hint')

# -----------------------------------------------------------------------------
# Live update: a Compose cancellation is lifecycle, not a network failure.
# -----------------------------------------------------------------------------
rel_live = 'app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt'
live = read(rel_live)
if 'import kotlinx.coroutines.CancellationException' not in live:
    live = live.replace('import kotlinx.coroutines.Dispatchers\n', 'import kotlinx.coroutines.CancellationException\nimport kotlinx.coroutines.Dispatchers\n', 1)
old = '''        } catch (error: Throwable) {
            FabOperationRegistry.fail(operationId, error.message ?: "Mise à jour automatique impossible")
            false
        } finally {'''
new = '''        } catch (cancel: CancellationException) {
            FabOperationRegistry.cancelled(operationId, "Routine remplacée / composition quittée")
            throw cancel
        } catch (error: Throwable) {
            FabOperationRegistry.fail(operationId, error.message ?: "Mise à jour automatique impossible")
            false
        } finally {'''
live = replace_once(live, old, new, 'cancellation handling')
write(rel_live, live)

# Version.
rel_gradle = 'app/build.gradle.kts'
g = read(rel_gradle)
g = replace_once(g, 'versionCode = 45', 'versionCode = 46', 'versionCode')
g = replace_once(g, 'versionName = "0.20.9"', 'versionName = "0.21.0"', 'versionName')
write(rel_gradle, g)

write(rel, t)
print('v0.21 LOD pyramid patch applied')
