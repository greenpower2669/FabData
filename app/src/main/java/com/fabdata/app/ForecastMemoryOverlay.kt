package com.fabdata.app

import android.app.Activity
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
import android.widget.FrameLayout
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
    private const val TRIGGER = "trg_fabdata_forecast_memory_insert"

    /**
     * Additive schema only. weather_reference_samples remains the active cache and is not
     * migrated or rewritten. Every newly inserted FORECAST row is copied here once.
     */
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
                provider TEXT NOT NULL DEFAULT 'active_reference'
            )
            """.trimIndent()
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_target ON $TABLE(reference_key, target_ts, issued_at)"
        )
        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_issue ON $TABLE(reference_key, issued_at)"
        )

        // De-duplicate identical refreshes for thirty minutes while preserving genuine
        // forecast revisions. No past snapshot is ever updated or replaced.
        sql.execSQL("DROP TRIGGER IF EXISTS $TRIGGER")
        sql.execSQL(
            """
            CREATE TRIGGER $TRIGGER
            AFTER INSERT ON weather_reference_samples
            WHEN NEW.source='forecast'
            BEGIN
                INSERT INTO $TABLE(
                    reference_key, issued_at, target_ts, temperature, humidity, confidence, provider
                )
                SELECT
                    NEW.reference_key,
                    NEW.updated_at,
                    NEW.timestamp,
                    NEW.temperature,
                    NEW.humidity,
                    NEW.confidence,
                    'active_reference'
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM $TABLE a
                    WHERE a.reference_key=NEW.reference_key
                      AND a.target_ts=NEW.timestamp
                      AND a.provider='active_reference'
                      AND ABS(a.temperature-NEW.temperature) < 0.001
                      AND ABS(COALESCE(a.humidity, 0.0)-COALESCE(NEW.humidity, 0.0)) < 0.01
                      AND a.issued_at >= NEW.updated_at - 1800000
                );
            END
            """.trimIndent()
        )

        // Seed the currently active forecast so the right dial can work immediately.
        sql.execSQL(
            """
            INSERT INTO $TABLE(reference_key, issued_at, target_ts, temperature, humidity, confidence, provider)
            SELECT w.reference_key, w.updated_at, w.timestamp, w.temperature, w.humidity, w.confidence, 'active_reference'
            FROM weather_reference_samples w
            WHERE w.source='forecast'
              AND NOT EXISTS (
                  SELECT 1 FROM $TABLE a
                  WHERE a.reference_key=w.reference_key
                    AND a.target_ts=w.timestamp
                    AND a.provider='active_reference'
                    AND ABS(a.temperature-w.temperature) < 0.001
                    AND ABS(a.issued_at-w.updated_at) < 1800000
              )
            """.trimIndent()
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
    val samples: List<DialSample>
)

private class ForecastDialDataSource(
    context: Context,
    private val db: FabDataDb
) {
    private val appContext = context.applicationContext

    fun load(now: Long = System.currentTimeMillis()): DialState {
        ForecastMemoryStore.ensure(db.writableDatabase)
        val reference = WeatherReferencePrefs(appContext).selectedReference()
        val nowHour = hourBucket(now)
        val targets = listOf(
            "PASSÉ" to (nowHour - HOUR_MS),
            "PRÉSENT" to nowHour,
            "FUTUR" to (nowHour + HOUR_MS)
        )
        val result = targets.map { (label, target) -> buildDial(reference.key, label, target, now) }
        return DialState(reference.label, result)
    }

    private fun buildDial(referenceKey: String, label: String, target: Long, now: Long): DialSample {
        val forecast = bestOneHourForecast(referenceKey, target, now)
        val model = forecast?.let { residualModel(referenceKey, min(now, it.issuedAt)) } ?: ResidualModel()
        val actual = measuredAt(referenceKey, target)

        val officialSlope = forecast?.let { forecastSlope(referenceKey, it) }
        val officialAcceleration = forecast?.let { forecastAcceleration(referenceKey, it) }
        val localSlope = officialSlope?.let { (it + model.slopePerHour).coerceIn(-3.0, 3.0) }
        val localAcceleration = officialAcceleration?.let {
            (it + model.accelerationPerHour2).coerceIn(-1.5, 1.5)
        }
        val actualSlope = if (actual != null) measuredSlope(referenceKey, target) else null
        val actualAcceleration = if (actual != null) measuredAcceleration(referenceKey, target) else null

        val localTemp = forecast?.let {
            (it.temperature + model.residualAt(target, min(now, it.issuedAt))).coerceIn(-70.0, 70.0)
        }
        val officialError = if (forecast != null && actual != null) abs(forecast.temperature - actual) else null
        val localError = if (localTemp != null && actual != null) abs(localTemp - actual) else null

        return DialSample(
            label = label,
            targetTs = target,
            officialTemp = forecast?.temperature,
            localTemp = localTemp,
            actualTemp = actual,
            officialSlope = officialSlope,
            localSlope = localSlope,
            actualSlope = actualSlope,
            officialAcceleration = officialAcceleration,
            localAcceleration = localAcceleration,
            actualAcceleration = actualAcceleration,
            officialError = officialError,
            localError = localError,
            trainingSamples = model.samples
        )
    }

    /** Pick the snapshot that was closest to a genuine H+1 prediction for this target. */
    private fun bestOneHourForecast(referenceKey: String, target: Long, now: Long): ArchivedForecast? {
        val maxIssue = min(now, target - 5L * 60L * 1000L)
        val minIssue = target - 3L * HOUR_MS
        if (maxIssue <= minIssue) return null
        return db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, temperature, humidity, confidence
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=?
              AND target_ts BETWEEN ? AND ?
              AND issued_at BETWEEN ? AND ?
            ORDER BY ABS((target_ts-issued_at)-?) ASC, issued_at DESC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey,
                (target - 12L * 60L * 1000L).toString(),
                (target + 12L * 60L * 1000L).toString(),
                minIssue.toString(),
                maxIssue.toString(),
                HOUR_MS.toString()
            )
        ).use { c ->
            if (!c.moveToFirst()) null
            else ArchivedForecast(
                issuedAt = c.getLong(0),
                targetTs = c.getLong(1),
                temperature = c.getDouble(2),
                humidity = if (c.isNull(3)) 50.0 else c.getDouble(3),
                confidence = if (c.isNull(4)) 0.65 else c.getDouble(4)
            )
        }
    }

    private fun forecastAtSameIssue(referenceKey: String, target: Long, issue: Long): ArchivedForecast? {
        val issueWindow = 3L * 60L * 1000L
        return db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, temperature, humidity, confidence
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=?
              AND target_ts BETWEEN ? AND ?
              AND issued_at BETWEEN ? AND ?
            ORDER BY ABS(target_ts-?) ASC, ABS(issued_at-?) ASC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey,
                (target - 12L * 60L * 1000L).toString(),
                (target + 12L * 60L * 1000L).toString(),
                (issue - issueWindow).toString(),
                (issue + issueWindow).toString(),
                target.toString(),
                issue.toString()
            )
        ).use { c ->
            if (!c.moveToFirst()) null
            else ArchivedForecast(
                c.getLong(0), c.getLong(1), c.getDouble(2),
                if (c.isNull(3)) 50.0 else c.getDouble(3),
                if (c.isNull(4)) 0.65 else c.getDouble(4)
            )
        }
    }

    private fun forecastSlope(referenceKey: String, center: ArchivedForecast): Double? {
        val previous = forecastAtSameIssue(referenceKey, center.targetTs - HOUR_MS, center.issuedAt)
        val next = forecastAtSameIssue(referenceKey, center.targetTs + HOUR_MS, center.issuedAt)
        return when {
            previous != null && next != null -> (next.temperature - previous.temperature) / 2.0
            next != null -> next.temperature - center.temperature
            previous != null -> center.temperature - previous.temperature
            else -> null
        }?.coerceIn(-3.0, 3.0)
    }

    private fun forecastAcceleration(referenceKey: String, center: ArchivedForecast): Double? {
        val previous = forecastAtSameIssue(referenceKey, center.targetTs - HOUR_MS, center.issuedAt) ?: return null
        val next = forecastAtSameIssue(referenceKey, center.targetTs + HOUR_MS, center.issuedAt) ?: return null
        return (next.temperature - 2.0 * center.temperature + previous.temperature).coerceIn(-1.5, 1.5)
    }

    /** Green is real only: reconstructed weather is deliberately not accepted here. */
    private fun measuredAt(referenceKey: String, target: Long): Double? {
        val tolerance = 36L * 60L * 1000L
        return db.readableDatabase.rawQuery(
            """
            SELECT temperature
            FROM weather_reference_samples
            WHERE reference_key=?
              AND source='measured'
              AND timestamp BETWEEN ? AND ?
            ORDER BY ABS(timestamp-?) ASC
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey,
                (target - tolerance).toString(),
                (target + tolerance).toString(),
                target.toString()
            )
        ).use { c -> if (c.moveToFirst()) c.getDouble(0) else null }
    }

    private fun measuredSlope(referenceKey: String, target: Long): Double? {
        val center = measuredAt(referenceKey, target) ?: return null
        val previous = measuredAt(referenceKey, target - HOUR_MS)
        val next = measuredAt(referenceKey, target + HOUR_MS)
        return when {
            previous != null && next != null -> (next - previous) / 2.0
            next != null -> next - center
            previous != null -> center - previous
            else -> null
        }?.coerceIn(-3.0, 3.0)
    }

    private fun measuredAcceleration(referenceKey: String, target: Long): Double? {
        val center = measuredAt(referenceKey, target) ?: return null
        val previous = measuredAt(referenceKey, target - HOUR_MS) ?: return null
        val next = measuredAt(referenceKey, target + HOUR_MS) ?: return null
        return (next - 2.0 * center + previous).coerceIn(-1.5, 1.5)
    }

    /**
     * 24 h short-memory residual learner. For a historical dial the cutoff is the original
     * forecast issue time, so observations that were still in the future cannot leak into
     * its yellow estimate.
     */
    private fun residualModel(referenceKey: String, asOf: Long): ResidualModel {
        val from = asOf - 24L * HOUR_MS
        val candidates = mutableListOf<ArchivedForecast>()
        db.readableDatabase.rawQuery(
            """
            SELECT issued_at, target_ts, temperature, humidity, confidence
            FROM ${ForecastMemoryStore.TABLE}
            WHERE reference_key=?
              AND target_ts BETWEEN ? AND ?
              AND issued_at < target_ts - 300000
              AND target_ts-issued_at BETWEEN 1200000 AND 10800000
            ORDER BY target_ts, issued_at
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), asOf.toString())
        ).use { c ->
            while (c.moveToNext()) {
                candidates += ArchivedForecast(
                    c.getLong(0), c.getLong(1), c.getDouble(2),
                    if (c.isNull(3)) 50.0 else c.getDouble(3),
                    if (c.isNull(4)) 0.65 else c.getDouble(4)
                )
            }
        }
        if (candidates.isEmpty()) return ResidualModel()

        // One fair sample per target hour: keep the prediction closest to H+1.
        val selected = candidates.groupBy { hourBucket(it.targetTs) }
            .values
            .mapNotNull { group -> group.minByOrNull { abs((it.targetTs - it.issuedAt) - HOUR_MS) } }
            .sortedBy { it.targetTs }

        val residuals = selected.mapNotNull { f ->
            measuredAt(referenceKey, f.targetTs)?.let { actual -> ResidualPoint(f.targetTs, actual - f.temperature) }
        }
        if (residuals.isEmpty()) return ResidualModel()
        if (residuals.size == 1) {
            return ResidualModel(biasNow = residuals.first().residual.coerceIn(-4.0, 4.0), samples = 1)
        }

        // Exponentially favour recent errors while still allowing the full 24 h window to help.
        var sw = 0.0
        var sx = 0.0
        var sy = 0.0
        var sxx = 0.0
        var sxy = 0.0
        residuals.forEach { p ->
            val x = (p.targetTs - asOf).toDouble() / HOUR_MS.toDouble()
            val w = exp(x / 6.0).coerceAtLeast(0.01)
            sw += w
            sx += w * x
            sy += w * p.residual
            sxx += w * x * x
            sxy += w * x * p.residual
        }
        val denom = sw * sxx - sx * sx
        val slope = if (abs(denom) > 1e-9) ((sw * sxy - sx * sy) / denom).coerceIn(-1.2, 1.2) else 0.0
        val bias = if (sw > 0.0) ((sy - slope * sx) / sw).coerceIn(-4.0, 4.0) else 0.0

        val accelerations = residuals.zipWithNext().zipWithNext().mapNotNull { (leftPair, rightPair) ->
            val (a, b) = leftPair
            val (_, c) = rightPair
            val dt1 = (b.targetTs - a.targetTs).toDouble() / HOUR_MS.toDouble()
            val dt2 = (c.targetTs - b.targetTs).toDouble() / HOUR_MS.toDouble()
            if (dt1 !in 0.5..2.0 || dt2 !in 0.5..2.0) return@mapNotNull null
            val s1 = (b.residual - a.residual) / dt1
            val s2 = (c.residual - b.residual) / dt2
            val dt = (dt1 + dt2) / 2.0
            ((s2 - s1) / dt).coerceIn(-1.5, 1.5) to c.targetTs
        }
        var accel = 0.0
        if (accelerations.isNotEmpty()) {
            var aw = 0.0
            var av = 0.0
            accelerations.forEach { (value, ts) ->
                val x = (ts - asOf).toDouble() / HOUR_MS.toDouble()
                val w = exp(x / 4.0).coerceAtLeast(0.01)
                aw += w
                av += w * value
            }
            if (aw > 0.0) accel = (av / aw).coerceIn(-0.8, 0.8)
        }
        return ResidualModel(bias, slope, accel, residuals.size)
    }
}

private class ForecastDialStripView(
    context: Context,
    db: FabDataDb
) : View(context) {
    companion object {
        const val TAG = "fabdata_forecast_tangent_dials"
        private const val PREFS = "fabdata_forecast_dial_overlay"
        private const val KEY_X = "x_fraction"
        private const val KEY_Y = "y_fraction"
        private const val KEY_WIDTH_DP = "width_dp"
        private const val KEY_HEIGHT_DP = "height_dp"
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
        val minWidth = dp(270f).toInt()
        val minHeight = dp(130f).toInt()
        val maxWidth = maxOf(minWidth, root.width - dp(8f).toInt())
        val maxHeight = maxOf(minHeight, root.height - dp(8f).toInt())
        layoutParams = layoutParams.apply {
            width = dp(prefs.getFloat(KEY_WIDTH_DP, 348f)).toInt().coerceIn(minWidth, maxWidth)
            height = dp(prefs.getFloat(KEY_HEIGHT_DP, 154f)).toInt().coerceIn(minHeight, maxHeight)
        }
        requestLayout()
        post {
            val maxX = (root.width - width).coerceAtLeast(0).toFloat()
            val maxY = (root.height - height).coerceAtLeast(0).toFloat()
            val xFraction = prefs.getFloat(KEY_X, -1f)
            val yFraction = prefs.getFloat(KEY_Y, -1f)
            x = if (xFraction >= 0f) maxX * xFraction.coerceIn(0f, 1f) else dp(8f)
            y = if (yFraction >= 0f) maxY * yFraction.coerceIn(0f, 1f) else dp(96f)
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val parentView = parent as? ViewGroup ?: return true
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastRawX = event.rawX
                lastRawY = event.rawY
                startX = x
                startY = y
                startWidth = width
                startHeight = height
                val handle = dp(36f)
                resizing = event.x >= width - handle && event.y >= height - handle
                parentView.requestDisallowInterceptTouchEvent(true)
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.rawX - lastRawX
                val dy = event.rawY - lastRawY
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
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                parentView.requestDisallowInterceptTouchEvent(false)
                persistGeometry(parentView)
                resizing = false
                performClick()
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    private fun persistGeometry(root: ViewGroup) {
        val maxX = (root.width - width).coerceAtLeast(1).toFloat()
        val maxY = (root.height - height).coerceAtLeast(1).toFloat()
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putFloat(KEY_X, (x / maxX).coerceIn(0f, 1f))
            .putFloat(KEY_Y, (y / maxY).coerceIn(0f, 1f))
            .putFloat(KEY_WIDTH_DP, width / resources.displayMetrics.density.coerceAtLeast(0.1f))
            .putFloat(KEY_HEIGHT_DP, height / resources.displayMetrics.density.coerceAtLeast(0.1f))
            .apply()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val current = state
        val night = (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES
        val panel = if (night) Color.rgb(28, 30, 34) else Color.rgb(250, 250, 250)
        paint.style = Paint.Style.FILL
        paint.color = withAlpha(panel, if (night) 215 else 232)
        canvas.drawRoundRect(0f, 0f, width.toFloat(), height.toFloat(), dp(16f), dp(16f), paint)

        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(1f)
        paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, 55)
        canvas.drawRoundRect(dp(0.5f), dp(0.5f), width - dp(0.5f), height - dp(0.5f), dp(16f), dp(16f), paint)

        drawLegend(canvas, night, current?.referenceLabel ?: "Prévision locale")
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

    private fun drawLegend(canvas: Canvas, night: Boolean, reference: String) {
        val textColor = if (night) Color.WHITE else Color.rgb(40, 40, 40)
        paint.style = Paint.Style.FILL
        paint.color = textColor
        paint.textSize = sp(10f)
        paint.isFakeBoldText = true
        canvas.drawText("Tangentes · $reference", dp(10f), dp(14f), paint)
        paint.isFakeBoldText = false
        paint.textSize = sp(8.5f)
        val y = dp(25f)
        var x = dp(10f)
        x = legendItem(canvas, x, y, OFFICIAL_RED, "Météo")
        x = legendItem(canvas, x + dp(8f), y, LOCAL_YELLOW, "Fab")
        legendItem(canvas, x + dp(8f), y, REAL_GREEN, "Réel")
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
        // Future green remains absent until a real MEASURED value exists.
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
            sample.actualTemp == null -> "réel en attente"
            sample.officialError != null && sample.localError != null ->
                "M ${oneDec(sample.officialError)}° · F ${oneDec(sample.localError)}°"
            else -> "mesure disponible"
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
            state.samples.forEach { s ->
                append("${s.label.lowercase()} ${timeFormatter.format(Instant.ofEpochMilli(s.targetTs))}. ")
                if (s.actualTemp == null) {
                    append("Réel en attente. ")
                } else if (s.officialError != null && s.localError != null) {
                    append("Erreur météo ${oneDec(s.officialError)} degré, erreur Fab ${oneDec(s.localError)} degré. ")
                }
            }
        }
    }

    private fun emptyDial(label: String) = DialSample(
        label, System.currentTimeMillis(), null, null, null,
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
