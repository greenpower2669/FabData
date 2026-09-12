from pathlib import Path
import re


def replace_once(path: str, old: str, new: str, marker: str) -> None:
    p = Path(path)
    s = p.read_text()
    if marker in s:
        return
    if old not in s:
        raise SystemExit(f"missing patch anchor {marker} in {path}")
    p.write_text(s.replace(old, new, 1))


# --- Version ---
build = Path("app/build.gradle.kts")
s = build.read_text()
s = s.replace('versionCode = 52', 'versionCode = 53', 1)
s = s.replace('versionName = "0.21.6"', 'versionName = "0.21.7"', 1)
build.write_text(s)


# --- Prediction history: past MUST be fixed-lead H+24, never the old near-H+1 local replay. ---
curves = Path("app/src/main/java/com/fabdata/app/ForecastSelectableCurves.kt")
s = curves.read_text()
s = s.replace(
    " * Weather curve priority:\n * 1. immutable snapshots really captured by FabData;\n * 2. API historical-forecast backfill for older missing hours;\n * 3. active future forecast.",
    " * Weather curve priority:\n * 1. past = fixed-lead Météo-France H+24 archive only;\n * 2. future = the currently active forecast captured by FabData.\n * Old near-H+1 replay snapshots are deliberately excluded from past verification.",
)
pattern = re.compile(r"        buckets\.forEach \{ bucket ->.*?\n        \}\n\n        val generatedWeather", re.S)
if "past = fixed-lead Météo-France H+24 archive only" not in s or "val nowBucket = forecastCurveHourBucket(now)" not in s:
    match = pattern.search(s)
    if not match:
        raise SystemExit("missing forecast bucket selection block")
    replacement = '''        val nowBucket = forecastCurveHourBucket(now)\n        buckets.forEach { bucket ->\n            val actual = actualByBucket[bucket]\n            val backfilled = backfillByBucket[bucket]\n\n            if (bucket <= nowBucket) {\n                // Scientific comparison: never fall back to the old H+1-ish local replay.\n                // If H+24 history is unavailable, leave a visible gap instead of inventing history.\n                backfilled?.let { p ->\n                    reconstructedAnchors += SamplePoint(\n                        sensorId = FORECAST_RECONSTRUCTED_SENSOR_ID,\n                        timestamp = p.targetAt,\n                        temperature = p.weatherTemperature,\n                        humidity = p.humidity,\n                        source = PointSource.FORECAST,\n                        confidence = p.weatherConfidence\n                    )\n                    fabAnchors += SamplePoint(\n                        sensorId = FORECAST_FAB_SENSOR_ID,\n                        timestamp = p.targetAt,\n                        temperature = p.fabTemperature,\n                        humidity = p.humidity,\n                        source = PointSource.FORECAST,\n                        confidence = p.fabConfidence\n                    )\n                }\n            } else if (actual != null) {\n                // Future side stays live/current.\n                reconstructedAnchors += SamplePoint(\n                    sensorId = FORECAST_RECONSTRUCTED_SENSOR_ID,\n                    timestamp = actual.targetAt,\n                    temperature = actual.temperature,\n                    humidity = actual.humidity,\n                    source = PointSource.FORECAST,\n                    confidence = actual.confidence\n                )\n                val local = localByKey[actual.issuedAt to actual.targetAt]\n                fabAnchors += SamplePoint(\n                    sensorId = FORECAST_FAB_SENSOR_ID,\n                    timestamp = actual.targetAt,\n                    temperature = local?.first ?: actual.temperature,\n                    humidity = actual.humidity,\n                    source = PointSource.FORECAST,\n                    confidence = local?.second ?: actual.confidence * 0.45\n                )\n            }\n        }\n\n        val generatedWeather'''
    s = pattern.sub(replacement, s, count=1)
curves.write_text(s)


# --- Main UI: one terrain curve, measured wins over reconstructed; same prediction IDs in every LOD. ---
main = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
s = main.read_text()

if "mergeTerrainReference" not in s:
    insert_at = s.index("private fun navigationWeatherPoints")
    helper = '''private fun mergeTerrainReference(\n    measured: List<SamplePoint>,\n    reconstructed: List<SamplePoint>\n): List<SamplePoint> {\n    if (measured.isEmpty()) {\n        return reconstructed.map { it.copy(sensorId = LYON_RECONSTRUCTED_SENSOR_ID) }.sortedBy { it.timestamp }\n    }\n    val tolerance = 36L * 60L * 1000L\n    val measuredTimes = measured.map { it.timestamp }.sorted()\n    fun hasMeasuredNear(timestamp: Long): Boolean {\n        val index = measuredTimes.binarySearch(timestamp)\n        if (index >= 0) return true\n        val insertion = -index - 1\n        val before = measuredTimes.getOrNull(insertion - 1)\n        val after = measuredTimes.getOrNull(insertion)\n        return (before != null && kotlin.math.abs(before - timestamp) <= tolerance) ||\n            (after != null && kotlin.math.abs(after - timestamp) <= tolerance)\n    }\n    val fallback = reconstructed.filterNot { hasMeasuredNear(it.timestamp) }\n    return (fallback + measured)\n        .map { it.copy(sensorId = LYON_RECONSTRUCTED_SENSOR_ID) }\n        .associateBy { it.timestamp }\n        .values\n        .sortedBy { it.timestamp }\n}\n\n'''
    s = s[:insert_at] + helper + s[insert_at:]

old_weather_block = '''    val weatherOfficialSensor = Sensor(\n        id = WEATHER_OFFICIAL_SENSOR_ID,\n        stableKey = WEATHER_OFFICIAL_STABLE_KEY,\n        name = "Station météo officielle",\n        room = visualReference.label,\n        colorIndex = 2,\n        latestTimestamp = weatherOfficialSamples.lastOrNull()?.timestamp\n    )\n    val lyonReconstructedSensor = Sensor(\n        id = LYON_RECONSTRUCTED_SENSOR_ID,\n        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,\n        name = "Station météo reconstruite",\n        room = visualReference.label,\n        colorIndex = 3,\n        latestTimestamp = weatherReconstructedSamples.lastOrNull()?.timestamp\n    )'''
new_weather_block = '''    val terrainWeatherSamples = mergeTerrainReference(weatherOfficialSamples, weatherReconstructedSamples)\n    val lyonReconstructedSensor = Sensor(\n        id = LYON_RECONSTRUCTED_SENSOR_ID,\n        stableKey = LYON_RECONSTRUCTED_STABLE_KEY,\n        name = "Référence terrain",\n        room = "${visualReference.label} · réel prioritaire + reconstruction",\n        colorIndex = 2,\n        latestTimestamp = terrainWeatherSamples.lastOrNull()?.timestamp\n    )'''
if old_weather_block in s:
    s = s.replace(old_weather_block, new_weather_block, 1)
elif "val terrainWeatherSamples = mergeTerrainReference" not in s:
    raise SystemExit("missing weather sensor block")

s = s.replace(
    'val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo reconstruite", "Passé Météo-France H+24 · futur actif · rendu 10 min", 13, forecastReconstructedSamples.lastOrNull()?.timestamp)',
    'val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo H+24", "Passé Météo-France H+24 · futur actif · rendu 10 min", 12, forecastReconstructedSamples.lastOrNull()?.timestamp)',
)
s = s.replace(
    'val forecastFabSensor = Sensor(FORECAST_FAB_SENSOR_ID, FORECAST_FAB_STABLE_KEY, "Prévision Fab reconstruite", "Correction locale H+24 · rendu 10 min", 8, forecastFabSamples.lastOrNull()?.timestamp)',
    'val forecastFabSensor = Sensor(FORECAST_FAB_SENSOR_ID, FORECAST_FAB_STABLE_KEY, "Prévision Fab H+24", "Correction locale H+24 · rendu 10 min", 11, forecastFabSamples.lastOrNull()?.timestamp)',
)

old_maps = '''    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }\n    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + forecastReconstructedSensor + forecastFabSensor + inertiaSensor\n    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +\n        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +\n        (FORECAST_RECONSTRUCTED_SENSOR_ID to forecastReconstructedSamples) +\n        (FORECAST_FAB_SENSOR_ID to forecastFabSamples) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)\n\n    fun chartLodMap(source: Map<Long, List<SamplePoint>>): Map<Long, List<SamplePoint>> {\n        val reference = source[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()\n        return source.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n            (WEATHER_OFFICIAL_SENSOR_ID to reference.filter { it.source == PointSource.MEASURED }\n                .map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +\n            (LYON_RECONSTRUCTED_SENSOR_ID to reference.filter { it.source == PointSource.RECONSTRUCTED }\n                .map { it.copy(sensorId = LYON_RECONSTRUCTED_SENSOR_ID) }) +\n            (THERMAL_INERTIA_SENSOR_ID to source[THERMAL_INERTIA_SENSOR_ID].orEmpty())\n    }\n    val chartGigaOverviewSampleMap = chartLodMap(gigaOverviewSampleMap)\n    val chartNavigatorOverviewSampleMap = chartLodMap(navigatorOverviewSampleMap)\n    val chartExplorationOverviewSampleMap = chartLodMap(explorationOverviewSampleMap)'''
new_maps = '''    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }\n    val chartSensors = physicalChartSensors + lyonReconstructedSensor + forecastReconstructedSensor + forecastFabSensor + inertiaSensor\n    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (LYON_RECONSTRUCTED_SENSOR_ID to terrainWeatherSamples) +\n        (FORECAST_RECONSTRUCTED_SENSOR_ID to forecastReconstructedSamples) +\n        (FORECAST_FAB_SENSOR_ID to forecastFabSamples) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)\n\n    fun predictionLod(points: List<SamplePoint>, bucketMs: Long): List<SamplePoint> =\n        points.groupBy { (it.timestamp / bucketMs) * bucketMs }\n            .mapNotNull { (bucket, values) ->\n                if (values.isEmpty()) null else SamplePoint(\n                    sensorId = values.first().sensorId,\n                    timestamp = bucket + bucketMs / 2L,\n                    temperature = values.map { it.temperature }.average(),\n                    humidity = values.map { it.humidity }.average(),\n                    source = PointSource.FORECAST,\n                    confidence = values.mapNotNull { it.confidence }.takeIf { it.isNotEmpty() }?.average()\n                )\n            }\n            .sortedBy { it.timestamp }\n\n    fun chartLodMap(source: Map<Long, List<SamplePoint>>, bucketMs: Long): Map<Long, List<SamplePoint>> {\n        val reference = source[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()\n        val measured = reference.filter { it.source == PointSource.MEASURED }\n        val reconstructed = reference.filter { it.source == PointSource.RECONSTRUCTED }\n        val terrain = if (reference.isNotEmpty()) mergeTerrainReference(measured, reconstructed)\n            else predictionLod(terrainWeatherSamples, bucketMs).map { it.copy(source = PointSource.RECONSTRUCTED) }\n        return source.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n            (LYON_RECONSTRUCTED_SENSOR_ID to terrain) +\n            (FORECAST_RECONSTRUCTED_SENSOR_ID to predictionLod(forecastReconstructedSamples, bucketMs)) +\n            (FORECAST_FAB_SENSOR_ID to predictionLod(forecastFabSamples, bucketMs)) +\n            (THERMAL_INERTIA_SENSOR_ID to source[THERMAL_INERTIA_SENSOR_ID].orEmpty())\n    }\n    val chartGigaOverviewSampleMap = chartLodMap(gigaOverviewSampleMap, OVERVIEW_LOD_MONTH_MS)\n    val chartNavigatorOverviewSampleMap = chartLodMap(navigatorOverviewSampleMap, OVERVIEW_LOD_DAY_MS)\n    val chartExplorationOverviewSampleMap = chartLodMap(explorationOverviewSampleMap, OVERVIEW_LOD_6H_MS)'''
if old_maps in s:
    s = s.replace(old_maps, new_maps, 1)
elif "fun predictionLod(points: List<SamplePoint>" not in s:
    raise SystemExit("missing chart map block")

s = s.replace('LYON_RECONSTRUCTED_SENSOR_ID -> "Station météo reconstruite"', 'LYON_RECONSTRUCTED_SENSOR_ID -> "Référence terrain · réel > reconstruit"')
s = s.replace('FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision météo reconstruite"', 'FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision météo H+24"')
s = s.replace('FORECAST_FAB_SENSOR_ID -> "Prévision Fab reconstruite"', 'FORECAST_FAB_SENSOR_ID -> "Prévision Fab H+24"')
s = s.replace('"Chaque pièce peut afficher T°, humidité, les deux ou aucune."', '"Chaque courbe est indépendante : terrain, prévision météo, prévision Fab et sol inertiel."')
main.write_text(s)


# --- Tangent dials: use the SAME H+24/Fab curves and terrain fallback as the main chart. ---
overlay = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")
s = overlay.read_text()

if "private data class TerrainDialPoint" not in s:
    s = s.replace(
        '''private data class ArchivedForecast(\n    val issuedAt: Long,\n    val targetTs: Long,\n    val temperature: Double,\n    val humidity: Double,\n    val confidence: Double\n)\n''',
        '''private data class ArchivedForecast(\n    val issuedAt: Long,\n    val targetTs: Long,\n    val temperature: Double,\n    val humidity: Double,\n    val confidence: Double\n)\n\nprivate data class TerrainDialPoint(\n    val temperature: Double,\n    val measured: Boolean\n)\n\nprivate data class CurveKinematics(\n    val temperature: Double,\n    val slope: Double?,\n    val acceleration: Double?\n)\n''',
        1,
    )

if "val actualIsMeasured: Boolean" not in s:
    s = s.replace('    val actualTemp: Double?,\n    val officialSlope:', '    val actualTemp: Double?,\n    val actualIsMeasured: Boolean,\n    val officialSlope:', 1)

load_pattern = re.compile(r"    fun load\(now: Long = System\.currentTimeMillis\(\)\): DialState \{.*?\n    \}\n\n    private fun buildDial\(.*?\n    \}\n\n    /\*\* Pick the snapshot", re.S)
if "Passé = H+24 fixe" not in s:
    match = load_pattern.search(s)
    if not match:
        raise SystemExit("missing dial load/build block")
    replacement = '''    fun load(now: Long = System.currentTimeMillis()): DialState {\n        ForecastMemoryStore.ensure(db.writableDatabase)\n        val reference = WeatherReferencePrefs(appContext).selectedReference()\n        runCatching {\n            ForecastPastArchiveBackfill(db).ensure(reference, now - 4L * HOUR_MS, now - HOUR_MS, now)\n        }\n        val curves = runCatching {\n            ForecastSelectableCurveStore(db).query(reference.key, now - 4L * HOUR_MS, now + 3L * HOUR_MS, now)\n        }.getOrDefault(ForecastSelectableCurves.EMPTY)\n        val nowHour = hourBucket(now)\n        val targets = listOf(\n            "PASSÉ" to (nowHour - HOUR_MS),\n            "PRÉSENT" to nowHour,\n            "FUTUR" to (nowHour + HOUR_MS)\n        )\n        // Passé = H+24 fixe; futur = prévision active. Terrain = réel prioritaire, reconstruction sinon.\n        val result = targets.map { (label, target) -> buildDial(reference.key, label, target, curves) }\n        return DialState(reference.label, result)\n    }\n\n    private fun buildDial(\n        referenceKey: String,\n        label: String,\n        target: Long,\n        curves: ForecastSelectableCurves\n    ): DialSample {\n        val official = curveKinematics(curves.reconstructed, target)\n        val local = curveKinematics(curves.fab, target)\n        val terrain = terrainAt(referenceKey, target)\n        val actual = terrain?.temperature\n        val actualSlope = if (terrain != null) terrainSlope(referenceKey, target) else null\n        val actualAcceleration = if (terrain != null) terrainAcceleration(referenceKey, target) else null\n        val officialError = if (official != null && actual != null) abs(official.temperature - actual) else null\n        val localError = if (local != null && actual != null) abs(local.temperature - actual) else null\n\n        return DialSample(\n            label = label,\n            targetTs = target,\n            officialTemp = official?.temperature,\n            localTemp = local?.temperature,\n            actualTemp = actual,\n            actualIsMeasured = terrain?.measured == true,\n            officialSlope = official?.slope,\n            localSlope = local?.slope,\n            actualSlope = actualSlope,\n            officialAcceleration = official?.acceleration,\n            localAcceleration = local?.acceleration,\n            actualAcceleration = actualAcceleration,\n            officialError = officialError,\n            localError = localError,\n            trainingSamples = 0\n        )\n    }\n\n    private fun curveKinematics(points: List<SamplePoint>, target: Long): CurveKinematics? {\n        fun nearest(at: Long): SamplePoint? = points.minByOrNull { abs(it.timestamp - at) }\n            ?.takeIf { abs(it.timestamp - at) <= 22L * 60L * 1000L }\n        val center = nearest(target) ?: return null\n        val previous = nearest(target - HOUR_MS)\n        val next = nearest(target + HOUR_MS)\n        val slope = when {\n            previous != null && next != null -> (next.temperature - previous.temperature) / 2.0\n            next != null -> next.temperature - center.temperature\n            previous != null -> center.temperature - previous.temperature\n            else -> null\n        }?.coerceIn(-3.0, 3.0)\n        val acceleration = if (previous != null && next != null)\n            (next.temperature - 2.0 * center.temperature + previous.temperature).coerceIn(-1.5, 1.5)\n        else null\n        return CurveKinematics(center.temperature, slope, acceleration)\n    }\n\n    private fun terrainAt(referenceKey: String, target: Long): TerrainDialPoint? {\n        fun query(source: String, tolerance: Long, measured: Boolean): TerrainDialPoint? =\n            db.readableDatabase.rawQuery(\n                """\n                SELECT temperature\n                FROM weather_reference_samples\n                WHERE reference_key=? AND source=? AND timestamp BETWEEN ? AND ?\n                ORDER BY ABS(timestamp-?) ASC\n                LIMIT 1\n                """.trimIndent(),\n                arrayOf(\n                    referenceKey, source,\n                    (target - tolerance).toString(), (target + tolerance).toString(), target.toString()\n                )\n            ).use { c -> if (c.moveToFirst()) TerrainDialPoint(c.getDouble(0), measured) else null }\n\n        return query("measured", 36L * 60L * 1000L, true)\n            ?: query("reconstructed", 75L * 60L * 1000L, false)\n    }\n\n    private fun terrainSlope(referenceKey: String, target: Long): Double? {\n        val center = terrainAt(referenceKey, target)?.temperature ?: return null\n        val previous = terrainAt(referenceKey, target - HOUR_MS)?.temperature\n        val next = terrainAt(referenceKey, target + HOUR_MS)?.temperature\n        return when {\n            previous != null && next != null -> (next - previous) / 2.0\n            next != null -> next - center\n            previous != null -> center - previous\n            else -> null\n        }?.coerceIn(-3.0, 3.0)\n    }\n\n    private fun terrainAcceleration(referenceKey: String, target: Long): Double? {\n        val center = terrainAt(referenceKey, target)?.temperature ?: return null\n        val previous = terrainAt(referenceKey, target - HOUR_MS)?.temperature ?: return null\n        val next = terrainAt(referenceKey, target + HOUR_MS)?.temperature ?: return null\n        return (next - 2.0 * center + previous).coerceIn(-1.5, 1.5)\n    }\n\n    /** Pick the snapshot'''
    s = load_pattern.sub(replacement, s, count=1)

s = s.replace('legendItem(canvas, x + dp(8f), y, REAL_GREEN, "Réel")', 'legendItem(canvas, x + dp(8f), y, REAL_GREEN, "Terrain")')
s = s.replace('// Future green remains absent until a real MEASURED value exists.', '// Future terrain remains absent until measured/reconstructed reference data exists.')
s = s.replace(
    '''        val status = when {\n            sample.actualTemp == null -> "réel en attente"\n            sample.officialError != null && sample.localError != null ->\n                "M ${oneDec(sample.officialError)}° · F ${oneDec(sample.localError)}°"\n            else -> "mesure disponible"\n        }''',
    '''        val status = when {\n            sample.actualTemp == null -> "terrain en attente"\n            sample.officialError != null && sample.localError != null -> {\n                val origin = if (sample.actualIsMeasured) "R" else "r"\n                "$origin · M ${oneDec(sample.officialError)}° · F ${oneDec(sample.localError)}°"\n            }\n            sample.actualIsMeasured -> "terrain réel"\n            else -> "terrain reconstruit"\n        }''',
)
s = s.replace('append("Réel en attente. ")', 'append("Terrain en attente. ")')
s = s.replace(
    '''    private fun emptyDial(label: String) = DialSample(\n        label, System.currentTimeMillis(), null, null, null,\n        null, null, null, null, null, null, null, null, 0\n    )''',
    '''    private fun emptyDial(label: String) = DialSample(\n        label, System.currentTimeMillis(), null, null, null, false,\n        null, null, null, null, null, null, null, null, 0\n    )''',
)
overlay.write_text(s)

print("Applied v0.21.7 terrain reference, H+24 audit and UI fixes")
