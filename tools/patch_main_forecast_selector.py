from pathlib import Path

# First make the new prediction-only curve source self-contained.  The app already has
# multiple package-level hourBucket helpers, so this feature uses a unique helper name.
curves=Path('app/src/main/java/com/fabdata/app/ForecastSelectableCurves.kt')
cs=curves.read_text()
if 'private fun curveHourBucket' not in cs:
    cs=cs.replace(
        'private const val CURVE_HOUR_MS = 60L * 60L * 1000L\n',
        'private const val CURVE_HOUR_MS = 60L * 60L * 1000L\nprivate fun curveHourBucket(timestamp: Long): Long = (timestamp / CURVE_HOUR_MS) * CURVE_HOUR_MS\n',
        1
    )
cs=cs.replace('hourBucket(', 'curveHourBucket(')
# The replacement above also touches the helper declaration if re-run; normalize it.
cs=cs.replace('private fun curvecurveHourBucket(', 'private fun curveHourBucket(')
curves.write_text(cs)

p=Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
s=p.read_text()
def r(a,b,m):
    global s
    if m in s:return
    if a not in s: raise SystemExit('missing '+m)
    s=s.replace(a,b,1)
r('            put(LYON_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("lyon:reconstructed"))\n            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))\n','            put(LYON_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("lyon:reconstructed"))\n            put(FORECAST_RECONSTRUCTED_SENSOR_ID, curveStyleStore.load("forecast:reconstructed"))\n            put(FORECAST_FAB_SENSOR_ID, curveStyleStore.load("forecast:fab"))\n            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))\n','forecast:reconstructed')
r('    val visualReference = WeatherReferencePrefs(context).selectedReference()\n    val weatherOfficialSamples = lyonReconstructedSamples\n','    val visualReference = WeatherReferencePrefs(context).selectedReference()\n    var selectableForecastCurves by remember(visualReference.key) { mutableStateOf(ForecastSelectableCurves.EMPTY) }\n    LaunchedEffect(reloadToken, visualReference.key, globalBounds?.first, globalBounds?.last) {\n        val history = globalBounds\n        if (history == null) selectableForecastCurves = ForecastSelectableCurves.EMPTY else {\n            val now = System.currentTimeMillis()\n            val queryTo = maxOf(history.last, now + 24L * 60L * 60L * 1000L)\n            selectableForecastCurves = withContext(Dispatchers.IO) { ForecastSelectableCurveStore(db).query(visualReference.key, history.first, queryTo, now) }\n        }\n    }\n    val forecastReconstructedSamples = selectableForecastCurves.reconstructed\n    val forecastFabSamples = selectableForecastCurves.fab\n    val weatherOfficialSamples = lyonReconstructedSamples\n','forecastReconstructedSamples = selectableForecastCurves.reconstructed')
r('    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }\n    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + inertiaSensor\n','    val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision reconstruite", "Archive prévisionnelle + futur actif", 13, forecastReconstructedSamples.lastOrNull()?.timestamp)\n    val forecastFabSensor = Sensor(FORECAST_FAB_SENSOR_ID, FORECAST_FAB_STABLE_KEY, "Prévision Fab", "Notre prévision locale corrigée", 8, forecastFabSamples.lastOrNull()?.timestamp)\n    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }\n    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + forecastReconstructedSensor + forecastFabSensor + inertiaSensor\n','forecastReconstructedSensor = Sensor(')
r('        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)\n','        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +\n        (FORECAST_RECONSTRUCTED_SENSOR_ID to forecastReconstructedSamples) +\n        (FORECAST_FAB_SENSOR_ID to forecastFabSamples) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)\n','FORECAST_FAB_SENSOR_ID to forecastFabSamples')
r('        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true\n','        if (!showTemp.containsKey(FORECAST_RECONSTRUCTED_SENSOR_ID)) showTemp[FORECAST_RECONSTRUCTED_SENSOR_ID] = true\n        if (!showTemp.containsKey(FORECAST_FAB_SENSOR_ID)) showTemp[FORECAST_FAB_SENSOR_ID] = true\n        showHumidity[FORECAST_RECONSTRUCTED_SENSOR_ID] = false\n        showHumidity[FORECAST_FAB_SENSOR_ID] = false\n        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true\n','showHumidity[FORECAST_RECONSTRUCTED_SENSOR_ID]')
r('                                LYON_RECONSTRUCTED_SENSOR_ID -> "lyon:reconstructed"\n                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"\n','                                LYON_RECONSTRUCTED_SENSOR_ID -> "lyon:reconstructed"\n                                FORECAST_RECONSTRUCTED_SENSOR_ID -> "forecast:reconstructed"\n                                FORECAST_FAB_SENSOR_ID -> "forecast:fab"\n                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"\n','FORECAST_FAB_SENSOR_ID -> "forecast:fab"')
r('                            LYON_RECONSTRUCTED_SENSOR_ID -> "Station météo reconstruite"\n                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"\n','                            LYON_RECONSTRUCTED_SENSOR_ID -> "Station météo reconstruite"\n                            FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision reconstruite"\n                            FORECAST_FAB_SENSOR_ID -> "Prévision Fab"\n                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"\n','FORECAST_FAB_SENSOR_ID -> "Prévision Fab reconstruite"')
r('                    if (sensor.id != THERMAL_INERTIA_SENSOR_ID) {\n','                    if (sensor.id != THERMAL_INERTIA_SENSOR_ID && sensor.id != FORECAST_RECONSTRUCTED_SENSOR_ID && sensor.id != FORECAST_FAB_SENSOR_ID) {\n','sensor.id != FORECAST_RECONSTRUCTED_SENSOR_ID &&')
p.write_text(s)