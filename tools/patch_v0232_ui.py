from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT/'app/src/main/java/com/fabdata/app/MainActivity.kt'
s = p.read_text(encoding='utf-8')

def once(old, new, label):
    global s
    if new in s: return
    n=s.count(old)
    if n < 1: raise RuntimeError(f'{label}: expected at least 1 occurrence, got {n}')
    s=s.replace(old,new,1)

once('val queryTo = maxOf(history.last, now + 24L * 60L * 60L * 1000L)',
     'val queryTo = maxOf(history.last, now + FORECAST_DISPLAY_FUTURE_MS + 60L * 60L * 1000L)', 'query H48')
once('val forecastHorizonSamples = forecastHorizonCurves.weatherByLead.filterKeys { it < 24 }',
     'val forecastHorizonSamples = forecastHorizonCurves.weatherByLead.filterKeys { it != 24 }', 'horizon map')
once('maxOf(history.last, now + 25L * 60L * 60L * 1000L),',
     'maxOf(history.last, now + FORECAST_DISPLAY_FUTURE_MS + 60L * 60L * 1000L),', 'adaptive query')
once('FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->',
     'FORECAST_HORIZON_HOURS.filter { it != 24 }.forEach { lead ->', 'visibility range')
once('''        FORECAST_ADAPTIVE_HORIZONS.forEach { lead ->
            val id = forecastAdaptiveSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = uiPrefs.curveTemperature(forecastAdaptiveStableKey(lead)) ?: false
            showHumidity[id] = false
        }
''','''        FORECAST_ADAPTIVE_HORIZONS.forEach { lead ->
            val id = forecastAdaptiveSensorId(lead)
            val defaultVisible = lead == 24
            if (!showTemp.containsKey(id)) {
                showTemp[id] = uiPrefs.curveTemperature(forecastAdaptiveStableKey(lead)) ?: defaultVisible
            }
            showHumidity[id] = false
        }
''','adaptive default')
once('if (!showTemp.containsKey(FORECAST_FAB_SENSOR_ID)) showTemp[FORECAST_FAB_SENSOR_ID] = uiPrefs.curveTemperature(FORECAST_FAB_STABLE_KEY) ?: true',
     'if (!showTemp.containsKey(FORECAST_FAB_SENSOR_ID)) showTemp[FORECAST_FAB_SENSOR_ID] = uiPrefs.curveTemperature(FORECAST_FAB_STABLE_KEY) ?: false','legacy fab hidden')
once('if (!showTemp.containsKey(FORECAST_ACTIVE_SENSOR_ID)) showTemp[FORECAST_ACTIVE_SENSOR_ID] = uiPrefs.curveTemperature(FORECAST_ACTIVE_STABLE_KEY) ?: true',
     'if (!showTemp.containsKey(FORECAST_ACTIVE_SENSOR_ID)) showTemp[FORECAST_ACTIVE_SENSOR_ID] = uiPrefs.curveTemperature(FORECAST_ACTIVE_STABLE_KEY) ?: false','active hidden')
once('val forecastHorizonSensors = FORECAST_HORIZON_HOURS.filter { it < 24 }.map { lead ->',
     'val forecastHorizonSensors = FORECAST_HORIZON_HOURS.filter { it != 24 }.map { lead ->','sensor range')
once('listOf(10, 5, 13, 8)[index]','listOf(10, 5, 13, 8, 6)[index]','adaptive color')

once('''                    sensors.filter { sensor ->
                        forecastHorizonLeadForSensorId(sensor.id) == null &&
                            forecastAdaptiveLeadForSensorId(sensor.id) == null && (
''','''                    sensors.filter { sensor ->
                        sensor.id != FORECAST_ACTIVE_SENSOR_ID &&
                            sensor.id != FORECAST_RECONSTRUCTED_SENSOR_ID &&
                            sensor.id != FORECAST_FAB_SENSOR_ID &&
                            forecastHorizonLeadForSensorId(sensor.id) == null &&
                            forecastAdaptiveLeadForSensorId(sensor.id) == null && (
''','band forecast exclusion')

once('''    var archiveExpanded by rememberSaveable { mutableStateOf(uiPrefs.forecastArchiveExpanded()) }
    val archiveSensors = sensors
        .filter { sensor -> forecastHorizonLeadForSensorId(sensor.id)?.let { it in 1..23 } == true }
        .sortedBy { forecastHorizonLeadForSensorId(it.id) ?: Int.MAX_VALUE }
    val archiveIds = archiveSensors.map { it.id }.toSet()
    val mainSensors = sensors.filterNot { it.id in archiveIds }

    LaunchedEffect(archiveExpanded) { uiPrefs.saveForecastArchiveExpanded(archiveExpanded) }
''','''    var weatherExpanded by rememberSaveable { mutableStateOf(uiPrefs.forecastArchiveExpanded()) }
    var adaptiveExpanded by rememberSaveable { mutableStateOf(uiPrefs.adaptiveForecastExpanded()) }

    fun fixedWeatherLead(sensor: Sensor): Int? = when (sensor.id) {
        FORECAST_RECONSTRUCTED_SENSOR_ID -> 24
        else -> forecastHorizonLeadForSensorId(sensor.id)
    }

    val weatherForecastSensors = sensors
        .filter { sensor -> sensor.id == FORECAST_ACTIVE_SENSOR_ID || fixedWeatherLead(sensor) != null }
        .sortedWith(compareBy<Sensor> { if (it.id == FORECAST_ACTIVE_SENSOR_ID) -1 else fixedWeatherLead(it) ?: Int.MAX_VALUE })
    val adaptiveForecastSensors = sensors
        .filter { sensor -> sensor.id == FORECAST_FAB_SENSOR_ID || isAdaptiveForecastSensorId(sensor.id) }
        .sortedWith(compareBy<Sensor> { if (it.id == FORECAST_FAB_SENSOR_ID) -1 else forecastAdaptiveLeadForSensorId(it.id) ?: Int.MAX_VALUE })
    val groupedIds = (weatherForecastSensors + adaptiveForecastSensors).map { it.id }.toSet()
    val mainSensors = sensors.filterNot { it.id in groupedIds }

    LaunchedEffect(weatherExpanded) { uiPrefs.saveForecastArchiveExpanded(weatherExpanded) }
    LaunchedEffect(adaptiveExpanded) { uiPrefs.saveAdaptiveForecastExpanded(adaptiveExpanded) }
''','selector groups')

once('''                "Chaque courbe est indépendante. Les horizons H+1 à H+23 restent rangés dans Archives météo.",
''','''                "Les prévisions météo et Fab sont rangées en groupes repliables. Par défaut, seules H+24 météo et H+24 adaptative sont affichées.",
''','selector help')
once('''                val lead = forecastHorizonLeadForSensorId(sensor.id)
                val adaptiveLead = forecastAdaptiveLeadForSensorId(sensor.id)
''','''                val lead = fixedWeatherLead(sensor)
                val adaptiveLead = forecastAdaptiveLeadForSensorId(sensor.id)
''','selector lead')
once('''                            FORECAST_ACTIVE_SENSOR_ID -> "Prévision météo active · dernière disponible"
''','''                            FORECAST_ACTIVE_SENSOR_ID -> "Prévision météo active · jusqu’à H+48"
''','active label')

old='''            if (archiveSensors.isNotEmpty()) {
                HorizontalDivider()
                val visibleCount = archiveSensors.count { showTemp[it.id] == true }
                OutlinedButton(
                    onClick = { archiveExpanded = !archiveExpanded },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        "Archives météo H+1 → H+23 · $visibleCount/${archiveSensors.size} " +
                            if (archiveExpanded) "▴" else "▾"
                    )
                }
                if (archiveExpanded) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.End
                    ) {
                        TextButton(onClick = {
                            archiveSensors.forEach { sensor ->
                                showTemp[sensor.id] = true
                                uiPrefs.saveCurveTemperature(sensor.stableKey, true)
                            }
                        }) { Text("Tout afficher") }
                        TextButton(onClick = {
                            archiveSensors.forEach { sensor ->
                                showTemp[sensor.id] = false
                                uiPrefs.saveCurveTemperature(sensor.stableKey, false)
                            }
                        }) { Text("Tout masquer") }
                    }
                    archiveSensors.forEach { sensor -> SensorRow(sensor) }
                }
            }
'''
new='''            fun setGroupVisible(group: List<Sensor>, visible: Boolean) {
                group.forEach { sensor ->
                    showTemp[sensor.id] = visible
                    uiPrefs.saveCurveTemperature(sensor.stableKey, visible)
                }
            }

            if (weatherForecastSensors.isNotEmpty()) {
                HorizontalDivider()
                val visibleCount = weatherForecastSensors.count { showTemp[it.id] == true }
                OutlinedButton(onClick = { weatherExpanded = !weatherExpanded }, modifier = Modifier.fillMaxWidth()) {
                    Text(
                        "Prévisions météo · active + H+1 → H+48 · $visibleCount/${weatherForecastSensors.size} " +
                            if (weatherExpanded) "▴" else "▾"
                    )
                }
                if (weatherExpanded) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        TextButton(onClick = { setGroupVisible(weatherForecastSensors, true) }) { Text("Tout afficher") }
                        TextButton(onClick = { setGroupVisible(weatherForecastSensors, false) }) { Text("Tout masquer") }
                    }
                    weatherForecastSensors.forEach { sensor -> SensorRow(sensor) }
                }
            }

            if (adaptiveForecastSensors.isNotEmpty()) {
                HorizontalDivider()
                val visibleCount = adaptiveForecastSensors.count { showTemp[it.id] == true }
                OutlinedButton(onClick = { adaptiveExpanded = !adaptiveExpanded }, modifier = Modifier.fillMaxWidth()) {
                    Text(
                        "Prévisions Fab · adaptatives jusqu’à H+48 · $visibleCount/${adaptiveForecastSensors.size} " +
                            if (adaptiveExpanded) "▴" else "▾"
                    )
                }
                if (adaptiveExpanded) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        TextButton(onClick = { setGroupVisible(adaptiveForecastSensors, true) }) { Text("Tout afficher") }
                        TextButton(onClick = { setGroupVisible(adaptiveForecastSensors, false) }) { Text("Tout masquer") }
                    }
                    adaptiveForecastSensors.forEach { sensor -> SensorRow(sensor) }
                }
            }
'''
once(old,new,'collapsed groups body')

p.write_text(s,encoding='utf-8')