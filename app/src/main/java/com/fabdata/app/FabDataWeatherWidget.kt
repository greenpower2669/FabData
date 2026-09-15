package com.fabdata.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.widget.RemoteViews
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

private const val WIDGET_HOUR_MS = 60L * 60L * 1000L
private const val WIDGET_MINUTE_MS = 60L * 1000L
private const val ACTION_WIDGET_TAP = "com.fabdata.app.action.WIDGET_DOUBLE_TAP"
private const val WIDGET_DOUBLE_TAP_MS = 520L
private const val WIDGET_PREFS = "fabdata_android_widget"

private data class WidgetCurvePoint(
    val timestamp: Long,
    val temperature: Double
)

private data class WidgetAdaptivePoint(
    val horizonHour: Int,
    val temperature: Double
)

private data class WidgetSnapshot(
    val referenceLabel: String,
    val weather: List<WidgetCurvePoint>,
    val weatherNow: Double?,
    val weatherPlus1: Double?,
    val inertiaNow: Double?,
    val inertiaPlus1: Double?,
    val inertiaPlus2: Double?,
    val adaptive: List<WidgetAdaptivePoint>
)

/**
 * Real Android home-screen widget for FabData.
 *
 * Important invariant: this component is READ ONLY. It never starts a weather provider
 * request, never reserves a 10-minute capture slot, never retrains a thermal model, and
 * never writes forecast rows. It only renders data already present in FabData.
 */
class FabDataWeatherWidget : AppWidgetProvider() {

    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        ids.forEach { id -> renderAsync(context.applicationContext, manager, id) }
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetId: Int,
        newOptions: android.os.Bundle
    ) {
        renderAsync(context.applicationContext, appWidgetManager, appWidgetId)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action != ACTION_WIDGET_TAP) return
        val id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
        if (id == AppWidgetManager.INVALID_APPWIDGET_ID) return
        val prefs = context.getSharedPreferences(WIDGET_PREFS, Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        val key = "last_tap_$id"
        val previous = prefs.getLong(key, 0L)
        if (previous > 0L && now - previous <= WIDGET_DOUBLE_TAP_MS) {
            val collapsedKey = "collapsed_$id"
            prefs.edit()
                .putBoolean(collapsedKey, !prefs.getBoolean(collapsedKey, false))
                .putLong(key, 0L)
                .apply()
            renderAsync(context.applicationContext, AppWidgetManager.getInstance(context), id)
        } else {
            prefs.edit().putLong(key, now).apply()
        }
    }

    companion object {
        private val executor = Executors.newSingleThreadExecutor()

        private fun renderAsync(context: Context, manager: AppWidgetManager, id: Int) {
            executor.execute {
                val snapshot = runCatching { loadSnapshot(context) }.getOrNull()
                val views = buildRemoteViews(context, snapshot, id)
                manager.updateAppWidget(id, views)
            }
        }

        private fun buildRemoteViews(context: Context, snapshot: WidgetSnapshot?, widgetId: Int): RemoteViews {
            val views = RemoteViews(context.packageName, R.layout.fabdata_weather_widget)
            val launchIntent = Intent(context, MainActivity::class.java)
            val openIntent = PendingIntent.getActivity(
                context,
                2400 + widgetId,
                launchIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val tapIntent = Intent(context, FabDataWeatherWidget::class.java).apply {
                action = ACTION_WIDGET_TAP
                putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId)
            }
            val tapPendingIntent = PendingIntent.getBroadcast(
                context,
                24000 + widgetId,
                tapIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widget_root, tapPendingIntent)
            views.setOnClickPendingIntent(R.id.widget_title, openIntent)
            views.setOnClickPendingIntent(R.id.widget_reference, openIntent)

            val collapsed = context.getSharedPreferences(WIDGET_PREFS, Context.MODE_PRIVATE)
                .getBoolean("collapsed_$widgetId", false)
            views.setViewVisibility(R.id.widget_compact_values, if (collapsed) android.view.View.VISIBLE else android.view.View.GONE)
            views.setViewVisibility(R.id.widget_weather_panel, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)
            views.setViewVisibility(R.id.widget_separator, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)
            views.setViewVisibility(R.id.widget_inertia_values, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)
            views.setViewVisibility(R.id.widget_adaptive_caption, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)
            views.setViewVisibility(R.id.widget_adaptive_curve, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)

            if (snapshot == null) {
                views.setTextViewText(R.id.widget_reference, "FabData")
                views.setTextViewText(R.id.widget_weather_values, "Météo 12 h · maintenant — · +1 h —")
                views.setTextViewText(R.id.widget_compact_values, "Météo 12 h · maintenant — · +1 h —")
                views.setTextViewText(R.id.widget_inertia_values, "Sol inertiel  —   +1 h —   +2 h —")
                views.setTextViewText(R.id.widget_adaptive_caption, "Fab adaptative H+1 → H+48 · données en attente")
                views.setImageViewBitmap(R.id.widget_weather_curve, emptyChart(720, 180))
                views.setImageViewBitmap(R.id.widget_adaptive_curve, emptyChart(720, 130))
                views.setContentDescription(R.id.widget_root, "Widget FabData. Données en attente. Touchez pour ouvrir FabData.")
                return views
            }

            val weatherNow = formatTemp(snapshot.weatherNow)
            val weatherPlus1 = formatTemp(snapshot.weatherPlus1)
            val inertiaNow = formatTemp(snapshot.inertiaNow)
            val inertiaPlus1 = formatTemp(snapshot.inertiaPlus1)
            val inertiaPlus2 = formatTemp(snapshot.inertiaPlus2)

            views.setTextViewText(R.id.widget_reference, snapshot.referenceLabel)
            views.setTextViewText(
                R.id.widget_weather_values,
                "Maintenant  $weatherNow        +1 h  $weatherPlus1"
            )
            views.setTextViewText(
                R.id.widget_compact_values,
                "Météo 12 h · maintenant $weatherNow · +1 h $weatherPlus1"
            )
            views.setTextViewText(
                R.id.widget_inertia_values,
                "Sol inertiel   $inertiaNow     +1 h $inertiaPlus1     +2 h $inertiaPlus2"
            )
            views.setTextViewText(
                R.id.widget_adaptive_caption,
                if (snapshot.adaptive.isEmpty()) "Fab adaptative H+1 → H+48 · en attente"
                else "Fab adaptative H+1 → H+48"
            )
            views.setImageViewBitmap(
                R.id.widget_weather_curve,
                weatherBitmap(snapshot.weather, 720, 180)
            )
            views.setImageViewBitmap(
                R.id.widget_adaptive_curve,
                adaptiveBitmap(snapshot.adaptive, 720, 130)
            )
            views.setContentDescription(
                R.id.widget_root,
                "FabData ${snapshot.referenceLabel}. Météo maintenant $weatherNow, dans une heure $weatherPlus1. " +
                    "Sol inertiel maintenant $inertiaNow, dans une heure $inertiaPlus1, dans deux heures $inertiaPlus2. " +
                    "Prévision météo visible sur douze heures et Fab adaptative de H plus 1 à H plus 48. " +
                    "Double-tapez le widget pour le replier ou le déplier; touchez le titre pour ouvrir FabData."
            )
            return views
        }

        private fun loadSnapshot(context: Context): WidgetSnapshot {
            val db = FabDataDb(context)
            val reference = WeatherReferencePrefs(context).selectedReference()
            val now = System.currentTimeMillis()
            val weather = readWeatherCurve(db, reference.key, now)
            val weatherNow = nearest(weather, now, 45L * WIDGET_MINUTE_MS)
            val weatherPlus1 = nearest(weather, now + WIDGET_HOUR_MS, 45L * WIDGET_MINUTE_MS)
            val inertia = readInertia(context, db, reference, now)
            val adaptive = readAdaptive(db, reference.key, now)
            return WidgetSnapshot(
                referenceLabel = reference.label,
                weather = weather,
                weatherNow = weatherNow,
                weatherPlus1 = weatherPlus1,
                inertiaNow = inertia.getOrNull(0),
                inertiaPlus1 = inertia.getOrNull(1),
                inertiaPlus2 = inertia.getOrNull(2),
                adaptive = adaptive
            )
        }

        private fun readWeatherCurve(db: FabDataDb, referenceKey: String, now: Long): List<WidgetCurvePoint> {
            // Keep one hour of context, then show the next twelve forecast hours.
            val from = now - 1L * WIDGET_HOUR_MS
            val to = now + 12L * WIDGET_HOUR_MS
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
                    val temperature = c.getDouble(1)
                    if (temperature.isFinite()) byTimestamp[ts] = temperature
                }
            }
            return byTimestamp.entries
                .map { WidgetCurvePoint(it.key, it.value) }
                .sortedBy { it.timestamp }
        }

        private fun nearest(points: List<WidgetCurvePoint>, target: Long, tolerance: Long): Double? =
            points.minByOrNull { abs(it.timestamp - target) }
                ?.takeIf { abs(it.timestamp - target) <= tolerance }
                ?.temperature

        private fun readInertia(
            context: Context,
            db: FabDataDb,
            reference: WeatherReference,
            now: Long
        ): List<Double?> {
            val model = ThermalTrainedModelStore(context).loadUsable(reference.key)
                ?: return listOf(null, null, null)
            val estimate = runCatching {
                ThermalInertiaEstimator(db, WeatherReferenceStore(db)).projectTrained(reference, model)
            }.getOrNull() ?: return listOf(null, null, null)
            val points = estimate.surfacePoints.takeLast(4)
            val last = points.lastOrNull() ?: return listOf(null, null, null)
            val previous = points.dropLast(1).lastOrNull()
            val ageHours = ((now - last.timestamp).coerceAtLeast(0L)).toDouble() / WIDGET_HOUR_MS.toDouble()
            if (ageHours > 6.0) return listOf(null, null, null)
            val slope = if (previous != null && last.timestamp > previous.timestamp) {
                ((last.temperature - previous.temperature) /
                    ((last.timestamp - previous.timestamp).toDouble() / WIDGET_HOUR_MS.toDouble()))
                    .coerceIn(-0.60, 0.60)
            } else 0.0
            val present = last.temperature + slope * ageHours
            return listOf(present, present + slope, present + 2.0 * slope)
                .map { it.takeIf(Double::isFinite) }
        }

        private fun readAdaptive(db: FabDataDb, referenceKey: String, now: Long): List<WidgetAdaptivePoint> {
            ForecastAdaptiveStore.ensure(db.readableDatabase)
            val nowHour = (now / WIDGET_HOUR_MS) * WIDGET_HOUR_MS
            return FORECAST_ADAPTIVE_HORIZONS.mapNotNull { horizon ->
                val target = nowHour + horizon.toLong() * WIDGET_HOUR_MS
                val tolerance = 45L * WIDGET_MINUTE_MS
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
                        if (value.isFinite()) WidgetAdaptivePoint(horizon, value) else null
                    } else null
                }
            }
        }

        private fun weatherBitmap(points: List<WidgetCurvePoint>, width: Int, height: Int): Bitmap {
            val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            if (points.size < 2) return bitmap

            val padX = 20f
            val padY = 16f
            val minTs = points.first().timestamp
            val maxTs = points.last().timestamp.coerceAtLeast(minTs + 1L)
            val minT = points.minOf { it.temperature }
            val maxT = points.maxOf { it.temperature }
            val range = (maxT - minT).takeIf { it > 0.05 } ?: 1.0
            fun x(ts: Long): Float = padX + ((ts - minTs).toDouble() / (maxTs - minTs).toDouble()).toFloat() * (width - 2f * padX)
            fun y(t: Double): Float = height - padY - ((t - minT) / range).toFloat() * (height - 2f * padY)

            paint.style = Paint.Style.STROKE
            paint.strokeWidth = 7f
            paint.strokeCap = Paint.Cap.ROUND
            points.zipWithNext().forEach { (a, b) ->
                paint.color = temperatureColor((a.temperature + b.temperature) / 2.0)
                canvas.drawLine(x(a.timestamp), y(a.temperature), x(b.timestamp), y(b.temperature), paint)
            }
            return bitmap
        }

        private fun adaptiveBitmap(points: List<WidgetAdaptivePoint>, width: Int, height: Int): Bitmap {
            val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            if (points.isEmpty()) return bitmap

            val sorted = points.sortedBy { it.horizonHour }
            val minH = 1
            val maxH = 48
            val minT = sorted.minOf { it.temperature }
            val maxT = sorted.maxOf { it.temperature }
            val range = (maxT - minT).takeIf { it > 0.05 } ?: 1.0
            val padX = 22f
            val padTop = 10f
            val padBottom = 26f
            fun x(h: Int): Float = padX + ((h - minH).toFloat() / (maxH - minH).toFloat()) * (width - 2f * padX)
            fun y(t: Double): Float = height - padBottom - ((t - minT) / range).toFloat() * (height - padTop - padBottom)

            if (sorted.size >= 2) {
                val path = Path()
                sorted.forEachIndexed { index, p ->
                    if (index == 0) path.moveTo(x(p.horizonHour), y(p.temperature))
                    else path.lineTo(x(p.horizonHour), y(p.temperature))
                }
                paint.style = Paint.Style.STROKE
                paint.strokeWidth = 6f
                paint.strokeCap = Paint.Cap.ROUND
                paint.strokeJoin = Paint.Join.ROUND
                paint.color = Color.rgb(246, 191, 58)
                canvas.drawPath(path, paint)
            }

            paint.style = Paint.Style.FILL
            paint.color = Color.rgb(246, 191, 58)
            sorted.forEach { p -> canvas.drawCircle(x(p.horizonHour), y(p.temperature), 7f, paint) }

            paint.textSize = 20f
            paint.color = Color.argb(210, 230, 230, 230)
            paint.textAlign = Paint.Align.CENTER
            listOf(1, 12, 24, 48).forEach { h ->
                canvas.drawText("H+$h", x(h), height - 3f, paint)
            }
            return bitmap
        }

        private fun emptyChart(width: Int, height: Int): Bitmap =
            Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)

        private fun formatTemp(value: Double?): String =
            value?.takeIf { it.isFinite() }?.let { String.format(java.util.Locale.FRANCE, "%.1f°", it) } ?: "—"

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
            fun c(v1: Int, v2: Int): Int = (v1 + (v2 - v1) * x).toInt().coerceIn(0, 255)
            return Color.rgb(
                c(Color.red(a), Color.red(b)),
                c(Color.green(a), Color.green(b)),
                c(Color.blue(a), Color.blue(b))
            )
        }
    }
}
