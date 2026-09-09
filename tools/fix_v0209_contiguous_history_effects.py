from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"pattern not found in {path}: {old[:120]!r}")
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")


def replace_all(path: str, old: str, new: str):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"pattern not found in {path}: {old[:120]!r}")
    text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")

# -----------------------------------------------------------------------------
# Weather: derive the backward cursor from ACTUAL contiguous data, never clicks.
# -----------------------------------------------------------------------------
weather = "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt"

replace_once(
    weather,
'''    fun historyBounds(referenceKey: String): LongRange? {
        db.readableDatabase.rawQuery(
            "SELECT MIN(timestamp), MAX(timestamp) FROM weather_reference_samples WHERE reference_key=? AND source<>'forecast'",
            arrayOf(referenceKey)
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    fun clear(referenceKey: String) {''',
'''    fun historyBounds(referenceKey: String): LongRange? {
        db.readableDatabase.rawQuery(
            "SELECT MIN(timestamp), MAX(timestamp) FROM weather_reference_samples WHERE reference_key=? AND source<>'forecast'",
            arrayOf(referenceKey)
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    /**
     * Portion réellement continue de la météo en remontant depuis le présent.
     *
     * On raisonne par heures distinctes (une station peut contenir plusieurs mesures
     * dans la même heure). Jusqu'à 3 heures manquantes isolées sont tolérées, comme
     * dans WeatherReferenceCoverage.ready. En revanche un îlot ancien séparé par un
     * gros trou n'allonge JAMAIS artificiellement la profondeur.
     */
    fun continuousHistoryRange(
        referenceKey: String,
        now: Long = System.currentTimeMillis(),
        maxMissingHours: Int = 3,
        recentToleranceHours: Int = 36
    ): LongRange? {
        val hourMs = 60L * 60L * 1000L
        val nowHour = (now / hourMs) * hourMs
        val hours = ArrayList<Long>()
        var previousHour: Long? = null
        db.readableDatabase.rawQuery(
            "SELECT timestamp FROM weather_reference_samples WHERE reference_key=? AND source<>'forecast' ORDER BY timestamp DESC",
            arrayOf(referenceKey)
        ).use { c ->
            while (c.moveToNext()) {
                val hour = (c.getLong(0) / hourMs) * hourMs
                if (hour != previousHour) {
                    hours += hour
                    previousHour = hour
                }
            }
        }
        if (hours.isEmpty()) return null
        val newest = hours.first()
        if (nowHour - newest > recentToleranceHours.toLong() * hourMs) return null

        var oldest = newest
        val maximumStepHours = maxMissingHours.coerceAtLeast(0) + 1L
        for (index in 1 until hours.size) {
            val candidate = hours[index]
            val stepHours = ((oldest - candidate) / hourMs).coerceAtLeast(0L)
            if (stepHours > maximumStepHours) break
            oldest = candidate
        }
        return oldest..newest
    }

    fun continuousHistoryDepthDays(referenceKey: String, now: Long = System.currentTimeMillis()): Int {
        val range = continuousHistoryRange(referenceKey, now) ?: return 0
        val dayMs = 24L * 60L * 60L * 1000L
        val nowHour = (now / (60L * 60L * 1000L)) * (60L * 60L * 1000L)
        return ((nowHour - range.first).coerceAtLeast(0L) / dayMs).toInt().coerceAtMost(3650)
    }

    fun clear(referenceKey: String) {'''
)

replace_once(
    weather,
'''data class WeatherReferencePreparation(
    val sync: WeatherReferenceSyncResult,
    val coverage: WeatherReferenceCoverage,
    val days: Int
)''',
'''data class WeatherReferencePreparation(
    val sync: WeatherReferenceSyncResult,
    val coverage: WeatherReferenceCoverage,
    val days: Int,
    /** Profondeur réellement continue depuis le présent, jamais un compteur de clics. */
    val continuousDepthDays: Int = 0
)'''
)

replace_once(
    weather,
'''    fun extendHistoryBackward(
        reference: WeatherReference,
        alreadyLoadedDays: Int,
        requestedStepDays: Int = 90
    ): WeatherReferencePreparation {
        val depth = alreadyLoadedDays.coerceAtLeast(0)
        val step = requestedStepDays.coerceIn(1, 90)
        val dayMs = 24L * hourMs
        val now = roundHour(System.currentTimeMillis())
        val to = now - depth.toLong() * dayMs
        val from = to - step.toLong() * dayMs
        return prepareHistoryRange(reference, from, to)
    }''',
'''    fun extendHistoryBackward(
        reference: WeatherReference,
        requestedStepDays: Int = 90
    ): WeatherReferencePreparation {
        val step = requestedStepDays.coerceIn(1, 90)
        val dayMs = 24L * hourMs
        val now = roundHour(System.currentTimeMillis())

        // v0.20.9 anti-trou : le curseur n'est plus reconstructedDepthDays.
        // Il part du bord le plus ancien de la portion réellement CONTINUE.
        // Les îlots plus vieux sont conservés mais ignorés jusqu'à ce que le raccord
        // soit effectivement rempli.
        val contiguous = store.continuousHistoryRange(reference.key, now)
        val to = contiguous?.first ?: now
        val from = to - step.toLong() * dayMs
        val prepared = prepareHistoryRange(reference, from, to)
        val actualDepth = store.continuousHistoryDepthDays(reference.key, now)
        return prepared.copy(continuousDepthDays = actualDepth)
    }

    fun continuousHistoryDepthDays(referenceKey: String): Int =
        store.continuousHistoryDepthDays(referenceKey)'''
)

# Migration journal: keep the display value, but make it a measured cache.
migration = "app/src/main/java/com/fabdata/app/WeatherReferenceMigration.kt"
replace_once(
    migration,
'''    fun addReconstructedDepth(days: Int) {
        val current = load() ?: return
        val next = (current.reconstructedDepthDays + days.coerceAtLeast(0)).coerceAtMost(3650)
        prefs.edit()
            .putInt("reconstructed_depth_days", next)
            .putLong("last_action_at", System.currentTimeMillis())
            .apply()
    }''',
'''    fun addReconstructedDepth(days: Int) {
        val current = load() ?: return
        val next = (current.reconstructedDepthDays + days.coerceAtLeast(0)).coerceAtMost(3650)
        setReconstructedDepth(next)
    }

    /** v0.20.9 : cette valeur est un cache de la profondeur CONTINUE réellement observée. */
    fun setReconstructedDepth(days: Int) {
        if (load() == null) return
        prefs.edit()
            .putInt("reconstructed_depth_days", days.coerceIn(0, 3650))
            .putLong("last_action_at", System.currentTimeMillis())
            .apply()
    }'''
)

thermal_ui = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
replace_once(
    thermal_ui,
'''    var weatherMigration by remember { mutableStateOf(weatherMigrationStore.load()) }
    var trainedModel by remember { mutableStateOf<ThermalModel?>(null) }''',
'''    var weatherMigration by remember { mutableStateOf(weatherMigrationStore.load()) }

    // Répare aussi les anciens compteurs v0.20.5-v0.20.8 au premier affichage :
    // la profondeur affichée devient la profondeur réellement continue de la station.
    LaunchedEffect(reference.key, dataVersion) {
        val pending = weatherMigrationStore.load()?.takeIf { it.newKey == reference.key }
        if (pending != null) {
            val actual = withContext(Dispatchers.IO) {
                manager.continuousHistoryDepthDays(reference.key)
            }
            if (actual != pending.reconstructedDepthDays) {
                weatherMigrationStore.setReconstructedDepth(actual)
                weatherMigration = weatherMigrationStore.load()
            }
        }
    }

    var trainedModel by remember { mutableStateOf<ThermalModel?>(null) }'''
)

replace_once(
    thermal_ui,
'''                manager.extendHistoryBackward(
                    reference = reference,
                    alreadyLoadedDays = migration.reconstructedDepthDays,
                    requestedStepDays = 90
                )''',
'''                manager.extendHistoryBackward(
                    reference = reference,
                    requestedStepDays = 90
                )'''
)

replace_once(
    thermal_ui,
'''            onSuccess = { prepared ->
                weatherMigrationStore.addReconstructedDepth(90)
                weatherMigration = weatherMigrationStore.load()
                val depth = weatherMigration?.reconstructedDepthDays ?: 90
                info = "${reference.label} · météo étendue à ~$depth j vers le passé · couverture ${(prepared.coverage.coverage * 100).toInt()} %"
                suppressNextAuto = true
                onDataChanged()
                FabOperationRegistry.finish(operationId, info)
            },''',
'''            onSuccess = { prepared ->
                val depth = prepared.continuousDepthDays
                weatherMigrationStore.setReconstructedDepth(depth)
                weatherMigration = weatherMigrationStore.load()
                val coveragePct = (prepared.coverage.coverage * 100).toInt()
                info = if (prepared.coverage.ready) {
                    "${reference.label} · profondeur continue ~$depth j · bloc $coveragePct %"
                } else {
                    "${reference.label} · bloc incomplet ($coveragePct %) · profondeur continue ~$depth j · le prochain +90 j reprend au premier trou"
                }
                suppressNextAuto = true
                onDataChanged()
                FabOperationRegistry.finish(operationId, info)
            },'''
)

replace_all(
    thermal_ui,
'''Profondeur nouvelle station : ~${migration.reconstructedDepthDays} j.''',
'''Profondeur CONTINUE nouvelle station : ~${migration.reconstructedDepthDays} j.'''
)

# -----------------------------------------------------------------------------
# More base sensor colors.
# -----------------------------------------------------------------------------
data = "app/src/main/java/com/fabdata/app/DataLayer.kt"
replace_once(data, '''            c.getInt(0) % 8''', '''            c.getInt(0) % 16''')
replace_once(data, '''            put("color_index", colorIndex.coerceIn(0, 7))''', '''            put("color_index", colorIndex.coerceIn(0, 15))''')

main = "app/src/main/java/com/fabdata/app/MainActivity.kt"
replace_once(
    main,
'''private val palette = listOf(
    Color(0xFF1769AA),
    Color(0xFFD1495B),
    Color(0xFF2A9D8F),
    Color(0xFFE08E0B),
    Color(0xFF6A4C93),
    Color(0xFF0081A7),
    Color(0xFFB56576),
    Color(0xFF588157)
)''',
'''private val palette = listOf(
    Color(0xFF1769AA), Color(0xFFD1495B), Color(0xFF2A9D8F), Color(0xFFE08E0B),
    Color(0xFF6A4C93), Color(0xFF0081A7), Color(0xFFB56576), Color(0xFF588157),
    Color(0xFF9C27B0), Color(0xFFE91E63), Color(0xFF00BFA5), Color(0xFFC0CA33),
    Color(0xFFFF7043), Color(0xFF3949AB), Color(0xFF8D6E63), Color(0xFF546E7A)
)'''
)

# Do not visually bridge huge missing-weather gaps in either overview level.
replace_once(
    main,
'''                                val path = Path()
                                points.forEachIndexed { index, point ->
                                    val x = (((point.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                                        .coerceIn(0f, size.width)
                                    val y = size.height - (((point.temperature - navigatorMin) / navigatorTempRange)
                                        .toFloat() * size.height)
                                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                                }''',
'''                                val path = Path()
                                var previous: SamplePoint? = null
                                val navigatorGapLimit = maxOf(
                                    12L * 60L * 60L * 1000L,
                                    fullSpan / 120L
                                )
                                points.forEach { point ->
                                    val x = (((point.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                                        .coerceIn(0f, size.width)
                                    val y = size.height - (((point.temperature - navigatorMin) / navigatorTempRange)
                                        .toFloat() * size.height)
                                    val weatherCurve = sensor.stableKey == LyonWeatherSync.STABLE_KEY ||
                                        sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID
                                    val breakHere = weatherCurve && previous?.let {
                                        point.timestamp - it.timestamp > navigatorGapLimit
                                    } == true
                                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                                    previous = point
                                }'''
)

replace_once(
    main,
'''                                    val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                                        previous?.let { point.timestamp - it.timestamp > previewGapLimit } == true''',
'''                                    val weatherCurve = sensor.stableKey == LyonWeatherSync.STABLE_KEY ||
                                        sensor.id == WEATHER_OFFICIAL_SENSOR_ID || sensor.id == LYON_RECONSTRUCTED_SENSOR_ID
                                    val breakHere = weatherCurve &&
                                        previous?.let { point.timestamp - it.timestamp > previewGapLimit } == true'''
)

# Third personalization layer: animated decorations around the temperature curve.
replace_once(
    main,
'''                // Nuage d'incertitude : +σ, -σ, +σ... Les marqueurs deviennent
                // volontairement plus rares quand l'horizon s'éloigne.''',
'''                // v0.20.9 : troisième couche de personnalisation, indépendante de
                // la couleur et de l'aura. Elle reste volontairement légère : au plus
                // quelques dizaines de particules, même sur plusieurs années de data.
                if (visual.effectA != "NONE" || visual.effectB != "NONE") {
                    val effectStride = (points.size / 36).coerceAtLeast(1)
                    val effectPoints = points
                        .filterIndexed { index, _ -> index % effectStride == 0 }
                        .take(40)
                        .map { Offset(mapX(it.timestamp), mapTemp(it.temperature)) }
                    drawCurveDecorations(
                        points = effectPoints,
                        prefs = visual,
                        baseColor = if (color.alpha > 0f) color else baseColor.copy(alpha = visual.opacity),
                        tickMs = styleTick,
                        seed = sensor.id.toInt()
                    )
                }

                // Nuage d'incertitude : +σ, -σ, +σ... Les marqueurs deviennent
                // volontairement plus rares quand l'horizon s'éloigne.'''
)

# -----------------------------------------------------------------------------
# Existing curve personalization: add colors, auras and a third animated effect layer.
# -----------------------------------------------------------------------------
lyon = "app/src/main/java/com/fabdata/app/LyonLabLayer.kt"
replace_once(
    lyon,
'''import androidx.compose.ui.graphics.drawscope.Stroke''',
'''import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke'''
)
replace_once(
    lyon,
'''data class CurveVisualPrefs(
    val styleA: String = "BASE",
    val styleB: String = "BASE",
    val auraA: String = "NONE",
    val auraB: String = "NONE",
    val opacity: Float = 1f
)''',
'''data class CurveVisualPrefs(
    val styleA: String = "BASE",
    val styleB: String = "BASE",
    val auraA: String = "NONE",
    val auraB: String = "NONE",
    /** Troisième couche : particules/objets animés autour de la courbe. */
    val effectA: String = "NONE",
    val effectB: String = "NONE",
    val effectDensity: Float = 0.45f,
    val effectOrbit: Float = 0.55f,
    val opacity: Float = 1f
)'''
)

replace_once(
    lyon,
'''        auraA = prefs.getString("$key.auraA", "NONE") ?: "NONE",
        auraB = prefs.getString("$key.auraB", "NONE") ?: "NONE",
        opacity = prefs.getFloat("$key.opacity", 1f).coerceIn(0f, 1f)''',
'''        auraA = prefs.getString("$key.auraA", "NONE") ?: "NONE",
        auraB = prefs.getString("$key.auraB", "NONE") ?: "NONE",
        effectA = prefs.getString("$key.effectA", "NONE") ?: "NONE",
        effectB = prefs.getString("$key.effectB", "NONE") ?: "NONE",
        effectDensity = prefs.getFloat("$key.effectDensity", 0.45f).coerceIn(0.08f, 1f),
        effectOrbit = prefs.getFloat("$key.effectOrbit", 0.55f).coerceIn(0f, 1f),
        opacity = prefs.getFloat("$key.opacity", 1f).coerceIn(0f, 1f)'''
)
replace_once(
    lyon,
'''            .putString("$key.auraA", value.auraA)
            .putString("$key.auraB", value.auraB)
            .putFloat("$key.opacity", value.opacity.coerceIn(0f, 1f))''',
'''            .putString("$key.auraA", value.auraA)
            .putString("$key.auraB", value.auraB)
            .putString("$key.effectA", value.effectA)
            .putString("$key.effectB", value.effectB)
            .putFloat("$key.effectDensity", value.effectDensity.coerceIn(0.08f, 1f))
            .putFloat("$key.effectOrbit", value.effectOrbit.coerceIn(0f, 1f))
            .putFloat("$key.opacity", value.opacity.coerceIn(0f, 1f))'''
)

replace_once(
    lyon,
'''private val STYLE_OPTIONS = listOf(
    "BASE", "RED", "ORANGE", "YELLOW", "GREEN", "CYAN", "BLUE", "PURPLE",
    "RAINBOW", "IRIDESCENT", "NONE"
)
private val AURA_OPTIONS = listOf("NONE", "SUN", "SHADOW", "ICE", "NATURE")''',
'''private val STYLE_OPTIONS = listOf(
    "BASE", "RED", "ORANGE", "YELLOW", "GREEN", "LIME", "MINT", "CYAN", "TEAL",
    "BLUE", "INDIGO", "PURPLE", "MAGENTA", "PINK", "CORAL", "GOLD", "BROWN", "SLATE",
    "RAINBOW", "IRIDESCENT", "RANDOM_COLOR", "NONE"
)
private val AURA_OPTIONS = listOf(
    "NONE", "SUN", "SHADOW", "ICE", "NATURE", "FIRE", "NEON", "MAGIC", "SMOKE", "ROSE"
)
private val EFFECT_OPTIONS = listOf(
    "NONE", "SPARKLE", "FIREWORKS", "FLY", "DRIP", "SMOKE", "FISH", "BIRD",
    "ORBIT", "COMET", "BUBBLES", "FIREFLY", "BUTTERFLY", "RAIN", "PLANET", "RANDOM"
)
private val RANDOM_EFFECT_POOL = EFFECT_OPTIONS.filterNot { it == "NONE" || it == "RANDOM" }'''
)

replace_once(
    lyon,
'''        style == "GREEN" -> Color(0xFF43A047).copy(alpha = alpha)
        style == "CYAN" -> Color(0xFF00ACC1).copy(alpha = alpha)
        style == "BLUE" -> Color(0xFF1E88E5).copy(alpha = alpha)
        style == "PURPLE" -> Color(0xFF8E24AA).copy(alpha = alpha)
        style == "RAINBOW" -> {''',
'''        style == "GREEN" -> Color(0xFF43A047).copy(alpha = alpha)
        style == "LIME" -> Color(0xFFC0CA33).copy(alpha = alpha)
        style == "MINT" -> Color(0xFF00BFA5).copy(alpha = alpha)
        style == "CYAN" -> Color(0xFF00ACC1).copy(alpha = alpha)
        style == "TEAL" -> Color(0xFF00897B).copy(alpha = alpha)
        style == "BLUE" -> Color(0xFF1E88E5).copy(alpha = alpha)
        style == "INDIGO" -> Color(0xFF3949AB).copy(alpha = alpha)
        style == "PURPLE" -> Color(0xFF8E24AA).copy(alpha = alpha)
        style == "MAGENTA" -> Color(0xFFD81B60).copy(alpha = alpha)
        style == "PINK" -> Color(0xFFF06292).copy(alpha = alpha)
        style == "CORAL" -> Color(0xFFFF7043).copy(alpha = alpha)
        style == "GOLD" -> Color(0xFFFFB300).copy(alpha = alpha)
        style == "BROWN" -> Color(0xFF8D6E63).copy(alpha = alpha)
        style == "SLATE" -> Color(0xFF546E7A).copy(alpha = alpha)
        style == "RAINBOW" -> {'''
)
replace_once(
    lyon,
'''        style == "IRIDESCENT" -> {
            val hue = ((tickMs / 45L + (position * 160f).toLong()) % 360L).toFloat()
            Color.hsv(hue, 0.42f, 1f, alpha)
        }
        style.startsWith("CUSTOM:") -> {''',
'''        style == "IRIDESCENT" -> {
            val hue = ((tickMs / 45L + (position * 160f).toLong()) % 360L).toFloat()
            Color.hsv(hue, 0.42f, 1f, alpha)
        }
        style == "RANDOM_COLOR" -> {
            val seed = ((tickMs / 4200L) * 97L + (position * 1000f).toLong())
            val hue = ((seed % 360L) + 360L).toFloat() % 360f
            Color.hsv(hue, 0.78f, 0.96f, alpha)
        }
        style.startsWith("CUSTOM:") -> {'''
)

replace_once(
    lyon,
'''        "NATURE" -> Color(0xFF66BB6A).copy(alpha = 0.23f * prefs.opacity)
        else -> null
    }
}

@Composable
fun CurveStyleDialog(''',
'''        "NATURE" -> Color(0xFF66BB6A).copy(alpha = 0.23f * prefs.opacity)
        "FIRE" -> Color(0xFFFF5722).copy(alpha = 0.27f * prefs.opacity)
        "NEON" -> Color(0xFF00E5FF).copy(alpha = 0.30f * prefs.opacity)
        "MAGIC" -> Color(0xFFB388FF).copy(alpha = 0.29f * prefs.opacity)
        "SMOKE" -> Color(0xFF78909C).copy(alpha = 0.20f * prefs.opacity)
        "ROSE" -> Color(0xFFF48FB1).copy(alpha = 0.26f * prefs.opacity)
        else -> null
    }
}

fun resolveCurveEffect(prefs: CurveVisualPrefs, tickMs: Long, seed: Int): String {
    val useB = prefs.effectA != prefs.effectB && ((tickMs / 3300L) % 2L == 1L)
    val raw = if (useB) prefs.effectB else prefs.effectA
    if (raw != "RANDOM" || RANDOM_EFFECT_POOL.isEmpty()) return raw
    val slot = tickMs / 5200L
    val index = kotlin.math.abs((slot + seed.toLong() * 31L) % RANDOM_EFFECT_POOL.size.toLong()).toInt()
    return RANDOM_EFFECT_POOL[index]
}

/**
 * Décor procédural ultra-léger : aucun bitmap, aucun objet persistant, aucune incidence
 * sur les données. Les positions sont déterministes à partir de la courbe + tick.
 */
fun DrawScope.drawCurveDecorations(
    points: List<Offset>,
    prefs: CurveVisualPrefs,
    baseColor: Color,
    tickMs: Long,
    seed: Int
) {
    if (points.isEmpty() || prefs.opacity <= 0f) return
    val effect = resolveCurveEffect(prefs, tickMs, seed)
    if (effect == "NONE") return

    val density = prefs.effectDensity.coerceIn(0.08f, 1f)
    val wanted = (5f + density * 23f).toInt().coerceIn(4, 28)
    val stride = (points.size / wanted).coerceAtLeast(1)
    val selected = points.filterIndexed { index, _ -> index % stride == 0 }.take(wanted)
    val orbit = (2.5f + 13f * prefs.effectOrbit.coerceIn(0f, 1f)).dp.toPx()
    val time = tickMs / 1000.0
    val alpha = (0.28f + 0.62f * prefs.opacity).coerceIn(0.18f, 0.92f)

    fun orbited(p: Offset, index: Int, speed: Double = 2.0): Offset {
        val phase = time * speed + index * 1.73 + seed * 0.117
        return Offset(
            p.x + kotlin.math.cos(phase).toFloat() * orbit,
            p.y + kotlin.math.sin(phase).toFloat() * orbit
        )
    }

    when (effect) {
        "SPARKLE" -> selected.forEachIndexed { i, p ->
            val q = orbited(p, i, 2.8)
            val pulse = (0.45 + 0.55 * kotlin.math.abs(kotlin.math.sin(time * 4.0 + i))).toFloat()
            val r = (1.4f + pulse * 3.2f).dp.toPx()
            val c = baseColor.copy(alpha = alpha * pulse)
            drawLine(c, Offset(q.x - r, q.y), Offset(q.x + r, q.y), 1.2.dp.toPx())
            drawLine(c, Offset(q.x, q.y - r), Offset(q.x, q.y + r), 1.2.dp.toPx())
            drawLine(c.copy(alpha = c.alpha * 0.75f), Offset(q.x - r * .65f, q.y - r * .65f), Offset(q.x + r * .65f, q.y + r * .65f), .8.dp.toPx())
        }
        "FIREWORKS" -> selected.filterIndexed { i, _ -> i % 5 == 0 }.forEachIndexed { i, p ->
            val phase = ((tickMs + i * 211L) % 1500L) / 1500f
            val radius = (3f + phase * 15f).dp.toPx()
            val c = baseColor.copy(alpha = alpha * (1f - phase).coerceAtLeast(.15f))
            repeat(8) { ray ->
                val a = ray * Math.PI / 4.0
                val end = Offset(p.x + kotlin.math.cos(a).toFloat() * radius, p.y + kotlin.math.sin(a).toFloat() * radius)
                drawLine(c, p, end, 1.dp.toPx())
            }
        }
        "FLY" -> selected.filterIndexed { i, _ -> i % 3 == 0 }.forEachIndexed { i, p ->
            val q = orbited(p, i, 4.7)
            val body = Color(0xFF263238).copy(alpha = alpha)
            drawCircle(body, 1.9.dp.toPx(), q)
            drawCircle(baseColor.copy(alpha = alpha * .45f), 2.2.dp.toPx(), Offset(q.x - 2.dp.toPx(), q.y - 1.4.dp.toPx()))
            drawCircle(baseColor.copy(alpha = alpha * .45f), 2.2.dp.toPx(), Offset(q.x + 2.dp.toPx(), q.y - 1.4.dp.toPx()))
        }
        "DRIP" -> selected.filterIndexed { i, _ -> i % 2 == 0 }.forEachIndexed { i, p ->
            val fall = ((tickMs / 12L + i * 17L) % 26L).toFloat().dp.toPx()
            val q = Offset(p.x, p.y + 3.dp.toPx() + fall)
            val c = baseColor.copy(alpha = alpha * (1f - fall / 40.dp.toPx()).coerceIn(.25f, 1f))
            drawLine(c.copy(alpha = c.alpha * .55f), p, q, .9.dp.toPx())
            drawCircle(c, 2.1.dp.toPx(), q)
        }
        "SMOKE" -> selected.filterIndexed { i, _ -> i % 2 == 0 }.forEachIndexed { i, p ->
            val rise = ((tickMs / 30L + i * 11L) % 22L).toFloat().dp.toPx()
            val q = Offset(p.x + kotlin.math.sin(time * 1.3 + i).toFloat() * 5.dp.toPx(), p.y - rise)
            val smoke = Color(0xFF78909C).copy(alpha = alpha * .20f)
            drawCircle(smoke, (4f + i % 3 * 1.5f).dp.toPx(), q)
            drawCircle(smoke.copy(alpha = smoke.alpha * .7f), (2.5f + i % 2).dp.toPx(), Offset(q.x + 4.dp.toPx(), q.y - 3.dp.toPx()))
        }
        "FISH" -> selected.filterIndexed { i, _ -> i % 4 == 0 }.forEachIndexed { i, p ->
            val q = orbited(p, i, 1.35)
            val c = baseColor.copy(alpha = alpha)
            val bodyR = 3.2.dp.toPx()
            drawCircle(c, bodyR, q)
            val tailX = q.x - 6.dp.toPx()
            drawLine(c, Offset(q.x - bodyR, q.y), Offset(tailX, q.y - 3.dp.toPx()), 1.4.dp.toPx())
            drawLine(c, Offset(q.x - bodyR, q.y), Offset(tailX, q.y + 3.dp.toPx()), 1.4.dp.toPx())
            drawCircle(Color.White.copy(alpha = .9f), .8.dp.toPx(), Offset(q.x + 1.7.dp.toPx(), q.y - .8.dp.toPx()))
        }
        "BIRD" -> selected.filterIndexed { i, _ -> i % 4 == 0 }.forEachIndexed { i, p ->
            val q = orbited(Offset(p.x, p.y - 5.dp.toPx()), i, 1.8)
            val wing = (3.5f + 1.8f * kotlin.math.abs(kotlin.math.sin(time * 5 + i)).toFloat()).dp.toPx()
            val c = baseColor.copy(alpha = alpha)
            drawLine(c, Offset(q.x - wing, q.y), q, 1.4.dp.toPx())
            drawLine(c, q, Offset(q.x + wing, q.y), 1.4.dp.toPx())
            drawLine(c, Offset(q.x - wing, q.y), Offset(q.x - wing * .45f, q.y - 2.dp.toPx()), 1.dp.toPx())
            drawLine(c, Offset(q.x + wing, q.y), Offset(q.x + wing * .45f, q.y - 2.dp.toPx()), 1.dp.toPx())
        }
        "ORBIT" -> selected.forEachIndexed { i, p ->
            val q = orbited(p, i, 2.2)
            drawCircle(baseColor.copy(alpha = alpha * .22f), orbit, p, style = Stroke(width = .55.dp.toPx()))
            drawCircle(baseColor.copy(alpha = alpha), 1.8.dp.toPx(), q)
        }
        "COMET" -> selected.filterIndexed { i, _ -> i % 3 == 0 }.forEachIndexed { i, p ->
            val q = orbited(p, i, 2.5)
            val phase = time * 2.5 + i
            val tail = Offset(q.x - kotlin.math.cos(phase).toFloat() * 10.dp.toPx(), q.y - kotlin.math.sin(phase).toFloat() * 10.dp.toPx())
            drawLine(baseColor.copy(alpha = alpha * .45f), tail, q, 2.dp.toPx())
            drawCircle(Color.White.copy(alpha = alpha), 2.1.dp.toPx(), q)
        }
        "BUBBLES" -> selected.forEachIndexed { i, p ->
            val rise = ((tickMs / 25L + i * 13L) % 28L).toFloat().dp.toPx()
            val q = Offset(p.x + kotlin.math.sin(time + i).toFloat() * orbit * .45f, p.y - rise)
            drawCircle(baseColor.copy(alpha = alpha * .48f), (2.4f + i % 3).dp.toPx(), q, style = Stroke(width = .9.dp.toPx()))
        }
        "FIREFLY" -> selected.forEachIndexed { i, p ->
            val q = orbited(p, i, 3.1)
            val pulse = (0.45 + 0.55 * kotlin.math.abs(kotlin.math.sin(time * 3.7 + i))).toFloat()
            drawCircle(Color(0xFFFFF176).copy(alpha = alpha * .18f * pulse), 6.dp.toPx(), q)
            drawCircle(Color(0xFFFFEB3B).copy(alpha = alpha * pulse), 1.6.dp.toPx(), q)
        }
        "BUTTERFLY" -> selected.filterIndexed { i, _ -> i % 4 == 0 }.forEachIndexed { i, p ->
            val q = orbited(p, i, 2.7)
            val flap = (2.2f + 2f * kotlin.math.abs(kotlin.math.sin(time * 6 + i)).toFloat()).dp.toPx()
            val wing = baseColor.copy(alpha = alpha * .58f)
            drawCircle(wing, flap, Offset(q.x - flap * .8f, q.y))
            drawCircle(wing, flap, Offset(q.x + flap * .8f, q.y))
            drawLine(Color(0xFF37474F).copy(alpha = alpha), Offset(q.x, q.y - 2.dp.toPx()), Offset(q.x, q.y + 2.dp.toPx()), 1.dp.toPx())
        }
        "RAIN" -> selected.forEachIndexed { i, p ->
            val fall = ((tickMs / 10L + i * 19L) % 24L).toFloat().dp.toPx()
            val q = Offset(p.x + (i % 3 - 1) * 3.dp.toPx(), p.y + fall)
            val c = Color(0xFF42A5F5).copy(alpha = alpha * .55f)
            drawLine(c, Offset(q.x, q.y - 5.dp.toPx()), q, 1.dp.toPx())
        }
        "PLANET" -> selected.filterIndexed { i, _ -> i % 5 == 0 }.forEachIndexed { i, p ->
            val q = orbited(p, i, .9)
            val c = baseColor.copy(alpha = alpha)
            drawCircle(c, 3.1.dp.toPx(), q)
            drawCircle(c.copy(alpha = alpha * .55f), 5.5.dp.toPx(), q, style = Stroke(width = .8.dp.toPx()))
            drawLine(c.copy(alpha = alpha * .55f), Offset(q.x - 6.dp.toPx(), q.y + 1.dp.toPx()), Offset(q.x + 6.dp.toPx(), q.y - 1.dp.toPx()), .8.dp.toPx())
        }
    }
}

@Composable
fun CurveStyleDialog('''
)

# Human labels for all new choices.
replace_once(
    lyon,
'''        "GREEN" -> "Vert"
        "CYAN" -> "Cyan"
        "BLUE" -> "Bleu"
        "PURPLE" -> "Violet"
        "RAINBOW" -> "Arc-en-ciel"
        "IRIDESCENT" -> "Iridescence"
        "NONE" -> "Pas de couleur"
        "SUN" -> "Soleil"
        "SHADOW" -> "Ombre"
        "ICE" -> "Glace"
        "NATURE" -> "Nature"''',
'''        "GREEN" -> "Vert"
        "LIME" -> "Citron"
        "MINT" -> "Menthe"
        "CYAN" -> "Cyan"
        "TEAL" -> "Sarcelle"
        "BLUE" -> "Bleu"
        "INDIGO" -> "Indigo"
        "PURPLE" -> "Violet"
        "MAGENTA" -> "Magenta"
        "PINK" -> "Rose"
        "CORAL" -> "Corail"
        "GOLD" -> "Or"
        "BROWN" -> "Brun"
        "SLATE" -> "Ardoise"
        "RAINBOW" -> "Arc-en-ciel"
        "IRIDESCENT" -> "Iridescence"
        "RANDOM_COLOR" -> "Couleur aléatoire"
        "NONE" -> "Aucun / aucune"
        "SUN" -> "Soleil"
        "SHADOW" -> "Ombre"
        "ICE" -> "Glace"
        "NATURE" -> "Nature"
        "FIRE" -> "Feu"
        "NEON" -> "Néon"
        "MAGIC" -> "Magique"
        "SMOKE" -> "Fumée"
        "ROSE" -> "Halo rose"
        "SPARKLE" -> "Étincelles"
        "FIREWORKS" -> "Feu d’artifice"
        "FLY" -> "Mouches"
        "DRIP" -> "Goutte à goutte"
        "FISH" -> "Poissons"
        "BIRD" -> "Oiseaux"
        "ORBIT" -> "Orbites"
        "COMET" -> "Comètes"
        "BUBBLES" -> "Bulles"
        "FIREFLY" -> "Lucioles"
        "BUTTERFLY" -> "Papillons"
        "RAIN" -> "Pluie"
        "PLANET" -> "Planètes"
        "RANDOM" -> "Surprise aléatoire"'''
)

replace_once(
    lyon,
'''                StyleCarousel("Aura A", display(value.auraA)) { value = value.copy(auraA = next(value.auraA, AURA_OPTIONS)) }
                StyleCarousel("Aura B", display(value.auraB)) { value = value.copy(auraB = next(value.auraB, AURA_OPTIONS)) }
                Text("Opacité : ${(value.opacity * 100).toInt()} %")
                Slider(value = value.opacity, onValueChange = { value = value.copy(opacity = it) }, valueRange = 0f..1f)''',
'''                StyleCarousel("Aura A", display(value.auraA)) { value = value.copy(auraA = next(value.auraA, AURA_OPTIONS)) }
                StyleCarousel("Aura B", display(value.auraB)) { value = value.copy(auraB = next(value.auraB, AURA_OPTIONS)) }
                Text("Effets vivants · troisième couche", fontWeight = FontWeight.Bold)
                StyleCarousel("Effet A", display(value.effectA)) { value = value.copy(effectA = next(value.effectA, EFFECT_OPTIONS)) }
                StyleCarousel("Effet B", display(value.effectB)) { value = value.copy(effectB = next(value.effectB, EFFECT_OPTIONS)) }
                Text("Densité effet : ${(value.effectDensity * 100).toInt()} %")
                Slider(value = value.effectDensity, onValueChange = { value = value.copy(effectDensity = it) }, valueRange = 0.08f..1f)
                Text("Orbite autour de la courbe : ${(value.effectOrbit * 100).toInt()} %")
                Slider(value = value.effectOrbit, onValueChange = { value = value.copy(effectOrbit = it) }, valueRange = 0f..1f)
                Text("Opacité : ${(value.opacity * 100).toInt()} %")
                Slider(value = value.opacity, onValueChange = { value = value.copy(opacity = it) }, valueRange = 0f..1f)'''
)

replace_once(
    lyon,
'''                "Style A/B · Aura A/B · Opacité, indépendants pour chaque courbe.",''',
'''                "Couleur A/B · Aura A/B · Effet vivant A/B (orbites, étincelles, feu d’artifice, mouches, gouttes, fumée, poissons, oiseaux…) · Opacité.",'''
)

# Version is explicit for sideload/Play lineage.
gradle = "app/build.gradle.kts"
replace_once(gradle, '''        versionCode = 44\n        versionName = "0.19.8"''', '''        versionCode = 45\n        versionName = "0.20.9"''')

print("v0.20.9 contiguous-history + living curve effects patch applied")
