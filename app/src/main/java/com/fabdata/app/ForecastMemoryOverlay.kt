package com.fabdata.app

import android.app.Activity
import android.app.AlertDialog
import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.res.Configuration
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.TextView
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

private const val DIAL_PREFS = "fabdata_forecast_dial_overlay"
private const val DIAL_WEATHER_HORIZON_KEY = "monitor_weather_horizon"
private const val DIAL_ADAPTIVE_HORIZON_KEY = "monitor_adaptive_horizon"
private const val FORECAST_CAPTURE_SLOT_MS = 10L * 60L * 1000L

/**
 * Forecast memory / tangent cockpit.
 *
 * This file is intentionally additive: it does not alter the historical reconstruction,
 * chart LOD cascade, priority rules, or the existing forecast engine. The active weather
 * cache keeps its current replace-in-place semantics while this layer records immutable
 * forecast snapshots in a second table and evaluates them later against MEASURED data.
 *
 * V1 is a shadow observer only. The yellow local correction is computed and displayed,
 * but it never writes back to weather_reference_samples nor to indoor sensor forecasts.
 */
class ForecastMemoryBootstrapProvider : ContentProvider() {
    private var appCallbacks: Application.ActivityLifecycleCallbacks? = null
    private var db: FabDataDb? = null

    override fun onCreate(): Boolean {
        val app = context?.applicationContext as? Application ?: return true
        val localDb = FabDataDb(app)
        db = localDb
        runCatching { ForecastMemoryStore.ensure(localDb.writableDatabase) }

        val callbacks = object : Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
            override fun onActivityStarted(activity: Activity) = Unit
            override fun onActivityPaused(activity: Activity) = Unit
            override fun onActivityStopped(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit

            override fun onActivityResumed(activity: Activity) {
                if (activity !is MainActivity) return
                attachOverlay(activity, localDb)
            }
        }
        app.registerActivityLifecycleCallbacks(callbacks)
        appCallbacks = callbacks
        return true
    }

    private fun attachOverlay(activity: Activity, db: FabDataDb) {
        val root = activity.findViewById<ViewGroup>(android.R.id.content) ?: return
        if (root.findViewWithTag<View>(ForecastDialStripView.TAG) != null) return

        val density = activity.resources.displayMetrics.density
        fun dp(value: Float): Int = (value * density + 0.5f).toInt()
        val view = ForecastDialStripView(activity, db).apply {
            tag = ForecastDialStripView.TAG
            elevation = dp(12f).toFloat()
        }
        val params = FrameLayout.LayoutParams(dp(348f), dp(154f), Gravity.TOP or Gravity.START)
        root.addView(view, params)
        view.post { view.restorePosition(root) }
    }

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0
}

object ForecastMemoryStore {
    const val TABLE = "forecast_snapshot_archive"
    private const val LEGACY_TRIGGER = "trg_fabdata_forecast_memory_insert"
    private const val PREVIOUS_TRIGGER = "trg_fabdata_forecast_memory_insert_v2"
    private const val TRIGGER = "trg_fabdata_forecast_memory_insert_v3"
    private const val ATTEMPT_TABLE = "forecast_capture_attempt"
    private const val ATTEMPT_RETENTION_MS = 7L * 24L * 60L * 60L * 1000L

    fun captureSlot10m(timestamp: Long): Long =
        (timestamp / FORECAST_CAPTURE_SLOT_MS) * FORECAST_CAPTURE_SLOT_MS

    /**
     * Additive schema only. issued_at always keeps the real retrieval time.
     * capture_slot_10m is a canonical logical key used only to prevent a restore or
     * a second refresh in the same :00/:10/:20/... slot from duplicating an emission.
     */
    @Synchronized
    fun ensure(sql: SQLiteDatabase) {
        WeatherReferenceStore.ensure(sql)
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $TABLE (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_key TEXT NOT NULL,
                issued_at INTEGER NOT NULL,
                target_ts INTEGER NOT NULL,
                temperature REAL NOT NULL,
                humidity REAL,
                confidence REAL,
                provider TEXT NOT NULL DEFAULT 'active_reference',
                capture_slot_10m INTEGER
            )
            """.trimIndent()
        )
        var hasSlot = false
        sql.rawQuery("PRAGMA table_info($TABLE)", null).use { c ->
            while (c.moveToNext()) {
                if (c.getString(c.getColumnIndexOrThrow("name")) == "capture_slot_10m") {
                    hasSlot = true
                    break
                }
            }
        }
        if (!hasSlot) {
            sql.execSQL("ALTER TABLE $TABLE ADD COLUMN capture_slot_10m INTEGER")
        }
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_target ON $TABLE(reference_key, target_ts, issued_at)"
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_issue ON $TABLE(reference_key, issued_at)"
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_slot ON $TABLE(reference_key, capture_slot_10m, target_ts)"
        )
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $ATTEMPT_TABLE (
                reference_key TEXT NOT NULL,
                capture_slot_10m INTEGER NOT NULL,
                trigger TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                finished_at INTEGER,
                success INTEGER,
                detail TEXT,
                PRIMARY KEY(reference_key, capture_slot_10m)
            )
            """.trimIndent()
        )

        // v3: the archive slot is the slot CLAIMED before the provider request, not the
        // wall-clock minute at which an individual SQLite row happens to be inserted.
        // This matters when a request starts at 14:09:59 and finishes after 14:10:00:
        // every row still belongs to the single 14:00 emission. issued_at keeps the real time.
        fun triggerExists(name: String): Boolean = sql.rawQuery(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=? LIMIT 1",
            arrayOf(name)
        ).use { it.moveToFirst() }

        // Retire each obsolete trigger only if it actually exists. Normal ensure() calls are
        // read-only with respect to old trigger names, avoiding the former DROP/CREATE race.
        if (triggerExists(LEGACY_TRIGGER)) sql.execSQL("DROP TRIGGER $LEGACY_TRIGGER")
        if (triggerExists(PREVIOUS_TRIGGER)) sql.execSQL("DROP TRIGGER $PREVIOUS_TRIGGER")

        val claimedSlotSql = """
            COALESCE(
                (SELECT ca.capture_slot_10m
                 FROM $ATTEMPT_TABLE ca
                 WHERE ca.reference_key=NEW.reference_key
                   AND ca.finished_at IS NULL
                   AND ca.started_at<=NEW.updated_at
                 ORDER BY ca.started_at DESC
                 LIMIT 1),
                (NEW.updated_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS
            )
        """.trimIndent()
        sql.execSQL(
            """
            CREATE TRIGGER IF NOT EXISTS $TRIGGER
            AFTER INSERT ON weather_reference_samples
            WHEN NEW.source='forecast'
            BEGIN
                INSERT INTO $TABLE(
                    reference_key, issued_at, target_ts, temperature, humidity, confidence, provider, capture_slot_10m
                )
                SELECT
                    NEW.reference_key,
                    NEW.updated_at,
                    NEW.timestamp,
                    NEW.temperature,
                    NEW.humidity,
                    NEW.confidence,
                    'active_reference',
                    $claimedSlotSql
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM $TABLE a
                    WHERE a.reference_key=NEW.reference_key
                      AND a.target_ts=NEW.timestamp
                      AND a.provider='active_reference'
                      AND COALESCE(
                          a.capture_slot_10m,
                          (a.issued_at / $FORECAST_CAPTURE_SLOT_MS) * $FORECAST_CAPTURE_SLOT_MS
                      ) = $claimedSlotSql
                );
            END
            """.trimIndent()
        )

        // No recurring cache seeding here. The v3 trigger archives each newly acquired raw
        // provider row exactly once. Re-seeding weather_reference_samples on every ensure()
        // could manufacture a second logical slot after a request crossed a 10-minute boundary.
    }

    fun hasCaptureSlot(sql: SQLiteDatabase, referenceKey: String, timestamp: Long): Boolean {
        ensure(sql)
        return hasCaptureSlotValue(sql, referenceKey, captureSlot10m(timestamp))
    }

    private fun hasCaptureSlotValue(sql: SQLiteDatabase, referenceKey: String, slot: Long): Boolean =
        sql.rawQuery(
            """
            SELECT 1 FROM $TABLE
            WHERE reference_key=?
              AND COALESCE(capture_slot_10m, (issued_at / ?) * ?) = ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(referenceKey, FORECAST_CAPTURE_SLOT_MS.toString(), FORECAST_CAPTURE_SLOT_MS.toString(), slot.toString())
        ).use { it.moveToFirst() }

    fun captureSlotClosed(sql: SQLiteDatabase, referenceKey: String, timestamp: Long): Boolean {
        ensure(sql)
        val slot = captureSlot10m(timestamp)
        if (hasCaptureSlotValue(sql, referenceKey, slot)) return true
        return sql.rawQuery(
            "SELECT 1 FROM $ATTEMPT_TABLE WHERE reference_key=? AND capture_slot_10m=? LIMIT 1",
            arrayOf(referenceKey, slot.toString())
        ).use { it.moveToFirst() }
    }

    /** Atomically reserves one automatic provider call for this canonical 10-minute slot. */
    fun tryClaimCaptureSlot(
        sql: SQLiteDatabase,
        referenceKey: String,
        timestamp: Long,
        trigger: String
    ): Long? {
        ensure(sql)
        val slot = captureSlot10m(timestamp)
        if (hasCaptureSlotValue(sql, referenceKey, slot)) return null
        sql.delete(ATTEMPT_TABLE, "capture_slot_10m<?", arrayOf((slot - ATTEMPT_RETENTION_MS).toString()))
        val values = ContentValues().apply {
            put("reference_key", referenceKey)
            put("capture_slot_10m", slot)
            put("trigger", trigger)
            put("started_at", System.currentTimeMillis())
        }
        val inserted = sql.insertWithOnConflict(ATTEMPT_TABLE, null, values, SQLiteDatabase.CONFLICT_IGNORE)
        return slot.takeIf { inserted != -1L }
    }

    fun finishCaptureSlot(
        sql: SQLiteDatabase,
        referenceKey: String,
        slot: Long,
        success: Boolean,
        detail: String
    ) {
        ensure(sql)
        val values = ContentValues().apply {
            put("finished_at", System.currentTimeMillis())
            put("success", if (success) 1 else 0)
            put("detail", detail.take(240))
        }
        sql.update(
            ATTEMPT_TABLE,
            values,
            "reference_key=? AND capture_slot_10m=?",
            arrayOf(referenceKey, slot.toString())
        )
    }
}

private data class ArchivedForecast(
    val issuedAt: Long,
    val targetTs: Long,
    val temperature: Double,
    val humidity: Double,
    val confidence: Double
)

private data class TerrainDialPoint(
    val temperature: Double,
    val measured: Boolean
)

private data class CurveKinematics(
    val temperature: Double,
    val slope: Double?,
    val acceleration: Double?
)

private data class ResidualPoint(
    val targetTs: Long,
    val residual: Double
)

private data class ResidualModel(
    val biasNow: Double = 0.0,
    val slopePerHour: Double = 0.0,
    val accelerationPerHour2: Double = 0.0,
    val samples: Int = 0
) {
    fun residualAt(targetTs: Long, asOf: Long): Double {
        val horizon = (targetTs - asOf).toDouble() / HOUR_MS.toDouble()
        return (biasNow + slopePerHour * horizon + 0.5 * accelerationPerHour2 * horizon * horizon)
            .coerceIn(-5.0, 5.0)
    }
}

private data class DialSample(
    val label: String,
    val targetTs: Long,
    val officialTemp: Double?,
    val localTemp: Double?,
    val actualTemp: Double?,
    val actualIsMeasured: Boolean,
    val officialSlope: Double?,
    val localSlope: Double?,
    val actualSlope: Double?,
    val officialAcceleration: Double?,
    val localAcceleration: Double?,
    val actualAcceleration: Double?,
    val officialError: Double?,
    val localError: Double?,
    val trainingSamples: Int
)

private data class DialState(
    val referenceLabel: String,
    val weatherHorizon: Int,
    val adaptiveHorizon: Int,
    val samples: List<DialSample>
)

private class ForecastDialDataSource(
    context: Context,
    private val db: FabDataDb
) {
    private val appContext = context.applicationContext
    private val dialPrefs = appContext.getSharedPreferences(DIAL_PREFS, Context.MODE_PRIVATE)

    fun load(now: Long = System.currentTimeMillis()): DialState {
        ForecastMemoryStore.ensure(db.writableDatabase)
        ForecastHorizonArchiveStore.ensure(db.writableDatabase)
        ForecastAdaptiveStore.ensure(db.writableDatabase)
        val reference = WeatherReferencePrefs(appContext).selectedReference()
        val weatherHorizon = dialPrefs.getInt(DIAL_WEATHER_HORIZON_KEY, 1).coerceIn(1, 48)
        val requestedAdaptive = dialPrefs.getInt(DIAL_ADAPTIVE_HORIZON_KEY, 1)
        val adaptiveHorizon = requestedAdaptive.takeIf { it in FORECAST_ADAPTIVE_HORIZONS } ?: 1

        // Materialise only a narrow target window from already archived raw snapshots.
        // No terrain/training data is modified by the cockpit.
        runCatching {
            ForecastHorizonArchive(db).materialize(
                reference.key, now - 3L * HOUR_MS, now + 3L * HOUR_MS, now
            )
        }

        val nowHour = hourBucket(now)
        val targets = listOf(
            "PASSÉ" to (nowHour - HOUR_MS),
            "PRÉSENT" to nowHour,
            "FUTUR" to (nowHour + HOUR_MS)
        )
        val result = targets.map { (label, target) ->
            buildDial(reference.key, label, target, weatherHorizon, adaptiveHorizon)
        }
        return DialState(reference.label, weatherHorizon, adaptiveHorizon, result)
    }

    private fun buildDial(
        referenceKey: String,
        label: String,
        target: Long,
        weatherHorizon: Int,
        adaptiveHorizon: Int
    ): DialSample {
        val official = fixedWeatherKinematics(referenceKey, weatherHorizon, target)
        val local = adaptiveKinematics(referenceKey, adaptiveHorizon, target)
        val terrain = if (label == "FUTUR") null else terrainAt(referenceKey, target)
        val actual = terrain?.temperature
        val actualSlope = if (terrain != null) terrainSlope(referenceKey, target) else null
        val actualAcceleration = if (terrain != null) terrainAcceleration(referenceKey, target) else null

        return DialSample(
            label = label,
            targetTs = target,
            officialTemp = official?.temperature,
            localTemp = local?.temperature,
            actualTemp = actual,
            actualIsMeasured = terrain?.measured == true,
            officialSlope = official?.slope,
            localSlope = local?.slope,
            actualSlope = actualSlope,
            officialAcceleration = official?.acceleration,
            localAcceleration = local?.acceleration,
            actualAcceleration = actualAcceleration,
            officialError = if (official != null && actual != null) abs(official.temperature - actual) else null,
            localError = if (local != null && actual != null) abs(local.temperature - actual) else null,
            trainingSamples = adaptiveHistorySamples(referenceKey, adaptiveHorizon, target)
        )
    }

    private fun fixedWeatherAt(referenceKey: String, horizon: Int, target: Long): Double? {
        val tolerance = 36L * 60L * 1000L
        return db.readableDatabase.rawQuery(
            """
            SELECT weather_temperature
            FROM ${ForecastHorizonArchiveStore.TABLE}
            WHERE reference_key=? AND lead_hour=? AND target_ts BETWEEN ? AND ?
              AND policy_version=?
            ORDER BY ABS(target_ts-?) ASC, issued_at DESC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey, horizon.toString(),
                (target - tolerance).toString(), (target + tolerance).toString(),
                ForecastHorizonArchiveStore.POLICY_VERSION, target.toString()
            )
        ).use { c -> if (c.moveToFirst()) c.getDouble(0) else null }
    }

    private fun adaptiveAt(referenceKey: String, horizon: Int, target: Long): Double? {
        val tolerance = 36L * 60L * 1000L
        return db.readableDatabase.rawQuery(
            """
            SELECT adaptive_temperature
            FROM ${ForecastAdaptiveStore.TABLE}
            WHERE reference_key=? AND horizon_hour=? AND target_ts BETWEEN ? AND ?
              AND model_version=?
            ORDER BY ABS(target_ts-?) ASC, issued_at DESC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey, horizon.toString(),
                (target - tolerance).toString(), (target + tolerance).toString(),
                ForecastAdaptiveStore.MODEL_VERSION, target.toString()
            )
        ).use { c -> if (c.moveToFirst()) c.getDouble(0) else null }
    }

    private fun adaptiveHistorySamples(referenceKey: String, horizon: Int, target: Long): Int {
        val tolerance = 36L * 60L * 1000L
        return db.readableDatabase.rawQuery(
            """
            SELECT history_samples
            FROM ${ForecastAdaptiveStore.TABLE}
            WHERE reference_key=? AND horizon_hour=? AND target_ts BETWEEN ? AND ?
              AND model_version=?
            ORDER BY ABS(target_ts-?) ASC, issued_at DESC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey, horizon.toString(),
                (target - tolerance).toString(), (target + tolerance).toString(),
                ForecastAdaptiveStore.MODEL_VERSION, target.toString()
            )
        ).use { c -> if (c.moveToFirst()) c.getInt(0) else 0 }
    }

    private fun kinematics(center: Double?, previous: Double?, next: Double?): CurveKinematics? {
        center ?: return null
        val slope = when {
            previous != null && next != null -> (next - previous) / 2.0
            next != null -> next - center
            previous != null -> center - previous
            else -> null
        }?.coerceIn(-3.0, 3.0)
        val acceleration = if (previous != null && next != null)
            (next - 2.0 * center + previous).coerceIn(-1.5, 1.5) else null
        return CurveKinematics(center, slope, acceleration)
    }

    private fun fixedWeatherKinematics(referenceKey: String, horizon: Int, target: Long): CurveKinematics? =
        kinematics(
            fixedWeatherAt(referenceKey, horizon, target),
            fixedWeatherAt(referenceKey, horizon, target - HOUR_MS),
            fixedWeatherAt(referenceKey, horizon, target + HOUR_MS)
        )

    private fun adaptiveKinematics(referenceKey: String, horizon: Int, target: Long): CurveKinematics? =
        kinematics(
            adaptiveAt(referenceKey, horizon, target),
            adaptiveAt(referenceKey, horizon, target - HOUR_MS),
            adaptiveAt(referenceKey, horizon, target + HOUR_MS)
        )

    private fun terrainAt(referenceKey: String, target: Long): TerrainDialPoint? {
        fun query(source: String, tolerance: Long, measured: Boolean): TerrainDialPoint? =
            db.readableDatabase.rawQuery(
                """
                SELECT temperature FROM weather_reference_samples
                WHERE reference_key=? AND source=? AND timestamp BETWEEN ? AND ?
                ORDER BY ABS(timestamp-?) ASC LIMIT 1
                """.trimIndent(),
                arrayOf(
                    referenceKey, source,
                    (target - tolerance).toString(), (target + tolerance).toString(), target.toString()
                )
            ).use { c -> if (c.moveToFirst()) TerrainDialPoint(c.getDouble(0), measured) else null }
        return query("measured", 36L * 60L * 1000L, true)
            ?: query("reconstructed", 75L * 60L * 1000L, false)
    }

    private fun terrainSlope(referenceKey: String, target: Long): Double? {
        val center = terrainAt(referenceKey, target)?.temperature ?: return null
        val previous = terrainAt(referenceKey, target - HOUR_MS)?.temperature
        val next = terrainAt(referenceKey, target + HOUR_MS)?.temperature
        return when {
            previous != null && next != null -> (next - previous) / 2.0
            next != null -> next - center
            previous != null -> center - previous
            else -> null
        }?.coerceIn(-3.0, 3.0)
    }

    private fun terrainAcceleration(referenceKey: String, target: Long): Double? {
        val center = terrainAt(referenceKey, target)?.temperature ?: return null
        val previous = terrainAt(referenceKey, target - HOUR_MS)?.temperature ?: return null
        val next = terrainAt(referenceKey, target + HOUR_MS)?.temperature ?: return null
        return (next - 2.0 * center + previous).coerceIn(-1.5, 1.5)
    }
}

private class ForecastDialStripView(
    context: Context,
    db: FabDataDb
) : View(context) {
    companion object {
        const val TAG = "fabdata_forecast_tangent_dials"
        private const val PREFS = DIAL_PREFS
        private const val KEY_X = "x_fraction"
        private const val KEY_Y = "y_fraction"
        private const val KEY_WIDTH_DP = "width_dp"
        private const val KEY_HEIGHT_DP = "height_dp"
        private const val KEY_COMPACT = "compact"
        private const val COMPACT_WIDTH_DP = 76f
        private const val COMPACT_HEIGHT_DP = 46f
    }

    private val dataSource = ForecastDialDataSource(context, db)
    private val executor = Executors.newSingleThreadExecutor()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val timeFormatter = DateTimeFormatter.ofPattern("HH:mm")
        .withZone(ZoneId.systemDefault())
    private var state: DialState? = null
    private var lastRawX = 0f
    private var lastRawY = 0f
    private var startX = 0f
    private var startY = 0f
    private var resizing = false
    private var startWidth = 0
    private var startHeight = 0
    private var compact = false
    private var downRawX = 0f
    private var downRawY = 0f
    private var moved = false
    private var lastTapUp = 0L
    private var downEventTime = 0L

    private val refresh = object : Runnable {
        override fun run() {
            if (!isAttachedToWindow) return
            executor.execute {
                val next = runCatching { dataSource.load() }.getOrNull()
                if (next != null) {
                    post {
                        state = next
                        updateAccessibility(next)
                        invalidate()
                    }
                }
            }
            postDelayed(this, 60_000L)
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        removeCallbacks(refresh)
        post(refresh)
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(refresh)
        executor.shutdownNow()
        super.onDetachedFromWindow()
    }

    fun restorePosition(root: ViewGroup) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        compact = prefs.getBoolean(KEY_COMPACT, false)
        val expandedMinWidth = dp(270f).toInt()
        val expandedMinHeight = dp(130f).toInt()
        val maxWidth = maxOf(expandedMinWidth, root.width - dp(8f).toInt())
        val maxHeight = maxOf(expandedMinHeight, root.height - dp(8f).toInt())
        layoutParams = layoutParams.apply {
            if (compact) {
                width = dp(COMPACT_WIDTH_DP).toInt().coerceAtMost(root.width.coerceAtLeast(1))
                height = dp(COMPACT_HEIGHT_DP).toInt().coerceAtMost(root.height.coerceAtLeast(1))
            } else {
                width = dp(prefs.getFloat(KEY_WIDTH_DP, 348f)).toInt().coerceIn(expandedMinWidth, maxWidth)
                height = dp(prefs.getFloat(KEY_HEIGHT_DP, 154f)).toInt().coerceIn(expandedMinHeight, maxHeight)
            }
        }
        requestLayout()
        post {
            val maxX = (root.width - width).coerceAtLeast(0).toFloat()
            val maxY = (root.height - height).coerceAtLeast(0).toFloat()
            val xFraction = prefs.getFloat(KEY_X, -1f)
            val yFraction = prefs.getFloat(KEY_Y, -1f)
            x = if (xFraction >= 0f) maxX * xFraction.coerceIn(0f, 1f) else dp(8f)
            y = if (yFraction >= 0f) maxY * yFraction.coerceIn(0f, 1f) else dp(96f)
            state?.let(::updateAccessibility)
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val parentView = parent as? ViewGroup ?: return true
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastRawX = event.rawX
                lastRawY = event.rawY
                downRawX = event.rawX
                downRawY = event.rawY
                moved = false
                downEventTime = event.eventTime
                startX = x
                startY = y
                startWidth = width
                startHeight = height
                val handle = dp(36f)
                resizing = !compact && event.x >= width - handle && event.y >= height - handle
                parentView.requestDisallowInterceptTouchEvent(true)
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.rawX - lastRawX
                val dy = event.rawY - lastRawY
                if (abs(event.rawX - downRawX) > dp(5f) || abs(event.rawY - downRawY) > dp(5f)) moved = true
                if (resizing) {
                    val minWidth = dp(270f).toInt()
                    val minHeight = dp(130f).toInt()
                    val maxWidth = maxOf(minWidth, (parentView.width - x).toInt())
                    val maxHeight = maxOf(minHeight, (parentView.height - y).toInt())
                    layoutParams = layoutParams.apply {
                        width = (startWidth + dx).toInt().coerceIn(minWidth, maxWidth)
                        height = (startHeight + dy).toInt().coerceIn(minHeight, maxHeight)
                    }
                    requestLayout()
                } else {
                    val maxX = (parentView.width - width).coerceAtLeast(0).toFloat()
                    val maxY = (parentView.height - height).coerceAtLeast(0).toFloat()
                    x = (startX + dx).coerceIn(0f, maxX)
                    y = (startY + dy).coerceIn(0f, maxY)
                }
                return true
            }
            MotionEvent.ACTION_UP -> {
                parentView.requestDisallowInterceptTouchEvent(false)
                if (!moved && !resizing) {
                    val now = event.eventTime
                    val heldMs = now - downEventTime
                    if (heldMs >= 650L) {
                        lastTapUp = 0L
                        showMonitoringDialog()
                    } else if (lastTapUp > 0L && now - lastTapUp <= 340L) {
                        lastTapUp = 0L
                        toggleCompact(parentView)
                    } else {
                        lastTapUp = now
                        persistGeometry(parentView)
                    }
                } else {
                    lastTapUp = 0L
                    persistGeometry(parentView)
                }
                resizing = false
                performClick()
                return true
            }
            MotionEvent.ACTION_CANCEL -> {
                parentView.requestDisallowInterceptTouchEvent(false)
                lastTapUp = 0L
                persistGeometry(parentView)
                resizing = false
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    private fun showMonitoringDialog() {
        val prefs = context.getSharedPreferences(DIAL_PREFS, Context.MODE_PRIVATE)
        val weatherHorizons = (1..48).toList()
        val adaptiveHorizons = FORECAST_ADAPTIVE_HORIZONS.toList()

        fun label(text: String) = TextView(context).apply {
            this.text = text
            textSize = 14f
            setPadding(dp(4f).toInt(), dp(8f).toInt(), dp(4f).toInt(), dp(4f).toInt())
        }
        val weatherSpinner = Spinner(context).apply {
            adapter = ArrayAdapter(
                context, android.R.layout.simple_spinner_dropdown_item,
                weatherHorizons.map { "Météo fixe H+$it" }
            )
            val selected = prefs.getInt(DIAL_WEATHER_HORIZON_KEY, 24).coerceIn(1, 48)
            setSelection(weatherHorizons.indexOf(selected).coerceAtLeast(0))
        }
        val adaptiveSpinner = Spinner(context).apply {
            adapter = ArrayAdapter(
                context, android.R.layout.simple_spinner_dropdown_item,
                adaptiveHorizons.map { "Fab adaptative H+$it" }
            )
            val selected = prefs.getInt(DIAL_ADAPTIVE_HORIZON_KEY, 24)
            setSelection(adaptiveHorizons.indexOf(selected).takeIf { it >= 0 } ?: adaptiveHorizons.indexOf(24))
        }
        val panel = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            val pad = dp(18f).toInt()
            setPadding(pad, dp(4f).toInt(), pad, dp(4f).toInt())
            addView(label("Prévision météo monitorée"))
            addView(weatherSpinner)
            addView(label("Prévision Fab adaptative monitorée"))
            addView(adaptiveSpinner)
        }
        AlertDialog.Builder(context)
            .setTitle("Monitoring des cadrans")
            .setView(panel)
            .setPositiveButton("Enregistrer") { _, _ ->
                prefs.edit()
                    .putInt(DIAL_WEATHER_HORIZON_KEY, weatherHorizons[weatherSpinner.selectedItemPosition])
                    .putInt(DIAL_ADAPTIVE_HORIZON_KEY, adaptiveHorizons[adaptiveSpinner.selectedItemPosition])
                    .apply()
                removeCallbacks(refresh)
                post(refresh)
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun toggleCompact(root: ViewGroup) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (!compact) persistGeometry(root)
        compact = !compact
        prefs.edit().putBoolean(KEY_COMPACT, compact).apply()

        val minWidth = dp(270f).toInt()
        val minHeight = dp(130f).toInt()
        val maxWidth = maxOf(minWidth, root.width - dp(8f).toInt())
        val maxHeight = maxOf(minHeight, root.height - dp(8f).toInt())
        layoutParams = layoutParams.apply {
            if (compact) {
                width = dp(COMPACT_WIDTH_DP).toInt().coerceAtMost(root.width.coerceAtLeast(1))
                height = dp(COMPACT_HEIGHT_DP).toInt().coerceAtMost(root.height.coerceAtLeast(1))
            } else {
                width = dp(prefs.getFloat(KEY_WIDTH_DP, 348f)).toInt().coerceIn(minWidth, maxWidth)
                height = dp(prefs.getFloat(KEY_HEIGHT_DP, 154f)).toInt().coerceIn(minHeight, maxHeight)
            }
        }
        requestLayout()
        post {
            x = x.coerceIn(0f, (root.width - width).coerceAtLeast(0).toFloat())
            y = y.coerceIn(0f, (root.height - height).coerceAtLeast(0).toFloat())
            persistGeometry(root)
            state?.let(::updateAccessibility)
            invalidate()
        }
    }

    private fun persistGeometry(root: ViewGroup) {
        val maxX = (root.width - width).coerceAtLeast(1).toFloat()
        val maxY = (root.height - height).coerceAtLeast(1).toFloat()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().apply {
            putFloat(KEY_X, (x / maxX).coerceIn(0f, 1f))
            putFloat(KEY_Y, (y / maxY).coerceIn(0f, 1f))
            putBoolean(KEY_COMPACT, compact)
            if (!compact) {
                putFloat(KEY_WIDTH_DP, width / resources.displayMetrics.density.coerceAtLeast(0.1f))
                putFloat(KEY_HEIGHT_DP, height / resources.displayMetrics.density.coerceAtLeast(0.1f))
            }
        }.apply()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val current = state
        val night = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        if (compact) {
            drawCompact(canvas, night, current)
            return
        }
        val panel = if (night) Color.rgb(28, 30, 34) else Color.rgb(250, 250, 250)
        paint.style = Paint.Style.FILL
        paint.color = withAlpha(panel, if (night) 215 else 232)
        canvas.drawRoundRect(0f, 0f, width.toFloat(), height.toFloat(), dp(16f), dp(16f), paint)

        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(1f)
        paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, 55)
        canvas.drawRoundRect(dp(0.5f), dp(0.5f), width - dp(0.5f), height - dp(0.5f), dp(16f), dp(16f), paint)

        drawLegend(canvas, night, current)
        val dials = current?.samples ?: listOf(
            emptyDial("PASSÉ"), emptyDial("PRÉSENT"), emptyDial("FUTUR")
        )
        val top = dp(30f)
        val availableH = height - top - dp(4f)
        val slotWidth = width / 3f
        dials.take(3).forEachIndexed { index, sample ->
            val cx = slotWidth * (index + 0.5f)
            val cy = top + availableH * 0.48f
            val radius = min(slotWidth * 0.41f, availableH * 0.35f)
            drawDial(canvas, sample, cx, cy, radius, index, night)
        }
        drawResizeHandle(canvas, night)
    }

    private fun drawCompact(canvas: Canvas, night: Boolean, current: DialState?) {
        val dials = current?.samples ?: listOf(
            emptyDial("PASSÉ"), emptyDial("PRÉSENT"), emptyDial("FUTUR")
        )
        val present = dials.getOrNull(1) ?: emptyDial("PRÉSENT")
        val fill = comparisonFill(present, night)
        val border = officialBorder(present, night)
        val corner = dp(18f)

        paint.style = Paint.Style.FILL
        paint.color = withAlpha(fill, 225)
        canvas.drawRoundRect(0f, 0f, width.toFloat(), height.toFloat(), corner, corner, paint)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(2.2f)
        paint.color = withAlpha(border, 245)
        canvas.drawRoundRect(dp(1.1f), dp(1.1f), width - dp(1.1f), height - dp(1.1f), corner, corner, paint)

        val centerY = height / 2f
        val spacing = width / 4f
        dials.take(3).forEachIndexed { index, sample ->
            val cx = spacing * (index + 1)
            val radius = dp(if (index == 1) 7.0f else 5.0f)
            paint.style = Paint.Style.FILL
            paint.color = withAlpha(comparisonFill(sample, night), if (index == 1) 255 else 205)
            canvas.drawCircle(cx, centerY, radius, paint)
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = dp(if (index == 1) 2.0f else 1.4f)
            paint.color = withAlpha(officialBorder(sample, night), if (index == 1) 255 else 220)
            canvas.drawCircle(cx, centerY, radius, paint)
        }
    }

    private fun drawResizeHandle(canvas: Canvas, night: Boolean) {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(1.5f)
        paint.strokeCap = Paint.Cap.ROUND
        paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, 105)
        val pad = dp(7f)
        for (i in 0..2) {
            val o = dp(5f * i)
            canvas.drawLine(width - pad - o - dp(8f), height - pad, width - pad, height - pad - o - dp(8f), paint)
        }
        paint.strokeCap = Paint.Cap.BUTT
    }

    private fun drawLegend(canvas: Canvas, night: Boolean, current: DialState?) {
        val textColor = if (night) Color.WHITE else Color.rgb(40, 40, 40)
        paint.style = Paint.Style.FILL
        paint.color = textColor
        paint.textSize = sp(10f)
        paint.isFakeBoldText = true
        val monitor = current?.let { "M H+${it.weatherHorizon} / Fab H+${it.adaptiveHorizon}" } ?: "M H+24 / Fab H+24"
        canvas.drawText("Tangentes · $monitor", dp(10f), dp(14f), paint)
        paint.isFakeBoldText = false
        paint.textSize = sp(8.5f)
        val y = dp(25f)
        var x = dp(10f)
        x = legendItem(canvas, x, y, OFFICIAL_RED, "Météo")
        x = legendItem(canvas, x + dp(8f), y, LOCAL_YELLOW, "Fab")
        legendItem(canvas, x + dp(8f), y, REAL_GREEN, "Terrain")
    }

    private fun legendItem(canvas: Canvas, x: Float, y: Float, color: Int, label: String): Float {
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(2.5f)
        paint.color = color
        canvas.drawLine(x, y - dp(2f), x + dp(12f), y - dp(2f), paint)
        paint.style = Paint.Style.FILL
        paint.textSize = sp(8.5f)
        paint.color = if (isNight()) Color.WHITE else Color.DKGRAY
        canvas.drawText(label, x + dp(15f), y, paint)
        return x + dp(15f) + paint.measureText(label)
    }

    private fun drawDial(
        canvas: Canvas,
        sample: DialSample,
        cx: Float,
        cy: Float,
        r: Float,
        index: Int,
        night: Boolean
    ) {
        // Right/future is intentionally the least transparent, then present, then past.
        val slotAlpha = intArrayOf(115, 170, 225)[index.coerceIn(0, 2)]
        val fillColor = comparisonFill(sample, night)
        paint.style = Paint.Style.FILL
        paint.color = withAlpha(fillColor, (slotAlpha * 0.54f).toInt())
        canvas.drawCircle(cx, cy, r, paint)

        val borderColor = officialBorder(sample, night)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(2.2f)
        paint.color = withAlpha(borderColor, slotAlpha)
        canvas.drawCircle(cx, cy, r, paint)

        // Outer tangent scale.
        val arcRect = RectF(cx - r * 0.83f, cy - r * 0.83f, cx + r * 0.83f, cy + r * 0.83f)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(1f)
        paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, (slotAlpha * 0.52f).toInt())
        canvas.drawArc(arcRect, 135f, 270f, false, paint)
        for (i in 0..8) {
            val v = -2.0 + i * 0.5
            val angle = valueAngle(v, -2.0, 2.0)
            val p1 = polar(cx, cy, r * 0.72f, angle)
            val p2 = polar(cx, cy, r * 0.82f, angle)
            canvas.drawLine(p1.first, p1.second, p2.first, p2.second, paint)
        }

        // Inner scale = derivative of the tangent / curvature. Coloured dots show Δ slope.
        val inner = RectF(cx - r * 0.57f, cy - r * 0.57f, cx + r * 0.57f, cy + r * 0.57f)
        paint.strokeWidth = dp(0.8f)
        paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, (slotAlpha * 0.34f).toInt())
        canvas.drawArc(inner, 135f, 270f, false, paint)
        drawAccelerationDot(canvas, sample.officialAcceleration, cx, cy, r * 0.57f, OFFICIAL_RED, slotAlpha)
        drawAccelerationDot(canvas, sample.localAcceleration, cx, cy, r * 0.57f, LOCAL_YELLOW, slotAlpha)
        drawAccelerationDot(canvas, sample.actualAcceleration, cx, cy, r * 0.57f, REAL_GREEN, slotAlpha)

        drawNeedle(canvas, sample.officialSlope, cx, cy, r * 0.73f, OFFICIAL_RED, slotAlpha)
        drawNeedle(canvas, sample.localSlope, cx, cy, r * 0.69f, LOCAL_YELLOW, slotAlpha)
        // Future terrain remains absent until measured/reconstructed reference data exists.
        drawNeedle(canvas, sample.actualSlope, cx, cy, r * 0.63f, REAL_GREEN, slotAlpha)

        paint.style = Paint.Style.FILL
        paint.color = withAlpha(if (night) Color.WHITE else Color.rgb(35, 35, 35), slotAlpha)
        paint.textAlign = Paint.Align.CENTER
        paint.isFakeBoldText = true
        paint.textSize = sp(9f)
        canvas.drawText(sample.label, cx, cy - r - dp(5f), paint)
        paint.isFakeBoldText = false
        paint.textSize = sp(8f)
        canvas.drawText(timeFormatter.format(Instant.ofEpochMilli(sample.targetTs)), cx, cy + r + dp(11f), paint)

        val status = when {
            sample.actualTemp == null -> "terrain en attente"
            sample.officialError != null && sample.localError != null -> {
                val origin = if (sample.actualIsMeasured) "R" else "r"
                "$origin · M ${oneDec(sample.officialError)}° · F ${oneDec(sample.localError)}°"
            }
            sample.actualIsMeasured -> "terrain réel"
            else -> "terrain reconstruit"
        }
        paint.textSize = sp(7.4f)
        canvas.drawText(status, cx, cy + r + dp(21f), paint)
        if (sample.trainingSamples > 0) {
            paint.textSize = sp(6.7f)
            canvas.drawText("24 h · n=${sample.trainingSamples}", cx, cy + r + dp(30f), paint)
        }
        paint.textAlign = Paint.Align.LEFT
    }

    private fun drawNeedle(canvas: Canvas, value: Double?, cx: Float, cy: Float, length: Float, color: Int, alpha: Int) {
        if (value == null || !value.isFinite()) return
        val angle = valueAngle(value, -2.0, 2.0)
        val end = polar(cx, cy, length, angle)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(2.3f)
        paint.strokeCap = Paint.Cap.ROUND
        paint.color = withAlpha(color, alpha)
        canvas.drawLine(cx, cy, end.first, end.second, paint)
        paint.style = Paint.Style.FILL
        canvas.drawCircle(cx, cy, dp(2.3f), paint)
        paint.strokeCap = Paint.Cap.BUTT
    }

    private fun drawAccelerationDot(
        canvas: Canvas,
        value: Double?,
        cx: Float,
        cy: Float,
        radius: Float,
        color: Int,
        alpha: Int
    ) {
        if (value == null || !value.isFinite()) return
        val angle = valueAngle(value, -1.0, 1.0)
        val pos = polar(cx, cy, radius, angle)
        paint.style = Paint.Style.FILL
        paint.color = withAlpha(color, alpha)
        canvas.drawCircle(pos.first, pos.second, dp(2.2f), paint)
    }

    /*
     * Error colours deliberately use a palette that is distinct from the three needles.
     * Border = absolute error of the large weather model against the real value.
     * Background = absolute error of the Fab local model against the real value.
     * Both use the same continuous severity scale: blue -> orange -> red -> violet.
     */
    private fun officialBorder(sample: DialSample, night: Boolean): Int {
        val error = sample.officialError
            ?: return if (night) Color.rgb(130, 138, 150) else Color.rgb(170, 175, 182)
        return errorSeverityColor(error)
    }

    private fun comparisonFill(sample: DialSample, night: Boolean): Int {
        val error = sample.localError
            ?: return if (night) Color.rgb(52, 55, 62) else Color.rgb(242, 243, 245)
        return errorSeverityColor(error)
    }

    private fun errorSeverityColor(errorC: Double): Int {
        val error = errorC.coerceAtLeast(0.0)
        val blue = Color.rgb(45, 115, 205)
        val orange = Color.rgb(238, 145, 35)
        val red = Color.rgb(210, 55, 70)
        val violet = Color.rgb(120, 65, 175)

        return when {
            error <= 0.75 -> blend(blue, orange, (error / 0.75).toFloat())
            error <= 1.50 -> blend(orange, red, ((error - 0.75) / 0.75).toFloat())
            error <= 2.50 -> blend(red, violet, ((error - 1.50) / 1.00).toFloat())
            else -> violet
        }
    }

    private fun updateAccessibility(state: DialState) {
        contentDescription = buildString {
            append("Cadrans tangentiels ${state.referenceLabel}. ")
            append(if (compact) "Mode compact. Double-tape pour ouvrir les cadrans. " else "Mode complet. Double-tape le cadre pour réduire les cadrans. ")
            state.samples.forEach { s ->
                append("${s.label.lowercase()} ${timeFormatter.format(Instant.ofEpochMilli(s.targetTs))}. ")
                if (s.actualTemp == null) {
                    append("Terrain en attente. ")
                } else if (s.officialError != null && s.localError != null) {
                    append("Erreur météo ${oneDec(s.officialError)} degré, erreur Fab ${oneDec(s.localError)} degré. ")
                }
            }
        }
    }

    private fun emptyDial(label: String) = DialSample(
        label, System.currentTimeMillis(), null, null, null, false,
        null, null, null, null, null, null, null, null, 0
    )

    private fun isNight(): Boolean =
        (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES

    private fun valueAngle(value: Double, minValue: Double, maxValue: Double): Double {
        val f = ((value.coerceIn(minValue, maxValue) - minValue) / (maxValue - minValue))
        return 135.0 + 270.0 * f
    }

    private fun polar(cx: Float, cy: Float, radius: Float, angleDeg: Double): Pair<Float, Float> {
        val rad = Math.toRadians(angleDeg)
        return (cx + cos(rad).toFloat() * radius) to (cy + sin(rad).toFloat() * radius)
    }

    private fun blend(a: Int, b: Int, t: Float): Int {
        val u = t.coerceIn(0f, 1f)
        return Color.rgb(
            (Color.red(a) + (Color.red(b) - Color.red(a)) * u).toInt(),
            (Color.green(a) + (Color.green(b) - Color.green(a)) * u).toInt(),
            (Color.blue(a) + (Color.blue(b) - Color.blue(a)) * u).toInt()
        )
    }

    private fun withAlpha(color: Int, alpha: Int): Int = Color.argb(
        alpha.coerceIn(0, 255), Color.red(color), Color.green(color), Color.blue(color)
    )

    private fun dp(v: Float): Float = v * resources.displayMetrics.density
    private fun sp(v: Float): Float = v * resources.displayMetrics.scaledDensity
    private fun oneDec(v: Double): String = String.format(java.util.Locale.FRANCE, "%.1f", v)
}

private const val HOUR_MS = 60L * 60L * 1000L
private fun hourBucket(ts: Long): Long = (ts / HOUR_MS) * HOUR_MS
private val OFFICIAL_RED = Color.rgb(220, 50, 55)
private val LOCAL_YELLOW = Color.rgb(235, 180, 30)
private val REAL_GREEN = Color.rgb(40, 165, 90)
