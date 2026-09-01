from pathlib import Path

MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
LAB = Path('app/src/main/java/com/fabdata/app/LyonLabLayer.kt')

main = MAIN.read_text(encoding='utf-8')

# -----------------------------------------------------------------------------
# v0.9.2: Lyon is a permanent system sensor. Network/token only feed data;
# they never decide whether Lyon or Lyon reconstructed exist in the UI.
# -----------------------------------------------------------------------------

if 'private data class LyonHybridSyncResult' not in main:
    anchor = 'private data class ChartPrefs(\n'
    helper = '''private data class LyonHybridSyncResult(
    val received: Int,
    val stored: Int,
    val label: String
)

private suspend fun syncLyonHybrid(
    db: FabDataDb,
    legacy: LyonWeatherSync,
    official: MeteoFranceOfficialClient,
    credentials: MeteoFranceCredentialStore
): LyonHybridSyncResult = withContext(Dispatchers.IO) {
    // System invariant: Lyon exists before any network call.
    db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)

    if (credentials.hasCredential()) {
        runCatching { official.syncSixMinute24h() }
            .fold(
                onSuccess = { LyonHybridSyncResult(it.received, it.stored, "Lyon officiel · 6 min") },
                onFailure = {
                    val fallback = legacy.syncToday()
                    LyonHybridSyncResult(
                        fallback.parsed,
                        fallback.added + fallback.corrected,
                        "Lyon secours auto · officiel indisponible"
                    )
                }
            )
    } else {
        val fallback = legacy.syncToday()
        LyonHybridSyncResult(
            fallback.parsed,
            fallback.added + fallback.corrected,
            "Lyon secours auto · sans token"
        )
    }
}

private suspend fun completeLyonHybrid(
    db: FabDataDb,
    legacy: LyonWeatherSync,
    official: MeteoFranceOfficialClient,
    credentials: MeteoFranceCredentialStore
): LyonHybridSyncResult = withContext(Dispatchers.IO) {
    db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
    if (credentials.hasCredential()) {
        val bounds = db.physicalSensorBounds() ?: error("Aucune période physique")
        runCatching { official.syncHourly(bounds.first, bounds.last) }
            .fold(
                onSuccess = { LyonHybridSyncResult(it.received, it.stored, "Lyon horaire officiel") },
                onFailure = {
                    val fallback = legacy.completePhysicalPeriod()
                    LyonHybridSyncResult(
                        fallback.daysDownloaded,
                        fallback.added + fallback.corrected,
                        "Lyon secours historique · officiel indisponible"
                    )
                }
            )
    } else {
        val fallback = legacy.completePhysicalPeriod()
        LyonHybridSyncResult(
            fallback.daysDownloaded,
            fallback.added + fallback.corrected,
            "Lyon secours historique · sans token"
        )
    }
}

'''
    if anchor not in main:
        raise SystemExit('v0.9.2: ChartPrefs anchor missing')
    main = main.replace(anchor, helper + anchor, 1)

old_start = '''    // v0.9 : la source principale devient l'API officielle Météo-France.
    // Sans clé configurée, on n'écrit rien et l'application démarre normalement.
    LaunchedEffect(Unit) {
        if (meteoCredentials.hasCredential()) {
            val result = withContext(Dispatchers.IO) { runCatching { meteoOfficial.syncSixMinute24h() } }
            reloadToken++
            result.exceptionOrNull()?.let { error ->
                snackbar.showSnackbar("Lyon officiel non actualisé : ${error.message ?: "source indisponible"}")
            }
        }
    }
'''
new_start = '''    // v0.9.2 : Lyon est une sonde système permanente.
    // Officiel si possible, secours automatique sinon. Le token n'agit jamais sur la visibilité.
    LaunchedEffect(Unit) {
        val result = runCatching { syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }
        reloadToken++
        result.exceptionOrNull()?.let { error ->
            snackbar.showSnackbar("Lyon non actualisé : ${error.message ?: "source indisponible"}")
        }
    }
'''
if old_start in main:
    main = main.replace(old_start, new_start, 1)
elif 'v0.9.2 : Lyon est une sonde système permanente.' not in main:
    raise SystemExit('v0.9.2: startup sync anchor missing')

# Load reconstructed series unconditionally: it is a permanent virtual curve.
old_recon = '''                val lyonReconstructed = if (s.any { it.stableKey == LyonWeatherSync.STABLE_KEY }) {
                    lyonLab.reconstruct(chosen.first, chosen.last).points.map {
                        SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity)
                    }
                } else emptyList()
'''
new_recon = '''                val lyonReconstructed = lyonLab.reconstruct(chosen.first, chosen.last).points.map {
                    SamplePoint(LYON_RECONSTRUCTED_SENSOR_ID, it.timestamp, it.temperature, it.humidity)
                }
'''
if old_recon in main:
    main = main.replace(old_recon, new_recon, 1)

old_toggle = '''        if (sensors.any { it.stableKey == LyonWeatherSync.STABLE_KEY }) {
            if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
                showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = loaded.lyonReconstructedSamples.isNotEmpty()
            }
            if (!showHumidity.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
                showHumidity[LYON_RECONSTRUCTED_SENSOR_ID] = false
            }
        }
'''
new_toggle = '''        if (!showTemp.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            // Always checked: if data arrives later the curve appears without another user action.
            showTemp[LYON_RECONSTRUCTED_SENSOR_ID] = true
        }
        if (!showHumidity.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            showHumidity[LYON_RECONSTRUCTED_SENSOR_ID] = false
        }
'''
if old_toggle in main:
    main = main.replace(old_toggle, new_toggle, 1)

old_chart_sensors = '''    val chartSensors = if (sensors.any { it.stableKey == LyonWeatherSync.STABLE_KEY }) {
        sensors + lyonReconstructedSensor
    } else sensors
    val chartSampleMap = if (chartSensors.any { it.id == LYON_RECONSTRUCTED_SENSOR_ID }) {
        sampleMap + (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples)
    } else sampleMap
'''
new_chart_sensors = '''    // Permanent virtual curve: never hidden by token/network/source state.
    val chartSensors = sensors.filterNot { it.id == LYON_RECONSTRUCTED_SENSOR_ID } + lyonReconstructedSensor
    val chartSampleMap = sampleMap + (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples)
'''
if old_chart_sensors in main:
    main = main.replace(old_chart_sensors, new_chart_sensors, 1)

# Main selector wording must stay truthful when the no-token fallback is in use.
main = main.replace(
    'sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon officiel · 6 min"',
    'sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon brut · officiel/secours"'
)

# Top refresh: use the hybrid source rather than requiring a token.
old_top = '''                            val result = withContext(Dispatchers.IO) {
                                runCatching { meteoOfficial.syncSixMinute24h() }
                            }
                            busy = false
                            reloadToken++
                            snackbar.showSnackbar(
                                result.fold(
                                    onSuccess = {
                                        "Lyon 6 min officiel : ${it.received} reçue(s) · ${it.stored} stockée(s)"
                                    },
                                    onFailure = {
                                        "Lyon non actualisé : ${it.message ?: "réseau ou source indisponible"}"
                                    }
                                )
                            )
'''
new_top = '''                            val result = runCatching { syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }
                            busy = false
                            reloadToken++
                            snackbar.showSnackbar(
                                result.fold(
                                    onSuccess = { "${it.label} : ${it.received} reçue(s) · ${it.stored} stockée(s)" },
                                    onFailure = { "Lyon non actualisé : ${it.message ?: "réseau ou source indisponible"}" }
                                )
                            )
'''
if old_top in main:
    main = main.replace(old_top, new_top, 1)

old_card_sync = '''                                val result = withContext(Dispatchers.IO) { runCatching { meteoOfficial.syncSixMinute24h() } }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "Lyon 6 min officiel : ${it.received} reçue(s) · ${it.stored} stockée(s)" },
                                        onFailure = { "Lyon : ${it.message ?: "source indisponible"}" }
                                    )
                                )
'''
new_card_sync = '''                                val result = runCatching { syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "${it.label} : ${it.received} reçue(s) · ${it.stored} stockée(s)" },
                                        onFailure = { "Lyon : ${it.message ?: "source indisponible"}" }
                                    )
                                )
'''
if old_card_sync in main:
    main = main.replace(old_card_sync, new_card_sync, 1)

old_complete = '''                                val result = withContext(Dispatchers.IO) {
                                    runCatching {
                                    val b = db.physicalSensorBounds() ?: error("Aucune période physique")
                                    meteoOfficial.syncHourly(b.first, b.last)
                                }
                                }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = {
                                            "Lyon horaire officiel : ${it.received} reçue(s) · ${it.stored} stockée(s)"
                                        },
                                        onFailure = { "Compléter Lyon : ${it.message ?: "archives indisponibles"}" }
                                    )
                                )
'''
new_complete = '''                                val result = runCatching { completeLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "${it.label} : ${it.received} lot(s) · ${it.stored} valeur(s) stockée(s)" },
                                        onFailure = { "Compléter Lyon : ${it.message ?: "archives indisponibles"}" }
                                    )
                                )
'''
if old_complete in main:
    main = main.replace(old_complete, new_complete, 1)

main = main.replace(
    '"Lyon-Bron officiel : 6 min sur 24 h + archive horaire. Détail = brut / horaire / reconstruit."',
    '"Lyon-Bron permanent : officiel 6 min prioritaire, secours auto sans token. Reconstruit reste toujours disponible."'
)

MAIN.write_text(main, encoding='utf-8')

# -----------------------------------------------------------------------------
# Reconstruction: official data wins, legacy/no-token Lyon becomes fallback
# anchors only. Suspicious V-shaped excursions are rejected before interpolation.
# -----------------------------------------------------------------------------
lab = LAB.read_text(encoding='utf-8')

if 'fun queryLegacyFallback' not in lab:
    anchor = '    fun reconstruct(from: Long, to: Long): LyonReconstruction {\n'
    helper = '''    private fun queryLegacyFallback(from: Long, to: Long): List<LyonLabPoint> {
        val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
        return db.querySamples(sensor.id, from, to).map {
            LyonLabPoint(it.timestamp, it.temperature, it.humidity, LyonSeriesKind.RECONSTRUCTED)
        }
    }

'''
    if anchor not in lab:
        raise SystemExit('v0.9.2: reconstruct anchor missing')
    lab = lab.replace(anchor, helper + anchor, 1)

old_head = '''        val six = queryOfficial(LyonSeriesKind.SIX_MIN, paddedFrom, paddedTo).sortedBy { it.timestamp }
        val hourly = queryOfficial(LyonSeriesKind.HOURLY, paddedFrom, paddedTo).sortedBy { it.timestamp }
        val overrides = queryOverrides(from, to)

        val sixByTs = six.associateBy { it.timestamp }
        val hourByTs = hourly.associateBy { it.timestamp }
        val validSix = six.filterIndexed { index, p -> !isSuspectSix(p, index, six, hourly) }
        val anchorsByTs = linkedMapOf<Long, LyonLabPoint>()
        hourly.forEach { anchorsByTs[it.timestamp] = it }
        validSix.forEach { anchorsByTs[it.timestamp] = it }
'''
new_head = '''        val six = queryOfficial(LyonSeriesKind.SIX_MIN, paddedFrom, paddedTo).sortedBy { it.timestamp }
        val hourly = queryOfficial(LyonSeriesKind.HOURLY, paddedFrom, paddedTo).sortedBy { it.timestamp }
        val fallback = queryLegacyFallback(paddedFrom, paddedTo).sortedBy { it.timestamp }
        val overrides = queryOverrides(from, to)

        val sixByTs = six.associateBy { it.timestamp }
        val validSix = six.filterIndexed { index, p -> !isSuspectSix(p, index, six, hourly) }
        val validFallback = fallback.filterIndexed { index, p -> !isSuspectFallback(p, index, fallback, hourly) }
        val fallbackByTs = validFallback.associateBy { it.timestamp }
        val anchorsByTs = linkedMapOf<Long, LyonLabPoint>()
        // Priority: fallback < hourly official < six-minute official < manual override.
        validFallback.forEach { anchorsByTs[it.timestamp] = it }
        hourly.forEach { anchorsByTs[it.timestamp] = it }
        validSix.forEach { anchorsByTs[it.timestamp] = it }
'''
if old_head in lab:
    lab = lab.replace(old_head, new_head, 1)
elif 'val validFallback = fallback.filterIndexed' not in lab:
    raise SystemExit('v0.9.2: reconstruction header anchor missing')

old_loop = '''            if (raw6 != null && !isSuspectSix(raw6, six.indexOf(raw6), six, hourly)) {
                out += LyonLabPoint(ts, raw6.temperature, raw6.humidity, LyonSeriesKind.RECONSTRUCTED)
                ts += SIX_MIN_MS
                continue
            }

            val interpolated = interpolateAt(anchors, ts)
'''
new_loop = '''            if (raw6 != null && !isSuspectSix(raw6, six.indexOf(raw6), six, hourly)) {
                out += LyonLabPoint(ts, raw6.temperature, raw6.humidity, LyonSeriesKind.RECONSTRUCTED)
                ts += SIX_MIN_MS
                continue
            }

            // Exact fallback point is accepted only after anomaly filtering.
            val rawFallback = fallbackByTs[ts]
            if (raw6 == null && rawFallback != null) {
                out += LyonLabPoint(ts, rawFallback.temperature, rawFallback.humidity, LyonSeriesKind.RECONSTRUCTED)
                ts += SIX_MIN_MS
                continue
            }

            val interpolated = interpolateAt(anchors, ts)
'''
if old_loop in lab:
    lab = lab.replace(old_loop, new_loop, 1)

lab = lab.replace(
    '"Continuité bornée entre deux ancres officielles fiables.", false',
    '"Continuité bornée entre ancres fiables ; l’officiel garde la priorité.", false'
)

if 'private fun isSuspectFallback(' not in lab:
    anchor = '    private fun interpolateAt(anchors: List<LyonLabPoint>, timestamp: Long): Pair<Double, Double>? {\n'
    helper = '''    private fun isSuspectFallback(
        point: LyonLabPoint,
        index: Int,
        fallback: List<LyonLabPoint>,
        hourly: List<LyonLabPoint>
    ): Boolean {
        if (point.temperature !in -35.0..50.0 || point.humidity !in 0.0..100.0) return true
        if (index !in fallback.indices) return false

        val hour = nearestWithin(hourly, point.timestamp, 31L * 60L * 1000L)
        if (hour != null && abs(point.temperature - hour.temperature) >= 5.0) return true

        // Reject a short-lived V/peak: a nearby value before and after agree,
        // while the current point is >= 5 °C away from their baseline.
        val before = fallback.subList(max(0, index - 4), index)
        val after = fallback.subList(index + 1, min(fallback.size, index + 5))
        val excursion = before.any { left ->
            point.timestamp - left.timestamp <= 4L * HOUR_MS && after.any { right ->
                right.timestamp - point.timestamp <= 4L * HOUR_MS &&
                    abs(left.temperature - right.temperature) <= 3.0 &&
                    abs(point.temperature - ((left.temperature + right.temperature) / 2.0)) >= 5.0
            }
        }
        return excursion
    }

'''
    if anchor not in lab:
        raise SystemExit('v0.9.2: interpolate anchor missing')
    lab = lab.replace(anchor, helper + anchor, 1)

# Detail token is optional, not a visibility requirement.
lab = lab.replace('label = { Text("Clé / token Météo-France") }', 'label = { Text("Clé / token Météo-France (facultatif)") }')

LAB.write_text(lab, encoding='utf-8')
print('FabData v0.9.2 permanent Lyon + hybrid fallback patch applied')
