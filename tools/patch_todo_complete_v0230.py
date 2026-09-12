from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel, text):
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 occurrence, got {count}")
    return text.replace(old, new, 1)


def replace_section(text, start, end, new_body, label):
    i = text.find(start)
    if i < 0:
        raise RuntimeError(f"{label}: start marker not found")
    j = text.find(end, i + len(start))
    if j < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:i] + new_body + text[j:]


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
build = read("app/build.gradle.kts")
build = replace_once(build, 'versionCode = 56\n        versionName = "0.22.0"',
                     'versionCode = 57\n        versionName = "0.23.0"', "version")
write("app/build.gradle.kts", build)


# ---------------------------------------------------------------------------
# Adaptive engine small compile/clarity cleanup
# ---------------------------------------------------------------------------
adaptive_path = "app/src/main/java/com/fabdata/app/ForecastAdaptive.kt"
adaptive = read(adaptive_path)
adaptive = adaptive.replace("import kotlin.math.min\n", "")
adaptive = adaptive.replace("import kotlin.math.sqrt\n", "")
adaptive = replace_once(
    adaptive,
    """        fun atOrBefore(target: Long, tolerance: Long): AdaptiveTerrainPoint? =
            terrain.asSequence()
                .filter { it.timestamp <= target && target - it.timestamp <= tolerance }
                .maxWithOrNull(compareBy<AdaptiveTerrainPoint> { it.timestamp }.thenBy { it.measured })
""",
    """        fun atOrBefore(target: Long, tolerance: Long): AdaptiveTerrainPoint? =
            terrain.asSequence()
                .filter { it.timestamp <= target && target - it.timestamp <= tolerance }
                .sortedWith(
                    compareBy<AdaptiveTerrainPoint> { it.timestamp }
                        .thenBy { if (it.measured) 1 else 0 }
                )
                .lastOrNull()
""",
    "adaptive terrain ordering"
)
write(adaptive_path, adaptive)


# ---------------------------------------------------------------------------
# Main UI integration: adaptive curves + validation + provenance panel
# ---------------------------------------------------------------------------
main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)

main = replace_once(
    main,
    """            FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
                put(forecastHorizonSensorId(lead), curveStyleStore.load("forecast:weather:h$lead"))
            }
            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))
""",
    """            FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
                put(forecastHorizonSensorId(lead), curveStyleStore.load("forecast:weather:h$lead"))
            }
            FORECAST_ADAPTIVE_HORIZONS.forEach { lead ->
                put(forecastAdaptiveSensorId(lead), curveStyleStore.load("forecast:fab:adaptive:h$lead"))
            }
            put(THERMAL_INERTIA_SENSOR_ID, curveStyleStore.load("thermal:inertia"))
""",
    "adaptive curve styles"
)

main = replace_once(
    main,
    """        FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
            val id = forecastHorizonSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = false
            showHumidity[id] = false
        }
        showHumidity[FORECAST_RECONSTRUCTED_SENSOR_ID] = false
""",
    """        FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->
            val id = forecastHorizonSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = false
            showHumidity[id] = false
        }
        FORECAST_ADAPTIVE_HORIZONS.forEach { lead ->
            val id = forecastAdaptiveSensorId(lead)
            if (!showTemp.containsKey(id)) showTemp[id] = false
            showHumidity[id] = false
        }
        showHumidity[FORECAST_RECONSTRUCTED_SENSOR_ID] = false
""",
    "adaptive defaults"
)

main = replace_once(
    main,
    """    val forecastActiveSamples = forecastHorizonCurves.activeWeather
    val forecastHorizonSamples = forecastHorizonCurves.weatherByLead.filterKeys { it < 24 }
    val weatherOfficialSamples = lyonReconstructedSamples
""",
    """    val forecastActiveSamples = forecastHorizonCurves.activeWeather
    val forecastHorizonSamples = forecastHorizonCurves.weatherByLead.filterKeys { it < 24 }
    var adaptiveForecastCurves by remember(visualReference.key) { mutableStateOf(ForecastAdaptiveCurveSet.EMPTY) }
    LaunchedEffect(reloadToken, visualReference.key, globalBounds?.first, globalBounds?.last) {
        val history = globalBounds
        adaptiveForecastCurves = if (history == null) {
            ForecastAdaptiveCurveSet.EMPTY
        } else {
            val now = System.currentTimeMillis()
            withContext(Dispatchers.IO) {
                ForecastAdaptiveEngine(db).queryCurves(
                    visualReference.key,
                    history.first,
                    maxOf(history.last, now + 25L * 60L * 60L * 1000L),
                    now
                )
            }
        }
    }
    val adaptiveForecastSamples = adaptiveForecastCurves.byLead
    val weatherOfficialSamples = lyonReconstructedSamples
""",
    "adaptive curve loading"
)

main = replace_once(
    main,
    """    val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo H+24", "H+24 fixe · archive locale, backfill si disponible · rendu 10 min", 12, forecastReconstructedSamples.lastOrNull()?.timestamp)
    val forecastFabSensor = Sensor(FORECAST_FAB_SENSOR_ID, FORECAST_FAB_STABLE_KEY, "Prévision Fab H+24", "Correction locale H+24 · rendu 10 min", 11, forecastFabSamples.lastOrNull()?.timestamp)
    val forecastHorizonSampleMap = forecastHorizonSamples.mapKeys { (lead, _) -> forecastHorizonSensorId(lead) }
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + lyonReconstructedSensor + forecastActiveSensor + forecastHorizonSensors + forecastReconstructedSensor + forecastFabSensor + inertiaSensor
""",
    """    val forecastReconstructedSensor = Sensor(FORECAST_RECONSTRUCTED_SENSOR_ID, FORECAST_RECONSTRUCTED_STABLE_KEY, "Prévision météo H+24", "H+24 fixe · archive locale, backfill si disponible · rendu 10 min", 12, forecastReconstructedSamples.lastOrNull()?.timestamp)
    val forecastFabSensor = Sensor(FORECAST_FAB_SENSOR_ID, FORECAST_FAB_STABLE_KEY, "Prévision Fab H+24", "Correction locale H+24 · rendu 10 min", 11, forecastFabSamples.lastOrNull()?.timestamp)
    val adaptiveForecastSensors = FORECAST_ADAPTIVE_HORIZONS.mapIndexed { index, lead ->
        val points = adaptiveForecastSamples[lead].orEmpty()
        Sensor(
            forecastAdaptiveSensorId(lead), forecastAdaptiveStableKey(lead),
            "Prévision Fab adaptative H+$lead",
            "Tangente + changement de régime · archive causale H+$lead",
            listOf(10, 5, 13, 8)[index], points.lastOrNull()?.timestamp
        )
    }
    val forecastHorizonSampleMap = forecastHorizonSamples.mapKeys { (lead, _) -> forecastHorizonSensorId(lead) }
    val adaptiveForecastSampleMap = adaptiveForecastSamples.mapKeys { (lead, _) -> forecastAdaptiveSensorId(lead) }
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + lyonReconstructedSensor + forecastActiveSensor + forecastHorizonSensors + adaptiveForecastSensors + forecastReconstructedSensor + forecastFabSensor + inertiaSensor
""",
    "adaptive sensors"
)

main = replace_once(
    main,
    """        (FORECAST_ACTIVE_SENSOR_ID to forecastActiveSamples) +
        forecastHorizonSampleMap +
        (FORECAST_RECONSTRUCTED_SENSOR_ID to forecastReconstructedSamples) +
""",
    """        (FORECAST_ACTIVE_SENSOR_ID to forecastActiveSamples) +
        forecastHorizonSampleMap +
        adaptiveForecastSampleMap +
        (FORECAST_RECONSTRUCTED_SENSOR_ID to forecastReconstructedSamples) +
""",
    "adaptive sample map"
)

main = replace_once(
    main,
    """        val horizonLod = forecastHorizonSamples.mapKeys { (lead, _) -> forecastHorizonSensorId(lead) }
            .mapValues { (_, points) -> predictionLod(points, bucketMs) }
        return source.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
            (LYON_RECONSTRUCTED_SENSOR_ID to terrain) +
            (FORECAST_ACTIVE_SENSOR_ID to predictionLod(forecastActiveSamples, bucketMs)) +
            horizonLod +
            (FORECAST_RECONSTRUCTED_SENSOR_ID to predictionLod(forecastReconstructedSamples, bucketMs)) +
""",
    """        val horizonLod = forecastHorizonSamples.mapKeys { (lead, _) -> forecastHorizonSensorId(lead) }
            .mapValues { (_, points) -> predictionLod(points, bucketMs) }
        val adaptiveLod = adaptiveForecastSamples.mapKeys { (lead, _) -> forecastAdaptiveSensorId(lead) }
            .mapValues { (_, points) -> predictionLod(points, bucketMs) }
        return source.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
            (LYON_RECONSTRUCTED_SENSOR_ID to terrain) +
            (FORECAST_ACTIVE_SENSOR_ID to predictionLod(forecastActiveSamples, bucketMs)) +
            horizonLod +
            adaptiveLod +
            (FORECAST_RECONSTRUCTED_SENSOR_ID to predictionLod(forecastReconstructedSamples, bucketMs)) +
""",
    "adaptive LOD"
)

main = replace_once(
    main,
    """                item {
                    ForecastReplayCard(
                        db = db,
                        reference = visualReference,
                        refreshToken = reloadToken
                    )
                }

                item {
                    TimeTabs(preset = preset, onSelect = {
""",
    """                item {
                    ForecastReplayCard(
                        db = db,
                        reference = visualReference,
                        refreshToken = reloadToken
                    )
                }

                item {
                    ForecastAdaptiveCard(
                        db = db,
                        reference = visualReference,
                        refreshToken = reloadToken
                    )
                }

                item {
                    TimeTabs(preset = preset, onSelect = {
""",
    "adaptive validation card"
)

main = replace_once(
    main,
    """                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"
                                else -> forecastHorizonLeadForSensorId(sensor.id)
                                    ?.let { "forecast:weather:h$it" }
                                    ?: "sensor:${sensor.stableKey}"
""",
    """                                THERMAL_INERTIA_SENSOR_ID -> "thermal:inertia"
                                else -> forecastAdaptiveLeadForSensorId(sensor.id)
                                    ?.let { "forecast:fab:adaptive:h$it" }
                                    ?: forecastHorizonLeadForSensorId(sensor.id)
                                        ?.let { "forecast:weather:h$it" }
                                    ?: "sensor:${sensor.stableKey}"
""",
    "adaptive style editor"
)

main = replace_once(
    main,
    """                item {
                    ThermalReferenceCard(
                        db = db,
                        lyonLab = lyonLab,
""",
    """                item {
                    ThermalLearningReferenceStatusCard(
                        db = db,
                        reference = visualReference,
                        refreshToken = reloadToken
                    )
                }

                item {
                    ThermalReferenceCard(
                        db = db,
                        lyonLab = lyonLab,
""",
    "thermal learning reference card"
)

main = replace_once(
    main,
    """                val availableBandSensorIds = remember(sensors, gigaSampleMap, navigatorSampleMap, sampleMap) {
                    sensors.filter { sensor ->
                        forecastHorizonLeadForSensorId(sensor.id) == null && (
""",
    """                val availableBandSensorIds = remember(sensors, gigaSampleMap, navigatorSampleMap, sampleMap) {
                    sensors.filter { sensor ->
                        forecastHorizonLeadForSensorId(sensor.id) == null &&
                            forecastAdaptiveLeadForSensorId(sensor.id) == null && (
""",
    "hide adaptive curves from overview selector"
)

main = replace_once(
    main,
    """            @Composable
            fun SensorRow(sensor: Sensor) {
                val lead = forecastHorizonLeadForSensorId(sensor.id)
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
""",
    """            @Composable
            fun SensorRow(sensor: Sensor) {
                val lead = forecastHorizonLeadForSensorId(sensor.id)
                val adaptiveLead = forecastAdaptiveLeadForSensorId(sensor.id)
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
""",
    "adaptive sensor selector row"
)

main = replace_once(
    main,
    """                            THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"
                            else -> lead?.let { "Prévision météo H+$it" } ?: sensor.room
""",
    """                            THERMAL_INERTIA_SENSOR_ID -> "Sol inertiel estimé · expérimental"
                            else -> adaptiveLead?.let { "Prévision Fab adaptative H+$it" }
                                ?: lead?.let { "Prévision météo H+$it" }
                                ?: sensor.room
""",
    "adaptive selector label"
)

main = replace_once(
    main,
    """                        } else if (lead != null) {
                            Text(
                                "Archive locale fixe H+$lead · conservée avant remplacement",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        } else if (sensor.name != sensor.room && sensor.id != THERMAL_INERTIA_SENSOR_ID) {
""",
    """                        } else if (adaptiveLead != null) {
                            Text(
                                "Modèle adaptatif causal H+$adaptiveLead · tangente + régime",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        } else if (lead != null) {
                            Text(
                                "Archive locale fixe H+$lead · conservée avant remplacement",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        } else if (sensor.name != sensor.room && sensor.id != THERMAL_INERTIA_SENSOR_ID) {
""",
    "adaptive selector subtitle"
)

main = replace_once(
    main,
    """                        sensor.id != FORECAST_FAB_SENSOR_ID &&
                        !isForecastArchiveSensorId(sensor.id)
""",
    """                        sensor.id != FORECAST_FAB_SENSOR_ID &&
                        !isForecastArchiveSensorId(sensor.id) &&
                        !isAdaptiveForecastSensorId(sensor.id)
""",
    "adaptive humidity hidden"
)

write(main_path, main)


# ---------------------------------------------------------------------------
# Dial compact mode: persistent double-tap collapse using PRESENT identity
# ---------------------------------------------------------------------------
dial_path = "app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt"
dial = read(dial_path)

dial = replace_once(
    dial,
    """        private const val KEY_WIDTH_DP = "width_dp"
        private const val KEY_HEIGHT_DP = "height_dp"
""",
    """        private const val KEY_WIDTH_DP = "width_dp"
        private const val KEY_HEIGHT_DP = "height_dp"
        private const val KEY_COMPACT = "compact"
        private const val COMPACT_WIDTH_DP = 76f
        private const val COMPACT_HEIGHT_DP = 46f
""",
    "dial compact constants"
)

dial = replace_once(
    dial,
    """    private var startWidth = 0
    private var startHeight = 0
""",
    """    private var startWidth = 0
    private var startHeight = 0
    private var compact = false
    private var downRawX = 0f
    private var downRawY = 0f
    private var moved = false
    private var lastTapUp = 0L
""",
    "dial compact state"
)

restore_block = """    fun restorePosition(root: ViewGroup) {
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
            updateAccessibility(state)
        }
    }

"""
dial = replace_section(dial, "    fun restorePosition(root: ViewGroup) {", "    override fun onTouchEvent(event: MotionEvent): Boolean {", restore_block, "dial restore")

touch_block = """    override fun onTouchEvent(event: MotionEvent): Boolean {
        val parentView = parent as? ViewGroup ?: return true
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastRawX = event.rawX
                lastRawY = event.rawY
                downRawX = event.rawX
                downRawY = event.rawY
                moved = false
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
                    if (lastTapUp > 0L && now - lastTapUp <= 340L) {
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

"""
dial = replace_section(dial, "    override fun onTouchEvent(event: MotionEvent): Boolean {", "    override fun performClick(): Boolean {", touch_block, "dial touch")

persist_block = """    private fun toggleCompact(root: ViewGroup) {
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
            updateAccessibility(state)
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

"""
dial = replace_section(dial, "    private fun persistGeometry(root: ViewGroup) {", "    override fun onDraw(canvas: Canvas) {", persist_block, "dial persistence")

draw_block = """    override fun onDraw(canvas: Canvas) {
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

"""
dial = replace_section(dial, "    override fun onDraw(canvas: Canvas) {", "    private fun drawResizeHandle(canvas: Canvas, night: Boolean) {", draw_block, "dial drawing")

# Accessibility now explains the persistent compact interaction.
dial = replace_once(
    dial,
    """        contentDescription = buildString {
            append("Cadrans tangentiels ${state.referenceLabel}. ")
            state.samples.forEach { s ->
""",
    """        contentDescription = buildString {
            append("Cadrans tangentiels ${state.referenceLabel}. ")
            append(if (compact) "Mode compact. Double-tape pour ouvrir les cadrans. " else "Mode complet. Double-tape le cadre pour réduire les cadrans. ")
            state.samples.forEach { s ->
""",
    "dial accessibility"
)
write(dial_path, dial)


# ---------------------------------------------------------------------------
# Backup/restore: adaptive forecasts are frozen artefacts and must round-trip
# ---------------------------------------------------------------------------
backup_path = "app/src/main/java/com/fabdata/app/BackupV3Support.kt"
backup = read(backup_path)
backup = replace_once(
    backup,
    """        ForecastPastArchiveStore.ensure(db.writableDatabase)
        ForecastCurve10mStore.ensure(db.writableDatabase)

        writeJson(writer, "WEATHER_META", weatherMetaJson())
""",
    """        ForecastPastArchiveStore.ensure(db.writableDatabase)
        ForecastCurve10mStore.ensure(db.writableDatabase)
        ForecastAdaptiveStore.ensure(db.writableDatabase)

        writeJson(writer, "WEATHER_META", weatherMetaJson())
""",
    "backup adaptive ensure"
)

backup = replace_once(
    backup,
    """        db.readableDatabase.rawQuery(
            """
            SELECT reference_key, timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
""",
    """        db.readableDatabase.rawQuery(
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

        db.readableDatabase.rawQuery(
            """
            SELECT reference_key, timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
""",
    "backup adaptive rows"
)

backup = replace_once(
    backup,
    """                "FORECAST_CURVE_10M_ARCHIVE" -> restoreForecastCurve10mArchive(json(values))
                "WEATHER" -> restoreWeather(values)
""",
    """                "FORECAST_CURVE_10M_ARCHIVE" -> restoreForecastCurve10mArchive(json(values))
                "FORECAST_ADAPTIVE_ARCHIVE" -> restoreForecastAdaptiveArchive(json(values))
                "WEATHER" -> restoreWeather(values)
""",
    "backup adaptive import case"
)

backup = replace_once(
    backup,
    """    private fun restoreWeather(values: Map<String, String>) {
""",
    """    private fun restoreForecastAdaptiveArchive(o: JSONObject) {
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

    private fun restoreWeather(values: Map<String, String>) {
""",
    "backup adaptive restore helper"
)
write(backup_path, backup)


# ---------------------------------------------------------------------------
# TODO: keep it as an auditable checklist, now completed in v0.23.0
# ---------------------------------------------------------------------------
todo_path = "TODO.md"
todo = read(todo_path)
todo = todo.replace("- [ ] **Mieux afficher la référence météo liée aux modèles d’apprentissage.**",
                    "- [x] **Mieux afficher la référence météo liée aux modèles d’apprentissage.**")
todo = todo.replace("- [ ] **Permettre de réduire les cadrans en un petit paquet de points circulaires.**",
                    "- [x] **Permettre de réduire les cadrans en un petit paquet de points circulaires.**")
todo = todo.replace("- [ ] **Construire une prévision Fab adaptative à quatre horizons fixes : H+3, H+6, H+12 et H+24.**",
                    "- [x] **Construire une prévision Fab adaptative à quatre horizons fixes : H+3, H+6, H+12 et H+24.**")
todo = todo.replace(
    "- **Prévision météo H+24** = prévision Météo-France à échéance fixe H+24.",
    "- **Prévision météo H+24** = courbe météo fixe H+24 archivée, distincte de la prévision active/glissante."
)
if "## Livraison v0.23.0" not in todo:
    todo += """

## Livraison v0.23.0

- [x] Les trois blocs ci-dessus sont implémentés sans modifier la sémantique des cadrans H+24 existants.
- [x] Les prévisions adaptatives restent une couche informative séparée : aucune écriture dans la Référence terrain ni dans les modèles thermiques.
- [x] Les sorties adaptatives émises sont archivées et incluses dans la sauvegarde/restauration FabData.
"""
write(todo_path, todo)

print("v0.23.0 TODO completion patch applied")
