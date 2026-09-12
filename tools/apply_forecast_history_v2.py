from pathlib import Path


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"{path}: already patched: {marker}")
        return
    if old not in text:
        raise SystemExit(f"{path}: expected block missing for {marker}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{path}: patched {marker}")


def replace_region(path: Path, start: str, end: str, new: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"{path}: already patched: {marker}")
        return
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{path}: start marker missing for {marker}")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"{path}: end marker missing for {marker}")
    path.write_text(text[:a] + new + text[b:], encoding="utf-8")
    print(f"{path}: patched {marker}")


# ---------------------------------------------------------------------------
# Prediction replay: NEVER use real/reconstructed values to rebuild this curve.
# Gaps are transient estimates between prediction anchors and are not persisted.
# ---------------------------------------------------------------------------
replay = Path("app/src/main/java/com/fabdata/app/ForecastReplayUi.kt")
text = replay.read_text(encoding="utf-8")
text = text.replace(
    ''' * Missing past slots may be bridged with the existing measured/reconstructed weather\n * reference, but those bridge points are display-only and are never training samples.\n''',
    ''' * This curve is prediction-only. MEASURED and RECONSTRUCTED values never enter it.\n * Missing slots are transient estimates between prediction anchors and are never persisted.\n'''
)
text = text.replace("    BRIDGE\n", "    ESTIMATED\n")
text = text.replace("    val bridgeCount: Int\n", "    val estimatedCount: Int\n")

start = "        // Existing real/reconstructed weather only fills holes on the left."
end = "        return ForecastReplayState("
a = text.find(start)
if a >= 0:
    b = text.find(end, a)
    if b < 0:
        raise SystemExit("ForecastReplayUi.kt: replay return marker missing")
    replacement = '''        // Build a single prediction-only chronology. For small gaps we estimate\n        // between two prediction anchors. These estimates exist in RAM only.\n        val anchors = (archived + future)\n            .groupBy { replayHourBucket(it.timestamp) }\n            .values\n            .mapNotNull { group ->\n                group.maxByOrNull { if (it.kind == ForecastReplayKind.CURRENT) 2 else 1 }\n            }\n            .sortedBy { it.timestamp }\n\n        val points = mutableListOf<ForecastReplayPoint>()\n        if (anchors.isNotEmpty()) {\n            anchors.zipWithNext().forEach { (left, right) ->\n                points += left\n                val gap = right.timestamp - left.timestamp\n                if (gap > REPLAY_HOUR_MS && gap <= 6L * REPLAY_HOUR_MS) {\n                    var ts = replayHourBucket(left.timestamp) + REPLAY_HOUR_MS\n                    while (ts < right.timestamp) {\n                        val f = ((ts - left.timestamp).toDouble() / gap.toDouble()).coerceIn(0.0, 1.0)\n                        points += ForecastReplayPoint(\n                            timestamp = ts,\n                            temperature = left.temperature + (right.temperature - left.temperature) * f,\n                            confidence = (left.confidence + (right.confidence - left.confidence) * f).coerceIn(0.0, 1.0),\n                            kind = ForecastReplayKind.ESTIMATED\n                        )\n                        ts += REPLAY_HOUR_MS\n                    }\n                }\n            }\n            points += anchors.last()\n        }\n\n'''
    text = text[:a] + replacement + text[b:]

text = text.replace("            bridgeCount = bridgeCandidates.size\n", "            estimatedCount = points.count { it.kind == ForecastReplayKind.ESTIMATED }\n")
text = text.replace(
    '''                            "${state.bridgeCount} point(s) de continuité",''',
    '''                            "${state.estimatedCount} estimation(s) visuelle(s)",'''
)
text = text.replace(
    '''                        "Les segments pointillés servent seulement à combler un trou d’affichage avec le réel/reconstruit existant ; ils ne servent jamais à entraîner le correcteur.",''',
    '''                        "Cette courbe n’utilise jamais le réel ni les données reconstruites. Les pointillés sont estimés uniquement entre deux prévisions et ne sont jamais sauvegardés.",'''
)
text = text.replace("    val bridgeColor = MaterialTheme.colorScheme.outline\n", "    val estimatedColor = MaterialTheme.colorScheme.outline\n")
text = text.replace("ForecastReplayKind.BRIDGE", "ForecastReplayKind.ESTIMATED")
text = text.replace("val bridge = a.kind == ForecastReplayKind.ESTIMATED || b.kind == ForecastReplayKind.ESTIMATED", "val estimated = a.kind == ForecastReplayKind.ESTIMATED || b.kind == ForecastReplayKind.ESTIMATED")
text = text.replace("bridge -> bridgeColor", "estimated -> estimatedColor")
text = text.replace("if (bridge) 0.72f else 0.95f", "if (estimated) 0.72f else 0.95f")
text = text.replace("if (bridge) 1.5.dp.toPx() else 2.4.dp.toPx()", "if (estimated) 1.5.dp.toPx() else 2.4.dp.toPx()")
text = text.replace("if (bridge) {", "if (estimated) {")
text = text.replace("ForecastReplayKind.ESTIMATED -> bridgeColor", "ForecastReplayKind.ESTIMATED -> estimatedColor")
text = text.replace("if (p.kind == ForecastReplayKind.ESTIMATED) 0.55f else 0.9f", "if (p.kind == ForecastReplayKind.ESTIMATED) 0.50f else 0.9f")
text = text.replace("Text(\"┄ continuité\", color = bridgeColor", "Text(\"┄ estimé\", color = estimatedColor")
if "MEASURED and RECONSTRUCTED values never enter it" not in text:
    raise SystemExit("ForecastReplayUi.kt: prediction-only guard was not applied")
replay.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tangent overlay: bottom-right resize handle, persisted width/height.
# ---------------------------------------------------------------------------
overlay = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")
replace_once(
    overlay,
    '''        private const val KEY_X = "x_fraction"\n        private const val KEY_Y = "y_fraction"\n''',
    '''        private const val KEY_X = "x_fraction"\n        private const val KEY_Y = "y_fraction"\n        private const val KEY_WIDTH_DP = "width_dp"\n        private const val KEY_HEIGHT_DP = "height_dp"\n''',
    'KEY_WIDTH_DP = "width_dp"'
)
replace_once(
    overlay,
    '''    private var startX = 0f\n    private var startY = 0f\n''',
    '''    private var startX = 0f\n    private var startY = 0f\n    private var resizing = false\n    private var startWidth = 0\n    private var startHeight = 0\n''',
    'private var resizing = false'
)
replace_once(
    overlay,
    '''    fun restorePosition(root: ViewGroup) {\n        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)\n        val maxX = (root.width - width).coerceAtLeast(0).toFloat()\n        val maxY = (root.height - height).coerceAtLeast(0).toFloat()\n        val xFraction = prefs.getFloat(KEY_X, -1f)\n        val yFraction = prefs.getFloat(KEY_Y, -1f)\n        x = if (xFraction >= 0f) maxX * xFraction.coerceIn(0f, 1f) else dp(8f)\n        y = if (yFraction >= 0f) maxY * yFraction.coerceIn(0f, 1f) else dp(96f)\n    }\n''',
    '''    fun restorePosition(root: ViewGroup) {\n        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)\n        val minWidth = dp(270f).toInt()\n        val minHeight = dp(130f).toInt()\n        val maxWidth = maxOf(minWidth, root.width - dp(8f).toInt())\n        val maxHeight = maxOf(minHeight, root.height - dp(8f).toInt())\n        layoutParams = layoutParams.apply {\n            width = dp(prefs.getFloat(KEY_WIDTH_DP, 348f)).toInt().coerceIn(minWidth, maxWidth)\n            height = dp(prefs.getFloat(KEY_HEIGHT_DP, 154f)).toInt().coerceIn(minHeight, maxHeight)\n        }\n        requestLayout()\n        post {\n            val maxX = (root.width - width).coerceAtLeast(0).toFloat()\n            val maxY = (root.height - height).coerceAtLeast(0).toFloat()\n            val xFraction = prefs.getFloat(KEY_X, -1f)\n            val yFraction = prefs.getFloat(KEY_Y, -1f)\n            x = if (xFraction >= 0f) maxX * xFraction.coerceIn(0f, 1f) else dp(8f)\n            y = if (yFraction >= 0f) maxY * yFraction.coerceIn(0f, 1f) else dp(96f)\n        }\n    }\n''',
    'prefs.getFloat(KEY_WIDTH_DP, 348f)'
)
replace_once(
    overlay,
    '''                startX = x\n                startY = y\n                parentView.requestDisallowInterceptTouchEvent(true)\n''',
    '''                startX = x\n                startY = y\n                startWidth = width\n                startHeight = height\n                val handle = dp(36f)\n                resizing = event.x >= width - handle && event.y >= height - handle\n                parentView.requestDisallowInterceptTouchEvent(true)\n''',
    'resizing = event.x >= width - handle'
)
replace_once(
    overlay,
    '''                val maxX = (parentView.width - width).coerceAtLeast(0).toFloat()\n                val maxY = (parentView.height - height).coerceAtLeast(0).toFloat()\n                x = (startX + dx).coerceIn(0f, maxX)\n                y = (startY + dy).coerceIn(0f, maxY)\n                return true\n''',
    '''                if (resizing) {\n                    val minWidth = dp(270f).toInt()\n                    val minHeight = dp(130f).toInt()\n                    val maxWidth = maxOf(minWidth, (parentView.width - x).toInt())\n                    val maxHeight = maxOf(minHeight, (parentView.height - y).toInt())\n                    layoutParams = layoutParams.apply {\n                        width = (startWidth + dx).toInt().coerceIn(minWidth, maxWidth)\n                        height = (startHeight + dy).toInt().coerceIn(minHeight, maxHeight)\n                    }\n                    requestLayout()\n                } else {\n                    val maxX = (parentView.width - width).coerceAtLeast(0).toFloat()\n                    val maxY = (parentView.height - height).coerceAtLeast(0).toFloat()\n                    x = (startX + dx).coerceIn(0f, maxX)\n                    y = (startY + dy).coerceIn(0f, maxY)\n                }\n                return true\n''',
    'width = (startWidth + dx).toInt().coerceIn'
)
text = overlay.read_text(encoding="utf-8")
text = text.replace("                persistPosition(parentView)\n", "                persistGeometry(parentView)\n                resizing = false\n")
text = text.replace("    private fun persistPosition(root: ViewGroup) {\n", "    private fun persistGeometry(root: ViewGroup) {\n")
text = text.replace(
    '''            .putFloat(KEY_Y, (y / maxY).coerceIn(0f, 1f))\n            .apply()\n    }\n\n    override fun onDraw''',
    '''            .putFloat(KEY_Y, (y / maxY).coerceIn(0f, 1f))\n            .putFloat(KEY_WIDTH_DP, width / resources.displayMetrics.density.coerceAtLeast(0.1f))\n            .putFloat(KEY_HEIGHT_DP, height / resources.displayMetrics.density.coerceAtLeast(0.1f))\n            .apply()\n    }\n\n    override fun onDraw'''
)
if "persistGeometry(parentView)" not in text:
    raise SystemExit("ForecastMemoryOverlay.kt: resize persistence not applied")
if "drawResizeHandle(canvas" not in text:
    text = text.replace(
        '''            drawDial(canvas, sample, cx, cy, radius, index, night)\n        }\n    }\n\n    private fun drawLegend''',
        '''            drawDial(canvas, sample, cx, cy, radius, index, night)\n        }\n        drawResizeHandle(canvas, night)\n    }\n\n    private fun drawResizeHandle(canvas: Canvas, night: Boolean) {\n        paint.style = Paint.Style.STROKE\n        paint.strokeWidth = dp(1.5f)\n        paint.strokeCap = Paint.Cap.ROUND\n        paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, 105)\n        val pad = dp(7f)\n        for (i in 0..2) {\n            val o = dp(5f * i)\n            canvas.drawLine(width - pad - o - dp(8f), height - pad, width - pad, height - pad - o - dp(8f), paint)\n        }\n        paint.strokeCap = Paint.Cap.BUTT\n    }\n\n    private fun drawLegend'''
    )
overlay.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Backup/restore: archive immutable prediction snapshots only.
# Transient replay estimates do not exist in SQLite and therefore cannot be exported.
# ---------------------------------------------------------------------------
backup = Path("app/src/main/java/com/fabdata/app/BackupV3Support.kt")
replace_once(
    backup,
    '''        ThermalWallSolarModelStore.ensure(db.writableDatabase)\n        WeatherReferenceStore.ensure(db.writableDatabase)\n''',
    '''        ThermalWallSolarModelStore.ensure(db.writableDatabase)\n        WeatherReferenceStore.ensure(db.writableDatabase)\n        ForecastMemoryStore.ensure(db.writableDatabase)\n''',
    'ForecastMemoryStore.ensure(db.writableDatabase)'
)
replace_once(
    backup,
    '''        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, timestamp, temperature, humidity, source, confidence\n            FROM weather_reference_samples\n            ORDER BY reference_key, timestamp\n            """.trimIndent(), null\n        ).use { c ->\n''',
    '''        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, issued_at, target_ts, temperature, humidity, confidence, provider\n            FROM ${ForecastMemoryStore.TABLE}\n            ORDER BY reference_key, target_ts, issued_at\n            """.trimIndent(), null\n        ).use { c ->\n            while (c.moveToNext()) {\n                writeJson(writer, "FORECAST_ARCHIVE", JSONObject().apply {\n                    put("referenceKey", c.getString(0))\n                    put("issuedAt", c.getLong(1))\n                    put("targetAt", c.getLong(2))\n                    put("temperature", c.getDouble(3))\n                    putNullable("humidity", if (c.isNull(4)) null else c.getDouble(4))\n                    putNullable("confidence", if (c.isNull(5)) null else c.getDouble(5))\n                    put("provider", c.getString(6))\n                })\n            }\n        }\n\n        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, timestamp, temperature, humidity, source, confidence\n            FROM weather_reference_samples\n            ORDER BY reference_key, timestamp\n            """.trimIndent(), null\n        ).use { c ->\n''',
    'writeJson(writer, "FORECAST_ARCHIVE"'
)
replace_once(
    backup,
    '''                "TRAINING_EXCLUSION" -> restoreTrainingExclusion(json(values))\n                "WEATHER" -> restoreWeather(values)\n''',
    '''                "TRAINING_EXCLUSION" -> restoreTrainingExclusion(json(values))\n                "FORECAST_ARCHIVE" -> restoreForecastArchive(json(values))\n                "WEATHER" -> restoreWeather(values)\n''',
    '"FORECAST_ARCHIVE" -> restoreForecastArchive'
)
replace_once(
    backup,
    '''    private fun restoreWeather(values: Map<String, String>) {\n''',
    '''    private fun restoreForecastArchive(o: JSONObject) {\n        ForecastMemoryStore.ensure(db.writableDatabase)\n        val key = o.optString("referenceKey", "").trim()\n        val issuedAt = o.optLong("issuedAt", -1L)\n        val targetAt = o.optLong("targetAt", -1L)\n        val temperature = o.optDouble("temperature", Double.NaN)\n        if (key.isBlank() || issuedAt < 0L || targetAt < 0L || !temperature.isFinite()) return\n        val humidity = nullableDouble(o, "humidity")\n        val confidence = nullableDouble(o, "confidence")\n        val provider = o.optString("provider", "active_reference").ifBlank { "active_reference" }\n        db.writableDatabase.execSQL(\n            """\n            INSERT INTO ${ForecastMemoryStore.TABLE}(reference_key, issued_at, target_ts, temperature, humidity, confidence, provider)\n            SELECT ?, ?, ?, ?, ?, ?, ?\n            WHERE NOT EXISTS (\n                SELECT 1 FROM ${ForecastMemoryStore.TABLE}\n                WHERE reference_key=? AND issued_at=? AND target_ts=? AND provider=?\n                  AND ABS(temperature-?) < 0.001\n            )\n            """.trimIndent(),\n            arrayOf(\n                key, issuedAt, targetAt, temperature, humidity, confidence, provider,\n                key, issuedAt, targetAt, provider, temperature\n            )\n        )\n    }\n\n    private fun restoreWeather(values: Map<String, String>) {\n''',
    'private fun restoreForecastArchive(o: JSONObject)'
)


# ---------------------------------------------------------------------------
# Main screen: separate expandable prediction-memory curve.
# ---------------------------------------------------------------------------
main = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
replace_once(
    main,
    '''                item {\n                    TimeTabs(preset = preset, onSelect = {\n''',
    '''                item {\n                    ForecastReplayCard(\n                        db = db,\n                        reference = visualReference,\n                        refreshToken = reloadToken\n                    )\n                }\n\n                item {\n                    TimeTabs(preset = preset, onSelect = {\n''',
    'ForecastReplayCard('
)

print("Prediction history v2 patch complete")
