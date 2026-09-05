from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Missing patch anchor: {label}")
    if text.count(old) != 1:
        raise SystemExit(f"Patch anchor not unique ({text.count(old)}): {label}")
    return text.replace(old, new, 1)


# ---- version ----
gradle_path = ROOT / "app/build.gradle.kts"
gradle = gradle_path.read_text()
gradle = replace_once(gradle, 'versionCode = 32', 'versionCode = 33', 'versionCode')
gradle = replace_once(gradle, 'versionName = "0.17.0"', 'versionName = "0.17.1"', 'versionName')
gradle_path.write_text(gradle)


# ---- foreground-only 5-minute coordinator ----
live_path = ROOT / "app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt"
live_path.write_text('''package com.fabdata.app

import androidx.activity.ComponentActivity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * Orchestrateur toujours composé, indépendant des cartes LazyColumn.
 *
 * - uniquement quand l'app est réellement au premier plan ;
 * - ouverture / retour au focus : rafraîchissement immédiat ;
 * - ensuite toutes les 5 minutes tant que l'utilisateur regarde l'app ;
 * - lorsqu'une vraie mesure intérieure change : météo fraîche -> inertie/reconstruction -> forecast ;
 * - un changement reçu en arrière-plan est seulement mémorisé, aucun calcul n'y est lancé ;
 * - ne modifie jamais directement une mesure MEASURED.
 */
@Composable
fun FabLiveUpdateCoordinator(
    db: FabDataDb,
    lyonLab: LyonLabStore,
    credentials: MeteoFranceCredentialStore,
    dataVersion: Int,
    onDataChanged: () -> Unit
) {
    val context = LocalContext.current
    val activity = context as? ComponentActivity
    val weatherPrefs = remember { WeatherReferencePrefs(context) }
    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val profileStore = remember { ThermalProfileStore(context) }
    val modelPrefs = remember {
        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)
    }
    val lyonWeather = remember { LyonWeatherSync(db) }
    val meteoOfficial = remember { MeteoFranceOfficialClient(context, lyonLab, credentials) }

    var foreground by remember {
        mutableStateOf(activity?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) == true)
    }
    var working by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }
    var pendingMeasuredRefresh by remember { mutableStateOf(false) }

    DisposableEffect(activity) {
        if (activity == null) return@DisposableEffect onDispose { }
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> foreground = true
                Lifecycle.Event.ON_PAUSE, Lifecycle.Event.ON_STOP -> foreground = false
                else -> Unit
            }
        }
        activity.lifecycle.addObserver(observer)
        onDispose { activity.lifecycle.removeObserver(observer) }
    }

    suspend fun updateLive(rebuildFromMeasured: Boolean): Boolean {
        // Garde-fou central : même si un effet UI se déclenche tardivement,
        // rien de météo/thermique ne part lorsque l'app n'est plus regardée.
        if (!foreground || working) return false
        working = true
        return try {
            val reference = weatherPrefs.selectedReference()
            withContext(Dispatchers.IO) {
                // La station système Lyon possède une vraie source d'observation fraîche.
                if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                    if (credentials.hasCredential()) {
                        runCatching { meteoOfficial.syncSixMinute24h() }
                    } else {
                        runCatching { lyonWeather.syncToday() }
                    }
                }

                PointSourceStore.reconcileMeasuredDominance(db)
                manager.refreshRecent(reference)

                val profile = profileStore.load()
                val mode = profileStore.forecastMode()
                val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }

                if (rebuildFromMeasured) {
                    engine.refreshExistingReconstructions(reference, profile, selectedSensorId)
                }
                engine.refreshForecasts(reference, selectedSensorId, profile, mode)
            }
            onDataChanged()
            true
        } finally {
            working = false
        }
    }

    // Une nouvelle vraie mesure déclenche immédiatement le recalcul seulement si l'app
    // est visible. En arrière-plan on pose juste un drapeau, repris au prochain focus.
    LaunchedEffect(dataVersion) {
        val current = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val previous = measuredRevision
        measuredRevision = current
        if (previous != null && current != previous) {
            pendingMeasuredRefresh = true
            if (foreground && updateLive(rebuildFromMeasured = true)) {
                pendingMeasuredRefresh = false
            }
        }
    }

    // Ouverture / retour au premier plan : immédiat. Puis cadence douce de 5 minutes.
    // Le changement de lifecycle annule cet effet dès que l'app repasse derrière.
    LaunchedEffect(foreground) {
        if (!foreground) return@LaunchedEffect

        val rebuildNow = pendingMeasuredRefresh
        if (updateLive(rebuildFromMeasured = rebuildNow) && rebuildNow) {
            pendingMeasuredRefresh = false
        }

        while (true) {
            delay(300_000L)
            if (!foreground) break
            val rebuild = pendingMeasuredRefresh
            if (updateLive(rebuildFromMeasured = rebuild) && rebuild) {
                pendingMeasuredRefresh = false
            }
        }
    }
}
''')


# ---- true 2D crosshair ----
main_path = ROOT / "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = main_path.read_text()

main = replace_once(
    main,
    '''    var zoom by remember(resetKey, from, to) { mutableFloatStateOf(1f) }\n    var center by remember(resetKey, from, to) { mutableFloatStateOf(0.5f) }\n''',
    '''    var zoom by remember(resetKey, from, to) { mutableFloatStateOf(1f) }\n    var center by remember(resetKey, from, to) { mutableFloatStateOf(0.5f) }\n    var sightTemperature by remember(resetKey, from, to) { mutableStateOf<Double?>(null) }\n''',
    'crosshair temperature state'
)

main = replace_once(
    main,
    '''    fun visibleWindow(): LongRange {\n        val fullSpan = (to - from).coerceAtLeast(1L)\n        val visibleFraction = 1f / zoom\n        val startFraction = (center - visibleFraction / 2f).coerceIn(0f, 1f - visibleFraction)\n        val endFraction = startFraction + visibleFraction\n        return (from + (fullSpan * startFraction).toLong())..\n            (from + (fullSpan * endFraction).toLong())\n    }\n\n''',
    '''    fun visibleWindow(): LongRange {\n        val fullSpan = (to - from).coerceAtLeast(1L)\n        val visibleFraction = 1f / zoom\n        val startFraction = (center - visibleFraction / 2f).coerceIn(0f, 1f - visibleFraction)\n        val endFraction = startFraction + visibleFraction\n        return (from + (fullSpan * startFraction).toLong())..\n            (from + (fullSpan * endFraction).toLong())\n    }\n\n    fun visibleTemperatureRange(window: LongRange): Pair<Double, Double> {\n        val values = sensors\n            .filter { showTemp[it.id] == true }\n            .flatMap { sampleMap[it.id].orEmpty() }\n            .filter { it.timestamp in window }\n            .flatMap { p ->\n                if (p.source == PointSource.FORECAST && p.uncertaintyC != null) {\n                    listOf(p.temperature, p.temperature + p.uncertaintyC, p.temperature - p.uncertaintyC)\n                } else listOf(p.temperature)\n            }\n        return paddedRange(values, 15.0, 35.0, -50.0, 80.0)\n    }\n\n''',
    'temperature range helper'
)

old_gesture = '''            .pointerInput(from, to, resetKey, selectedTimestamp) {\n                detectTransformGestures { centroid, pan, zoomChange, _ ->\n                    val window = visibleWindow()\n                    val span = (window.last - window.first).coerceAtLeast(1L)\n                    val leftPx = 52.dp.toPx()\n                    val rightPx = size.width - 44.dp.toPx()\n                    val selectedX = selectedTimestamp\n                        ?.takeIf { it in window }\n                        ?.let { leftPx + ((it - window.first).toDouble() / span.toDouble()).toFloat() * (rightPx - leftPx) }\n                    val grabsSight = selectedX != null &&\n                        kotlin.math.abs(centroid.x - selectedX) <= 30.dp.toPx() &&\n                        zoomChange in 0.97f..1.03f\n\n                    if (grabsSight && centroid.x in leftPx..rightPx) {\n                        val frac = ((centroid.x - leftPx) / (rightPx - leftPx)).coerceIn(0f, 1f)\n                        onSelectTimestamp(window.first + (span * frac).toLong())\n                    } else {\n                        val oldVisible = 1f / zoom\n                        val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)\n                        zoom = newZoom\n                        val visible = 1f / zoom\n                        center = (center - (pan.x / size.width.toFloat()) * oldVisible)\n                            .coerceIn(visible / 2f, 1f - visible / 2f)\n                    }\n                }\n            }\n'''
new_gesture = '''            .pointerInput(from, to, resetKey, selectedTimestamp, sightTemperature) {\n                detectTransformGestures { centroid, pan, zoomChange, _ ->\n                    val window = visibleWindow()\n                    val span = (window.last - window.first).coerceAtLeast(1L)\n                    val leftPx = 52.dp.toPx()\n                    val rightPx = size.width - 44.dp.toPx()\n                    val topPx = 22.dp.toPx()\n                    val bottomPx = size.height - 38.dp.toPx()\n                    val plotHeight = (bottomPx - topPx).coerceAtLeast(1f)\n                    val range = visibleTemperatureRange(window)\n                    val selectedX = selectedTimestamp\n                        ?.takeIf { it in window }\n                        ?.let { leftPx + ((it - window.first).toDouble() / span.toDouble()).toFloat() * (rightPx - leftPx) }\n                    val selectedY = sightTemperature?.let { temp ->\n                        bottomPx - (((temp - range.first) / (range.second - range.first)).toFloat() * plotHeight)\n                    }\n                    val grabsSight = selectedX != null &&\n                        (kotlin.math.abs(centroid.x - selectedX) <= 30.dp.toPx() ||\n                            (selectedY != null && kotlin.math.abs(centroid.y - selectedY) <= 24.dp.toPx())) &&\n                        zoomChange in 0.97f..1.03f\n\n                    if (grabsSight && centroid.x in leftPx..rightPx && centroid.y in topPx..bottomPx) {\n                        val fracX = ((centroid.x - leftPx) / (rightPx - leftPx)).coerceIn(0f, 1f)\n                        onSelectTimestamp(window.first + (span * fracX).toLong())\n                        val fracY = ((bottomPx - centroid.y) / plotHeight).coerceIn(0f, 1f)\n                        sightTemperature = range.first + (range.second - range.first) * fracY.toDouble()\n                    } else {\n                        val oldVisible = 1f / zoom\n                        val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)\n                        zoom = newZoom\n                        val visible = 1f / zoom\n                        center = (center - (pan.x / size.width.toFloat()) * oldVisible)\n                            .coerceIn(visible / 2f, 1f - visible / 2f)\n                    }\n                }\n            }\n'''
main = replace_once(main, old_gesture, new_gesture, '2D drag gesture')

old_tap = '''                            } else {\n                                val frac = ((p.x - left) / (right - left)).coerceIn(0f, 1f)\n                                onSelectTimestamp(window.first + (span * frac).toLong())\n                            }\n'''
new_tap = '''                            } else {\n                                val frac = ((p.x - left) / (right - left)).coerceIn(0f, 1f)\n                                onSelectTimestamp(window.first + (span * frac).toLong())\n                                val top = 22.dp.toPx()\n                                val bottom = size.height - 38.dp.toPx()\n                                if (p.y in top..bottom) {\n                                    val range = visibleTemperatureRange(window)\n                                    val fracY = ((bottom - p.y) / (bottom - top).coerceAtLeast(1f)).coerceIn(0f, 1f)\n                                    sightTemperature = range.first + (range.second - range.first) * fracY.toDouble()\n                                }\n                            }\n'''
main = replace_once(main, old_tap, new_tap, 'tap sets crosshair temperature')

old_selected = '''        selectedTimestamp?.takeIf { it in visibleFrom..visibleTo }?.let { ts ->\n            val x = mapX(ts)\n            drawLine(selectColor, Offset(x, top), Offset(x, bottom), strokeWidth = 2f)\n\n            // Heure directement sur la visée.\n            val sightPaint = android.graphics.Paint(centerPaint).apply {\n                color = selectColor.toArgbCompat()\n                textSize = 9.dp.toPx()\n                isFakeBoldText = true\n            }\n            drawContext.canvas.nativeCanvas.drawText(\n                formatDateTime(ts),\n                x.coerceIn(left + 54.dp.toPx(), right - 54.dp.toPx()),\n                top + 10.dp.toPx(),\n                sightPaint\n            )\n\n            // Petit trait horizontal + valeur colorée à la hauteur de chaque sonde.\n            sensors.filter { showTemp[it.id] == true }.forEach { sensor ->\n                val point = nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), ts) ?: return@forEach\n                val y = mapTemp(point.temperature)\n                if (y !in top..bottom) return@forEach\n                val markerColor = palette[sensor.colorIndex % palette.size]\n                drawLine(markerColor, Offset(x - 13.dp.toPx(), y), Offset(x + 13.dp.toPx(), y), strokeWidth = 2.2.dp.toPx())\n                drawCircle(markerColor, 3.2.dp.toPx(), Offset(x, y))\n                val valuePaint = android.graphics.Paint(paint).apply {\n                    color = markerColor.toArgbCompat()\n                    textSize = 9.dp.toPx()\n                    isFakeBoldText = true\n                }\n                val label = String.format(Locale.FRANCE, "%.1f°", point.temperature)\n                val width = valuePaint.measureText(label)\n                val tx = if (x + 18.dp.toPx() + width <= right) x + 18.dp.toPx() else x - 18.dp.toPx() - width\n                drawContext.canvas.nativeCanvas.drawText(label, tx, y - 4.dp.toPx(), valuePaint)\n            }\n        }\n'''
new_selected = '''        selectedTimestamp?.takeIf { it in visibleFrom..visibleTo }?.let { ts ->\n            val x = mapX(ts)\n            drawLine(selectColor, Offset(x, top), Offset(x, bottom), strokeWidth = 2.dp.toPx())\n\n            val fallbackTemperature = sensors\n                .firstOrNull { showTemp[it.id] == true }\n                ?.let { sensor -> nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), ts)?.temperature }\n            val crossTemperature = (sightTemperature ?: fallbackTemperature)\n                ?.coerceIn(tempRange.first, tempRange.second)\n            val crossY = crossTemperature?.let { mapTemp(it) }\n\n            // Vrai crosshair : température horizontale sur toute la zone utile.\n            if (crossY != null && crossY in top..bottom) {\n                drawLine(\n                    selectColor.copy(alpha = 0.88f),\n                    Offset(left, crossY),\n                    Offset(right, crossY),\n                    strokeWidth = 1.8.dp.toPx()\n                )\n                drawCircle(Color.White, 5.dp.toPx(), Offset(x, crossY))\n                drawCircle(selectColor, 3.2.dp.toPx(), Offset(x, crossY))\n            }\n\n            val sightPaint = android.graphics.Paint(centerPaint).apply {\n                color = selectColor.toArgbCompat()\n                textSize = 9.dp.toPx()\n                isFakeBoldText = true\n            }\n            val timeLabel = formatDateTime(ts)\n            val timeHalf = sightPaint.measureText(timeLabel) / 2f + 4.dp.toPx()\n            val timeX = x.coerceIn(left + timeHalf, right - timeHalf)\n\n            // Date/heure répétée en haut ET en bas du graphe.\n            drawContext.canvas.nativeCanvas.drawText(timeLabel, timeX, top + 10.dp.toPx(), sightPaint)\n            drawContext.canvas.nativeCanvas.drawText(timeLabel, timeX, bottom - 5.dp.toPx(), sightPaint)\n\n            // Température du crosshair répétée à gauche ET à droite.\n            if (crossTemperature != null && crossY != null) {\n                val tempLabel = String.format(Locale.FRANCE, "%.1f°", crossTemperature)\n                val leftSightPaint = android.graphics.Paint(paint).apply {\n                    color = selectColor.toArgbCompat()\n                    textSize = 9.dp.toPx()\n                    isFakeBoldText = true\n                    textAlign = android.graphics.Paint.Align.LEFT\n                }\n                val rightSightPaint = android.graphics.Paint(leftSightPaint).apply {\n                    textAlign = android.graphics.Paint.Align.RIGHT\n                }\n                val baseline = (crossY - 4.dp.toPx()).coerceIn(top + 9.dp.toPx(), bottom - 3.dp.toPx())\n                drawContext.canvas.nativeCanvas.drawText(tempLabel, left + 4.dp.toPx(), baseline, leftSightPaint)\n                drawContext.canvas.nativeCanvas.drawText(tempLabel, right - 4.dp.toPx(), baseline, rightSightPaint)\n            }\n\n            // Les températures réelles de chaque sonde restent indiquées à leur propre niveau.\n            sensors.filter { showTemp[it.id] == true }.forEach { sensor ->\n                val point = nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), ts) ?: return@forEach\n                val y = mapTemp(point.temperature)\n                if (y !in top..bottom) return@forEach\n                val markerColor = palette[sensor.colorIndex % palette.size]\n                drawLine(markerColor, Offset(x - 13.dp.toPx(), y), Offset(x + 13.dp.toPx(), y), strokeWidth = 2.2.dp.toPx())\n                drawCircle(markerColor, 3.2.dp.toPx(), Offset(x, y))\n                val valuePaint = android.graphics.Paint(paint).apply {\n                    color = markerColor.toArgbCompat()\n                    textSize = 9.dp.toPx()\n                    isFakeBoldText = true\n                }\n                val label = String.format(Locale.FRANCE, "%.1f°", point.temperature)\n                val width = valuePaint.measureText(label)\n                val tx = if (x + 18.dp.toPx() + width <= right) x + 18.dp.toPx() else x - 18.dp.toPx() - width\n                drawContext.canvas.nativeCanvas.drawText(label, tx, y - 4.dp.toPx(), valuePaint)\n            }\n        }\n'''
main = replace_once(main, old_selected, new_selected, 'crosshair drawing')
main_path.write_text(main)

print('FabData v0.17.1 focus-only 5 min + true crosshair patch applied')
