package com.fabdata.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import kotlin.math.abs
import kotlin.math.max

private const val DASH_HOUR_MS = 60L * 60L * 1000L
private const val DASH_MINUTE_MS = 60L * 1000L

internal data class ForecastDashboardCurvePoint(
    val timestamp: Long,
    val temperature: Double
)

internal data class ForecastDashboardAdaptivePoint(
    val horizonHour: Int,
    val temperature: Double
)

internal data class ForecastDashboardSnapshot(
    val referenceLabel: String,
    val weather: List<ForecastDashboardCurvePoint>,
    val weatherNow: Double?,
    val weatherPlus1: Double?,
    val inertiaNow: Double?,
    val inertiaPlus1: Double?,
    val inertiaPlus2: Double?,
    val adaptive: List<ForecastDashboardAdaptivePoint>
)

/**
 * Read-only data source used by the expanded in-app forecast panel.
 * It deliberately mirrors the Android home widget without triggering providers,
 * reserving forecast slots, retraining models, or mutating weather rows.
 */
internal class ForecastDashboardOverlayDataSource(
    context: Context,
    private val db: FabDataDb
) {
    private val appContext = context.applicationContext

    fun load(now: Long = System.currentTimeMillis()): ForecastDashboardSnapshot {
        val reference = WeatherReferencePrefs(appContext).selectedReference()
        val weather = readWeatherCurve(reference.key, now)
        val inertia = readInertia(reference, now)
        return ForecastDashboardSnapshot(
            referenceLabel = reference.label,
            weather = weather,
            weatherNow = nearest(weather, now, 45L * DASH_MINUTE_MS),
            weatherPlus1 = nearest(weather, now + DASH_HOUR_MS, 45L * DASH_MINUTE_MS),
            inertiaNow = inertia.getOrNull(0),
            inertiaPlus1 = inertia.getOrNull(1),
            inertiaPlus2 = inertia.getOrNull(2),
            adaptive = readAdaptive(reference.key, now)
        )
    }

    private fun readWeatherCurve(referenceKey: String, now: Long): List<ForecastDashboardCurvePoint> {
        val from = now - DASH_HOUR_MS
        val to = now + 12L * DASH_HOUR_MS
        val byTimestamp = linkedMapOf<Long, Double>()
        db.readableDatabase.rawQuery(
            """
            SELECT timestamp, temperature, source
            FROM weather_reference_samples
            WHERE reference_key=? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp,
                CASE source
                    WHEN 'forecast' THEN 0
                    WHEN 'reconstructed' THEN 1
                    WHEN 'measured' THEN 2
                    ELSE 0
                END
            """.trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val ts = c.getLong(0)
                val t = c.getDouble(1)
                if (t.isFinite()) byTimestamp[ts] = t
            }
        }
        return byTimestamp.entries
            .map { ForecastDashboardCurvePoint(it.key, it.value) }
            .sortedBy { it.timestamp }
    }

    private fun nearest(
        points: List<ForecastDashboardCurvePoint>,
        target: Long,
        tolerance: Long
    ): Double? = points.minByOrNull { abs(it.timestamp - target) }
        ?.takeIf { abs(it.timestamp - target) <= tolerance }
        ?.temperature

    private fun readInertia(reference: WeatherReference, now: Long): List<Double?> {
        val model = ThermalTrainedModelStore(appContext).loadUsable(reference.key)
            ?: return listOf(null, null, null)
        val estimate = runCatching {
            ThermalInertiaEstimator(db, WeatherReferenceStore(db)).projectTrained(reference, model)
        }.getOrNull() ?: return listOf(null, null, null)
        val points = estimate.surfacePoints.takeLast(4)
        val last = points.lastOrNull() ?: return listOf(null, null, null)
        val previous = points.dropLast(1).lastOrNull()
        val ageHours = ((now - last.timestamp).coerceAtLeast(0L)).toDouble() / DASH_HOUR_MS.toDouble()
        if (ageHours > 6.0) return listOf(null, null, null)
        val slope = if (previous != null && last.timestamp > previous.timestamp) {
            ((last.temperature - previous.temperature) /
                ((last.timestamp - previous.timestamp).toDouble() / DASH_HOUR_MS.toDouble()))
                .coerceIn(-0.60, 0.60)
        } else 0.0
        val present = last.temperature + slope * ageHours
        return listOf(present, present + slope, present + 2.0 * slope)
            .map { it.takeIf(Double::isFinite) }
    }

    private fun readAdaptive(referenceKey: String, now: Long): List<ForecastDashboardAdaptivePoint> {
        ForecastAdaptiveStore.ensure(db.readableDatabase)
        val nowHour = (now / DASH_HOUR_MS) * DASH_HOUR_MS
        return FORECAST_ADAPTIVE_HORIZONS.mapNotNull { horizon ->
            val target = nowHour + horizon.toLong() * DASH_HOUR_MS
            val tolerance = 45L * DASH_MINUTE_MS
            db.readableDatabase.rawQuery(
                """
                SELECT adaptive_temperature
                FROM ${ForecastAdaptiveStore.TABLE}
                WHERE reference_key=?
                  AND horizon_hour=?
                  AND model_version=?
                  AND target_ts BETWEEN ? AND ?
                ORDER BY ABS(target_ts-?) ASC, issued_at DESC
                LIMIT 1
                """.trimIndent(),
                arrayOf(
                    referenceKey,
                    horizon.toString(),
                    ForecastAdaptiveStore.MODEL_VERSION,
                    (target - tolerance).toString(),
                    (target + tolerance).toString(),
                    target.toString()
                )
            ).use { c ->
                if (c.moveToFirst()) {
                    val value = c.getDouble(0)
                    if (value.isFinite()) ForecastDashboardAdaptivePoint(horizon, value) else null
                } else null
            }
        }
    }
}

/** Same visual language as the Android home widget, rendered into the floating in-app panel. */
internal object ForecastDashboardPainter {
    fun draw(
        canvas: Canvas,
        width: Float,
        height: Float,
        snapshot: ForecastDashboardSnapshot?,
        night: Boolean,
        density: Float,
        scaledDensity: Float
    ) {
        fun dp(v: Float) = v * density
        fun sp(v: Float) = v * scaledDensity
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        val main = if (night) Color.WHITE else Color.rgb(38, 38, 42)
        val muted = if (night) Color.argb(205, 235, 235, 240) else Color.rgb(90, 90, 98)
        val purple = if (night) Color.rgb(225, 205, 255) else Color.rgb(112, 73, 158)
        val amber = Color.rgb(235, 180, 30)

        paint.style = Paint.Style.FILL
        paint.color = main
        paint.textSize = sp(13f)
        paint.isFakeBoldText = true
        canvas.drawText("FabData · MÉTÉO 12 h", dp(10f), dp(19f), paint)
        paint.isFakeBoldText = false
        paint.textAlign = Paint.Align.RIGHT
        paint.textSize = sp(9.5f)
        paint.color = muted
        canvas.drawText(snapshot?.referenceLabel ?: "FabData", width - dp(10f), dp(19f), paint)
        paint.textAlign = Paint.Align.LEFT

        val weatherTop = dp(30f)
        val weatherBottom = max(weatherTop + dp(70f), height * 0.49f)
        drawWeatherCurve(canvas, paint, snapshot?.weather.orEmpty(), dp(12f), weatherTop, width - dp(12f), weatherBottom)

        val nowText = formatTemp(snapshot?.weatherNow)
        val plus1Text = formatTemp(snapshot?.weatherPlus1)
        val pillText = "Maintenant  $nowText        +1 h  $plus1Text"
        paint.textSize = sp(13f)
        paint.isFakeBoldText = true
        val textW = paint.measureText(pillText)
        val cx = width / 2f
        val cy = (weatherTop + weatherBottom) / 2f
        val pill = RectF(
            cx - textW / 2f - dp(10f), cy - dp(16f),
            cx + textW / 2f + dp(10f), cy + dp(10f)
        )
        paint.color = if (night) Color.argb(205, 30, 32, 38) else Color.argb(220, 250, 250, 252)
        canvas.drawRoundRect(pill, dp(10f), dp(10f), paint)
        paint.color = main
        paint.textAlign = Paint.Align.CENTER
        canvas.drawText(pillText, cx, cy + dp(2f), paint)
        paint.isFakeBoldText = false

        val dividerY = weatherBottom + dp(7f)
        paint.color = if (night) Color.argb(50, 255, 255, 255) else Color.argb(45, 50, 50, 60)
        canvas.drawRect(dp(10f), dividerY, width - dp(10f), dividerY + dp(1f), paint)

        paint.textAlign = Paint.Align.CENTER
        paint.textSize = sp(11f)
        paint.isFakeBoldText = true
        paint.color = purple
        canvas.drawText(
            "Sol inertiel   ${formatTemp(snapshot?.inertiaNow)}     +1 h ${formatTemp(snapshot?.inertiaPlus1)}     +2 h ${formatTemp(snapshot?.inertiaPlus2)}",
            cx,
            dividerY + dp(22f),
            paint
        )
        paint.isFakeBoldText = false

        val adaptiveLabelY = dividerY + dp(42f)
        paint.textAlign = Paint.Align.LEFT
        paint.textSize = sp(9.5f)
        paint.color = amber
        canvas.drawText(
            if (snapshot?.adaptive.isNullOrEmpty()) "Fab adaptative H+1 → H+48 · en attente" else "Fab adaptative H+1 → H+48",
            dp(12f), adaptiveLabelY, paint
        )

        drawAdaptiveCurve(
            canvas, paint, snapshot?.adaptive.orEmpty(),
            dp(12f), adaptiveLabelY + dp(6f), width - dp(12f), height - dp(10f), amber, muted, sp(8f)
        )
        paint.textAlign = Paint.Align.LEFT
    }

    private fun drawWeatherCurve(
        canvas: Canvas,
        paint: Paint,
        points: List<ForecastDashboardCurvePoint>,
        left: Float,
        top: Float,
        right: Float,
        bottom: Float
    ) {
        if (points.size < 2 || right <= left || bottom <= top) return
        val minTs = points.first().timestamp
        val maxTs = points.last().timestamp.coerceAtLeast(minTs + 1L)
        val minT = points.minOf { it.temperature }
        val maxT = points.maxOf { it.temperature }
        val range = (maxT - minT).takeIf { it > 0.05 } ?: 1.0
        fun x(ts: Long) = left + ((ts - minTs).toDouble() / (maxTs - minTs).toDouble()).toFloat() * (right - left)
        fun y(t: Double) = bottom - ((t - minT) / range).toFloat() * (bottom - top)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = max(2.5f, (right - left) / 120f)
        paint.strokeCap = Paint.Cap.ROUND
        points.zipWithNext().forEach { (a, b) ->
            paint.color = temperatureColor((a.temperature + b.temperature) / 2.0)
            canvas.drawLine(x(a.timestamp), y(a.temperature), x(b.timestamp), y(b.temperature), paint)
        }
        paint.style = Paint.Style.FILL
    }

    private fun drawAdaptiveCurve(
        canvas: Canvas,
        paint: Paint,
        points: List<ForecastDashboardAdaptivePoint>,
        left: Float,
        top: Float,
        right: Float,
        bottom: Float,
        color: Int,
        labelColor: Int,
        labelSize: Float
    ) {
        if (points.isEmpty() || right <= left || bottom <= top) return
        val sorted = points.sortedBy { it.horizonHour }
        val minT = sorted.minOf { it.temperature }
        val maxT = sorted.maxOf { it.temperature }
        val range = (maxT - minT).takeIf { it > 0.05 } ?: 1.0
        val padBottom = labelSize * 1.6f
        fun x(h: Int) = left + ((h - 1).toFloat() / 47f) * (right - left)
        fun y(t: Double) = bottom - padBottom - ((t - minT) / range).toFloat() * (bottom - top - padBottom)

        if (sorted.size >= 2) {
            val path = Path()
            sorted.forEachIndexed { i, p ->
                if (i == 0) path.moveTo(x(p.horizonHour), y(p.temperature))
                else path.lineTo(x(p.horizonHour), y(p.temperature))
            }
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = max(2.2f, (right - left) / 145f)
            paint.strokeCap = Paint.Cap.ROUND
            paint.strokeJoin = Paint.Join.ROUND
            paint.color = color
            canvas.drawPath(path, paint)
        }
        paint.style = Paint.Style.FILL
        paint.color = color
        sorted.forEach { canvas.drawCircle(x(it.horizonHour), y(it.temperature), max(2.2f, labelSize * 0.32f), paint) }
        paint.color = labelColor
        paint.textSize = labelSize
        paint.textAlign = Paint.Align.CENTER
        listOf(1, 12, 24, 48).forEach { h -> canvas.drawText("H+$h", x(h), bottom, paint) }
    }

    private fun formatTemp(value: Double?): String =
        value?.takeIf(Double::isFinite)?.let { String.format(java.util.Locale.FRANCE, "%.1f°", it) } ?: "—"

    private fun temperatureColor(value: Double): Int {
        val t = value.coerceIn(-10.0, 40.0)
        return when {
            t <= 5.0 -> blend(Color.rgb(55, 120, 220), Color.rgb(70, 190, 225), ((t + 10.0) / 15.0).toFloat())
            t <= 18.0 -> blend(Color.rgb(70, 190, 225), Color.rgb(85, 195, 105), ((t - 5.0) / 13.0).toFloat())
            t <= 28.0 -> blend(Color.rgb(85, 195, 105), Color.rgb(245, 170, 55), ((t - 18.0) / 10.0).toFloat())
            else -> blend(Color.rgb(245, 170, 55), Color.rgb(220, 65, 70), ((t - 28.0) / 12.0).toFloat())
        }
    }

    private fun blend(a: Int, b: Int, f: Float): Int {
        val x = f.coerceIn(0f, 1f)
        fun c(v1: Int, v2: Int) = (v1 + (v2 - v1) * x).toInt().coerceIn(0, 255)
        return Color.rgb(
            c(Color.red(a), Color.red(b)),
            c(Color.green(a), Color.green(b)),
            c(Color.blue(a), Color.blue(b))
        )
    }
}
