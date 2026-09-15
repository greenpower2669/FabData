from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]

gradle = root / "app/build.gradle.kts"
text = gradle.read_text(encoding="utf-8")
text = replace_once(text, 'versionCode = 70', 'versionCode = 71', 'versionCode')
text = replace_once(text, 'versionName = "0.24.3"', 'versionName = "0.24.4"', 'versionName')
gradle.write_text(text, encoding="utf-8")

overlay = root / "app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt"
text = overlay.read_text(encoding="utf-8")
old_targets = '''        val nowHour = hourBucket(now)
        val targets = listOf(
            "PASSÉ" to (nowHour - HOUR_MS),
            "PRÉSENT" to nowHour,
            "FUTUR" to (nowHour + HOUR_MS)
        )
'''
new_targets = '''        // v0.24.4 : the cockpit itself now lives on the same canonical ten-minute clock
        // as forecast acquisition. Nine sealed past universes + one live present + one frozen
        // future move left by one slot every :00/:10/:20/:30/:40/:50 boundary.
        val nowSlot = ForecastMemoryStore.captureSlot10m(now)
        val targets = buildList {
            for (stepsBack in 9 downTo 1) {
                add("P−${stepsBack * 10}" to (nowSlot - stepsBack.toLong() * FORECAST_CAPTURE_SLOT_MS))
            }
            add("PRÉSENT" to nowSlot)
            add("FUTUR" to (nowSlot + FORECAST_CAPTURE_SLOT_MS))
        }
'''
text = replace_once(text, old_targets, new_targets, 'ten-minute dial targets')

old_lifecycle = '''        val allowTerrain = label != "FUTUR"
        val actual = if (allowTerrain) live.actualTemp ?: base.actualTemp else base.actualTemp
        val actualMeasured = if (allowTerrain && live.actualTemp != null) {
            live.actualIsMeasured
        } else base.actualIsMeasured
        val phase = when (label) {
            "FUTUR" -> ForecastDialHistoryStore.PHASE_FUTURE
            "PRÉSENT" -> ForecastDialHistoryStore.PHASE_PRESENT
            else -> ForecastDialHistoryStore.PHASE_HISTORY
        }
        val lock = label == "PASSÉ"
'''
new_lifecycle = '''        val isFuture = label == "FUTUR"
        val isPresent = label == "PRÉSENT"
        val allowTerrain = !isFuture
        val actual = if (allowTerrain) live.actualTemp ?: base.actualTemp else base.actualTemp
        val actualMeasured = if (allowTerrain && live.actualTemp != null) {
            live.actualIsMeasured
        } else base.actualIsMeasured
        val phase = when {
            isFuture -> ForecastDialHistoryStore.PHASE_FUTURE
            isPresent -> ForecastDialHistoryStore.PHASE_PRESENT
            else -> ForecastDialHistoryStore.PHASE_HISTORY
        }
        // PRESENT may still receive a better real/reconstructed terrain value during its
        // ten-minute slot. The instant it moves left, it is sealed forever. FUTURE is also
        // forecast-immutable: its forecast fields are created once and never replaced.
        val lock = !isFuture && !isPresent
'''
text = replace_once(text, old_lifecycle, new_lifecycle, 'dial lifecycle lock')

start = text.index('    private fun drawBackgroundDials(')
end = text.index('    private fun drawResizeHandle(', start)
new_draw = '''    private fun drawBackgroundDials(canvas: Canvas, night: Boolean, current: DialState?) {
        val dials = current?.samples ?: (
            List(9) { index -> emptyDial("P−${90 - index * 10}") } +
                listOf(emptyDial("PRÉSENT"), emptyDial("FUTUR"))
        )
        val presentIndex = (dials.size - 2).coerceAtLeast(0)
        val past = dials.take(presentIndex)
        val present = dials.getOrNull(presentIndex) ?: emptyDial("PRÉSENT")
        val future = dials.getOrNull(presentIndex + 1) ?: emptyDial("FUTUR")
        val cy = height * 0.48f

        fun ghostDial(sample: DialSample, cx: Float, radius: Float, alpha: Int, major: Boolean) {
            paint.style = Paint.Style.FILL
            paint.color = withAlpha(comparisonFill(sample, night), (alpha * 0.68f).toInt())
            canvas.drawCircle(cx, cy, radius, paint)

            paint.style = Paint.Style.STROKE
            paint.strokeWidth = dp(if (major) 1.6f else 0.9f)
            paint.color = withAlpha(officialBorder(sample, night), alpha)
            canvas.drawCircle(cx, cy, radius, paint)

            val outer = RectF(
                cx - radius * 0.82f, cy - radius * 0.82f,
                cx + radius * 0.82f, cy + radius * 0.82f
            )
            paint.strokeWidth = dp(if (major) 0.8f else 0.55f)
            paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, (alpha * 0.70f).toInt())
            canvas.drawArc(outer, 135f, 270f, false, paint)
            if (major) {
                for (i in 0..8) {
                    val angle = valueAngle(-2.0 + i * 0.5, -2.0, 2.0)
                    val p1 = polar(cx, cy, radius * 0.72f, angle)
                    val p2 = polar(cx, cy, radius * 0.81f, angle)
                    canvas.drawLine(p1.first, p1.second, p2.first, p2.second, paint)
                }
            }

            drawNeedle(canvas, sample.officialSlope, cx, cy, radius * 0.72f, OFFICIAL_RED, alpha)
            drawNeedle(canvas, sample.localSlope, cx, cy, radius * 0.67f, LOCAL_YELLOW, alpha)
            drawNeedle(canvas, sample.actualSlope, cx, cy, radius * 0.61f, REAL_GREEN, alpha)
        }

        // Nine smaller sealed pasts occupy the left side. Their opacity grows slightly toward
        // the present, so the eye naturally reads the strip from old -> recent.
        val pastStart = dp(10f)
        val pastEnd = width * 0.61f
        val spacing = (pastEnd - pastStart) / past.size.coerceAtLeast(1).toFloat()
        val miniRadius = min(dp(8.5f), spacing * 0.34f)
        past.forEachIndexed { index, sample ->
            val cx = pastStart + spacing * (index + 0.5f)
            ghostDial(sample, cx, miniRadius, 22 + index * 3, major = false)
        }

        // PRESENT and FUTURE remain the two large anchors of the multiverse strip.
        val majorRadius = min(dp(25f), height * 0.16f)
        ghostDial(present, width * 0.76f, majorRadius, 58, major = true)
        ghostDial(future, width * 0.91f, majorRadius * 0.92f, 66, major = true)
    }

    private fun drawCompact(canvas: Canvas, night: Boolean, current: DialState?) {
        val dials = current?.samples ?: (
            List(9) { index -> emptyDial("P−${90 - index * 10}") } +
                listOf(emptyDial("PRÉSENT"), emptyDial("FUTUR"))
        )
        val presentIndex = (dials.size - 2).coerceAtLeast(0)
        val past = dials.take(presentIndex)
        val present = dials.getOrNull(presentIndex) ?: emptyDial("PRÉSENT")
        val future = dials.getOrNull(presentIndex + 1) ?: emptyDial("FUTUR")
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
        val pastStart = dp(5f)
        val pastEnd = width * 0.58f
        val spacing = (pastEnd - pastStart) / past.size.coerceAtLeast(1).toFloat()
        past.forEachIndexed { index, sample ->
            val cx = pastStart + spacing * (index + 0.5f)
            val radius = dp(1.55f + index * 0.05f)
            paint.style = Paint.Style.FILL
            paint.color = withAlpha(comparisonFill(sample, night), 125 + index * 8)
            canvas.drawCircle(cx, centerY, radius, paint)
        }

        listOf(present to (width * 0.74f), future to (width * 0.90f)).forEachIndexed { index, pair ->
            val sample = pair.first
            val cx = pair.second
            val radius = dp(if (index == 0) 6.0f else 5.2f)
            paint.style = Paint.Style.FILL
            paint.color = withAlpha(comparisonFill(sample, night), if (index == 0) 255 else 220)
            canvas.drawCircle(cx, centerY, radius, paint)
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = dp(if (index == 0) 2.0f else 1.5f)
            paint.color = withAlpha(officialBorder(sample, night), if (index == 0) 255 else 230)
            canvas.drawCircle(cx, centerY, radius, paint)
        }
    }

'''
text = text[:start] + new_draw + text[end:]

old_access = 'append(if (compact) "Mode compact. Double-tape pour ouvrir la vue météo. " else "Mode complet : cadrans passé présent futur en arrière-plan, météo douze heures, inertie et Fab adaptative. Double-tape le cadre pour réduire. ")'
new_access = 'append(if (compact) "Mode compact. Neuf passés, présent et futur. Double-tape pour ouvrir la vue météo. " else "Mode complet : neuf cadrans passés scellés de dix minutes, un présent vivant et un futur figé en arrière-plan, météo douze heures, inertie et Fab adaptative. Double-tape le cadre pour réduire. ")'
text = replace_once(text, old_access, new_access, 'accessibility multiverse description')
overlay.write_text(text, encoding="utf-8")

main = root / "app/src/main/java/com/fabdata/app/MainActivity.kt"
text = main.read_text(encoding="utf-8")
old_anchor = '''                val terrainAnchor = userPhysicalBounds?.last ?: System.currentTimeMillis()
                runCatching {
                    weatherReferenceManager.reconstructRecentLocalOnly(
                        selectedWeatherReference,
                        anchorTimestamp = terrainAnchor,
                        hours = 48
                    )
                }
'''
new_anchor = '''                // Terrain is an autonomous 48 h weather reference. It must not stop at the
                // last indoor/user probe sample: real station data + local reconstruction keep
                // progressing even when no physical probe is connected.
                val terrainAnchor = System.currentTimeMillis()
                runCatching {
                    weatherReferenceManager.reconstructRecentLocalOnly(
                        selectedWeatherReference,
                        anchorTimestamp = terrainAnchor,
                        hours = 48
                    )
                }
'''
text = replace_once(text, old_anchor, new_anchor, '48h terrain anchor')
main.write_text(text, encoding="utf-8")

history = root / "app/src/main/java/com/fabdata/app/ForecastDialHistoryStore.kt"
text = history.read_text(encoding="utf-8")
text = replace_once(
    text,
    ' * Persistent life-cycle for the three forecast dials.\n',
    ' * Persistent life-cycle for the canonical ten-minute multiverse dial strip.\n',
    'dial history documentation'
)
text = replace_once(
    text,
    ' * A target is born as FUTURE, is enriched when it becomes PRESENT, then is sealed when it\n * reaches HISTORY. The original forecast fields never move after creation; only terrain/error\n * fields may be enriched before the row is sealed.\n',
    ' * A target is born as the single FUTURE slot, is enriched while it is the single PRESENT,\n * then is sealed forever when it enters one of the nine visible HISTORY slots. The original\n * forecast fields never move after creation; only terrain/error fields may be enriched before\n * the row is sealed. Older rows remain in the full archive after leaving the nine-slot strip.\n',
    'dial history lifecycle documentation'
)
history.write_text(text, encoding="utf-8")

print('v0.24.4 multiverse/10m/terrain48h patch applied')
