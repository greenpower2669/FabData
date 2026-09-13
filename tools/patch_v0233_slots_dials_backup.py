from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one occurrence, got {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise RuntimeError(f"{label}: markers not found")
    return text[:start] + replacement + text[end:]


# ---------------------------------------------------------------------------
# App version
# ---------------------------------------------------------------------------
build_path = "app/build.gradle.kts"
build = read(build_path)
build = once(
    build,
    'versionCode = 59\n        versionName = "0.23.2"',
    'versionCode = 60\n        versionName = "0.23.3"',
    "version bump",
)
write(build_path, build)


# ---------------------------------------------------------------------------
# Backup format v5. v1-v4 remain importable; v4/v5 both keep footer integrity.
# ---------------------------------------------------------------------------
backup_path = "app/src/main/java/com/fabdata/app/BackupLayer.kt"
backup = read(backup_path)
backup = once(backup, 'const val FORMAT_VERSION = "4"', 'const val FORMAT_VERSION = "5"', "backup format")
backup = once(
    backup,
    'if (fileVersion == FORMAT_VERSION) {',
    'if (fileVersion in setOf("4", FORMAT_VERSION)) {',
    "v4/v5 footer integrity",
)
backup = once(
    backup,
    'formatVersion !in setOf("1", "2", "3", FORMAT_VERSION)',
    'formatVersion !in setOf("1", "2", "3", "4", FORMAT_VERSION)',
    "old format compatibility",
)
backup = backup.replace("Sauvegarde v4 vide ou incomplète", "Sauvegarde complète vide ou incomplète")
backup = backup.replace("Sauvegarde v4 incomplète : marqueur de fin absent", "Sauvegarde complète incomplète : marqueur de fin absent")
backup = backup.replace("Sauvegarde v4 incomplète : compteurs d’intégrité incohérents", "Sauvegarde complète incomplète : compteurs d’intégrité incohérents")
write(backup_path, backup)


# ---------------------------------------------------------------------------
# Forecast archive: real retrieval timestamp stays untouched, while a canonical
# ten-minute slot acts as a logical anti-duplicate key for new captures/imports.
# ---------------------------------------------------------------------------
overlay_path = "app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt"
overlay = read(overlay_path)

overlay = once(
    overlay,
    'import android.app.Activity\nimport android.app.Application\n',
    'import android.app.Activity\nimport android.app.AlertDialog\nimport android.app.Application\n',
    "alert dialog import",
)
overlay = once(
    overlay,
    'import android.widget.FrameLayout\n',
    'import android.widget.ArrayAdapter\nimport android.widget.FrameLayout\nimport android.widget.LinearLayout\nimport android.widget.Spinner\nimport android.widget.TextView\n',
    "dial selector imports",
)

constants_marker = "/**\n * Forecast memory / tangent cockpit."
constants = '''private const val DIAL_PREFS = "fabdata_forecast_dial_overlay"\nprivate const val DIAL_WEATHER_HORIZON_KEY = "monitor_weather_horizon"\nprivate const val DIAL_ADAPTIVE_HORIZON_KEY = "monitor_adaptive_horizon"\nprivate const val FORECAST_CAPTURE_SLOT_MS = 10L * 60L * 1000L\n\n'''
if constants not in overlay:
    overlay = once(overlay, constants_marker, constants + constants_marker, "dial/slot constants")

store_start = "object ForecastMemoryStore {"
store_end = "private data class ArchivedForecast("
new_store = '''object ForecastMemoryStore {\n    const val TABLE = "forecast_snapshot_archive"\n    private const val LEGACY_TRIGGER = "trg_fabdata_forecast_memory_insert"\n    private const val TRIGGER = "trg_fabdata_forecast_memory_insert_v2"\n\n    fun captureSlot10m(timestamp: Long): Long =\n        (timestamp / FORECAST_CAPTURE_SLOT_MS) * FORECAST_CAPTURE_SLOT_MS\n\n    /**\n     * Additive schema only. issued_at always keeps the real retrieval time.\n     * capture_slot_10m is a canonical logical key used only to prevent a restore or\n     * a second refresh in the same :00/:10/:20/... slot from duplicating an emission.\n     */\n    @Synchronized\n    fun ensure(sql: SQLiteDatabase) {\n        WeatherReferenceStore.ensure(sql)\n        sql.execSQL(\n            """\n            CREATE TABLE IF NOT EXISTS $TABLE (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                reference_key TEXT NOT NULL,\n                issued_at INTEGER NOT NULL,\n                target_ts INTEGER NOT NULL,\n                temperature REAL NOT NULL,\n                humidity REAL,\n                confidence REAL,\n                provider TEXT NOT NULL DEFAULT 'active_reference',\n                capture_slot_10m INTEGER\n            )\n            """.trimIndent()\n        )\n        var hasSlot = false\n        sql.rawQuery("PRAGMA table_info($TABLE)", null).use { c ->\n            while (c.moveToNext()) {\n                if (c.getString(c.getColumnIndexOrThrow("name")) == "capture_slot_10m") {\n                    hasSlot = true\n                    break\n                }\n            }\n        }\n        if (!hasSlot) {\n            sql.execSQL("ALTER TABLE $TABLE ADD COLUMN capture_slot_10m INTEGER")\n        }\n        sql.execSQL(\n            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_target ON $TABLE(reference_key, target_ts, issued_at)"\n        )\n        sql.execSQL(\n            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_issue ON $TABLE(reference_key, issued_at)"\n        )\n        sql.execSQL(\n            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_slot ON $TABLE(reference_key, capture_slot_10m, target_ts)"\n        )\n\n        // v2 is a versioned migration. The old trigger is retired once; the active trigger\n        // is never DROP/CREATE'd during normal reads, avoiding the former concurrency crash.\n        sql.execSQL("DROP TRIGGER IF EXISTS $LEGACY_TRIGGER")\n        sql.execSQL(\n            """\n            CREATE TRIGGER IF NOT EXISTS $TRIGGER\n            AFTER INSERT ON weather_reference_samples\n            WHEN NEW.source='forecast'\n            BEGIN\n                INSERT INTO $TABLE(\n                    reference_key, issued_at, target_ts, temperature, humidity, confidence, provider, capture_slot_10m\n                )\n                SELECT\n                    NEW.reference_key,\n                    NEW.updated_at,\n                    NEW.timestamp,\n                    NEW.temperature,\n                    NEW.humidity,\n                    NEW.confidence,\n                    'active_reference',\n                    (NEW.updated_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS\n                WHERE NOT EXISTS (\n                    SELECT 1\n                    FROM $TABLE a\n                    WHERE a.reference_key=NEW.reference_key\n                      AND a.target_ts=NEW.timestamp\n                      AND a.provider='active_reference'\n                      AND COALESCE(\n                          a.capture_slot_10m,\n                          (a.issued_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS\n                      ) = (NEW.updated_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS\n                );\n            END\n            """.trimIndent()\n        )\n\n        // Seed only the current logical slot. Existing historical timestamps are never changed.\n        sql.execSQL(\n            """\n            INSERT INTO $TABLE(\n                reference_key, issued_at, target_ts, temperature, humidity, confidence, provider, capture_slot_10m\n            )\n            SELECT\n                w.reference_key, w.updated_at, w.timestamp, w.temperature, w.humidity, w.confidence,\n                'active_reference', (w.updated_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS\n            FROM weather_reference_samples w\n            WHERE w.source='forecast'\n              AND NOT EXISTS (\n                  SELECT 1 FROM $TABLE a\n                  WHERE a.reference_key=w.reference_key\n                    AND a.target_ts=w.timestamp\n                    AND a.provider='active_reference'\n                    AND COALESCE(\n                        a.capture_slot_10m,\n                        (a.issued_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS\n                    ) = (w.updated_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS\n              )\n            """.trimIndent()\n        )\n    }\n\n    fun hasCaptureSlot(sql: SQLiteDatabase, referenceKey: String, timestamp: Long): Boolean {\n        ensure(sql)\n        val slot = captureSlot10m(timestamp)\n        return sql.rawQuery(\n            """\n            SELECT 1 FROM $TABLE\n            WHERE reference_key=?\n              AND COALESCE(capture_slot_10m, (issued_at / ?) * ?) = ?\n            LIMIT 1\n            """.trimIndent(),\n            arrayOf(\n                referenceKey, FORECAST_CAPTURE_SLOT_MS.toString(), FORECAST_CAPTURE_SLOT_MS.toString(), slot.toString()\n            )\n        ).use { it.moveToFirst() }\n    }\n}\n\n'''
overlay = replace_between(overlay, store_start, store_end, new_store, "forecast memory store")

# Dial state carries persistent monitored horizons.
overlay = once(
    overlay,
    '''private data class DialState(\n    val referenceLabel: String,\n    val samples: List<DialSample>\n)''',
    '''private data class DialState(\n    val referenceLabel: String,\n    val weatherHorizon: Int,\n    val adaptiveHorizon: Int,\n    val samples: List<DialSample>\n)''',
    "dial state horizons",
)

# Replace the old H24-only data source with fixed-horizon weather + adaptive selections.
data_start = "private class ForecastDialDataSource("
data_end = "private class ForecastDialStripView("
new_data_source = '''private class ForecastDialDataSource(\n    context: Context,\n    private val db: FabDataDb\n) {\n    private val appContext = context.applicationContext\n    private val dialPrefs = appContext.getSharedPreferences(DIAL_PREFS, Context.MODE_PRIVATE)\n\n    fun load(now: Long = System.currentTimeMillis()): DialState {\n        ForecastMemoryStore.ensure(db.writableDatabase)\n        ForecastHorizonArchiveStore.ensure(db.writableDatabase)\n        ForecastAdaptiveStore.ensure(db.writableDatabase)\n        val reference = WeatherReferencePrefs(appContext).selectedReference()\n        val weatherHorizon = dialPrefs.getInt(DIAL_WEATHER_HORIZON_KEY, 24).coerceIn(1, 48)\n        val requestedAdaptive = dialPrefs.getInt(DIAL_ADAPTIVE_HORIZON_KEY, 24)\n        val adaptiveHorizon = requestedAdaptive.takeIf { it in FORECAST_ADAPTIVE_HORIZONS } ?: 24\n\n        // Materialise only a narrow target window from already archived raw snapshots.\n        // No terrain/training data is modified by the cockpit.\n        runCatching {\n            ForecastHorizonArchive(db).materialize(\n                reference.key, now - 3L * HOUR_MS, now + 3L * HOUR_MS, now\n            )\n        }\n\n        val nowHour = hourBucket(now)\n        val targets = listOf(\n            "PASSÉ" to (nowHour - HOUR_MS),\n            "PRÉSENT" to nowHour,\n            "FUTUR" to (nowHour + HOUR_MS)\n        )\n        val result = targets.map { (label, target) ->\n            buildDial(reference.key, label, target, weatherHorizon, adaptiveHorizon)\n        }\n        return DialState(reference.label, weatherHorizon, adaptiveHorizon, result)\n    }\n\n    private fun buildDial(\n        referenceKey: String,\n        label: String,\n        target: Long,\n        weatherHorizon: Int,\n        adaptiveHorizon: Int\n    ): DialSample {\n        val official = fixedWeatherKinematics(referenceKey, weatherHorizon, target)\n        val local = adaptiveKinematics(referenceKey, adaptiveHorizon, target)\n        val terrain = terrainAt(referenceKey, target)\n        val actual = terrain?.temperature\n        val actualSlope = if (terrain != null) terrainSlope(referenceKey, target) else null\n        val actualAcceleration = if (terrain != null) terrainAcceleration(referenceKey, target) else null\n\n        return DialSample(\n            label = label,\n            targetTs = target,\n            officialTemp = official?.temperature,\n            localTemp = local?.temperature,\n            actualTemp = actual,\n            actualIsMeasured = terrain?.measured == true,\n            officialSlope = official?.slope,\n            localSlope = local?.slope,\n            actualSlope = actualSlope,\n            officialAcceleration = official?.acceleration,\n            localAcceleration = local?.acceleration,\n            actualAcceleration = actualAcceleration,\n            officialError = if (official != null && actual != null) abs(official.temperature - actual) else null,\n            localError = if (local != null && actual != null) abs(local.temperature - actual) else null,\n            trainingSamples = adaptiveHistorySamples(referenceKey, adaptiveHorizon, target)\n        )\n    }\n\n    private fun fixedWeatherAt(referenceKey: String, horizon: Int, target: Long): Double? {\n        val tolerance = 36L * 60L * 1000L\n        return db.readableDatabase.rawQuery(\n            """\n            SELECT weather_temperature\n            FROM ${ForecastHorizonArchiveStore.TABLE}\n            WHERE reference_key=? AND lead_hour=? AND target_ts BETWEEN ? AND ?\n              AND policy_version=?\n            ORDER BY ABS(target_ts-?) ASC, issued_at DESC\n            LIMIT 1\n            """.trimIndent(),\n            arrayOf(\n                referenceKey, horizon.toString(),\n                (target - tolerance).toString(), (target + tolerance).toString(),\n                ForecastHorizonArchiveStore.POLICY_VERSION, target.toString()\n            )\n        ).use { c -> if (c.moveToFirst()) c.getDouble(0) else null }\n    }\n\n    private fun adaptiveAt(referenceKey: String, horizon: Int, target: Long): Double? {\n        val tolerance = 36L * 60L * 1000L\n        return db.readableDatabase.rawQuery(\n            """\n            SELECT adaptive_temperature\n            FROM ${ForecastAdaptiveStore.TABLE}\n            WHERE reference_key=? AND horizon_hour=? AND target_ts BETWEEN ? AND ?\n              AND model_version=?\n            ORDER BY ABS(target_ts-?) ASC, issued_at DESC\n            LIMIT 1\n            """.trimIndent(),\n            arrayOf(\n                referenceKey, horizon.toString(),\n                (target - tolerance).toString(), (target + tolerance).toString(),\n                ForecastAdaptiveStore.MODEL_VERSION, target.toString()\n            )\n        ).use { c -> if (c.moveToFirst()) c.getDouble(0) else null }\n    }\n\n    private fun adaptiveHistorySamples(referenceKey: String, horizon: Int, target: Long): Int {\n        val tolerance = 36L * 60L * 1000L\n        return db.readableDatabase.rawQuery(\n            """\n            SELECT history_samples\n            FROM ${ForecastAdaptiveStore.TABLE}\n            WHERE reference_key=? AND horizon_hour=? AND target_ts BETWEEN ? AND ?\n              AND model_version=?\n            ORDER BY ABS(target_ts-?) ASC, issued_at DESC\n            LIMIT 1\n            """.trimIndent(),\n            arrayOf(\n                referenceKey, horizon.toString(),\n                (target - tolerance).toString(), (target + tolerance).toString(),\n                ForecastAdaptiveStore.MODEL_VERSION, target.toString()\n            )\n        ).use { c -> if (c.moveToFirst()) c.getInt(0) else 0 }\n    }\n\n    private fun kinematics(center: Double?, previous: Double?, next: Double?): CurveKinematics? {\n        center ?: return null\n        val slope = when {\n            previous != null && next != null -> (next - previous) / 2.0\n            next != null -> next - center\n            previous != null -> center - previous\n            else -> null\n        }?.coerceIn(-3.0, 3.0)\n        val acceleration = if (previous != null && next != null)\n            (next - 2.0 * center + previous).coerceIn(-1.5, 1.5) else null\n        return CurveKinematics(center, slope, acceleration)\n    }\n\n    private fun fixedWeatherKinematics(referenceKey: String, horizon: Int, target: Long): CurveKinematics? =\n        kinematics(\n            fixedWeatherAt(referenceKey, horizon, target),\n            fixedWeatherAt(referenceKey, horizon, target - HOUR_MS),\n            fixedWeatherAt(referenceKey, horizon, target + HOUR_MS)\n        )\n\n    private fun adaptiveKinematics(referenceKey: String, horizon: Int, target: Long): CurveKinematics? =\n        kinematics(\n            adaptiveAt(referenceKey, horizon, target),\n            adaptiveAt(referenceKey, horizon, target - HOUR_MS),\n            adaptiveAt(referenceKey, horizon, target + HOUR_MS)\n        )\n\n    private fun terrainAt(referenceKey: String, target: Long): TerrainDialPoint? {\n        fun query(source: String, tolerance: Long, measured: Boolean): TerrainDialPoint? =\n            db.readableDatabase.rawQuery(\n                """\n                SELECT temperature FROM weather_reference_samples\n                WHERE reference_key=? AND source=? AND timestamp BETWEEN ? AND ?\n                ORDER BY ABS(timestamp-?) ASC LIMIT 1\n                """.trimIndent(),\n                arrayOf(\n                    referenceKey, source,\n                    (target - tolerance).toString(), (target + tolerance).toString(), target.toString()\n                )\n            ).use { c -> if (c.moveToFirst()) TerrainDialPoint(c.getDouble(0), measured) else null }\n        return query("measured", 36L * 60L * 1000L, true)\n            ?: query("reconstructed", 75L * 60L * 1000L, false)\n    }\n\n    private fun terrainSlope(referenceKey: String, target: Long): Double? {\n        val center = terrainAt(referenceKey, target)?.temperature ?: return null\n        val previous = terrainAt(referenceKey, target - HOUR_MS)?.temperature\n        val next = terrainAt(referenceKey, target + HOUR_MS)?.temperature\n        return when {\n            previous != null && next != null -> (next - previous) / 2.0\n            next != null -> next - center\n            previous != null -> center - previous\n            else -> null\n        }?.coerceIn(-3.0, 3.0)\n    }\n\n    private fun terrainAcceleration(referenceKey: String, target: Long): Double? {\n        val center = terrainAt(referenceKey, target)?.temperature ?: return null\n        val previous = terrainAt(referenceKey, target - HOUR_MS)?.temperature ?: return null\n        val next = terrainAt(referenceKey, target + HOUR_MS)?.temperature ?: return null\n        return (next - 2.0 * center + previous).coerceIn(-1.5, 1.5)\n    }\n}\n\n'''
overlay = replace_between(overlay, data_start, data_end, new_data_source, "dial data source")

# Reuse the same persistent preference file everywhere.
overlay = once(
    overlay,
    'private const val PREFS = "fabdata_forecast_dial_overlay"',
    'private const val PREFS = DIAL_PREFS',
    "overlay prefs constant",
)

overlay = once(
    overlay,
    '    private var lastTapUp = 0L\n',
    '    private var lastTapUp = 0L\n    private var downEventTime = 0L\n',
    "long press timestamp",
)
overlay = once(
    overlay,
    '                moved = false\n                startX = x\n',
    '                moved = false\n                downEventTime = event.eventTime\n                startX = x\n',
    "capture long press start",
)

old_up = '''                if (!moved && !resizing) {\n                    val now = event.eventTime\n                    if (lastTapUp > 0L && now - lastTapUp <= 340L) {\n                        lastTapUp = 0L\n                        toggleCompact(parentView)\n                    } else {\n                        lastTapUp = now\n                        persistGeometry(parentView)\n                    }\n                } else {\n'''
new_up = '''                if (!moved && !resizing) {\n                    val now = event.eventTime\n                    val heldMs = now - downEventTime\n                    if (heldMs >= 650L) {\n                        lastTapUp = 0L\n                        showMonitoringDialog()\n                    } else if (lastTapUp > 0L && now - lastTapUp <= 340L) {\n                        lastTapUp = 0L\n                        toggleCompact(parentView)\n                    } else {\n                        lastTapUp = now\n                        persistGeometry(parentView)\n                    }\n                } else {\n'''
overlay = once(overlay, old_up, new_up, "dial long press action")

perform_marker = '''    override fun performClick(): Boolean {\n        super.performClick()\n        return true\n    }\n\n'''
monitor_dialog = '''    private fun showMonitoringDialog() {\n        val prefs = context.getSharedPreferences(DIAL_PREFS, Context.MODE_PRIVATE)\n        val weatherHorizons = (1..48).toList()\n        val adaptiveHorizons = FORECAST_ADAPTIVE_HORIZONS.toList()\n\n        fun label(text: String) = TextView(context).apply {\n            this.text = text\n            textSize = 14f\n            setPadding(dp(4f).toInt(), dp(8f).toInt(), dp(4f).toInt(), dp(4f).toInt())\n        }\n        val weatherSpinner = Spinner(context).apply {\n            adapter = ArrayAdapter(\n                context, android.R.layout.simple_spinner_dropdown_item,\n                weatherHorizons.map { "Météo fixe H+$it" }\n            )\n            val selected = prefs.getInt(DIAL_WEATHER_HORIZON_KEY, 24).coerceIn(1, 48)\n            setSelection(weatherHorizons.indexOf(selected).coerceAtLeast(0))\n        }\n        val adaptiveSpinner = Spinner(context).apply {\n            adapter = ArrayAdapter(\n                context, android.R.layout.simple_spinner_dropdown_item,\n                adaptiveHorizons.map { "Fab adaptative H+$it" }\n            )\n            val selected = prefs.getInt(DIAL_ADAPTIVE_HORIZON_KEY, 24)\n            setSelection(adaptiveHorizons.indexOf(selected).takeIf { it >= 0 } ?: adaptiveHorizons.indexOf(24))\n        }\n        val panel = LinearLayout(context).apply {\n            orientation = LinearLayout.VERTICAL\n            val pad = dp(18f).toInt()\n            setPadding(pad, dp(4f).toInt(), pad, dp(4f).toInt())\n            addView(label("Prévision météo monitorée"))\n            addView(weatherSpinner)\n            addView(label("Prévision Fab adaptative monitorée"))\n            addView(adaptiveSpinner)\n        }\n        AlertDialog.Builder(context)\n            .setTitle("Monitoring des cadrans")\n            .setView(panel)\n            .setPositiveButton("Enregistrer") { _, _ ->\n                prefs.edit()\n                    .putInt(DIAL_WEATHER_HORIZON_KEY, weatherHorizons[weatherSpinner.selectedItemPosition])\n                    .putInt(DIAL_ADAPTIVE_HORIZON_KEY, adaptiveHorizons[adaptiveSpinner.selectedItemPosition])\n                    .apply()\n                removeCallbacks(refresh)\n                post(refresh)\n            }\n            .setNegativeButton("Annuler", null)\n            .show()\n    }\n\n'''
if monitor_dialog not in overlay:
    overlay = once(overlay, perform_marker, perform_marker + monitor_dialog, "monitor dialog")

# Show the monitored pair in the expanded legend.
overlay = once(
    overlay,
    '        drawLegend(canvas, night, current?.referenceLabel ?: "Prévision locale")',
    '        drawLegend(canvas, night, current)',
    "dial legend call",
)
overlay = once(
    overlay,
    '''    private fun drawLegend(canvas: Canvas, night: Boolean, reference: String) {\n        val textColor = if (night) Color.WHITE else Color.rgb(40, 40, 40)\n        paint.style = Paint.Style.FILL\n        paint.color = textColor\n        paint.textSize = sp(10f)\n        paint.isFakeBoldText = true\n        canvas.drawText("Tangentes · $reference", dp(10f), dp(14f), paint)\n''',
    '''    private fun drawLegend(canvas: Canvas, night: Boolean, current: DialState?) {\n        val textColor = if (night) Color.WHITE else Color.rgb(40, 40, 40)\n        paint.style = Paint.Style.FILL\n        paint.color = textColor\n        paint.textSize = sp(10f)\n        paint.isFakeBoldText = true\n        val monitor = current?.let { "M H+${it.weatherHorizon} / Fab H+${it.adaptiveHorizon}" } ?: "M H+24 / Fab H+24"\n        canvas.drawText("Tangentes · $monitor", dp(10f), dp(14f), paint)\n''',
    "dial legend horizons",
)

# Accessibility tells visually impaired users how to configure the persistent monitor.
overlay = overlay.replace(
    'Double tap pour basculer entre cadrans complets et mode compact.',
    'Double tap pour basculer entre cadrans complets et mode compact. Appui long pour choisir les horizons météo et Fab adaptatif monitorés.'
)
write(overlay_path, overlay)


# ---------------------------------------------------------------------------
# Foreground scheduler: wall-clock slots :00/:10/:20/...; opening the app can
# catch up a missing current slot, but an already captured slot is never refetched.
# ---------------------------------------------------------------------------
live_path = "app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt"
live = read(live_path)

old_last = '''    suspend fun lastForecastUpdatedAt(referenceKey: String): Long? = withContext(Dispatchers.IO) {\n        db.readableDatabase.rawQuery(\n            "SELECT MAX(updated_at) FROM weather_reference_samples WHERE reference_key=? AND source='forecast'",\n            arrayOf(referenceKey)\n        ).use { c -> if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null }\n    }\n'''
new_last = '''    suspend fun currentForecastSlotCaptured(referenceKey: String, now: Long = System.currentTimeMillis()): Boolean =\n        withContext(Dispatchers.IO) {\n            ForecastMemoryStore.hasCaptureSlot(db.writableDatabase, referenceKey, now)\n        }\n'''
live = once(live, old_last, new_last, "slot captured query")

live = once(
    live,
    '''        if (!force) {\n            val last = lastForecastUpdatedAt(referenceForOperation.key)\n            if (last != null && System.currentTimeMillis() - last < LIVE_FORECAST_INTERVAL_MS) return false\n        }\n''',
    '''        if (!force && currentForecastSlotCaptured(referenceForOperation.key)) return false\n''',
    "slot network guard",
)

loop_old = '''    // La dernière écriture FORECAST cadence le réseau : retour au focus, bouton manuel\n    // et worker Android partagent ainsi la même horloge sans spammer l'affichage.\n    LaunchedEffect(foreground) {\n        if (!foreground) return@LaunchedEffect\n        while (foreground) {\n            val hadPending = pendingMeasuredRefresh\n            if (!hadPending) {\n                val reference = weatherPrefs.selectedReference()\n                val last = lastForecastUpdatedAt(reference.key)\n                val waitMs = last?.let {\n                    (LIVE_FORECAST_INTERVAL_MS - (System.currentTimeMillis() - it)).coerceAtLeast(0L)\n                } ?: 0L\n                if (waitMs > 0L) {\n                    delay(waitMs)\n                    if (!foreground) break\n                }\n            }\n            val ran = updateLive(force = hadPending)\n            if (ran && hadPending) pendingMeasuredRefresh = false\n            if (!ran) delay(5_000L)\n        }\n    }\n'''
loop_new = '''    // Horloge canonique : :00 / :10 / :20 / :30 / :40 / :50.\n    // Si le créneau courant manque (ouverture tardive), on le rattrape immédiatement ;\n    // sinon on dort jusqu'à la prochaine frontière. Le vrai issued_at reste conservé.\n    LaunchedEffect(foreground) {\n        if (!foreground) return@LaunchedEffect\n        while (foreground) {\n            val hadPending = pendingMeasuredRefresh\n            if (!hadPending) {\n                val reference = weatherPrefs.selectedReference()\n                val now = System.currentTimeMillis()\n                if (currentForecastSlotCaptured(reference.key, now)) {\n                    val nextSlot = ForecastMemoryStore.captureSlot10m(now) + LIVE_FORECAST_INTERVAL_MS\n                    delay((nextSlot - now).coerceAtLeast(1_000L))\n                    if (!foreground) break\n                }\n            }\n            val ran = updateLive(force = hadPending)\n            if (ran && hadPending) pendingMeasuredRefresh = false\n            if (!ran) delay(30_000L)\n        }\n    }\n'''
live = once(live, loop_old, loop_new, "fixed 10m scheduler")
write(live_path, live)


# ---------------------------------------------------------------------------
# Backup UI personalization (including dial geometry/horizons and curve effects)
# without exporting credentials/tokens. Existing v1-v4 files simply lack these rows.
# ---------------------------------------------------------------------------
v3_path = "app/src/main/java/com/fabdata/app/BackupV3Support.kt"
v3 = read(v3_path)
v3 = once(v3, 'import java.io.Writer\n', 'import java.io.File\nimport java.io.Writer\n', "backup File import")

# Add personalization snapshot before the weather/model rows.
v3 = once(
    v3,
    '        writeJson(writer, "WEATHER_META", weatherMetaJson())\n',
    '        writePersonalizationRows(writer)\n        writeJson(writer, "WEATHER_META", weatherMetaJson())\n',
    "write personalization",
)

# Export canonical slot with each raw archive row.
v3 = once(
    v3,
    '''            SELECT reference_key, issued_at, target_ts, temperature, humidity, confidence, provider\n            FROM ${ForecastMemoryStore.TABLE}\n''',
    '''            SELECT reference_key, issued_at, target_ts, temperature, humidity, confidence, provider,\n                   COALESCE(capture_slot_10m, (issued_at / 600000) * 600000)\n            FROM ${ForecastMemoryStore.TABLE}\n''',
    "forecast slot export query",
)
v3 = once(
    v3,
    '                    put("provider", c.getString(6))\n',
    '                    put("provider", c.getString(6))\n                    put("captureSlot10m", c.getLong(7))\n',
    "forecast slot export json",
)

# Import record dispatch.
v3 = once(
    v3,
    '                "WEATHER_META" -> restoreWeatherMeta(json(values))\n',
    '                "UI_PREFERENCES" -> restorePersonalization(json(values))\n                "WEATHER_META" -> restoreWeatherMeta(json(values))\n',
    "restore personalization dispatch",
)

# Canonical-slot dedupe on import; old backups derive their slot from issuedAt.
restore_old = '''        db.writableDatabase.execSQL(\n            """\n            INSERT INTO ${ForecastMemoryStore.TABLE}(reference_key, issued_at, target_ts, temperature, humidity, confidence, provider)\n            SELECT ?, ?, ?, ?, ?, ?, ?\n            WHERE NOT EXISTS (\n                SELECT 1 FROM ${ForecastMemoryStore.TABLE}\n                WHERE reference_key=? AND issued_at=? AND target_ts=? AND provider=?\n                  AND ABS(temperature-?) < 0.001\n            )\n            """.trimIndent(),\n            arrayOf(\n                key, issuedAt, targetAt, temperature, humidity, confidence, provider,\n                key, issuedAt, targetAt, provider, temperature\n            )\n        )\n'''
restore_new = '''        val slot = o.optLong("captureSlot10m", ForecastMemoryStore.captureSlot10m(issuedAt))\n        db.writableDatabase.execSQL(\n            """\n            INSERT INTO ${ForecastMemoryStore.TABLE}(\n                reference_key, issued_at, target_ts, temperature, humidity, confidence, provider, capture_slot_10m\n            )\n            SELECT ?, ?, ?, ?, ?, ?, ?, ?\n            WHERE NOT EXISTS (\n                SELECT 1 FROM ${ForecastMemoryStore.TABLE}\n                WHERE reference_key=? AND target_ts=? AND provider=?\n                  AND COALESCE(capture_slot_10m, (issued_at / 600000) * 600000)=?\n            )\n            """.trimIndent(),\n            arrayOf(\n                key, issuedAt, targetAt, temperature, humidity, confidence, provider, slot,\n                key, targetAt, provider, slot\n            )\n        )\n'''
v3 = once(v3, restore_old, restore_new, "forecast slot restore")

# Insert personalization helpers before weatherMetaJson.
pref_helpers_marker = '    private fun weatherMetaJson(): JSONObject {'
pref_helpers = r'''    private fun isSafePersonalizationPreference(name: String): Boolean {
        val lower = name.lowercase()
        if (!lower.startsWith("fabdata_")) return false
        if (listOf("credential", "token", "secret", "password", "auth").any { it in lower }) return false
        return lower == "fabdata_prefs" || listOf(
            "ui", "curve", "style", "dial", "overview", "context", "display", "appearance"
        ).any { it in lower }
    }

    private fun personalizationPreferenceNames(): List<String> {
        val known = linkedSetOf(
            "fabdata_ui_preferences",
            "fabdata_prefs",
            "fabdata_forecast_dial_overlay",
            "fabdata_overview_band_curves",
            "fabdata_context_help",
            "fabdata_curve_styles",
            "fabdata_curve_style",
            "fabdata_styles"
        )
        val dir = File(context.applicationInfo.dataDir, "shared_prefs")
        dir.listFiles().orEmpty().forEach { file ->
            val name = file.name.removeSuffix(".xml")
            if (isSafePersonalizationPreference(name)) known += name
        }
        return known.filter(::isSafePersonalizationPreference).sorted()
    }

    private fun writePersonalizationRows(writer: Writer) {
        personalizationPreferenceNames().forEach { name ->
            val all = context.getSharedPreferences(name, Context.MODE_PRIVATE).all
            if (all.isEmpty()) return@forEach
            val entries = JSONArray()
            all.toSortedMap().forEach { (key, raw) ->
                val entry = JSONObject().put("key", key)
                when (raw) {
                    is Boolean -> entry.put("type", "boolean").put("value", raw)
                    is Int -> entry.put("type", "int").put("value", raw)
                    is Long -> entry.put("type", "long").put("value", raw)
                    is Float -> entry.put("type", "float").put("value", raw.toDouble())
                    is String -> entry.put("type", "string").put("value", raw)
                    is Set<*> -> entry.put("type", "string_set").put(
                        "value", JSONArray().apply { raw.filterIsInstance<String>().sorted().forEach { put(it) } }
                    )
                    else -> return@forEach
                }
                entries.put(entry)
            }
            writeJson(writer, "UI_PREFERENCES", JSONObject().apply {
                put("name", name)
                put("entries", entries)
            })
        }
    }

    private fun restorePersonalization(o: JSONObject) {
        val name = o.optString("name", "").trim()
        if (!isSafePersonalizationPreference(name)) return
        val entries = o.optJSONArray("entries") ?: return
        val editor = context.getSharedPreferences(name, Context.MODE_PRIVATE).edit().clear()
        for (i in 0 until entries.length()) {
            val entry = entries.optJSONObject(i) ?: continue
            val key = entry.optString("key", "").trim()
            if (key.isBlank()) continue
            when (entry.optString("type")) {
                "boolean" -> editor.putBoolean(key, entry.optBoolean("value", false))
                "int" -> editor.putInt(key, entry.optInt("value", 0))
                "long" -> editor.putLong(key, entry.optLong("value", 0L))
                "float" -> editor.putFloat(key, entry.optDouble("value", 0.0).toFloat())
                "string" -> editor.putString(key, entry.optString("value", ""))
                "string_set" -> {
                    val a = entry.optJSONArray("value") ?: JSONArray()
                    val set = linkedSetOf<String>()
                    for (j in 0 until a.length()) set += a.optString(j)
                    editor.putStringSet(key, set)
                }
            }
        }
        editor.apply()
    }

'''
if pref_helpers not in v3:
    v3 = once(v3, pref_helpers_marker, pref_helpers + pref_helpers_marker, "personalization helpers")

write(v3_path, v3)

# ---------------------------------------------------------------------------
# Documentation note, if present.
# ---------------------------------------------------------------------------
doc_path = "formatexport.md"
if (ROOT / doc_path).exists():
    doc = read(doc_path)
    note = "\n## Format v5 — personnalisation et créneaux météo 10 min\n\nLe format v5 ajoute des lignes `UI_PREFERENCES` pour les personnalisations visuelles non sensibles (courbes, effets/animations, visibilité, navigation et cadrans) ainsi qu’un `captureSlot10m` logique pour les archives de prévision. Le timestamp `issuedAt` réel n’est jamais réécrit. Les imports v1, v2, v3 et v4 restent acceptés.\n"
    if "## Format v5 — personnalisation" not in doc:
        doc += note
        write(doc_path, doc)

print("v0.23.3 patch applied")
