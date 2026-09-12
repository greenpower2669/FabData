from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/src/main/java/com/fabdata/app/MainActivity.kt"
SELECTABLE = ROOT / "app/src/main/java/com/fabdata/app/ForecastSelectableCurves.kt"
GRADLE = ROOT / "app/build.gradle.kts"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            print(f"[already] {label}")
            return text
        raise SystemExit(f"anchor missing: {label}")
    return text.replace(old, new, 1)


# --- MainActivity: styles for active + fixed H+1..H+23 ------------------------
text = MAIN.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''            put(FORECAST_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("forecast:reconstructed"))
            put(FORECAST_FAB_SENSOR_ID, curveStyleStore.load("forecast:fab"))
            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))''',
    '''            put(FORECAST_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("forecast:reconstructed"))
            put(FORECAST_FAB_SENSOR_ID, curveStyleStore.load("forecast:fab"))
            put(FORECAST_ACTIVE_SENSOR_ID, curveStyleStore.load("forecast:active"))
            FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
                put(forecastHorizonSensorId(lead), curveStyleStore.load("forecast:weather:h$lead"))
            }
            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))''',
    "curve styles"
)

# Defaults: active curve visible, analytical fixed leads available but off to avoid spaghetti.
text = replace_once(
    text,
    '''        if (!showTemp.containsKey(FORECAST_RECONSTRUCTED_SENSOR_ID)) showTemp[FORECAST_RECONSTRUCTED_SENSOR_ID] = true
        if (!showTemp.containsKey(FORECAST_FAB_SENSOR_ID)) showTemp[FORECAST_FAB_SENSOR_ID] = true
        showHumidity[FORECAST_RECONSTRUCTED_SENSOR_ID] = false
        showHumidity[FORECAST_FAB_SENSOR_ID] = false
        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true''',
    '''        if (!showTemp.containsKey(FORECAST_RECONSTRUCTED_SENSOR_ID)) showTemp[FORECAST_RECONSTRUCTED_SENSOR_ID] = true
        if (!showTemp.containsKey(FORECAST_FAB_SENSOR_ID)) showTemp[FORECAST_FAB_SENSOR_ID] = true
        if (!showTemp.containsKey(FORECAST_ACTIVE_SENSOR_ID)) showTemp[FORECAST_ACTIVE_SENSOR_ID] = true
        FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
            val id = forecastHorizonSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = false
            showHumidity[id] = false
        }
        showHumidity[FORECAST_RECONSTRUCTED_SENSOR_ID] = false
        showHumidity[FORECAST_FAB_SENSOR_ID] = false
        showHumidity[FORECAST_ACTIVE_SENSOR_ID] = false
        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true''',
    "visibility defaults"
)

# Query the old H+24 scientific curve and the new local multi-horizon memory side by side.
old_query = '''    val visualReference = WeatherReferencePrefs(context).selectedReference()
    var selectableForecastCurves by remember(visualReference.key) { mutableStateOf(ForecastSelectableCurves.EMPTY) }
    LaunchedEffect(reloadToken, visualReference.key, globalBounds?.first, globalBounds?.last) {
        val history = globalBounds
        if (history == null) selectableForecastCurves = ForecastSelectableCurves.EMPTY else {
            val now = System.currentTimeMillis()
            val queryTo = maxOf(history.last, now + 24L * 60L * 60L * 1000L)
            selectableForecastCurves = withContext(Dispatchers.IO) {
                // Historical forecast API is only a backfill. Once cached it is restored from
                // FabData backup, so an app update does not need to download it again.
                ForecastPastArchiveBackfill(db).ensure(
                    visualReference, history.first, minOf(history.last, now - 60L * 60L * 1000L), now
                )
                ForecastSelectableCurveStore(db).query(visualReference.key, history.first, queryTo, now)
            }
        }
    }
    val forecastReconstructedSamples = selectableForecastCurves.reconstructed
    val forecastFabSamples = selectableForecastCurves.fab'''
new_query = '''    val visualReference = WeatherReferencePrefs(context).selectedReference()
    var selectableForecastCurves by remember(visualReference.key) { mutableStateOf(ForecastSelectableCurves.EMPTY) }
    var forecastHorizonCurves by remember(visualReference.key) { mutableStateOf(ForecastHorizonCurveSet.EMPTY) }
    LaunchedEffect(reloadToken, visualReference.key, globalBounds?.first, globalBounds?.last) {
        val history = globalBounds
        if (history == null) {
            selectableForecastCurves = ForecastSelectableCurves.EMPTY
            forecastHorizonCurves = ForecastHorizonCurveSet.EMPTY
        } else {
            val now = System.currentTimeMillis()
            val queryTo = maxOf(history.last, now + 24L * 60L * 60L * 1000L)
            val curves = withContext(Dispatchers.IO) {
                // API H+24 stays a best-effort historical backfill. Local snapshots are the
                // durable source for H+1..H+24 and for the Météo-France-like gliding curve.
                ForecastPastArchiveBackfill(db).ensure(
                    visualReference, history.first, minOf(history.last, now - 60L * 60L * 1000L), now
                )
                val h24 = ForecastSelectableCurveStore(db).query(
                    visualReference.key, history.first, queryTo, now
                )
                val horizons = ForecastHorizonArchive(db).query(
                    visualReference.key, history.first, queryTo, now
                )
                h24 to horizons
            }
            selectableForecastCurves = curves.first
            forecastHorizonCurves = curves.second
        }
    }
    val forecastReconstructedSamples = selectableForecastCurves.reconstructed
    val forecastFabSamples = selectableForecastCurves.fab
    val forecastActiveSamples = forecastHorizonCurves.activeWeather
    val forecastHorizonSamples = forecastHorizonCurves.weatherByLead.filterKeys { it < 24 }'''
text = replace_once(text, old_query, new_query, "forecast query")

old_sensors = '''    val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo H+24", "Passé Météo-France H+24 · futur actif · rendu 10 min", 12, forecastReconstructedSamples.lastOrNull()?.timestamp)
    val forecastFabSensor = Sensor(FORECAST_FAB_SENSOR_ID, FORECAST_FAB_STABLE_KEY, "Prévision Fab H+24", "Correction locale H+24 · rendu 10 min", 11, forecastFabSamples.lastOrNull()?.timestamp)
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + lyonReconstructedSensor + forecastReconstructedSensor + forecastFabSensor + inertiaSensor
    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (LYON_RECONSTRUCTED_SENSOR_ID to terrainWeatherSamples) +
        (FORECAST_RECONSTRUCTED_SENSOR_ID to forecastReconstructedSamples) +
        (FORECAST_FAB_SENSOR_ID to forecastFabSamples) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)'''
new_sensors = '''    val forecastActiveSensor = Sensor(
        FORECAST_ACTIVE_SENSOR_ID, FORECAST_ACTIVE_STABLE_KEY,
        "Prévision météo active",
        "Dernière prévision disponible par échéance · archive glissante",
        12, forecastActiveSamples.lastOrNull()?.timestamp
    )
    val forecastHorizonSensors = FORECAST_HORIZON_HOURS.filter { it < 24 }.map { lead ->
        val points = forecastHorizonSamples[lead].orEmpty()
        Sensor(
            forecastHorizonSensorId(lead), "forecast-weather-h$lead",
            "Prévision météo H+$lead",
            "Archive locale fixe H+$lead · valeur conservée avant remplacement",
            (12 + lead) % palette.size, points.lastOrNull()?.timestamp
        )
    }
    val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo H+24", "H+24 fixe · archive locale, backfill si disponible · rendu 10 min", 12, forecastReconstructedSamples.lastOrNull()?.timestamp)
    val forecastFabSensor = Sensor(FORECAST_FAB_SENSOR_ID, FORECAST_FAB_STABLE_KEY, "Prévision Fab H+24", "Correction locale H+24 · rendu 10 min", 11, forecastFabSamples.lastOrNull()?.timestamp)
    val forecastHorizonSampleMap = forecastHorizonSamples.mapKeys { (lead, _) -> forecastHorizonSensorId(lead) }
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + lyonReconstructedSensor + forecastActiveSensor + forecastHorizonSensors + forecastReconstructedSensor + forecastFabSensor + inertiaSensor
    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (LYON_RECONSTRUCTED_SENSOR_ID to terrainWeatherSamples) +
        (FORECAST_ACTIVE_SENSOR_ID to forecastActiveSamples) +
        forecastHorizonSampleMap +
        (FORECAST_RECONSTRUCTED_SENSOR_ID to forecastReconstructedSamples) +
        (FORECAST_FAB_SENSOR_ID to forecastFabSamples) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)'''
text = replace_once(text, old_sensors, new_sensors, "synthetic sensors")

old_lod = '''        return source.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
            (LYON_RECONSTRUCTED_SENSOR_ID to terrain) +
            (FORECAST_RECONSTRUCTED_SENSOR_ID to predictionLod(forecastReconstructedSamples, bucketMs)) +
            (FORECAST_FAB_SENSOR_ID to predictionLod(forecastFabSamples, bucketMs)) +
            (THERMAL_INERTIA_SENSOR_ID to source[THERMAL_INERTIA_SENSOR_ID].orEmpty())'''
new_lod = '''        val horizonLod = forecastHorizonSamples.mapKeys { (lead, _) -> forecastHorizonSensorId(lead) }
            .mapValues { (_, points) -> predictionLod(points, bucketMs) }
        return source.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
            (LYON_RECONSTRUCTED_SENSOR_ID to terrain) +
            (FORECAST_ACTIVE_SENSOR_ID to predictionLod(forecastActiveSamples, bucketMs)) +
            horizonLod +
            (FORECAST_RECONSTRUCTED_SENSOR_ID to predictionLod(forecastReconstructedSamples, bucketMs)) +
            (FORECAST_FAB_SENSOR_ID to predictionLod(forecastFabSamples, bucketMs)) +
            (THERMAL_INERTIA_SENSOR_ID to source[THERMAL_INERTIA_SENSOR_ID].orEmpty())'''
text = replace_once(text, old_lod, new_lod, "lod maps")

# Synthetic styling/editor labels.
text = replace_once(
    text,
    '''                                FORECAST_RECONSTRUCTED_SENSOR_ID -> "forecast:reconstructed"
                                FORECAST_FAB_SENSOR_ID -> "forecast:fab"
                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"
                                else -> "sensor:${sensor.stableKey}"''',
    '''                                FORECAST_RECONSTRUCTED_SENSOR_ID -> "forecast:reconstructed"
                                FORECAST_FAB_SENSOR_ID -> "forecast:fab"
                                FORECAST_ACTIVE_SENSOR_ID -> "forecast:active"
                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"
                                else -> forecastHorizonLeadForSensorId(sensor.id)
                                    ?.let { "forecast:weather:h$it" }
                                    ?: "sensor:${sensor.stableKey}"''',
    "style edit key"
)
text = replace_once(
    text,
    '''                            FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision météo H+24"
                            FORECAST_FAB_SENSOR_ID -> "Prévision Fab H+24"
                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"
                            else -> sensor.room''',
    '''                            FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision météo H+24 fixe"
                            FORECAST_FAB_SENSOR_ID -> "Prévision Fab H+24"
                            FORECAST_ACTIVE_SENSOR_ID -> "Prévision météo active · dernière disponible"
                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"
                            else -> sensor.room''',
    "selector labels"
)
text = replace_once(
    text,
    '''                    if (sensor.id != THERMAL_INERTIA_SENSOR_ID && sensor.id != FORECAST_RECONSTRUCTED_SENSOR_ID && sensor.id != FORECAST_FAB_SENSOR_ID) {''',
    '''                    if (sensor.id != THERMAL_INERTIA_SENSOR_ID && sensor.id != FORECAST_RECONSTRUCTED_SENSOR_ID && sensor.id != FORECAST_FAB_SENSOR_ID && !isForecastArchiveSensorId(sensor.id)) {''',
    "humidity checkbox"
)
MAIN.write_text(text, encoding="utf-8")

# --- H+24 curve/cockpit: fixed lead locally too, never current gliding future -----
sel = SELECTABLE.read_text(encoding="utf-8")
sel = replace_once(
    sel,
    ''' * 1. past = fixed-lead Météo-France H+24 archive only;
 * 2. future = the currently active forecast captured by FabData.
 * Old near-H+1 replay snapshots are deliberately excluded from past verification.''',
    ''' * 1. past = fixed-lead Météo-France H+24 archive when available;
 * 2. local memory = snapshot captured closest to exactly H+24, for past or future.
 * The current/gliding forecast is a separate selectable curve and never contaminates H+24.''',
    "selectable docs"
)
old_func = '''    private fun selectReplayAnchors(rows: List<SelectableForecastRow>, now: Long): List<SelectableForecastRow> {
        val past = rows.filter { it.targetAt <= now }
            .groupBy { forecastCurveHourBucket(it.targetAt) }
            .values
            .mapNotNull { group ->
                group.minByOrNull { abs((it.targetAt - it.issuedAt) - CURVE_HOUR_MS) }
            }
        val future = rows.filter { it.targetAt > now && it.issuedAt <= now }
            .groupBy { forecastCurveHourBucket(it.targetAt) }
            .values
            .mapNotNull { group -> group.maxByOrNull { it.issuedAt } }
        return (past + future)
            .associateBy { forecastCurveHourBucket(it.targetAt) }
            .values
            .sortedBy { it.targetAt }
    }'''
new_func = '''    private fun selectReplayAnchors(rows: List<SelectableForecastRow>, now: Long): List<SelectableForecastRow> {
        val fixedLead = 24L * CURVE_HOUR_MS
        val tolerance = 35L * 60L * 1000L
        return rows.asSequence()
            .filter { it.issuedAt <= now && it.issuedAt < it.targetAt - 5L * 60L * 1000L }
            .groupBy { forecastCurveHourBucket(it.targetAt) }
            .values
            .mapNotNull { group ->
                group.minByOrNull { abs((it.targetAt - it.issuedAt) - fixedLead) }
                    ?.takeIf { abs((it.targetAt - it.issuedAt) - fixedLead) <= tolerance }
            }
            .sortedBy { it.targetAt }
    }'''
sel = replace_once(sel, old_func, new_func, "fixed H24 anchors")
sel = replace_once(
    sel,
    '''            } else if (actual != null) {
                // Future side stays live/current.''',
    '''            } else if (actual != null) {
                // Future H+24 is also fixed lead. The gliding/current curve lives separately.''',
    "future H24 comment"
)
SELECTABLE.write_text(sel, encoding="utf-8")

# --- Version ------------------------------------------------------------------
gradle = GRADLE.read_text(encoding="utf-8")
gradle = replace_once(gradle, 'versionCode = 54', 'versionCode = 55', "versionCode")
gradle = replace_once(gradle, 'versionName = "0.21.8"', 'versionName = "0.21.9"', "versionName")
GRADLE.write_text(gradle, encoding="utf-8")

print("v0.21.9 multi-horizon patch applied")
