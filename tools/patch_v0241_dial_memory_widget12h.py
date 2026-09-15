from pathlib import Path


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Production version.
gradle = Path("app/build.gradle.kts")
replace_once(gradle, 'versionCode = 67\n        versionName = "0.24.0"', 'versionCode = 68\n        versionName = "0.24.1"')

# Three dials become persistent entities: future -> present/enriched -> sealed history.
overlay = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")
replace_once(
    overlay,
    """        ForecastAdaptiveStore.ensure(db.writableDatabase)\n        val reference = WeatherReferencePrefs(appContext).selectedReference()""",
    """        ForecastAdaptiveStore.ensure(db.writableDatabase)\n        ForecastDialHistoryStore.ensure(db.writableDatabase)\n        val reference = WeatherReferencePrefs(appContext).selectedReference()"""
)
replace_once(
    overlay,
    """        val result = targets.map { (label, target) ->\n            buildDial(reference.key, label, target, weatherHorizon, adaptiveHorizon)\n        }\n        return DialState(reference.label, weatherHorizon, adaptiveHorizon, result)\n    }\n\n    private fun buildDial(""",
    """        val result = targets.map { (label, target) ->\n            persistentDial(reference.key, label, target, weatherHorizon, adaptiveHorizon)\n        }\n        return DialState(reference.label, weatherHorizon, adaptiveHorizon, result)\n    }\n\n    private fun persistentDial(\n        referenceKey: String,\n        label: String,\n        target: Long,\n        weatherHorizon: Int,\n        adaptiveHorizon: Int\n    ): DialSample {\n        val sql = db.writableDatabase\n        val existing = ForecastDialHistoryStore.get(\n            sql, referenceKey, target, weatherHorizon, adaptiveHorizon\n        )\n        // A left/history dial is immutable forever: this is the exact prediction that lived\n        // on the right, later enriched by terrain when it crossed the present.\n        if (existing?.locked == true) return existing.toDialSample(label)\n\n        val live = buildDial(referenceKey, label, target, weatherHorizon, adaptiveHorizon)\n        val now = System.currentTimeMillis()\n        val base = existing ?: ForecastDialRecord(\n            referenceKey = referenceKey,\n            targetTs = target,\n            weatherHorizon = weatherHorizon,\n            adaptiveHorizon = adaptiveHorizon,\n            officialTemp = live.officialTemp,\n            localTemp = live.localTemp,\n            actualTemp = null,\n            actualIsMeasured = false,\n            officialSlope = live.officialSlope,\n            localSlope = live.localSlope,\n            actualSlope = null,\n            officialAcceleration = live.officialAcceleration,\n            localAcceleration = live.localAcceleration,\n            actualAcceleration = null,\n            officialError = null,\n            localError = null,\n            trainingSamples = live.trainingSamples,\n            phase = ForecastDialHistoryStore.PHASE_FUTURE,\n            locked = false,\n            createdAt = now,\n            updatedAt = now\n        )\n\n        val allowTerrain = label != \"FUTUR\"\n        val actual = if (allowTerrain) live.actualTemp ?: base.actualTemp else base.actualTemp\n        val actualMeasured = if (allowTerrain && live.actualTemp != null) {\n            live.actualIsMeasured\n        } else base.actualIsMeasured\n        val phase = when (label) {\n            \"FUTUR\" -> ForecastDialHistoryStore.PHASE_FUTURE\n            \"PRÉSENT\" -> ForecastDialHistoryStore.PHASE_PRESENT\n            else -> ForecastDialHistoryStore.PHASE_HISTORY\n        }\n        val lock = label == \"PASSÉ\"\n        val merged = base.copy(\n            actualTemp = actual,\n            actualIsMeasured = actualMeasured,\n            actualSlope = if (allowTerrain) live.actualSlope ?: base.actualSlope else base.actualSlope,\n            actualAcceleration = if (allowTerrain) live.actualAcceleration ?: base.actualAcceleration else base.actualAcceleration,\n            officialError = if (base.officialTemp != null && actual != null) abs(base.officialTemp - actual) else base.officialError,\n            localError = if (base.localTemp != null && actual != null) abs(base.localTemp - actual) else base.localError,\n            phase = phase,\n            locked = lock,\n            updatedAt = now\n        )\n        return ForecastDialHistoryStore.save(sql, merged).toDialSample(label)\n    }\n\n    private fun ForecastDialRecord.toDialSample(label: String) = DialSample(\n        label = label,\n        targetTs = targetTs,\n        officialTemp = officialTemp,\n        localTemp = localTemp,\n        actualTemp = actualTemp,\n        actualIsMeasured = actualIsMeasured,\n        officialSlope = officialSlope,\n        localSlope = localSlope,\n        actualSlope = actualSlope,\n        officialAcceleration = officialAcceleration,\n        localAcceleration = localAcceleration,\n        actualAcceleration = actualAcceleration,\n        officialError = officialError,\n        localError = localError,\n        trainingSamples = trainingSamples\n    )\n\n    private fun buildDial("""
)

# Backup: preserve the new dial history, and keep all v1..v5 inputs accepted.
backup = Path("app/src/main/java/com/fabdata/app/BackupLayer.kt")
replace_once(
    backup,
    '"FORECAST_CURVE_10M_ARCHIVE", "FORECAST_ADAPTIVE_ARCHIVE"',
    '"FORECAST_CURVE_10M_ARCHIVE", "FORECAST_ADAPTIVE_ARCHIVE", "DIAL_HISTORY"'
)

v3 = Path("app/src/main/java/com/fabdata/app/BackupV3Support.kt")
text = v3.read_text(encoding="utf-8")
# There are two intentional ensure sequences: restore preparation and export preparation.
needle = "        ForecastAdaptiveStore.ensure(sql)"
if text.count(needle) != 1:
    raise SystemExit(f"BackupV3Support: expected one restore ensure sequence, got {text.count(needle)}")
text = text.replace(needle, needle + "\n        ForecastDialHistoryStore.ensure(sql)", 1)
needle2 = "        ForecastAdaptiveStore.ensure(db.writableDatabase)"
if text.count(needle2) != 1:
    raise SystemExit(f"BackupV3Support: expected one export ensure sequence, got {text.count(needle2)}")
text = text.replace(needle2, needle2 + "\n        ForecastDialHistoryStore.ensure(db.writableDatabase)", 1)
v3.write_text(text, encoding="utf-8")

replace_once(
    v3,
    '                "FORECAST_ADAPTIVE_ARCHIVE" -> restoreForecastAdaptiveArchive(json(values))\n                "WEATHER" -> restoreWeather(values)',
    '                "FORECAST_ADAPTIVE_ARCHIVE" -> restoreForecastAdaptiveArchive(json(values))\n                "DIAL_HISTORY" -> restoreDialHistory(json(values))\n                "WEATHER" -> restoreWeather(values)'
)

weather_anchor = '''        db.readableDatabase.rawQuery(\n            """\n            SELECT reference_key, timestamp, temperature, humidity, source, confidence\n            FROM weather_reference_samples'''
dial_export = '''        ForecastDialHistoryStore.all(db.readableDatabase).forEach { dial ->\n            writeJson(writer, "DIAL_HISTORY", JSONObject().apply {\n                put("referenceKey", dial.referenceKey)\n                put("targetTs", dial.targetTs)\n                put("weatherHorizon", dial.weatherHorizon)\n                put("adaptiveHorizon", dial.adaptiveHorizon)\n                putNullable("officialTemp", dial.officialTemp)\n                putNullable("localTemp", dial.localTemp)\n                putNullable("actualTemp", dial.actualTemp)\n                put("actualIsMeasured", dial.actualIsMeasured)\n                putNullable("officialSlope", dial.officialSlope)\n                putNullable("localSlope", dial.localSlope)\n                putNullable("actualSlope", dial.actualSlope)\n                putNullable("officialAcceleration", dial.officialAcceleration)\n                putNullable("localAcceleration", dial.localAcceleration)\n                putNullable("actualAcceleration", dial.actualAcceleration)\n                putNullable("officialError", dial.officialError)\n                putNullable("localError", dial.localError)\n                put("trainingSamples", dial.trainingSamples)\n                put("phase", dial.phase)\n                put("locked", dial.locked)\n                put("createdAt", dial.createdAt)\n                put("updatedAt", dial.updatedAt)\n            })\n        }\n\n'''
text = v3.read_text(encoding="utf-8")
if text.count(weather_anchor) != 1:
    raise SystemExit("BackupV3Support: weather export anchor not unique")
v3.write_text(text.replace(weather_anchor, dial_export + weather_anchor, 1), encoding="utf-8")

replace_once(
    v3,
    """    private fun restoreWeather(values: Map<String, String>) {""",
    """    private fun restoreDialHistory(o: JSONObject) {\n        val key = o.optString(\"referenceKey\", \"\").trim()\n        val targetTs = o.optLong(\"targetTs\", -1L)\n        if (key.isBlank() || targetTs < 0L) return\n        val weatherHorizon = o.optInt(\"weatherHorizon\", 1).coerceIn(1, 48)\n        val requestedAdaptive = o.optInt(\"adaptiveHorizon\", 1)\n        val adaptiveHorizon = requestedAdaptive.takeIf { it in FORECAST_ADAPTIVE_HORIZONS } ?: 1\n        val phase = o.optString(\"phase\", ForecastDialHistoryStore.PHASE_HISTORY).ifBlank {\n            ForecastDialHistoryStore.PHASE_HISTORY\n        }\n        ForecastDialHistoryStore.restore(\n            db.writableDatabase,\n            ForecastDialRecord(\n                referenceKey = key,\n                targetTs = targetTs,\n                weatherHorizon = weatherHorizon,\n                adaptiveHorizon = adaptiveHorizon,\n                officialTemp = nullableDouble(o, \"officialTemp\"),\n                localTemp = nullableDouble(o, \"localTemp\"),\n                actualTemp = nullableDouble(o, \"actualTemp\"),\n                actualIsMeasured = o.optBoolean(\"actualIsMeasured\", false),\n                officialSlope = nullableDouble(o, \"officialSlope\"),\n                localSlope = nullableDouble(o, \"localSlope\"),\n                actualSlope = nullableDouble(o, \"actualSlope\"),\n                officialAcceleration = nullableDouble(o, \"officialAcceleration\"),\n                localAcceleration = nullableDouble(o, \"localAcceleration\"),\n                actualAcceleration = nullableDouble(o, \"actualAcceleration\"),\n                officialError = nullableDouble(o, \"officialError\"),\n                localError = nullableDouble(o, \"localError\"),\n                trainingSamples = o.optInt(\"trainingSamples\", 0),\n                phase = phase,\n                locked = o.optBoolean(\"locked\", phase == ForecastDialHistoryStore.PHASE_HISTORY),\n                createdAt = o.optLong(\"createdAt\", targetTs),\n                updatedAt = o.optLong(\"updatedAt\", targetTs)\n            )\n        )\n    }\n\n    private fun restoreWeather(values: Map<String, String>) {"""
)

# Home-screen widget: 12-hour forecast + true double-tap collapse/expand.
widget = Path("app/src/main/java/com/fabdata/app/FabDataWeatherWidget.kt")
replace_once(
    widget,
    """private const val WIDGET_MINUTE_MS = 60L * 1000L""",
    """private const val WIDGET_MINUTE_MS = 60L * 1000L\nprivate const val ACTION_WIDGET_TAP = \"com.fabdata.app.action.WIDGET_DOUBLE_TAP\"\nprivate const val WIDGET_DOUBLE_TAP_MS = 520L\nprivate const val WIDGET_PREFS = \"fabdata_android_widget\""""
)
replace_once(
    widget,
    """    override fun onAppWidgetOptionsChanged(\n        context: Context,\n        appWidgetManager: AppWidgetManager,\n        appWidgetId: Int,\n        newOptions: android.os.Bundle\n    ) {\n        renderAsync(context.applicationContext, appWidgetManager, appWidgetId)\n    }\n\n    companion object {""",
    """    override fun onAppWidgetOptionsChanged(\n        context: Context,\n        appWidgetManager: AppWidgetManager,\n        appWidgetId: Int,\n        newOptions: android.os.Bundle\n    ) {\n        renderAsync(context.applicationContext, appWidgetManager, appWidgetId)\n    }\n\n    override fun onReceive(context: Context, intent: Intent) {\n        super.onReceive(context, intent)\n        if (intent.action != ACTION_WIDGET_TAP) return\n        val id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)\n        if (id == AppWidgetManager.INVALID_APPWIDGET_ID) return\n        val prefs = context.getSharedPreferences(WIDGET_PREFS, Context.MODE_PRIVATE)\n        val now = System.currentTimeMillis()\n        val key = \"last_tap_$id\"\n        val previous = prefs.getLong(key, 0L)\n        if (previous > 0L && now - previous <= WIDGET_DOUBLE_TAP_MS) {\n            val collapsedKey = \"collapsed_$id\"\n            prefs.edit()\n                .putBoolean(collapsedKey, !prefs.getBoolean(collapsedKey, false))\n                .putLong(key, 0L)\n                .apply()\n            renderAsync(context.applicationContext, AppWidgetManager.getInstance(context), id)\n        } else {\n            prefs.edit().putLong(key, now).apply()\n        }\n    }\n\n    companion object {"""
)
replace_once(
    widget,
    """                val views = buildRemoteViews(context, snapshot)\n                manager.updateAppWidget(id, views)""",
    """                val views = buildRemoteViews(context, snapshot, id)\n                manager.updateAppWidget(id, views)"""
)
replace_once(
    widget,
    """        private fun buildRemoteViews(context: Context, snapshot: WidgetSnapshot?): RemoteViews {\n            val views = RemoteViews(context.packageName, R.layout.fabdata_weather_widget)\n            val launchIntent = Intent(context, MainActivity::class.java)\n            val pendingIntent = PendingIntent.getActivity(\n                context,\n                2400,\n                launchIntent,\n                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE\n            )\n            views.setOnClickPendingIntent(R.id.widget_root, pendingIntent)""",
    """        private fun buildRemoteViews(context: Context, snapshot: WidgetSnapshot?, widgetId: Int): RemoteViews {\n            val views = RemoteViews(context.packageName, R.layout.fabdata_weather_widget)\n            val launchIntent = Intent(context, MainActivity::class.java)\n            val openIntent = PendingIntent.getActivity(\n                context,\n                2400 + widgetId,\n                launchIntent,\n                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE\n            )\n            val tapIntent = Intent(context, FabDataWeatherWidget::class.java).apply {\n                action = ACTION_WIDGET_TAP\n                putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId)\n            }\n            val tapPendingIntent = PendingIntent.getBroadcast(\n                context,\n                24000 + widgetId,\n                tapIntent,\n                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE\n            )\n            views.setOnClickPendingIntent(R.id.widget_root, tapPendingIntent)\n            views.setOnClickPendingIntent(R.id.widget_title, openIntent)\n            views.setOnClickPendingIntent(R.id.widget_reference, openIntent)\n\n            val collapsed = context.getSharedPreferences(WIDGET_PREFS, Context.MODE_PRIVATE)\n                .getBoolean(\"collapsed_$widgetId\", false)\n            views.setViewVisibility(R.id.widget_compact_values, if (collapsed) android.view.View.VISIBLE else android.view.View.GONE)\n            views.setViewVisibility(R.id.widget_weather_panel, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)\n            views.setViewVisibility(R.id.widget_separator, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)\n            views.setViewVisibility(R.id.widget_inertia_values, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)\n            views.setViewVisibility(R.id.widget_adaptive_caption, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)\n            views.setViewVisibility(R.id.widget_adaptive_curve, if (collapsed) android.view.View.GONE else android.view.View.VISIBLE)"""
)
replace_once(
    widget,
    """                views.setTextViewText(R.id.widget_weather_values, \"Météo  —     +1 h  —\")""",
    """                views.setTextViewText(R.id.widget_weather_values, \"Météo 12 h · maintenant — · +1 h —\")\n                views.setTextViewText(R.id.widget_compact_values, \"Météo 12 h · maintenant — · +1 h —\")"""
)
replace_once(
    widget,
    """            views.setTextViewText(\n                R.id.widget_weather_values,\n                \"Maintenant  $weatherNow        +1 h  $weatherPlus1\"\n            )""",
    """            views.setTextViewText(\n                R.id.widget_weather_values,\n                \"Maintenant  $weatherNow        +1 h  $weatherPlus1\"\n            )\n            views.setTextViewText(\n                R.id.widget_compact_values,\n                \"Météo 12 h · maintenant $weatherNow · +1 h $weatherPlus1\"\n            )"""
)
replace_once(
    widget,
    """            val from = now - 3L * WIDGET_HOUR_MS\n            val to = now + 3L * WIDGET_HOUR_MS""",
    """            // Keep one hour of context, then show the next twelve forecast hours.\n            val from = now - 1L * WIDGET_HOUR_MS\n            val to = now + 12L * WIDGET_HOUR_MS"""
)
replace_once(
    widget,
    """                    \"Prévision Fab adaptative de H plus 1 à H plus 48. Touchez pour ouvrir FabData.\"""",
    """                    \"Prévision météo visible sur douze heures et Fab adaptative de H plus 1 à H plus 48. \" +\n                    \"Double-tapez le widget pour le replier ou le déplier; touchez le titre pour ouvrir FabData.\""""
)

# Widget layout: expanded 12 h chart + compact one-line state.
layout = Path("app/src/main/res/layout/fabdata_weather_widget.xml")
replace_once(
    layout,
    """        <TextView\n            android:layout_width=\"0dp\"""",
    """        <TextView\n            android:id=\"@+id/widget_title\"\n            android:layout_width=\"0dp\""""
)
replace_once(layout, 'android:text="FabData · MÉTÉO"', 'android:text="FabData · MÉTÉO 12 h"')
replace_once(
    layout,
    """    <FrameLayout\n        android:layout_width=\"match_parent\"""",
    """    <TextView\n        android:id=\"@+id/widget_compact_values\"\n        android:layout_width=\"match_parent\"\n        android:layout_height=\"wrap_content\"\n        android:layout_marginTop=\"8dp\"\n        android:gravity=\"center\"\n        android:padding=\"6dp\"\n        android:background=\"@drawable/fabdata_widget_value_pill\"\n        android:text=\"Météo 12 h · maintenant — · +1 h —\"\n        android:textStyle=\"bold\"\n        android:textSize=\"14sp\"\n        android:textColor=\"#FFFFFFFF\"\n        android:visibility=\"gone\" />\n\n    <FrameLayout\n        android:id=\"@+id/widget_weather_panel\"\n        android:layout_width=\"match_parent\""""
)
replace_once(
    layout,
    """    <View\n        android:layout_width=\"match_parent\"""",
    """    <View\n        android:id=\"@+id/widget_separator\"\n        android:layout_width=\"match_parent\""""
)

strings = Path("app/src/main/res/values/strings.xml")
replace_once(
    strings,
    "Météo, inertie sol et prévision Fab adaptative sur l’écran d’accueil",
    "Météo 12 h, inertie sol et prévision Fab adaptative sur l’écran d’accueil"
)

print("v0.24.1 persistent dial history + 12h collapsible Android widget patch applied")
