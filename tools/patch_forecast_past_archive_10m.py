from pathlib import Path


def replace_once(path: str, old: str, new: str, marker: str) -> None:
    p = Path(path)
    s = p.read_text()
    if marker in s:
        return
    if old not in s:
        raise SystemExit(f"missing patch anchor {marker} in {path}")
    p.write_text(s.replace(old, new, 1))


# Main chart: backfill cached archive once, then render both prediction curves on the shared 10-min grid.
main = "app/src/main/java/com/fabdata/app/MainActivity.kt"
replace_once(
    main,
    '''            val queryTo = maxOf(history.last, now + 24L * 60L * 60L * 1000L)\n            selectableForecastCurves = withContext(Dispatchers.IO) { ForecastSelectableCurveStore(db).query(visualReference.key, history.first, queryTo, now) }\n''',
    '''            val queryTo = maxOf(history.last, now + 24L * 60L * 60L * 1000L)\n            selectableForecastCurves = withContext(Dispatchers.IO) {\n                // Historical forecast API is only a backfill. Once cached it is restored from\n                // FabData backup, so an app update does not need to download it again.\n                ForecastPastArchiveBackfill(db).ensure(\n                    visualReference, history.first, minOf(history.last, now - 60L * 60L * 1000L), now\n                )\n                ForecastSelectableCurveStore(db).query(visualReference.key, history.first, queryTo, now)\n            }\n''',
    "Historical forecast API is only a backfill"
)

p = Path(main)
s = p.read_text()
s = s.replace('"Prévision reconstruite", "Archive prévisionnelle + futur actif"', '"Prévision météo reconstruite", "Archives de prévisions + futur actif · rendu 10 min"')
s = s.replace('"Prévision Fab", "Notre prévision locale corrigée"', '"Prévision Fab reconstruite", "Modèle local utilisateur · rendu 10 min"')
s = s.replace('FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision reconstruite"', 'FORECAST_RECONSTRUCTED_SENSOR_ID -> "Prévision météo reconstruite"')
s = s.replace('FORECAST_FAB_SENSOR_ID -> "Prévision Fab"', 'FORECAST_FAB_SENSOR_ID -> "Prévision Fab reconstruite"')
p.write_text(s)

# Freeze the exact 10-minute past visual/backtest by model version.
selectable = "app/src/main/java/com/fabdata/app/ForecastSelectableCurves.kt"
replace_once(
    selectable,
    '''        ForecastLocalSnapshotStore.ensure(writable)\n        ForecastPastArchiveStore.ensure(writable)\n''',
    '''        ForecastLocalSnapshotStore.ensure(writable)\n        ForecastPastArchiveStore.ensure(writable)\n        ForecastCurve10mStore.ensure(writable)\n''',
    "ForecastCurve10mStore.ensure(writable)"
)
replace_once(
    selectable,
    '''        return ForecastSelectableCurves(\n            reconstructed = interpolatePrediction10Minutes(reconstructedAnchors),\n            fab = interpolatePrediction10Minutes(fabAnchors)\n        )\n''',
    '''        val generatedWeather = interpolatePrediction10Minutes(reconstructedAnchors)\n        val generatedFab = interpolatePrediction10Minutes(fabAnchors)\n\n        // Once a 10-minute point becomes past, freeze both values together. This makes\n        // weather-vs-Fab comparison auditable and keeps exactly the same curve after restore.\n        ForecastCurve10mStore.persistAlignedPast(\n            db, referenceKey, generatedWeather, generatedFab, now\n        )\n        val frozenPast = ForecastCurve10mStore.query(\n            db, referenceKey, from, minOf(to, now)\n        )\n        val frozenWeather = frozenPast.map { p ->\n            SamplePoint(\n                FORECAST_RECONSTRUCTED_SENSOR_ID, p.targetAt, p.weatherTemperature, p.humidity,\n                PointSource.FORECAST, p.weatherConfidence\n            )\n        }\n        val frozenFab = frozenPast.map { p ->\n            SamplePoint(\n                FORECAST_FAB_SENSOR_ID, p.targetAt, p.fabTemperature, p.humidity,\n                PointSource.FORECAST, p.fabConfidence\n            )\n        }\n\n        return ForecastSelectableCurves(\n            reconstructed = (frozenWeather + generatedWeather.filter { it.timestamp > now })\n                .associateBy { it.timestamp }.values.sortedBy { it.timestamp },\n            fab = (frozenFab + generatedFab.filter { it.timestamp > now })\n                .associateBy { it.timestamp }.values.sortedBy { it.timestamp }\n        )\n''',
    "ForecastCurve10mStore.persistAlignedPast"
)

# Backup: store API historical anchors, per-user causal Fab backtest, AND frozen 10-min curves.
backup = "app/src/main/java/com/fabdata/app/BackupV3Support.kt"
replace_once(
    backup,
    '''        ForecastMemoryStore.ensure(db.writableDatabase)\n        ForecastLocalSnapshotStore.ensure(db.writableDatabase)\n''',
    '''        ForecastMemoryStore.ensure(db.writableDatabase)\n        ForecastLocalSnapshotStore.ensure(db.writableDatabase)\n        ForecastPastArchiveStore.ensure(db.writableDatabase)\n        ForecastCurve10mStore.ensure(db.writableDatabase)\n''',
    "ForecastCurve10mStore.ensure(db.writableDatabase)"
)

replace_once(
    backup,
    '''        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, timestamp, temperature, humidity, source, confidence\n            FROM weather_reference_samples\n''',
    '''        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, target_ts, weather_temperature, humidity, fab_temperature,\n                   weather_confidence, fab_confidence, provider, fetched_at\n            FROM ${ForecastPastArchiveStore.TABLE}\n            ORDER BY reference_key, target_ts\n            """.trimIndent(), null\n        ).use { c ->\n            while (c.moveToNext()) {\n                writeJson(writer, "FORECAST_PAST_API_ARCHIVE", JSONObject().apply {\n                    put("referenceKey", c.getString(0))\n                    put("targetAt", c.getLong(1))\n                    put("weatherTemperature", c.getDouble(2))\n                    put("humidity", c.getDouble(3))\n                    putNullable("fabTemperature", if (c.isNull(4)) null else c.getDouble(4))\n                    put("weatherConfidence", c.getDouble(5))\n                    putNullable("fabConfidence", if (c.isNull(6)) null else c.getDouble(6))\n                    put("provider", c.getString(7))\n                    put("fetchedAt", c.getLong(8))\n                })\n            }\n        }\n\n        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, timestamp, temperature, humidity, source, confidence\n            FROM weather_reference_samples\n''',
    "FORECAST_PAST_API_ARCHIVE"
)

replace_once(
    backup,
    '''        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, timestamp, temperature, humidity, source, confidence\n            FROM weather_reference_samples\n''',
    '''        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, target_ts, weather_temperature, fab_temperature, humidity,\n                   weather_confidence, fab_confidence, origin, model_version, created_at\n            FROM ${ForecastCurve10mStore.TABLE}\n            ORDER BY reference_key, target_ts, model_version\n            """.trimIndent(), null\n        ).use { c ->\n            while (c.moveToNext()) {\n                writeJson(writer, "FORECAST_CURVE_10M_ARCHIVE", JSONObject().apply {\n                    put("referenceKey", c.getString(0))\n                    put("targetAt", c.getLong(1))\n                    put("weatherTemperature", c.getDouble(2))\n                    put("fabTemperature", c.getDouble(3))\n                    put("humidity", c.getDouble(4))\n                    put("weatherConfidence", c.getDouble(5))\n                    put("fabConfidence", c.getDouble(6))\n                    put("origin", c.getString(7))\n                    put("modelVersion", c.getString(8))\n                    put("createdAt", c.getLong(9))\n                })\n            }\n        }\n\n        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, timestamp, temperature, humidity, source, confidence\n            FROM weather_reference_samples\n''',
    "FORECAST_CURVE_10M_ARCHIVE"
)

replace_once(
    backup,
    '''                "FORECAST_LOCAL_ARCHIVE" -> restoreForecastLocalArchive(json(values))\n                "WEATHER" -> restoreWeather(values)\n''',
    '''                "FORECAST_LOCAL_ARCHIVE" -> restoreForecastLocalArchive(json(values))\n                "FORECAST_PAST_API_ARCHIVE" -> restoreForecastPastApiArchive(json(values))\n                "FORECAST_CURVE_10M_ARCHIVE" -> restoreForecastCurve10mArchive(json(values))\n                "WEATHER" -> restoreWeather(values)\n''',
    '"FORECAST_CURVE_10M_ARCHIVE" -> restoreForecastCurve10mArchive'
)

replace_once(
    backup,
    '''    private fun restoreWeather(values: Map<String, String>) {\n''',
    '''    private fun restoreForecastPastApiArchive(o: JSONObject) {\n        val key = o.optString("referenceKey", "").trim()\n        val targetAt = o.optLong("targetAt", -1L)\n        val weather = o.optDouble("weatherTemperature", Double.NaN)\n        val humidity = o.optDouble("humidity", Double.NaN)\n        if (key.isBlank() || targetAt < 0L || !weather.isFinite() || !humidity.isFinite()) return\n        ForecastPastArchiveStore.restore(\n            sql = db.writableDatabase,\n            referenceKey = key,\n            targetAt = targetAt,\n            weatherTemperature = weather,\n            humidity = humidity,\n            fabTemperature = nullableDouble(o, "fabTemperature"),\n            weatherConfidence = o.optDouble("weatherConfidence", 0.78),\n            fabConfidence = nullableDouble(o, "fabConfidence"),\n            provider = o.optString("provider", ForecastPastArchiveStore.PROVIDER),\n            fetchedAt = o.optLong("fetchedAt", System.currentTimeMillis())\n        )\n    }\n\n    private fun restoreForecastCurve10mArchive(o: JSONObject) {\n        val key = o.optString("referenceKey", "").trim()\n        val targetAt = o.optLong("targetAt", -1L)\n        val weather = o.optDouble("weatherTemperature", Double.NaN)\n        val fab = o.optDouble("fabTemperature", Double.NaN)\n        val humidity = o.optDouble("humidity", Double.NaN)\n        if (key.isBlank() || targetAt < 0L || !weather.isFinite() || !fab.isFinite() || !humidity.isFinite()) return\n        ForecastCurve10mStore.restore(\n            sql = db.writableDatabase,\n            referenceKey = key,\n            targetAt = targetAt,\n            weatherTemperature = weather,\n            fabTemperature = fab,\n            humidity = humidity,\n            weatherConfidence = o.optDouble("weatherConfidence", 0.65),\n            fabConfidence = o.optDouble("fabConfidence", 0.45),\n            origin = o.optString("origin", ForecastCurve10mStore.ORIGIN),\n            modelVersion = o.optString("modelVersion", ForecastCurve10mStore.MODEL_VERSION),\n            createdAt = o.optLong("createdAt", targetAt)\n        )\n    }\n\n    private fun restoreWeather(values: Map<String, String>) {\n''',
    "private fun restoreForecastCurve10mArchive"
)

# Wording: an archive is not an observation. Keep this visually explicit.
replay = "app/src/main/java/com/fabdata/app/ForecastReplayUi.kt"
p = Path(replay)
s = p.read_text()
s = s.replace('Text("Mémoire prévisionnelle", fontWeight = FontWeight.Bold)', 'Text("Archives de prévisions météo", fontWeight = FontWeight.Bold)')
s = s.replace('"Prévisions sauvegardées à gauche · prévision active à droite"', '"Prévisions émises/archivées à gauche · prévision active à droite"')
p.write_text(s)

# Preserve already-restored user Fab backtests when the weather archive is refreshed.
past = "app/src/main/java/com/fabdata/app/ForecastPastArchive.kt"
p = Path(past)
s = p.read_text()
old = '''        val values = ContentValues().apply {\n            put("reference_key", referenceKey)\n            put("target_ts", targetAt)\n            put("weather_temperature", weatherTemperature)\n            put("humidity", humidity.coerceIn(0.0, 100.0))\n            if (fabTemperature == null) putNull("fab_temperature") else put("fab_temperature", fabTemperature)\n            put("weather_confidence", weatherConfidence.coerceIn(0.0, 1.0))\n            if (fabConfidence == null) putNull("fab_confidence") else put("fab_confidence", fabConfidence.coerceIn(0.0, 1.0))\n            put("provider", provider.ifBlank { PROVIDER })\n            put("fetched_at", fetchedAt)\n        }\n        sql.insertWithOnConflict(TABLE, null, values, SQLiteDatabase.CONFLICT_REPLACE)\n'''
new = '''        val safeProvider = provider.ifBlank { PROVIDER }\n        sql.execSQL(\n            """\n            INSERT OR IGNORE INTO $TABLE(\n                reference_key, target_ts, weather_temperature, humidity, fab_temperature,\n                weather_confidence, fab_confidence, provider, fetched_at\n            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)\n            """.trimIndent(),\n            arrayOf(\n                referenceKey, targetAt, weatherTemperature, humidity.coerceIn(0.0, 100.0),\n                fabTemperature, weatherConfidence.coerceIn(0.0, 1.0), fabConfidence, safeProvider, fetchedAt\n            )\n        )\n        // API refresh may update the weather anchor, but must never erase a restored/user-specific\n        // Fab backtest. A non-null backup value is allowed to restore/replace it explicitly.\n        sql.execSQL(\n            """\n            UPDATE $TABLE SET\n                weather_temperature=?, humidity=?, weather_confidence=?, fetched_at=?,\n                fab_temperature=COALESCE(?, fab_temperature),\n                fab_confidence=COALESCE(?, fab_confidence)\n            WHERE reference_key=? AND target_ts=? AND provider=?\n            """.trimIndent(),\n            arrayOf(\n                weatherTemperature, humidity.coerceIn(0.0, 100.0),\n                weatherConfidence.coerceIn(0.0, 1.0), fetchedAt,\n                fabTemperature, fabConfidence, referenceKey, targetAt, safeProvider\n            )\n        )\n'''
if "API refresh may update the weather anchor" not in s:
    if old not in s:
        raise SystemExit("missing ForecastPastArchive restore patch anchor")
    s = s.replace(old, new, 1)
    s = s.replace("import android.content.ContentValues\n", "")
p.write_text(s)
