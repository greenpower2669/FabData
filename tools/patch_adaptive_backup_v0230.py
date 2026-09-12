from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "app/src/main/java/com/fabdata/app/BackupV3Support.kt"
text = PATH.read_text(encoding="utf-8")


def replace_once_or_done(old, new, label):
    global text
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 old occurrence, got {count}")
    text = text.replace(old, new, 1)


replace_once_or_done(
    '''        ForecastPastArchiveStore.ensure(db.writableDatabase)
        ForecastCurve10mStore.ensure(db.writableDatabase)

        writeJson(writer, "WEATHER_META", weatherMetaJson())
''',
    '''        ForecastPastArchiveStore.ensure(db.writableDatabase)
        ForecastCurve10mStore.ensure(db.writableDatabase)
        ForecastAdaptiveStore.ensure(db.writableDatabase)

        writeJson(writer, "WEATHER_META", weatherMetaJson())
''',
    "adaptive ensure"
)

old_weather_start = '''        db.readableDatabase.rawQuery(
            """
            SELECT reference_key, timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
'''
adaptive_rows = '''        db.readableDatabase.rawQuery(
            """
            SELECT reference_key, horizon_hour, issued_at, target_ts, baseline_temperature,
                   adaptive_temperature, tangent_temperature, history_bias, tangent_bias,
                   regime_score, history_samples, humidity, confidence, provider, model_version, created_at
            FROM ${ForecastAdaptiveStore.TABLE}
            ORDER BY reference_key, horizon_hour, target_ts, issued_at
            """.trimIndent(), null
        ).use { c ->
            while (c.moveToNext()) {
                writeJson(writer, "FORECAST_ADAPTIVE_ARCHIVE", JSONObject().apply {
                    put("referenceKey", c.getString(0))
                    put("horizonHour", c.getInt(1))
                    put("issuedAt", c.getLong(2))
                    put("targetAt", c.getLong(3))
                    put("baselineTemperature", c.getDouble(4))
                    put("adaptiveTemperature", c.getDouble(5))
                    put("tangentTemperature", c.getDouble(6))
                    put("historyBias", c.getDouble(7))
                    put("tangentBias", c.getDouble(8))
                    put("regimeScore", c.getDouble(9))
                    put("historySamples", c.getInt(10))
                    put("humidity", c.getDouble(11))
                    put("confidence", c.getDouble(12))
                    put("provider", c.getString(13))
                    put("modelVersion", c.getString(14))
                    put("createdAt", c.getLong(15))
                })
            }
        }

''' + old_weather_start
replace_once_or_done(old_weather_start, adaptive_rows, "adaptive backup rows")

replace_once_or_done(
    '''                "FORECAST_CURVE_10M_ARCHIVE" -> restoreForecastCurve10mArchive(json(values))
                "WEATHER" -> restoreWeather(values)
''',
    '''                "FORECAST_CURVE_10M_ARCHIVE" -> restoreForecastCurve10mArchive(json(values))
                "FORECAST_ADAPTIVE_ARCHIVE" -> restoreForecastAdaptiveArchive(json(values))
                "WEATHER" -> restoreWeather(values)
''',
    "adaptive import case"
)

restore_weather_marker = '''    private fun restoreWeather(values: Map<String, String>) {
'''
restore_adaptive = '''    private fun restoreForecastAdaptiveArchive(o: JSONObject) {
        val key = o.optString("referenceKey", "").trim()
        val horizon = o.optInt("horizonHour", -1)
        val issuedAt = o.optLong("issuedAt", -1L)
        val targetAt = o.optLong("targetAt", -1L)
        val baseline = o.optDouble("baselineTemperature", Double.NaN)
        val adaptive = o.optDouble("adaptiveTemperature", Double.NaN)
        val tangent = o.optDouble("tangentTemperature", Double.NaN)
        if (key.isBlank() || horizon !in FORECAST_ADAPTIVE_HORIZONS || issuedAt < 0L || targetAt < 0L ||
            !baseline.isFinite() || !adaptive.isFinite() || !tangent.isFinite()
        ) return
        ForecastAdaptiveStore.restore(
            sql = db.writableDatabase,
            referenceKey = key,
            horizonHour = horizon,
            issuedAt = issuedAt,
            targetAt = targetAt,
            baselineTemperature = baseline,
            adaptiveTemperature = adaptive,
            tangentTemperature = tangent,
            historyBias = o.optDouble("historyBias", 0.0),
            tangentBias = o.optDouble("tangentBias", 0.0),
            regimeScore = o.optDouble("regimeScore", 0.0),
            historySamples = o.optInt("historySamples", 0),
            humidity = o.optDouble("humidity", 50.0),
            confidence = o.optDouble("confidence", 0.5),
            provider = o.optString("provider", "active_reference"),
            modelVersion = o.optString("modelVersion", ForecastAdaptiveStore.MODEL_VERSION),
            createdAt = o.optLong("createdAt", issuedAt)
        )
    }

''' + restore_weather_marker
replace_once_or_done(restore_weather_marker, restore_adaptive, "adaptive restore helper")

PATH.write_text(text, encoding="utf-8")
print("v0.23.0 adaptive backup patch applied")
