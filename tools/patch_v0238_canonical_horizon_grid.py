from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'{path}: expected one match, got {n}: {old[:120]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')


def replace_all_exact(path: str, old: str, new: str, expected: int) -> None:
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    n = s.count(old)
    if n != expected:
        raise SystemExit(f'{path}: expected {expected} matches, got {n}: {old[:120]!r}')
    p.write_text(s.replace(old, new), encoding='utf-8')


# Version bump.
replace_once(
    'app/build.gradle.kts',
    '        versionCode = 64\n        versionName = "0.23.7"',
    '        versionCode = 65\n        versionName = "0.23.8"'
)

# Forecast acquisition is now strictly owned by the canonical 10-minute slot scheduler.
weather = 'app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt'
replace_once(
    weather,
    '    fun refreshSelected(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {',
    '    fun refreshSelected(\n        reference: WeatherReference,\n        from: Long,\n        to: Long,\n        includeForecastAfterCanonicalClaim: Boolean = false\n    ): WeatherReferenceSyncResult {'
)
replace_once(
    weather,
    '    fun refreshForecast(reference: WeatherReference): Int {\n        val now = System.currentTimeMillis()',
    '''    /**\n     * Provider forecast access is intentionally gated. Only callers that already own the\n     * canonical :00/:10/:20/... capture slot may set [canonicalSlotClaimed] to true.\n     * History refreshes, manual station refreshes and UI changes therefore cannot create\n     * a second H+1..H+48 provider request inside the same slot.\n     */\n    fun refreshForecast(reference: WeatherReference, canonicalSlotClaimed: Boolean = false): Int {\n        if (!canonicalSlotClaimed) return 0\n        val now = System.currentTimeMillis()'''
)
replace_once(
    weather,
    '        val oldForecasts = store.query(reference.key, now - hourMs, now + 50L * hourMs)',
    '        val oldForecasts = store.query(reference.key, now - 2L * hourMs, now + 50L * hourMs)'
)
replace_once(
    weather,
    '    fun refreshRecent(reference: WeatherReference): WeatherReferenceSyncResult {',
    '    fun refreshRecent(\n        reference: WeatherReference,\n        includeForecastAfterCanonicalClaim: Boolean = false\n    ): WeatherReferenceSyncResult {'
)
replace_all_exact(
    weather,
    '        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)',
    '        val forecast = if (includeForecastAfterCanonicalClaim) {\n            runCatching { refreshForecast(reference, canonicalSlotClaimed = true) }.getOrDefault(0)\n        } else 0',
    2
)
replace_once(
    weather,
    '            if (ts < now - 30L * 60L * 1000L || ts > end) continue',
    '''            // Keep the previous hourly anchor in the SAME provider jet. It is needed to\n            // interpolate the canonical H1 points (+10, +20, ... +60 min) even when the\n            // network call happens late in the current hour. No extra provider request is made.\n            if (ts < now - 70L * 60L * 1000L || ts > end) continue'''
)
replace_once(
    weather,
    '            // fallback coordonné + forecast peut être rafraîchi chaque minute.',
    '            // fallback coordonné reste indépendant ; le forecast futur est réservé au créneau canonique.'
)

# Foreground scheduler is the only foreground path allowed to request future forecast data.
replace_once(
    'app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt',
    '                    manager.refreshRecent(reference)',
    '                    manager.refreshRecent(reference, includeForecastAfterCanonicalClaim = true)'
)

# WorkManager already owns the same canonical slot claim; make that contract explicit.
replace_once(
    'app/src/main/java/com/fabdata/app/ForecastArchiveWorker.kt',
    '            val count = manager.refreshForecast(reference)',
    '            val count = manager.refreshForecast(reference, canonicalSlotClaimed = true)'
)

# Build the visible H1..H48 bands from one single raw provider jet. The 10-minute points
# are derived in memory and are never persisted, so the archive size does not multiply by six.
horizon = 'app/src/main/java/com/fabdata/app/ForecastHorizonArchive.kt'
old_helper = '''    private fun latestSnapshotWeatherByLead(\n        referenceKey: String,\n        from: Long,\n        to: Long,\n        now: Long\n    ): Map<Int, List<SamplePoint>> {\n        val slot = db.readableDatabase.rawQuery(\n            """\n            SELECT MAX(COALESCE(capture_slot_10m, (issued_at / 600000) * 600000))\n            FROM ${ForecastMemoryStore.TABLE}\n            WHERE reference_key=? AND issued_at<=?\n            """.trimIndent(),\n            arrayOf(referenceKey, now.toString())\n        ).use { c -> if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null } ?: return emptyMap()\n\n        val raw = mutableListOf<SamplePoint>()\n        db.readableDatabase.rawQuery(\n            """\n            SELECT target_ts, temperature, humidity, confidence\n            FROM ${ForecastMemoryStore.TABLE}\n            WHERE reference_key=?\n              AND COALESCE(capture_slot_10m, (issued_at / 600000) * 600000)=?\n            ORDER BY target_ts\n            """.trimIndent(),\n            arrayOf(referenceKey, slot.toString())\n        ).use { c ->\n            while (c.moveToNext()) {\n                raw += SamplePoint(\n                    FORECAST_ACTIVE_SENSOR_ID,\n                    c.getLong(0), c.getDouble(1),\n                    if (c.isNull(2)) 50.0 else c.getDouble(2),\n                    PointSource.FORECAST,\n                    if (c.isNull(3)) 0.65 else c.getDouble(3).coerceIn(0.0, 1.0)\n                )\n            }\n        }\n        if (raw.size < 2) return emptyMap()\n        val start = maxOf(from, slot + HORIZON_STEP_10M_MS)\n        val end = minOf(to, slot + 48L * HORIZON_HOUR_MS)\n        if (end < start) return emptyMap()\n\n        val grouped = mutableMapOf<Int, MutableList<SamplePoint>>()\n        interpolate10Minutes(raw).forEach { point ->\n            if (point.timestamp !in start..end) return@forEach\n            val delta = point.timestamp - slot\n            if (delta < HORIZON_STEP_10M_MS || delta > 48L * HORIZON_HOUR_MS) return@forEach\n            val lead = ((delta + HORIZON_HOUR_MS - 1L) / HORIZON_HOUR_MS).toInt()\n            if (lead !in FORECAST_HORIZON_HOURS) return@forEach\n            grouped.getOrPut(lead) { mutableListOf() } += point.copy(sensorId = forecastHorizonSensorId(lead))\n        }\n        return grouped\n    }\n'''
new_helper = '''    /**\n     * Expands the latest single provider jet to the canonical 10-minute display grid.\n     * H1 = +10..+60 min, H2 = +70..+120 min, ... H48. Every complete provider jet\n     * therefore yields six points per horizon immediately, without waiting for later captures.\n     * These interpolated points stay in memory only; raw provider snapshots remain the archive.\n     */\n    fun latestSnapshotWeatherByLead(\n        referenceKey: String,\n        from: Long,\n        to: Long,\n        now: Long\n    ): Map<Int, List<SamplePoint>> {\n        val slot = db.readableDatabase.rawQuery(\n            """\n            SELECT MAX(COALESCE(capture_slot_10m, (issued_at / 600000) * 600000))\n            FROM ${ForecastMemoryStore.TABLE}\n            WHERE reference_key=? AND issued_at<=?\n            """.trimIndent(),\n            arrayOf(referenceKey, now.toString())\n        ).use { c -> if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null } ?: return emptyMap()\n\n        val raw = mutableListOf<SamplePoint>()\n        db.readableDatabase.rawQuery(\n            """\n            SELECT target_ts, temperature, humidity, confidence\n            FROM ${ForecastMemoryStore.TABLE}\n            WHERE reference_key=?\n              AND COALESCE(capture_slot_10m, (issued_at / 600000) * 600000)=?\n            ORDER BY target_ts\n            """.trimIndent(),\n            arrayOf(referenceKey, slot.toString())\n        ).use { c ->\n            while (c.moveToNext()) {\n                raw += SamplePoint(\n                    FORECAST_ACTIVE_SENSOR_ID,\n                    c.getLong(0), c.getDouble(1),\n                    if (c.isNull(2)) 50.0 else c.getDouble(2),\n                    PointSource.FORECAST,\n                    if (c.isNull(3)) 0.65 else c.getDouble(3).coerceIn(0.0, 1.0)\n                )\n            }\n        }\n        val anchors = raw.distinctBy { it.timestamp }.sortedBy { it.timestamp }\n        if (anchors.size < 2) return emptyMap()\n\n        fun sampleAt(target: Long): SamplePoint? {\n            anchors.firstOrNull { it.timestamp == target }?.let { return it }\n            val rightIndex = anchors.indexOfFirst { it.timestamp > target }\n            if (rightIndex <= 0) return null\n            val left = anchors[rightIndex - 1]\n            val right = anchors[rightIndex]\n            val gap = right.timestamp - left.timestamp\n            if (gap <= 0L || gap > 95L * HORIZON_MINUTE_MS) return null\n            val linear = ((target - left.timestamp).toDouble() / gap.toDouble()).coerceIn(0.0, 1.0)\n            val smooth = 0.5 - 0.5 * cos(PI * linear)\n            val leftConfidence = left.confidence ?: 0.65\n            val rightConfidence = right.confidence ?: 0.65\n            return SamplePoint(\n                sensorId = FORECAST_ACTIVE_SENSOR_ID,\n                timestamp = target,\n                temperature = left.temperature + (right.temperature - left.temperature) * smooth,\n                humidity = left.humidity + (right.humidity - left.humidity) * smooth,\n                source = PointSource.FORECAST,\n                confidence = (leftConfidence + (rightConfidence - leftConfidence) * linear).coerceIn(0.0, 1.0)\n            )\n        }\n\n        val grouped = mutableMapOf<Int, MutableList<SamplePoint>>()\n        var target = slot + HORIZON_STEP_10M_MS\n        val lastTarget = slot + 48L * HORIZON_HOUR_MS\n        while (target <= lastTarget) {\n            if (target in from..to) {\n                val delta = target - slot\n                val lead = ((delta + HORIZON_HOUR_MS - 1L) / HORIZON_HOUR_MS).toInt()\n                if (lead in FORECAST_HORIZON_HOURS) {\n                    sampleAt(target)?.let { point ->\n                        grouped.getOrPut(lead) { mutableListOf() } +=\n                            point.copy(sensorId = forecastHorizonSensorId(lead))\n                    }\n                }\n            }\n            target += HORIZON_STEP_10M_MS\n        }\n        return grouped.mapValues { (_, points) -> points.sortedBy { it.timestamp } }\n    }\n'''
replace_once(horizon, old_helper, new_helper)

# Adaptive curves reuse the same current provider jet in memory: one stored adaptive endpoint
# still carries the scientific model result, while the visible six-point band gets the same
# local correction without persisting 6x more rows.
adaptive = 'app/src/main/java/com/fabdata/app/ForecastAdaptive.kt'
replace_once(
    adaptive,
    '''        return ForecastAdaptiveCurveSet(\n            grouped.mapValues { (_, targetMap) ->\n                interpolate10Minutes(targetMap.values.map { it.second }.sortedBy { it.timestamp })\n            }\n        )''',
    '''        val liveWeather = ForecastHorizonArchive(db).latestSnapshotWeatherByLead(referenceKey, from, to, now)\n        FORECAST_ADAPTIVE_HORIZONS.forEach { horizon ->\n            val current = latestCurrent(referenceKey, horizon, now) ?: return@forEach\n            val correction = (current.adaptiveTemperature - current.baselineTemperature).coerceIn(-12.0, 12.0)\n            val targetMap = grouped.getOrPut(horizon) { linkedMapOf() }\n            liveWeather[horizon].orEmpty().forEach { baseline ->\n                val point = SamplePoint(\n                    sensorId = forecastAdaptiveSensorId(horizon),\n                    timestamp = baseline.timestamp,\n                    temperature = (baseline.temperature + correction).coerceIn(-70.0, 70.0),\n                    humidity = baseline.humidity,\n                    source = PointSource.FORECAST,\n                    confidence = minOf(baseline.confidence ?: current.confidence, current.confidence)\n                )\n                // Current canonical band wins only in memory. The causal archive remains untouched.\n                targetMap[baseline.timestamp] = now to point\n            }\n        }\n\n        return ForecastAdaptiveCurveSet(\n            grouped.mapValues { (_, targetMap) ->\n                interpolate10Minutes(targetMap.values.map { it.second }.sortedBy { it.timestamp })\n            }\n        )'''
)

# H+24 now uses the same canonical six-point band as H1..H48 instead of the legacy exact-H24
# selector. Existing stable key/id is preserved so all user personalization remains compatible.
main = 'app/src/main/java/com/fabdata/app/MainActivity.kt'
replace_once(
    main,
    '    val forecastReconstructedSamples = selectableForecastCurves.reconstructed',
    '''    val forecastReconstructedSamples = forecastHorizonCurves.weatherByLead[24].orEmpty()\n        .map { it.copy(sensorId = FORECAST_RECONSTRUCTED_SENSOR_ID) }\n        .ifEmpty { selectableForecastCurves.reconstructed }'''
)
replace_once(
    main,
    '            "Archive locale fixe H+$lead · valeur conservée avant remplacement",',
    '            "Fenêtre canonique H+$lead · six points de 10 min par jet",'
)
replace_once(
    main,
    '    val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo H+24", "H+24 fixe · archive locale, backfill si disponible · rendu 10 min", 12, forecastReconstructedSamples.lastOrNull()?.timestamp)',
    '    val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo H+24", "Fenêtre canonique H+24 · six points de 10 min par jet · archive RAW inchangée", 12, forecastReconstructedSamples.lastOrNull()?.timestamp)'
)
replace_once(
    main,
    '            "Tangente + changement de régime · archive causale H+$lead",',
    '            "Tangente + changement de régime · bande canonique 10 min H+$lead",'
)

print('v0.23.8 canonical horizon grid patch applied')
