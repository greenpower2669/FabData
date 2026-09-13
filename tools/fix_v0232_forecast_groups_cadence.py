from pathlib import Path

R = Path(__file__).resolve().parents[1]

def patch(path, pairs):
    p = R / path
    s = p.read_text(encoding="utf-8")
    for old, new in pairs:
        if new in s:
            continue
        if s.count(old) != 1:
            raise RuntimeError(f"{path}: expected one match for {old[:60]!r}, got {s.count(old)}")
        s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")

patch("app/build.gradle.kts", [
    ('versionCode = 58\n        versionName = "0.23.1"', 'versionCode = 59\n        versionName = "0.23.2"'),
])

patch("app/src/main/java/com/fabdata/app/ForecastAdaptive.kt", [
    ('Causal Fab adaptive forecast at five fixed horizons.', 'Causal Fab adaptive forecast at six fixed horizons.'),
    ('val FORECAST_ADAPTIVE_HORIZONS: List<Int> = listOf(3, 6, 12, 24, 48)', 'val FORECAST_ADAPTIVE_HORIZONS: List<Int> = listOf(1, 3, 6, 12, 24, 48)'),
])

patch("app/src/main/java/com/fabdata/app/ForecastAdaptiveUi.kt", [
    ('H+3 · H+6 · H+12 · H+24 · H+48 · apprentissage causal', 'H+1 · H+3 · H+6 · H+12 · H+24 · H+48 · apprentissage causal'),
])

patch("app/src/main/java/com/fabdata/app/MainActivity.kt", [
    ('''    val weatherForecastSensors = sensors
        .filter { sensor -> sensor.id == FORECAST_ACTIVE_SENSOR_ID || fixedWeatherLead(sensor) != null }
        .sortedWith(compareBy<Sensor> { if (it.id == FORECAST_ACTIVE_SENSOR_ID) -1 else fixedWeatherLead(it) ?: Int.MAX_VALUE })
    val adaptiveForecastSensors = sensors
        .filter { sensor -> sensor.id == FORECAST_FAB_SENSOR_ID || isAdaptiveForecastSensorId(sensor.id) }
        .sortedWith(compareBy<Sensor> { if (it.id == FORECAST_FAB_SENSOR_ID) -1 else forecastAdaptiveLeadForSensorId(it.id) ?: Int.MAX_VALUE })
''', '''    val weatherForecastSensors = sensors
        .filter { sensor ->
            val lead = fixedWeatherLead(sensor)
            sensor.id == FORECAST_ACTIVE_SENSOR_ID || (lead != null && lead != 24)
        }
        .sortedWith(compareBy<Sensor> { if (it.id == FORECAST_ACTIVE_SENSOR_ID) -1 else fixedWeatherLead(it) ?: Int.MAX_VALUE })
    val adaptiveForecastSensors = sensors
        .filter { sensor ->
            val lead = forecastAdaptiveLeadForSensorId(sensor.id)
            sensor.id == FORECAST_FAB_SENSOR_ID || (lead != null && lead != 24)
        }
        .sortedWith(compareBy<Sensor> { if (it.id == FORECAST_FAB_SENSOR_ID) -1 else forecastAdaptiveLeadForSensorId(it.id) ?: Int.MAX_VALUE })
'''),
    ('listOf(10, 5, 13, 8, 6)[index], points.lastOrNull()?.timestamp', '(6 + index * 3) % palette.size, points.lastOrNull()?.timestamp'),
    ('Prévisions météo · active + H+1 → H+48', 'Prévisions météo · autres horizons jusqu’à H+48'),
    ('Prévisions Fab · adaptatives jusqu’à H+48', 'Prévisions Fab · autres horizons jusqu’à H+48'),
    ('durable source for H+1..H+24 and for the Météo-France-like gliding curve.', 'durable source for fixed H+1..H+48 and for the provider-like gliding curve.'),
])

live_path = R / "app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt"
live = live_path.read_text(encoding="utf-8")
if "LIVE_FORECAST_INTERVAL_MS" not in live:
    live = live.replace('import kotlinx.coroutines.withContext\n', 'import kotlinx.coroutines.withContext\n\nprivate const val LIVE_FORECAST_INTERVAL_MS = 10L * 60L * 1000L\n', 1)
    live = live.replace('''    suspend fun updateLive(): Boolean {
        if (!foreground || working) return false
        val referenceForOperation = weatherPrefs.selectedReference()
''', '''    suspend fun lastForecastUpdatedAt(referenceKey: String): Long? = withContext(Dispatchers.IO) {
        db.readableDatabase.rawQuery(
            "SELECT MAX(updated_at) FROM weather_reference_samples WHERE reference_key=? AND source='forecast'",
            arrayOf(referenceKey)
        ).use { c -> if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null }
    }

    suspend fun updateLive(force: Boolean = false): Boolean {
        if (!foreground || working) return false
        val referenceForOperation = weatherPrefs.selectedReference()
        if (!force) {
            val last = lastForecastUpdatedAt(referenceForOperation.key)
            if (last != null && System.currentTimeMillis() - last < LIVE_FORECAST_INTERVAL_MS) return false
        }
''', 1)
    live = live.replace('if (foreground && updateLive()) {', 'if (foreground && updateLive(force = true)) {', 1)
    old = '''    // Le retour au premier plan rafraîchit uniquement la référence déjà choisie.
    // Aucun scan de secteur et aucun changement automatique de station ne sont autorisés ici.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect

        val hadPendingMeasured = pendingMeasuredRefresh
        if (updateLive() && hadPendingMeasured) {
            pendingMeasuredRefresh = false
        }

        while (true) {
            delay(600_000L)
            if (!foreground) break
            val hadPending = pendingMeasuredRefresh
            if (updateLive() && hadPending) {
                pendingMeasuredRefresh = false
            }
        }
    }
'''
    new = '''    // La dernière écriture FORECAST cadence le réseau : retour au focus, bouton manuel
    // et worker Android partagent ainsi la même horloge sans spammer l'affichage.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect
        while (foreground) {
            val hadPending = pendingMeasuredRefresh
            if (!hadPending) {
                val reference = weatherPrefs.selectedReference()
                val last = lastForecastUpdatedAt(reference.key)
                val waitMs = last?.let {
                    (LIVE_FORECAST_INTERVAL_MS - (System.currentTimeMillis() - it)).coerceAtLeast(0L)
                } ?: 0L
                if (waitMs > 0L) {
                    delay(waitMs)
                    if (!foreground) break
                }
            }
            val ran = updateLive(force = hadPending)
            if (ran && hadPending) pendingMeasuredRefresh = false
            if (!ran) delay(5_000L)
        }
    }
'''
    if old not in live:
        raise RuntimeError("LiveUpdateCoordinator tail changed unexpectedly")
    live = live.replace(old, new, 1)
    live_path.write_text(live, encoding="utf-8")

print("v0.23.2 patch applied")
