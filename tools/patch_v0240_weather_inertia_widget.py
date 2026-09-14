from pathlib import Path

OVERLAY = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")
GRADLE = Path("app/build.gradle.kts")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


text = OVERLAY.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 1) Add read-only dashboard data beside the existing tangent cockpit state.
#    This must NEVER trigger a provider call or modify deterministic weather capture.
# ---------------------------------------------------------------------------
text = replace_once(
    text,
    '''private data class DialState(\n    val referenceLabel: String,\n    val weatherHorizon: Int,\n    val adaptiveHorizon: Int,\n    val samples: List<DialSample>\n)\n''',
    '''private data class DashboardCurvePoint(\n    val timestamp: Long,\n    val temperature: Double\n)\n\nprivate data class DashboardAdaptivePoint(\n    val horizonHour: Int,\n    val temperature: Double\n)\n\nprivate data class DialState(\n    val referenceLabel: String,\n    val weatherHorizon: Int,\n    val adaptiveHorizon: Int,\n    val samples: List<DialSample>,\n    val weatherCurve: List<DashboardCurvePoint> = emptyList(),\n    val weatherNow: Double? = null,\n    val weatherPlus1: Double? = null,\n    val inertiaNow: Double? = null,\n    val inertiaPlus1: Double? = null,\n    val inertiaPlus2: Double? = null,\n    val adaptiveCurve: List<DashboardAdaptivePoint> = emptyList()\n)\n''',
    "dashboard state",
)

text = replace_once(
    text,
    '''        val result = targets.map { (label, target) ->\n            buildDial(reference.key, label, target, weatherHorizon, adaptiveHorizon)\n        }\n        return DialState(reference.label, weatherHorizon, adaptiveHorizon, result)\n    }\n\n    private fun buildDial(\n''',
    '''        val result = targets.map { (label, target) ->\n            buildDial(reference.key, label, target, weatherHorizon, adaptiveHorizon)\n        }\n\n        // Dashboard is a pure reader. It reuses rows already present in SQLite and never\n        // invokes weatherReferenceManager, refreshRecent, a provider, or a capture slot.\n        val weatherCurve = dashboardWeatherCurve(reference.key, now)\n        val weatherNow = nearestDashboardTemperature(weatherCurve, now, 40L * 60L * 1000L)\n        val weatherPlus1 = nearestDashboardTemperature(weatherCurve, now + HOUR_MS, 40L * 60L * 1000L)\n        val inertia = dashboardInertia(reference, now)\n        val adaptiveCurve = FORECAST_ADAPTIVE_HORIZONS.mapNotNull { horizon ->\n            val target = hourBucket(now) + horizon.toLong() * HOUR_MS\n            adaptiveAt(reference.key, horizon, target)?.let {\n                DashboardAdaptivePoint(horizon, it)\n            }\n        }\n        return DialState(\n            reference.label, weatherHorizon, adaptiveHorizon, result,\n            weatherCurve = weatherCurve,\n            weatherNow = weatherNow,\n            weatherPlus1 = weatherPlus1,\n            inertiaNow = inertia.getOrNull(0),\n            inertiaPlus1 = inertia.getOrNull(1),\n            inertiaPlus2 = inertia.getOrNull(2),\n            adaptiveCurve = adaptiveCurve\n        )\n    }\n\n    private fun dashboardWeatherCurve(referenceKey: String, now: Long): List<DashboardCurvePoint> {\n        val from = now - HOUR_MS\n        val to = now + 2L * HOUR_MS\n        val byTimestamp = linkedMapOf<Long, Double>()\n        // Ordering intentionally makes MEASURED win over reconstructed, which wins over forecast\n        // if two sources share a timestamp. Future timestamps naturally keep the forecast row.\n        db.readableDatabase.rawQuery(\n            \"\"\"\n            SELECT timestamp, temperature, source\n            FROM weather_reference_samples\n            WHERE reference_key=? AND timestamp BETWEEN ? AND ?\n            ORDER BY timestamp,\n                     CASE source WHEN 'forecast' THEN 0 WHEN 'reconstructed' THEN 1 WHEN 'measured' THEN 2 ELSE 0 END\n            \"\"\".trimIndent(),\n            arrayOf(referenceKey, from.toString(), to.toString())\n        ).use { c ->\n            while (c.moveToNext()) {\n                val ts = c.getLong(0)\n                val temperature = c.getDouble(1)\n                if (temperature.isFinite()) byTimestamp[ts] = temperature\n            }\n        }\n        return byTimestamp.map { DashboardCurvePoint(it.key, it.value) }.sortedBy { it.timestamp }\n    }\n\n    private fun nearestDashboardTemperature(\n        points: List<DashboardCurvePoint>,\n        target: Long,\n        tolerance: Long\n    ): Double? = points.minByOrNull { abs(it.timestamp - target) }\n        ?.takeIf { abs(it.timestamp - target) <= tolerance }\n        ?.temperature\n\n    private fun dashboardInertia(reference: WeatherReference, now: Long): List<Double?> {\n        val model = ThermalTrainedModelStore(appContext).loadUsable(reference.key) ?: return listOf(null, null, null)\n        val estimate = runCatching {\n            ThermalInertiaEstimator(db, WeatherReferenceStore(db)).projectTrained(reference, model)\n        }.getOrNull() ?: return listOf(null, null, null)\n        val surface = estimate.surfacePoints.takeLast(4)\n        val last = surface.lastOrNull() ?: return listOf(null, null, null)\n        val previous = surface.dropLast(1).lastOrNull()\n        val slopePerHour = if (previous != null && last.timestamp > previous.timestamp) {\n            ((last.temperature - previous.temperature) /\n                ((last.timestamp - previous.timestamp).toDouble() / HOUR_MS.toDouble()))\n                .coerceIn(-0.60, 0.60)\n        } else 0.0\n        val ageHours = ((now - last.timestamp).coerceAtLeast(0L)).toDouble() / HOUR_MS.toDouble()\n        if (ageHours > 6.0) return listOf(null, null, null)\n        val present = last.temperature + slopePerHour * ageHours\n        return listOf(\n            present,\n            present + slopePerHour,\n            present + 2.0 * slopePerHour\n        ).map { it.takeIf(Double::isFinite) }\n    }\n\n    private fun buildDial(\n''',
    "dashboard loading",
)

# ---------------------------------------------------------------------------
# 2) Give the expanded cockpit enough room for two elegant stacked cards.
# ---------------------------------------------------------------------------
text = text.replace('val expandedMinWidth = dp(270f).toInt()', 'val expandedMinWidth = dp(300f).toInt()')
text = text.replace('val expandedMinHeight = dp(130f).toInt()', 'val expandedMinHeight = dp(220f).toInt()')
text = text.replace('prefs.getFloat(KEY_HEIGHT_DP, 154f)', 'prefs.getFloat(KEY_HEIGHT_DP, 248f)')
text = text.replace('val minWidth = dp(270f).toInt()', 'val minWidth = dp(300f).toInt()')
text = text.replace('val minHeight = dp(130f).toInt()', 'val minHeight = dp(220f).toInt()')

# ---------------------------------------------------------------------------
# 3) Expanded mode becomes a two-card aesthetic dashboard. Compact mode and gestures remain.
# ---------------------------------------------------------------------------
text = replace_once(
    text,
    '''        drawLegend(canvas, night, current)\n        val dials = current?.samples ?: listOf(\n            emptyDial(\"PASSÉ\"), emptyDial(\"PRÉSENT\"), emptyDial(\"FUTUR\")\n        )\n        val top = dp(30f)\n        val availableH = height - top - dp(4f)\n        val slotWidth = width / 3f\n        dials.take(3).forEachIndexed { index, sample ->\n            val cx = slotWidth * (index + 0.5f)\n            val cy = top + availableH * 0.48f\n            val radius = min(slotWidth * 0.41f, availableH * 0.35f)\n            drawDial(canvas, sample, cx, cy, radius, index, night)\n        }\n        drawResizeHandle(canvas, night)\n''',
    '''        drawForecastDashboard(canvas, night, current)\n        drawResizeHandle(canvas, night)\n''',
    "expanded dashboard draw",
)

insert_before = '''    private fun drawCompact(canvas: Canvas, night: Boolean, current: DialState?) {\n'''
if insert_before not in text:
    raise SystemExit("drawCompact marker missing")

dashboard_methods = r'''    private fun drawForecastDashboard(canvas: Canvas, night: Boolean, current: DialState?) {
        val margin = dp(8f)
        val gap = dp(7f)
        val usableH = height - 2f * margin - gap
        val topH = usableH * 0.47f
        val topRect = RectF(margin, margin, width - margin, margin + topH)
        val bottomRect = RectF(margin, topRect.bottom + gap, width - margin, height - margin)
        drawDashboardCard(canvas, topRect, night)
        drawDashboardCard(canvas, bottomRect, night)
        drawWeatherDashboard(canvas, topRect, night, current)
        drawInertiaDashboard(canvas, bottomRect, night, current)
    }

    private fun drawDashboardCard(canvas: Canvas, rect: RectF, night: Boolean) {
        paint.style = Paint.Style.FILL
        paint.color = if (night) Color.rgb(38, 41, 47) else Color.rgb(255, 255, 255)
        canvas.drawRoundRect(rect, dp(13f), dp(13f), paint)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = dp(1f)
        paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, 38)
        canvas.drawRoundRect(rect, dp(13f), dp(13f), paint)
    }

    private fun drawWeatherDashboard(canvas: Canvas, rect: RectF, night: Boolean, current: DialState?) {
        val textColor = if (night) Color.WHITE else Color.rgb(35, 38, 42)
        paint.textAlign = Paint.Align.LEFT
        paint.style = Paint.Style.FILL
        paint.isFakeBoldText = true
        paint.textSize = sp(9.4f)
        paint.color = textColor
        canvas.drawText("MÉTÉO · maintenant → +1 h", rect.left + dp(9f), rect.top + dp(15f), paint)
        paint.isFakeBoldText = false

        val curve = current?.weatherCurve.orEmpty()
        val chartLeft = rect.left + dp(8f)
        val chartRight = rect.right - dp(8f)
        val chartTop = rect.top + dp(27f)
        val chartBottom = rect.bottom - dp(9f)
        if (curve.size >= 2) {
            val minTs = curve.first().timestamp
            val maxTs = curve.last().timestamp.coerceAtLeast(minTs + 1L)
            val minT = curve.minOf { it.temperature }
            val maxT = curve.maxOf { it.temperature }
            val rangeT = (maxT - minT).takeIf { it > 0.05 } ?: 1.0
            fun x(ts: Long): Float = chartLeft + ((ts - minTs).toDouble() / (maxTs - minTs).toDouble()).toFloat() * (chartRight - chartLeft)
            fun y(t: Double): Float = chartBottom - ((t - minT) / rangeT).toFloat() * (chartBottom - chartTop)
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = dp(2.3f)
            paint.strokeCap = Paint.Cap.ROUND
            curve.zipWithNext().forEach { (a, b) ->
                paint.color = withAlpha(temperatureColor((a.temperature + b.temperature) / 2.0), 235)
                canvas.drawLine(x(a.timestamp), y(a.temperature), x(b.timestamp), y(b.temperature), paint)
            }
            paint.strokeCap = Paint.Cap.BUTT
        }

        val nowText = current?.weatherNow?.let { "${oneDec(it)}°" } ?: "—"
        val plusText = current?.weatherPlus1?.let { "${oneDec(it)}°" } ?: "—"
        val pillW = min(dp(178f), rect.width() - dp(24f))
        val pillH = dp(31f)
        val pill = RectF(
            rect.centerX() - pillW / 2f,
            rect.centerY() - pillH / 2f + dp(5f),
            rect.centerX() + pillW / 2f,
            rect.centerY() + pillH / 2f + dp(5f)
        )
        paint.style = Paint.Style.FILL
        paint.color = withAlpha(if (night) Color.rgb(22, 24, 28) else Color.WHITE, 218)
        canvas.drawRoundRect(pill, dp(13f), dp(13f), paint)
        paint.textAlign = Paint.Align.CENTER
        paint.isFakeBoldText = true
        paint.textSize = sp(11.5f)
        paint.color = textColor
        canvas.drawText("$nowText     +1 h $plusText", pill.centerX(), pill.centerY() + dp(4f), paint)
        paint.isFakeBoldText = false
        paint.textAlign = Paint.Align.LEFT
    }

    private fun drawInertiaDashboard(canvas: Canvas, rect: RectF, night: Boolean, current: DialState?) {
        val textColor = if (night) Color.WHITE else Color.rgb(35, 38, 42)
        val secondary = if (night) Color.rgb(205, 210, 218) else Color.rgb(82, 87, 96)
        paint.textAlign = Paint.Align.LEFT
        paint.style = Paint.Style.FILL
        paint.isFakeBoldText = true
        paint.textSize = sp(9.2f)
        paint.color = textColor
        canvas.drawText("INERTIE SOL · FAB ADAPTATIVE H+1 → H+48", rect.left + dp(9f), rect.top + dp(15f), paint)
        paint.isFakeBoldText = false

        val inertiaText = listOf(
            "maint." to current?.inertiaNow,
            "+1 h" to current?.inertiaPlus1,
            "+2 h" to current?.inertiaPlus2
        ).joinToString("   ") { (label, value) -> "$label ${value?.let { oneDec(it) + "°" } ?: "—"}" }
        paint.textAlign = Paint.Align.CENTER
        paint.textSize = sp(9.1f)
        paint.color = secondary
        canvas.drawText(inertiaText, rect.centerX(), rect.top + dp(31f), paint)

        val adaptive = current?.adaptiveCurve.orEmpty().sortedBy { it.horizonHour }
        val chartLeft = rect.left + dp(12f)
        val chartRight = rect.right - dp(12f)
        val chartTop = rect.top + dp(43f)
        val chartBottom = rect.bottom - dp(21f)
        if (adaptive.size >= 2) {
            val minT = adaptive.minOf { it.temperature }
            val maxT = adaptive.maxOf { it.temperature }
            val rangeT = (maxT - minT).takeIf { it > 0.05 } ?: 1.0
            fun x(h: Int): Float = chartLeft + ((h - 1).toFloat() / 47f) * (chartRight - chartLeft)
            fun y(t: Double): Float = chartBottom - ((t - minT) / rangeT).toFloat() * (chartBottom - chartTop)
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = dp(2.0f)
            paint.strokeCap = Paint.Cap.ROUND
            adaptive.zipWithNext().forEach { (a, b) ->
                paint.color = withAlpha(LOCAL_YELLOW, 230)
                canvas.drawLine(x(a.horizonHour), y(a.temperature), x(b.horizonHour), y(b.temperature), paint)
            }
            paint.strokeCap = Paint.Cap.BUTT
            adaptive.forEach { point ->
                paint.style = Paint.Style.FILL
                paint.color = temperatureColor(point.temperature)
                canvas.drawCircle(x(point.horizonHour), y(point.temperature), dp(2.7f), paint)
                paint.textAlign = Paint.Align.CENTER
                paint.textSize = sp(6.8f)
                paint.color = secondary
                canvas.drawText("H${point.horizonHour}", x(point.horizonHour), rect.bottom - dp(7f), paint)
            }
        } else {
            paint.textAlign = Paint.Align.CENTER
            paint.textSize = sp(8f)
            paint.color = secondary
            canvas.drawText("Adaptative en attente de données", rect.centerX(), rect.centerY() + dp(12f), paint)
        }
        paint.textAlign = Paint.Align.LEFT
    }

    private fun temperatureColor(temperature: Double): Int {
        if (!temperature.isFinite()) return Color.rgb(115, 119, 127)
        val normalized = ((temperature + 10.0) / 45.0).coerceIn(0.0, 1.0).toFloat()
        val hue = 220f * (1f - normalized)
        return Color.HSVToColor(floatArrayOf(hue, 0.72f, 0.88f))
    }

'''
text = text.replace(insert_before, dashboard_methods + insert_before, 1)

# Accessibility describes the new expanded dashboard without removing the old gesture contract.
text = replace_once(
    text,
    '''            append(if (compact) "Mode compact. Double-tape pour ouvrir les cadrans. " else "Mode complet. Double-tape le cadre pour réduire les cadrans. ")\n''',
    '''            append(if (compact) "Mode compact. Double-tape pour ouvrir le tableau météo et inertie. " else "Tableau météo et inertie ouvert. Double-tape le cadre pour réduire. ")\n            if (!compact) {\n                state.weatherNow?.let { append("Météo présente ${oneDec(it)} degrés. ") }\n                state.weatherPlus1?.let { append("Dans une heure ${oneDec(it)} degrés. ") }\n                state.inertiaNow?.let { append("Inertie sol présente ${oneDec(it)} degrés. ") }\n                state.inertiaPlus1?.let { append("Inertie sol dans une heure ${oneDec(it)} degrés. ") }\n                state.inertiaPlus2?.let { append("Inertie sol dans deux heures ${oneDec(it)} degrés. ") }\n            }\n''',
    "dashboard accessibility",
)

OVERLAY.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# 4) Production release identity. Same applicationId, no TEST suffix.
# ---------------------------------------------------------------------------
gradle = GRADLE.read_text(encoding="utf-8")
gradle = replace_once(gradle, 'versionCode = 66', 'versionCode = 67', 'versionCode')
gradle = replace_once(gradle, 'versionName = "0.23.9"', 'versionName = "0.24.0"', 'versionName')
GRADLE.write_text(gradle, encoding="utf-8")

print("v0.24.0 weather/inertia dashboard patch applied")
