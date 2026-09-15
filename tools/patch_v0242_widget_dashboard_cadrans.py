from pathlib import Path


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Release identity.
gradle = Path("app/build.gradle.kts")
replace_once(
    gradle,
    'versionCode = 68\n        versionName = "0.24.1"',
    'versionCode = 69\n        versionName = "0.24.2"'
)

# Samsung/RemoteViews compatibility: a bare <View> is not a safe RemoteViews child.
# Restore the separator as a TextView, which was the working form in the earlier widget.
layout = Path("app/src/main/res/layout/fabdata_weather_widget.xml")
replace_once(
    layout,
    '''    <View\n        android:id="@+id/widget_separator"\n        android:layout_width="match_parent"\n        android:layout_height="1dp"\n        android:layout_marginTop="4dp"\n        android:layout_marginBottom="5dp"\n        android:background="#33FFFFFF" />''',
    '''    <TextView\n        android:id="@+id/widget_separator"\n        android:layout_width="match_parent"\n        android:layout_height="1dp"\n        android:layout_marginTop="4dp"\n        android:layout_marginBottom="5dp"\n        android:background="#33FFFFFF"\n        android:text="" />'''
)

# Keep the persistent dial conveyor/history engine, but restore the beloved widget-style
# curves as the expanded visual state of the floating in-app panel.
overlay = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")
replace_once(
    overlay,
    '''    private val dataSource = ForecastDialDataSource(context, db)\n    private val executor = Executors.newSingleThreadExecutor()''',
    '''    private val dataSource = ForecastDialDataSource(context, db)\n    private val dashboardSource = ForecastDashboardOverlayDataSource(context, db)\n    private val executor = Executors.newSingleThreadExecutor()'''
)
replace_once(
    overlay,
    '''    private var state: DialState? = null\n    private var lastRawX = 0f''',
    '''    private var state: DialState? = null\n    private var dashboardState: ForecastDashboardSnapshot? = null\n    private var lastRawX = 0f'''
)
replace_once(
    overlay,
    '''            executor.execute {\n                val next = runCatching { dataSource.load() }.getOrNull()\n                if (next != null) {\n                    post {\n                        state = next\n                        updateAccessibility(next)\n                        invalidate()\n                    }\n                }\n            }''',
    '''            executor.execute {\n                val next = runCatching { dataSource.load() }.getOrNull()\n                val dashboard = runCatching { dashboardSource.load() }.getOrNull()\n                if (next != null || dashboard != null) {\n                    post {\n                        if (next != null) {\n                            state = next\n                            updateAccessibility(next)\n                        }\n                        if (dashboard != null) dashboardState = dashboard\n                        invalidate()\n                    }\n                }\n            }'''
)

text = overlay.read_text(encoding="utf-8")
old_count = text.count("dp(130f)")
if old_count < 3:
    raise SystemExit(f"ForecastMemoryOverlay: expected at least 3 expanded min-height anchors, got {old_count}")
text = text.replace("dp(130f)", "dp(245f)")
text = text.replace('prefs.getFloat(KEY_HEIGHT_DP, 154f)', 'prefs.getFloat(KEY_HEIGHT_DP, 286f)')
overlay.write_text(text, encoding="utf-8")

replace_once(
    overlay,
    '''        drawLegend(canvas, night, current)\n        val dials = current?.samples ?: listOf(\n            emptyDial("PASSÉ"), emptyDial("PRÉSENT"), emptyDial("FUTUR")\n        )\n        val top = dp(30f)\n        val availableH = height - top - dp(4f)\n        val slotWidth = width / 3f\n        dials.take(3).forEachIndexed { index, sample ->\n            val cx = slotWidth * (index + 0.5f)\n            val cy = top + availableH * 0.48f\n            val radius = min(slotWidth * 0.41f, availableH * 0.35f)\n            drawDial(canvas, sample, cx, cy, radius, index, night)\n        }\n        drawResizeHandle(canvas, night)''',
    '''        ForecastDashboardPainter.draw(\n            canvas = canvas,\n            width = width.toFloat(),\n            height = height.toFloat(),\n            snapshot = dashboardState,\n            night = night,\n            density = resources.displayMetrics.density,\n            scaledDensity = resources.displayMetrics.scaledDensity\n        )\n        drawResizeHandle(canvas, night)'''
)
replace_once(
    overlay,
    '''            append(if (compact) "Mode compact. Double-tape pour ouvrir les cadrans. " else "Mode complet. Double-tape le cadre pour réduire les cadrans. ")''',
    '''            append(if (compact) "Mode compact. Double-tape pour ouvrir la vue météo. " else "Mode complet : météo douze heures, inertie et Fab adaptative. Double-tape le cadre pour réduire. ")'''
)

print("v0.24.2 widget/dashboard patch applied")
