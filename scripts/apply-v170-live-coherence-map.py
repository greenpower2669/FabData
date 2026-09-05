#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text()


def write(path, value):
    (ROOT / path).write_text(value)


def replace_once(path, old, new, label):
    value = text(path)
    if new in value:
        return
    if old not in value:
        raise SystemExit(f"{label}: bloc introuvable dans {path}")
    write(path, value.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Version + cartographie MapLibre sans clé Google.
# ---------------------------------------------------------------------------
replace_once("app/build.gradle.kts", "versionCode = 31", "versionCode = 32", "versionCode")
replace_once("app/build.gradle.kts", 'versionName = "0.16.0"', 'versionName = "0.17.0"', "versionName")
replace_once(
    "app/build.gradle.kts",
    '    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")\n',
    '    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")\n    implementation("org.maplibre.gl:android-sdk:13.4.1")\n',
    "MapLibre dependency"
)

# ---------------------------------------------------------------------------
# 1. Une vraie mesure domine aussi les calculs voisins de la même heure.
#    On ne supprime JAMAIS une ligne MEASURED : elle n'a d'ailleurs pas de ligne
#    de provenance dans point_sources.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''        // Une vraie mesure change l'état connu : tout forecast situé après elle\n        // appartient désormais à un ancien état du monde et doit disparaître.\n        invalidateForecastsAfterMeasured(db, sensorId, timestamp)\n    }\n\n    private fun invalidateForecastsAfterMeasured''',
    '''        // v0.17 : une mesure réelle domine également les points CALCULÉS du même\n        // bucket horaire. Les mesures réelles voisines sont intouchables.\n        pruneCalculatedInMeasuredHour(db, sensorId, timestamp)\n\n        // Une vraie mesure change l'état connu : tout forecast situé après elle\n        // appartient désormais à un ancien état du monde et doit disparaître.\n        invalidateForecastsAfterMeasured(db, sensorId, timestamp)\n    }\n\n    private fun pruneCalculatedInMeasuredHour(db: FabDataDb, sensorId: Long, timestamp: Long): Int {\n        ensure(db.writableDatabase)\n        val hourMs = 60L * 60L * 1000L\n        val from = (timestamp / hourMs) * hourMs\n        val to = from + hourMs - 1L\n        val stale = mutableListOf<Long>()\n        db.readableDatabase.rawQuery(\n            "SELECT timestamp FROM point_sources WHERE sensor_id=? AND timestamp BETWEEN ? AND ? AND source<>'measured'",\n            arrayOf(sensorId.toString(), from.toString(), to.toString())\n        ).use { c -> while (c.moveToNext()) stale += c.getLong(0) }\n        stale.forEach { ts ->\n            db.writableDatabase.delete("samples", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))\n            db.writableDatabase.delete("point_sources", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))\n        }\n        return stale.size\n    }\n\n    /**\n     * Nettoyage conservateur pour les bases héritées : si un bucket horaire contient\n     * au moins une vraie mesure, seules les lignes calculées de ce même bucket sont\n     * retirées. Aucune mesure réelle ne peut apparaître dans la liste de suppression.\n     */\n    fun reconcileMeasuredDominance(db: FabDataDb): Int {\n        ensure(db.writableDatabase)\n        val stale = mutableListOf<Pair<Long, Long>>()\n        db.readableDatabase.rawQuery(\n            """\n            SELECT c.sensor_id, c.timestamp\n            FROM point_sources c\n            WHERE c.source<>'measured'\n              AND EXISTS (\n                SELECT 1\n                FROM samples m\n                LEFT JOIN point_sources mp ON mp.sensor_id=m.sensor_id AND mp.timestamp=m.timestamp\n                WHERE m.sensor_id=c.sensor_id\n                  AND (m.timestamp / 3600000)=(c.timestamp / 3600000)\n                  AND (mp.source IS NULL OR mp.source='measured')\n              )\n            """.trimIndent(), null\n        ).use { c -> while (c.moveToNext()) stale += c.getLong(0) to c.getLong(1) }\n        if (stale.isEmpty()) return 0\n        db.inTransaction {\n            stale.forEach { (sensorId, ts) ->\n                db.writableDatabase.delete("samples", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))\n                db.writableDatabase.delete("point_sources", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))\n            }\n        }\n        return stale.size\n    }\n\n    private fun invalidateForecastsAfterMeasured''',
    "measured dominance"
)

# Une correction au même timestamp doit elle aussi changer la révision thermique.
replace_once(
    "app/src/main/java/com/fabdata/app/DataLayer.kt",
    '''            SELECT COUNT(*), MIN(p.timestamp), MAX(p.timestamp)\n            FROM samples p''',
    '''            SELECT COUNT(*), MIN(p.timestamp), MAX(p.timestamp),\n                   COALESCE(SUM(CAST(ROUND(p.temperature * 1000.0) AS INTEGER)), 0),\n                   COALESCE(SUM(CAST(ROUND(p.humidity * 1000.0) AS INTEGER)), 0)\n            FROM samples p''',
    "measured revision sums"
)
replace_once(
    "app/src/main/java/com/fabdata/app/DataLayer.kt",
    '''            return "${c.getLong(0)}:${c.getLong(1)}:${c.getLong(2)}"\n''',
    '''            return "${c.getLong(0)}:${c.getLong(1)}:${c.getLong(2)}:${c.getLong(3)}:${c.getLong(4)}"\n''',
    "measured revision value"
)

# ---------------------------------------------------------------------------
# 2. Référence météo : dominance réelle dans le bucket + refresh récent léger.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''        db.writableDatabase.insertWithOnConflict(\n            "weather_reference_samples", null, values, SQLiteDatabase.CONFLICT_REPLACE\n        )\n    }\n\n    fun query''',
    '''        db.writableDatabase.insertWithOnConflict(\n            "weather_reference_samples", null, values, SQLiteDatabase.CONFLICT_REPLACE\n        )\n        if (point.source == PointSource.MEASURED) {\n            pruneCalculatedInMeasuredHour(referenceKey, point.timestamp)\n        }\n    }\n\n    private fun pruneCalculatedInMeasuredHour(referenceKey: String, timestamp: Long): Int {\n        val hourMs = 60L * 60L * 1000L\n        val from = (timestamp / hourMs) * hourMs\n        val to = from + hourMs - 1L\n        val stale = mutableListOf<Long>()\n        db.readableDatabase.rawQuery(\n            "SELECT timestamp FROM weather_reference_samples WHERE reference_key=? AND timestamp BETWEEN ? AND ? AND source<>'measured'",\n            arrayOf(referenceKey, from.toString(), to.toString())\n        ).use { c -> while (c.moveToNext()) stale += c.getLong(0) }\n        stale.forEach { ts ->\n            db.writableDatabase.delete(\n                "weather_reference_samples",\n                "reference_key=? AND timestamp=? AND source<>'measured'",\n                arrayOf(referenceKey, ts.toString())\n            )\n        }\n        return stale.size\n    }\n\n    fun reconcileMeasuredDominance(referenceKey: String): Int {\n        val stale = mutableListOf<Long>()\n        db.readableDatabase.rawQuery(\n            """\n            SELECT c.timestamp\n            FROM weather_reference_samples c\n            WHERE c.reference_key=? AND c.source<>'measured'\n              AND EXISTS (\n                SELECT 1 FROM weather_reference_samples m\n                WHERE m.reference_key=c.reference_key AND m.source='measured'\n                  AND (m.timestamp / 3600000)=(c.timestamp / 3600000)\n              )\n            """.trimIndent(), arrayOf(referenceKey)\n        ).use { c -> while (c.moveToNext()) stale += c.getLong(0) }\n        stale.forEach { ts ->\n            db.writableDatabase.delete(\n                "weather_reference_samples",\n                "reference_key=? AND timestamp=? AND source<>'measured'",\n                arrayOf(referenceKey, ts.toString())\n            )\n        }\n        return stale.size\n    }\n\n    fun query''',
    "weather measured dominance"
)

# Même les anciennes bases sont lues canoniquement : un calcul ne s'affiche/alimente
# jamais dans une heure où une observation réelle existe.
replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''        return out\n    }\n\n    fun bounds(referenceKey: String): LongRange?''',
    '''        val measuredHours = out.asSequence()\n            .filter { it.source == PointSource.MEASURED }\n            .map { it.timestamp / 3600000L }\n            .toSet()\n        return out.filter { it.source == PointSource.MEASURED || (it.timestamp / 3600000L) !in measuredHours }\n    }\n\n    fun bounds(referenceKey: String): LongRange?''',
    "canonical weather query"
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''    private val hourMs = 60L * 60L * 1000L\n\n    fun store(): WeatherReferenceStore = store\n''',
    '''    private val hourMs = 60L * 60L * 1000L\n    private var lastOfficialRecentAt = 0L\n\n    fun store(): WeatherReferenceStore = store\n''',
    "recent official throttle"
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n        val actual = store.query(reference.key, from, minOf(to, System.currentTimeMillis()))''',
    '''        store.reconcileMeasuredDominance(reference.key)\n        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n        val actual = store.query(reference.key, from, minOf(to, System.currentTimeMillis()))''',
    "refresh full reconcile"
)

# Ajoute un rafraîchissement live limité aux 36 dernières heures.
marker = '''    fun ensureLocalCache(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {\n'''
value = text("app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt")
if "fun refreshRecent(reference: WeatherReference)" not in value:
    if marker not in value:
        raise SystemExit("refreshRecent insertion marker missing")
    live = '''    /**\n     * Rafraîchissement live léger : jamais d'archive longue. Il est conçu pour être\n     * appelé au focus puis toutes les 60 s sans relancer une reconstruction historique.\n     */\n    fun refreshRecent(reference: WeatherReference): WeatherReferenceSyncResult {\n        store.keepOnly(reference.key)\n        val now = System.currentTimeMillis()\n        val from = now - 36L * hourMs\n        val to = now + 8L * hourMs\n\n        runCatching { fetchOpenMeteoRecentPast(reference, from, now) }\n            .getOrDefault(emptyList())\n            .forEach { store.upsert(reference.key, it) }\n\n        if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {\n            val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)\n            db.querySamples(sensor.id, from, now, maxPoints = 12_000).forEach { p ->\n                val source = PointSourceStore.sourceFor(db, sensor.id, p.timestamp)\n                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, source))\n            }\n            lyonLab.queryOfficial(LyonSeriesKind.HOURLY, from, now).forEach { p ->\n                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))\n            }\n            lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, from, now).forEach { p ->\n                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))\n            }\n        } else if (credentials.hasCredential() && now - lastOfficialRecentAt >= 15L * 60L * 1000L) {\n            // Les observations horaires officielles ne changent pas toutes les minutes :\n            // on vérifie l'archive récente au plus toutes les 15 min, tandis que le\n            // fallback coordonné + forecast peut être rafraîchi chaque minute.\n            runCatching { fetchOfficialHourly(reference, from, now) }\n                .getOrDefault(emptyList())\n                .forEach { store.upsert(reference.key, it) }\n            lastOfficialRecentAt = now\n        }\n\n        reconstructShortGaps(reference.key, from, now)\n        store.reconcileMeasuredDominance(reference.key)\n        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n        val actual = store.query(reference.key, from, now)\n        return WeatherReferenceSyncResult(\n            measured = actual.count { it.source == PointSource.MEASURED },\n            reconstructed = actual.count { it.source == PointSource.RECONSTRUCTED },\n            forecast = forecast,\n            label = reference.label\n        )\n    }\n\n'''
    write("app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt", value.replace(marker, live + marker, 1))

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''        } else {\n            val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n            WeatherReferenceSyncResult(measured, reconstructed, forecast, reference.label)\n        }\n    }\n''',
    '''        } else {\n            refreshRecent(reference)\n        }\n    }\n''',
    "ensure cache live refresh"
)

# ---------------------------------------------------------------------------
# 3. Catalogue stations : toutes les candidates du secteur, et fallback public
#    sans token. Le token garde l'index Météo-France officiel prioritaire.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/StationDiscovery.kt",
    '''            .filter { it.distanceKm <= radius.toDouble() }\n            .sortedBy { it.distanceKm }\n            .take(24)\n            .toList()''',
    '''            .filter { it.distanceKm <= radius.toDouble() }\n            .sortedBy { it.distanceKm }\n            .toList()''',
    "station candidate cap"
)

old_fetch = '''    private fun fetchObservationStationIndex(): String {\n        val credential = credentials.get().trim()\n        if (credential.isBlank()) {\n            error("Token Météo-France requis pour découvrir toutes les stations")\n        }\n        val endpoints = listOf(\n            "https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations",\n            "https://public-api.meteofrance.fr/public/DPObs/liste-stations"\n        )\n        var last: Throwable? = null\n        endpoints.forEach { endpoint ->\n            runCatching { httpGet(endpoint, credential) }\n                .onSuccess { return it }\n                .onFailure { last = it }\n        }\n        throw last ?: IllegalStateException("Index des stations Météo-France indisponible")\n    }\n'''
new_fetch = '''    private fun fetchObservationStationIndex(): String {\n        val credential = credentials.get().trim()\n        val publicFallback = "https://www.infoclimat.fr/opendata/stations_xhr.php?format=geojson"\n        if (credential.isBlank()) {\n            // Sans compte Météo-France : catalogue public open-data élargi\n            // (stations nationales ouvertes + réseau StatIC).\n            return httpGet(publicFallback, null)\n        }\n        val endpoints = listOf(\n            "https://public-api.meteofrance.fr/public/DPObs/v1/liste-stations",\n            "https://public-api.meteofrance.fr/public/DPObs/liste-stations"\n        )\n        endpoints.forEach { endpoint ->\n            runCatching { httpGet(endpoint, credential) }.onSuccess { return it }\n        }\n        // Une panne de l'index officiel ne doit plus réduire l'UI aux 7 stations bootstrap.\n        return httpGet(publicFallback, null)\n    }\n'''
replace_once("app/src/main/java/com/fabdata/app/StationDiscovery.kt", old_fetch, new_fetch, "station public fallback")
replace_once(
    "app/src/main/java/com/fabdata/app/StationDiscovery.kt",
    '''            val id = firstString(props, "id", "geo_id_insee", "num_poste", "id_station") ?: continue\n            val name = firstString(props, "nom", "nom_usuel", "name", "station") ?: "Station $id"''',
    '''            val id = firstString(props, "id", "geo_id_insee", "num_poste", "id_station", "station_id", "code", "code_station", "numer_sta") ?: continue\n            val name = firstString(props, "nom", "nom_usuel", "name", "station", "libelle", "libelle_station", "lieu") ?: "Station $id"''',
    "generic station metadata"
)

# ---------------------------------------------------------------------------
# 4. UI station : carte + message de couverture honnête.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/StationDiscoveryUi.kt",
    '''    var result by remember { mutableStateOf<StationDiscoveryResult?>(null) }\n    var selectedIndex by remember { mutableIntStateOf(0) }\n''',
    '''    var result by remember { mutableStateOf<StationDiscoveryResult?>(null) }\n    var selectedIndex by remember { mutableIntStateOf(0) }\n    var mapOpen by remember { mutableStateOf(false) }\n''',
    "map state"
)
replace_once(
    "app/src/main/java/com/fabdata/app/StationDiscoveryUi.kt",
    '''                    info = "${found.anchor.label} · ${found.candidates.size} station(s) à ≤ ${found.radiusKm} km · $warm classée(s) sur ${found.historyLabel}"''',
    '''                    val catalogue = if (credentials.hasCredential()) "index Météo-France" else "catalogue public élargi"\n                    info = "${found.anchor.label} · ${found.candidates.size} station(s) à ≤ ${found.radiusKm} km · $warm classée(s) · $catalogue · ${found.historyLabel}"''',
    "catalog label"
)
replace_once(
    "app/src/main/java/com/fabdata/app/StationDiscoveryUi.kt",
    '''                    Button(\n                        onClick = { auto?.let { onSelect(it.reference, true) } },''',
    '''                    OutlinedButton(\n                        onClick = { mapOpen = true },\n                        enabled = !busy && found.candidates.isNotEmpty(),\n                        modifier = Modifier.fillMaxWidth()\n                    ) { Text("🗺 Choisir sur la carte") }\n\n                    Button(\n                        onClick = { auto?.let { onSelect(it.reference, true) } },''',
    "map button"
)
replace_once(
    "app/src/main/java/com/fabdata/app/StationDiscoveryUi.kt",
    '''        dismissButton = {\n            TextButton(onClick = onDismiss, enabled = !busy) { Text("Fermer") }\n        }\n    )\n}\n''',
    '''        dismissButton = {\n            TextButton(onClick = onDismiss, enabled = !busy) { Text("Fermer") }\n        }\n    )\n\n    val mapped = result\n    if (mapOpen && mapped != null && mapped.candidates.isNotEmpty()) {\n        StationMapDialog(\n            result = mapped,\n            initialIndex = selectedIndex,\n            onDismiss = { mapOpen = false },\n            onSelectIndex = { index ->\n                selectedIndex = index.coerceIn(0, mapped.candidates.lastIndex)\n                mapOpen = false\n                onSelect(mapped.candidates[selectedIndex].reference, false)\n            }\n        )\n    }\n}\n''',
    "map dialog"
)

# ---------------------------------------------------------------------------
# 5. Orchestrateur global + sélection graphique recentrée et draggable.
# ---------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''    var initialHandled by remember { mutableStateOf(false) }\n\n    val activeCurveStyles''',
    '''    var initialHandled by remember { mutableStateOf(false) }\n\n    // v0.17 : cet orchestrateur reste composé même quand les réglages thermiques\n    // sont loin sous le viewport du LazyColumn.\n    FabLiveUpdateCoordinator(\n        db = db,\n        lyonLab = lyonLab,\n        credentials = meteoCredentials,\n        dataVersion = reloadToken,\n        onDataChanged = { reloadToken++ }\n    )\n\n    val activeCurveStyles''',
    "global live coordinator"
)

# Le vieux one-shot Lyon est remplacé par le coordinateur focus + 60 s.
old_startup = '''    // v0.9.2 : Lyon est une sonde système permanente.\n    // Officiel si possible, secours automatique sinon. Le token n'agit jamais sur la visibilité.\n    LaunchedEffect(Unit) {\n        val result = runCatching { syncLyonHybrid(db, lyonWeather, meteoOfficial, meteoCredentials) }\n        reloadToken++\n        result.exceptionOrNull()?.let { error ->\n            snackbar.showSnackbar("Lyon non actualisé : ${error.message ?: "source indisponible"}")\n        }\n    }\n'''
replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    old_startup,
    '''    // v0.17 : la météo live est désormais pilotée par FabLiveUpdateCoordinator\n    // à l'ouverture, au retour au focus et ensuite toutes les 60 secondes.\n''',
    "remove startup one-shot"
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                        onSelectTimestamp = { ts ->\n                            // Un simple tap ne modifie PAS la fenêtre principale.\n                            // Il déplace uniquement la sélection dans la mini-vue.\n                            selectedTimestamp = ts\n                            selectedAnnotation = null\n                        },''',
    '''                        onSelectTimestamp = { ts ->\n                            // v0.17 : une sélection depuis le bandeau place la visée\n                            // au centre de la fenêtre détaillée tout en gardant son zoom.\n                            selectedTimestamp = ts\n                            windowCenterTimestamp = ts\n                            selectedAnnotation = null\n                        },''',
    "overview recenter"
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''            .pointerInput(from, to, resetKey) {\n                detectTransformGestures { _, pan, zoomChange, _ ->\n                    val oldVisible = 1f / zoom\n                    val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)\n                    zoom = newZoom\n                    val visible = 1f / zoom\n                    center = (center - (pan.x / size.width.toFloat()) * oldVisible)\n                        .coerceIn(visible / 2f, 1f - visible / 2f)\n                }\n            }''',
    '''            .pointerInput(from, to, resetKey, selectedTimestamp) {\n                detectTransformGestures { centroid, pan, zoomChange, _ ->\n                    val window = visibleWindow()\n                    val span = (window.last - window.first).coerceAtLeast(1L)\n                    val leftPx = 52.dp.toPx()\n                    val rightPx = size.width - 44.dp.toPx()\n                    val selectedX = selectedTimestamp\n                        ?.takeIf { it in window }\n                        ?.let { leftPx + ((it - window.first).toDouble() / span.toDouble()).toFloat() * (rightPx - leftPx) }\n                    val grabsSight = selectedX != null &&\n                        kotlin.math.abs(centroid.x - selectedX) <= 30.dp.toPx() &&\n                        zoomChange in 0.97f..1.03f\n\n                    if (grabsSight && centroid.x in leftPx..rightPx) {\n                        val frac = ((centroid.x - leftPx) / (rightPx - leftPx)).coerceIn(0f, 1f)\n                        onSelectTimestamp(window.first + (span * frac).toLong())\n                    } else {\n                        val oldVisible = 1f / zoom\n                        val newZoom = (zoom * zoomChange).coerceIn(1f, 720f)\n                        zoom = newZoom\n                        val visible = 1f / zoom\n                        center = (center - (pan.x / size.width.toFloat()) * oldVisible)\n                            .coerceIn(visible / 2f, 1f - visible / 2f)\n                    }\n                }\n            }''',
    "draggable sight"
)

# Les longues lacunes de la référence virtuelle ne doivent jamais être reliées.
replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                            sensor.stableKey == LyonWeatherSync.STABLE_KEY || sensor.id == THERMAL_INERTIA_SENSOR_ID\n''',
    '''                            sensor.stableKey == LyonWeatherSync.STABLE_KEY ||\n                            sensor.id == LYON_RECONSTRUCTED_SENSOR_ID || sensor.id == THERMAL_INERTIA_SENSOR_ID\n''',
    "weather virtual gap break"
)
replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                        val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&\n                            p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS''',
    '''                        val breakHere = (sensor.stableKey == LyonWeatherSync.STABLE_KEY || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID) &&\n                            p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS''',
    "weather humidity gap break"
)

old_cross = '''        selectedTimestamp?.takeIf { it in visibleFrom..visibleTo }?.let { ts ->\n            val x = mapX(ts)\n            drawLine(selectColor, Offset(x, top), Offset(x, bottom), strokeWidth = 2f)\n        }\n'''
new_cross = '''        selectedTimestamp?.takeIf { it in visibleFrom..visibleTo }?.let { ts ->\n            val x = mapX(ts)\n            drawLine(selectColor, Offset(x, top), Offset(x, bottom), strokeWidth = 2f)\n\n            // Heure directement sur la visée.\n            val sightPaint = android.graphics.Paint(centerPaint).apply {\n                color = selectColor.toArgbCompat()\n                textSize = 9.dp.toPx()\n                isFakeBoldText = true\n            }\n            drawContext.canvas.nativeCanvas.drawText(\n                formatDateTime(ts),\n                x.coerceIn(left + 54.dp.toPx(), right - 54.dp.toPx()),\n                top + 10.dp.toPx(),\n                sightPaint\n            )\n\n            // Petit trait horizontal + valeur colorée à la hauteur de chaque sonde.\n            sensors.filter { showTemp[it.id] == true }.forEach { sensor ->\n                val point = nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), ts) ?: return@forEach\n                val y = mapTemp(point.temperature)\n                if (y !in top..bottom) return@forEach\n                val markerColor = palette[sensor.colorIndex % palette.size]\n                drawLine(markerColor, Offset(x - 13.dp.toPx(), y), Offset(x + 13.dp.toPx(), y), strokeWidth = 2.2.dp.toPx())\n                drawCircle(markerColor, 3.2.dp.toPx(), Offset(x, y))\n                val valuePaint = android.graphics.Paint(paint).apply {\n                    color = markerColor.toArgbCompat()\n                    textSize = 9.dp.toPx()\n                    isFakeBoldText = true\n                }\n                val label = String.format(Locale.FRANCE, "%.1f°", point.temperature)\n                val width = valuePaint.measureText(label)\n                val tx = if (x + 18.dp.toPx() + width <= right) x + 18.dp.toPx() else x - 18.dp.toPx() - width\n                drawContext.canvas.nativeCanvas.drawText(label, tx, y - 4.dp.toPx(), valuePaint)\n            }\n        }\n'''
replace_once("app/src/main/java/com/fabdata/app/MainActivity.kt", old_cross, new_cross, "sight labels")

# ---------------------------------------------------------------------------
# 6. La carte thermique n'est plus l'orchestrateur des nouvelles mesures : elle
#    garde la référence/profile/manual, le coordinateur global fait le live.
# ---------------------------------------------------------------------------
old_logic = '''            val stamped = withContext(Dispatchers.IO) { coherenceStore.hasStampedCalculatedPoints() }\n            if (measuredChanged || referenceChanged || (dataChanged && stamped)) {\n                val why = when {\n                    measuredChanged -> "Nouvelles mesures réelles"\n                    referenceChanged -> "Référence météo modifiée"\n                    else -> "Données sources modifiées"\n                }\n                rationalizeCurves(why, profile, manual = false)\n            } else {\n                refresh(allHistory = false, triggerChartReload = true)\n            }\n'''
new_logic = '''            when {\n                referenceChanged -> rationalizeCurves("Référence météo modifiée", profile, manual = false)\n                measuredChanged -> {\n                    // Le coordinateur global, toujours composé, traite la chaîne lourde.\n                    // Cette carte ne lance pas un second recalcul concurrent.\n                    info = "Nouvelle mesure réelle détectée · synchronisation globale en cours…"\n                }\n                dataChanged -> {\n                    status = withContext(Dispatchers.IO) { runCatching { engine.status(reference, selectedSensorId, profile) }.getOrNull() }\n                }\n                else -> refresh(allHistory = false, triggerChartReload = true)\n            }\n'''
replace_once("app/src/main/java/com/fabdata/app/ThermalUi.kt", old_logic, new_logic, "lazy card orchestration")

# Invariants de sécurité et de fonctionnalité.
checks = {
    "app/build.gradle.kts": ['versionCode = 32', 'versionName = "0.17.0"', 'org.maplibre.gl:android-sdk:13.4.1'],
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt": ['fun reconcileMeasuredDominance(db: FabDataDb)', 'Une mesure réelle ne peut jamais être invalidée'],
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt": ['fun refreshRecent(reference: WeatherReference)', 'fun reconcileMeasuredDominance(referenceKey: String)'],
    "app/src/main/java/com/fabdata/app/MainActivity.kt": ['FabLiveUpdateCoordinator(', 'grabsSight', 'formatDateTime(ts)'],
    "app/src/main/java/com/fabdata/app/StationDiscoveryUi.kt": ['Choisir sur la carte', 'StationMapDialog('],
}
for path, needles in checks.items():
    value = text(path)
    for needle in needles:
        if needle not in value:
            raise SystemExit(f"Invariant absent {path}: {needle}")

print("FabData v0.17 live coherence + sight + station map patch applied")
