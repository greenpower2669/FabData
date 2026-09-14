from pathlib import Path

p = Path('app/src/main/java/com/fabdata/app/ForecastHorizonArchive.kt')
s = p.read_text(encoding='utf-8')
if 'fixed-window-10m-v2' in s:
    print('horizon windows already patched')
    raise SystemExit(0)

def once(old, new):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'expected one match, got {n}: {old[:90]}')
    s = s.replace(old, new, 1)

once('    const val POLICY_VERSION = "fixed-lead-hour-v1"', '    const val POLICY_VERSION = "fixed-window-10m-v2"')
once(
'''private data class RawHorizonForecast(
    val issuedAt: Long,
    val targetAt: Long,
    val temperature: Double,
    val humidity: Double,
    val confidence: Double,
    val provider: String
)''',
'''private data class RawHorizonForecast(
    val issuedAt: Long,
    val captureSlot: Long,
    val targetAt: Long,
    val temperature: Double,
    val humidity: Double,
    val confidence: Double,
    val provider: String
)''')

once(
'''                val leadMs = row.targetAt - row.issuedAt
                if (leadMs <= 5L * HORIZON_MINUTE_MS) return@forEach
                val leadHour = (leadMs.toDouble() / HORIZON_HOUR_MS.toDouble()).roundToInt()
                if (leadHour !in FORECAST_HORIZON_HOURS) return@forEach
                val errorMinutes = (abs(leadMs - leadHour * HORIZON_HOUR_MS) / HORIZON_MINUTE_MS).toInt()
                if (errorMinutes > HORIZON_MATCH_TOLERANCE_MIN) return@forEach
''',
'''                // H1 = +10..+60 min, H2 = +70..+120 min, ... H48.
                // Anchor on the canonical capture slot, never the row download millisecond.
                val leadMs = row.targetAt - row.captureSlot
                if (leadMs < HORIZON_STEP_10M_MS || leadMs > 48L * HORIZON_HOUR_MS) return@forEach
                val leadHour = ((leadMs + HORIZON_HOUR_MS - 1L) / HORIZON_HOUR_MS).toInt()
                if (leadHour !in FORECAST_HORIZON_HOURS) return@forEach
                val errorMinutes = (abs(leadMs - leadHour * HORIZON_HOUR_MS) / HORIZON_MINUTE_MS).toInt()
''')

once(
'''            SELECT issued_at, target_ts, temperature, humidity, confidence, provider
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND issued_at<=?
            ORDER BY target_ts, issued_at''',
'''            SELECT issued_at,
                   COALESCE(capture_slot_10m, (issued_at / 600000) * 600000),
                   target_ts, temperature, humidity, confidence, provider
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND issued_at<=?
            ORDER BY target_ts, issued_at''')

once(
'''                out += RawHorizonForecast(
                    issuedAt = c.getLong(0),
                    targetAt = c.getLong(1),
                    temperature = c.getDouble(2),
                    humidity = if (c.isNull(3)) 50.0 else c.getDouble(3),
                    confidence = if (c.isNull(4)) 0.65 else c.getDouble(4).coerceIn(0.0, 1.0),
                    provider = if (c.isNull(5)) "active_reference" else c.getString(5)
                )''',
'''                out += RawHorizonForecast(
                    issuedAt = c.getLong(0),
                    captureSlot = c.getLong(1),
                    targetAt = c.getLong(2),
                    temperature = c.getDouble(3),
                    humidity = if (c.isNull(4)) 50.0 else c.getDouble(4),
                    confidence = if (c.isNull(5)) 0.65 else c.getDouble(5).coerceIn(0.0, 1.0),
                    provider = if (c.isNull(6)) "active_reference" else c.getString(6)
                )''')

once(
'''        return ForecastHorizonCurveSet(
            activeWeather = interpolate10Minutes(activeRows(referenceKey, from, to, now).map { row ->''',
'''        latestSnapshotWeatherByLead(referenceKey, from, to, now).forEach { (lead, livePoints) ->
            val merged = (weather[lead].orEmpty() + livePoints)
                .associateBy { it.timestamp }
                .values
                .sortedBy { it.timestamp }
            weather[lead] = merged.toMutableList()
        }

        return ForecastHorizonCurveSet(
            activeWeather = interpolate10Minutes(activeRows(referenceKey, from, to, now).map { row ->''')

anchor = '    private fun rawRows(referenceKey: String, from: Long, to: Long, now: Long): List<RawHorizonForecast> {'
helper = '''    /**
     * The latest single provider jet is expanded locally to a 10-minute grid for display.
     * Interpolated points are not persisted, avoiding a x6 archive size increase.
     */
    private fun latestSnapshotWeatherByLead(
        referenceKey: String,
        from: Long,
        to: Long,
        now: Long
    ): Map<Int, List<SamplePoint>> {
        val slot = db.readableDatabase.rawQuery(
            """
            SELECT MAX(COALESCE(capture_slot_10m, (issued_at / 600000) * 600000))
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=? AND issued_at<=?
            """.trimIndent(),
            arrayOf(referenceKey, now.toString())
        ).use { c -> if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null } ?: return emptyMap()

        val raw = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT target_ts, temperature, humidity, confidence
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=?
              AND COALESCE(capture_slot_10m, (issued_at / 600000) * 600000)=?
            ORDER BY target_ts
            """.trimIndent(),
            arrayOf(referenceKey, slot.toString())
        ).use { c ->
            while (c.moveToNext()) {
                raw += SamplePoint(
                    FORECAST_ACTIVE_SENSOR_ID,
                    c.getLong(0), c.getDouble(1),
                    if (c.isNull(2)) 50.0 else c.getDouble(2),
                    PointSource.FORECAST,
                    if (c.isNull(3)) 0.65 else c.getDouble(3).coerceIn(0.0, 1.0)
                )
            }
        }
        if (raw.size < 2) return emptyMap()
        val start = maxOf(from, slot + HORIZON_STEP_10M_MS)
        val end = minOf(to, slot + 48L * HORIZON_HOUR_MS)
        if (end < start) return emptyMap()

        val grouped = mutableMapOf<Int, MutableList<SamplePoint>>()
        interpolate10Minutes(raw).forEach { point ->
            if (point.timestamp !in start..end) return@forEach
            val delta = point.timestamp - slot
            if (delta < HORIZON_STEP_10M_MS || delta > 48L * HORIZON_HOUR_MS) return@forEach
            val lead = ((delta + HORIZON_HOUR_MS - 1L) / HORIZON_HOUR_MS).toInt()
            if (lead !in FORECAST_HORIZON_HOURS) return@forEach
            grouped.getOrPut(lead) { mutableListOf() } += point.copy(sensorId = forecastHorizonSensorId(lead))
        }
        return grouped
    }

''' + anchor
once(anchor, helper)
p.write_text(s, encoding='utf-8')
print('horizon windows patched')
