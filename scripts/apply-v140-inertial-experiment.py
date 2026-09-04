#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"{label}: déjà appliqué")
        return
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: OK")


def write_text(path: str, content: str, label: str) -> None:
    p = Path(path)
    if p.exists() and p.read_text(encoding="utf-8") == content:
        print(f"{label}: déjà appliqué")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"{label}: OK")


replace_once(
    "app/build.gradle.kts",
    '        versionCode = 28\n        versionName = "0.13.1"',
    '        versionCode = 29\n        versionName = "0.14.0"',
    "Version 0.14.0 / code 29",
)

# Extension volontaire de la seule limite de profondeur historique. Les équations RC restent inchangées.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    'private const val MAX_HISTORY_DAYS = 90',
    'private const val MAX_HISTORY_DAYS = 1098',
    "Reconstruction jusqu'à 36 mois",
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '        val days = requestedDays.coerceIn(1, 90)',
    '        val days = requestedDays.coerceIn(1, 1098)',
    "Historique météo jusqu'à 36 mois",
)

old_history = '''    private fun fetchOpenMeteoHistory(
        reference: WeatherReference,
        from: Long,
        to: Long
    ): List<WeatherReferencePoint> {
        // L'archive n'est pas une source temps réel. Demander aujourd'hui peut faire
        // échouer toute la requête ; on laisse 10 jours de marge, couverts par past_days=14.
        val historyTo = minOf(to, System.currentTimeMillis() - 10L * 24L * hourMs)
        if (historyTo <= from) return emptyList()
        val startDate = Instant.ofEpochMilli(from).atZone(zone).toLocalDate()
        val endDate = Instant.ofEpochMilli(historyTo).atZone(zone).toLocalDate()
        if (startDate.isAfter(endDate)) return emptyList()
        val url = "https://archive-api.open-meteo.com/v1/archive" +
            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
            "&start_date=$startDate&end_date=$endDate" +
            "&hourly=temperature_2m%2Crelative_humidity_2m&timezone=Europe%2FParis"
        val raw = httpGetAnonymous(url)
        val hourly = JSONObject(raw).getJSONObject("hourly")
        val times = hourly.getJSONArray("time")
        val temps = hourly.getJSONArray("temperature_2m")
        val hums = hourly.getJSONArray("relative_humidity_2m")
        val out = mutableListOf<WeatherReferencePoint>()
        for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {
            val time = times.optString(i)
            val temp = temps.optDouble(i, Double.NaN)
            val hum = hums.optDouble(i, Double.NaN)
            if (!temp.isFinite() || !hum.isFinite()) continue
            val ts = runCatching {
                LocalDateTime.parse(time).atZone(zone).toInstant().toEpochMilli()
            }.getOrNull() ?: continue
            if (ts !in from..historyTo || temp !in -60.0..65.0 || hum !in 0.0..100.0) continue
            out += WeatherReferencePoint(ts, temp, hum, PointSource.RECONSTRUCTED, 0.68)
        }
        return out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }
'''
new_history = '''    private fun fetchOpenMeteoHistory(
        reference: WeatherReference,
        from: Long,
        to: Long
    ): List<WeatherReferencePoint> {
        // L'archive n'est pas une source temps réel. Demander aujourd'hui peut faire
        // échouer toute la requête ; on laisse 10 jours de marge, couverts par past_days=14.
        val historyTo = minOf(to, System.currentTimeMillis() - 10L * 24L * hourMs)
        if (historyTo <= from) return emptyList()
        val startDate = Instant.ofEpochMilli(from).atZone(zone).toLocalDate()
        val endDate = Instant.ofEpochMilli(historyTo).atZone(zone).toLocalDate()
        if (startDate.isAfter(endDate)) return emptyList()

        // v0.14 : 36 mois représentent ~26 000 points horaires. On découpe volontairement
        // l'archive en fenêtres de 180 jours : moins de mémoire, moins de risque de timeout,
        // et exactement la même série finale après déduplication.
        val out = mutableListOf<WeatherReferencePoint>()
        var cursor = startDate
        while (!cursor.isAfter(endDate)) {
            val chunkEnd = minOf(cursor.plusDays(179L), endDate)
            val url = "https://archive-api.open-meteo.com/v1/archive" +
                "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
                "&start_date=$cursor&end_date=$chunkEnd" +
                "&hourly=temperature_2m%2Crelative_humidity_2m&timezone=Europe%2FParis"
            val raw = httpGetAnonymous(url)
            val hourly = JSONObject(raw).getJSONObject("hourly")
            val times = hourly.getJSONArray("time")
            val temps = hourly.getJSONArray("temperature_2m")
            val hums = hourly.getJSONArray("relative_humidity_2m")
            for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {
                val time = times.optString(i)
                val temp = temps.optDouble(i, Double.NaN)
                val hum = hums.optDouble(i, Double.NaN)
                if (!temp.isFinite() || !hum.isFinite()) continue
                val ts = runCatching {
                    LocalDateTime.parse(time).atZone(zone).toInstant().toEpochMilli()
                }.getOrNull() ?: continue
                if (ts !in from..historyTo || temp !in -60.0..65.0 || hum !in 0.0..100.0) continue
                out += WeatherReferencePoint(ts, temp, hum, PointSource.RECONSTRUCTED, 0.68)
            }
            cursor = chunkEnd.plusDays(1L)
        }
        return out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }
'''
replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    old_history,
    new_history,
    "Archive météo en blocs de 180 jours",
)

# Choix longs dans l'UI + remontée du texte de progression vers l'overlay fixe.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '@Composable\nfun ThermalReferenceCard(',
    '''private data class ThermalHistoryChoice(val label: String, val days: Int)

private val THERMAL_HISTORY_CHOICES = listOf(
    ThermalHistoryChoice("30 j", 30),
    ThermalHistoryChoice("90 j", 90),
    ThermalHistoryChoice("6 mois", 183),
    ThermalHistoryChoice("12 mois", 366),
    ThermalHistoryChoice("24 mois", 732),
    ThermalHistoryChoice("36 mois", 1098)
)

private fun thermalHistoryLabel(days: Int): String =
    THERMAL_HISTORY_CHOICES.firstOrNull { it.days == days }?.label ?: "$days jours"

@Composable
fun ThermalReferenceCard(''',
    "Choix historiques 30j à 36 mois",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''    dataVersion: Int,
    onDataChanged: () -> Unit,
    onBusyChanged: (Boolean) -> Unit = {}
) {''',
    '''    dataVersion: Int,
    onDataChanged: () -> Unit,
    onBusyChanged: (Boolean) -> Unit = {},
    onProgressChanged: (String?) -> Unit = {}
) {''',
    "Callback progression thermique",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''    var status by remember { mutableStateOf<ThermalStatus?>(null) }
    var info by remember { mutableStateOf("Référence prête à être chargée") }
''',
    '''    var status by remember { mutableStateOf<ThermalStatus?>(null) }
    var info by remember { mutableStateOf("Référence prête à être chargée") }
    LaunchedEffect(busy, info) { onProgressChanged(if (busy) info else null) }
''',
    "Propagation progression vers écran principal",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(30, 60, 90).forEach { d ->
                            AssistChip(
                                onClick = { weatherHistoryDays = d },
                                label = { Text("$d jours") }
                            )
                        }
                    }
                    Text("Sélection : $weatherHistoryDays jours avant la première vraie mesure intérieure.", style = MaterialTheme.typography.bodySmall)
''',
    '''                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        THERMAL_HISTORY_CHOICES.forEach { choice ->
                            FilterChip(
                                selected = weatherHistoryDays == choice.days,
                                onClick = { weatherHistoryDays = choice.days },
                                label = { Text(choice.label) }
                            )
                        }
                    }
                    Text("Sélection : ${thermalHistoryLabel(weatherHistoryDays)} avant la première vraie mesure intérieure.", style = MaterialTheme.typography.bodySmall)
''',
    "Choix longue référence météo",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                    scope.launch {
                        busy = true
                        val result = withContext(Dispatchers.IO) {
                            runCatching { manager.prepareHistory(reference, weatherHistoryDays) }
                        }
''',
    '''                    scope.launch {
                        busy = true
                        info = "Historique météo · préparation ${thermalHistoryLabel(weatherHistoryDays)}…"
                        val result = withContext(Dispatchers.IO) {
                            runCatching { manager.prepareHistory(reference, weatherHistoryDays) }
                        }
''',
    "Progression extension météo",
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(30, 60, 90).forEach { d ->
                            AssistChip(
                                onClick = { historyDays = d },
                                label = { Text("$d jours") }
                            )
                        }
                    }
                    Text("Sélection : $historyDays jours · maximum 3 mois.", style = MaterialTheme.typography.bodySmall)
''',
    '''                    Row(
                        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        THERMAL_HISTORY_CHOICES.forEach { choice ->
                            FilterChip(
                                selected = historyDays == choice.days,
                                onClick = { historyDays = choice.days },
                                label = { Text(choice.label) }
                            )
                        }
                    }
                    Text("Sélection : ${thermalHistoryLabel(historyDays)} · maximum 36 mois.", style = MaterialTheme.typography.bodySmall)
''',
    "Choix longue reconstruction bâtiment",
)

# Nouveau moteur expérimental : lecture seule, measured intérieur uniquement.
inertia_engine = r'''package com.fabdata.app

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

const val THERMAL_INERTIA_SENSOR_ID = -6902900104L
const val THERMAL_INERTIA_STABLE_KEY = "thermal-inertia-estimated"
private const val INERTIA_HOUR_MS = 60L * 60L * 1000L

data class ThermalInertiaDiagnostics(
    val sourceSensorId: Long,
    val sourceRoom: String,
    val currentC: Double,
    val trendCPerDay: Double,
    val tauHours: Double,
    val couplingPerHour: Double,
    val confidence: Double,
    val cleanHours: Int,
    val plateauHours: Int,
    val fitRmse: Double,
    val currentFluxCPerHour: Double
) {
    val trendLabel: String get() = when {
        trendCPerDay > 0.06 -> "↑ charge thermique"
        trendCPerDay < -0.06 -> "↓ décharge thermique"
        else -> "→ quasi stable"
    }
    val couplingLabel: String get() = when {
        couplingPerHour < 0.008 -> "faible"
        couplingPerHour < 0.025 -> "moyen"
        else -> "fort"
    }
    val confidenceLabel: String get() = when {
        confidence >= 0.72 -> "forte"
        confidence >= 0.46 -> "moyenne"
        else -> "faible"
    }
    val fluxLabel: String get() = when {
        currentFluxCPerHour > 0.01 -> "haut · masse → air"
        currentFluxCPerHour < -0.01 -> "bas · air → masse"
        else -> "quasi nul"
    }
}

data class ThermalInertiaEstimate(
    val points: List<SamplePoint>,
    val diagnostics: ThermalInertiaDiagnostics
) {
    fun window(from: Long, to: Long, maxPoints: Int = 5000): List<SamplePoint> {
        val selected = points.filter { it.timestamp in from..to }
        if (selected.size <= maxPoints || maxPoints < 2) return selected
        val step = ((selected.size + maxPoints - 1) / maxPoints).coerceAtLeast(1)
        val out = selected.filterIndexed { index, _ -> index % step == 0 }.toMutableList()
        selected.lastOrNull()?.let { last -> if (out.lastOrNull()?.timestamp != last.timestamp) out += last }
        return out
    }
}

private data class InertiaHour(
    val timestamp: Long,
    val air: Double,
    val humidity: Double,
    val outside: Double,
    val smoothAir: Double
)

private data class InertiaCandidate(
    val tauHours: Double,
    val outsideWeight: Double,
    val mass: DoubleArray,
    val kOutside: Double,
    val kMass: Double,
    val rmse: Double,
    val score: Double,
    val cleanHours: Int,
    val plateauHours: Int
)

/**
 * Expérience observationnelle v0.14.
 *
 * - ne lit que les points intérieurs MEASURED ;
 * - peut lire la référence météo comme variable explicative ;
 * - ne persiste rien et n'appelle jamais PointSourceStore.upsert* ;
 * - n'est utilisée ni par reconstructHistory, ni par refreshForecasts.
 *
 * T_mass est un état latent lent. Plusieurs constantes de temps et couplages extérieurs
 * sont testés ; le choix est fait sur la capacité à expliquer dT_air/dt sur des périodes
 * non perturbées, avec un bonus de cohérence près des plateaux/tangentes.
 */
class ThermalInertiaEstimator(
    private val db: FabDataDb,
    private val referenceStore: WeatherReferenceStore
) {
    private var cachedKey: String? = null
    private var cached: ThermalInertiaEstimate? = null

    fun estimate(reference: WeatherReference): ThermalInertiaEstimate? {
        val measuredRevision = db.physicalMeasuredRevision() ?: return null
        val weatherSignature = weatherSignature(reference.key) ?: return null
        val key = "$measuredRevision|${reference.key}|$weatherSignature"
        if (key == cachedKey) return cached

        val sensors = db.sensors().filter { s ->
            s.id >= 0L && !s.stableKey.startsWith("meteo-") && !s.stableKey.startsWith("http-get-")
        }
        val measuredBySensor = sensors.mapNotNull { sensor ->
            val pts = measuredHourly(sensor.id)
            if (pts.size >= 120) sensor to pts else null
        }
        val selected = measuredBySensor.maxByOrNull { it.second.size } ?: return null
        val sensor = selected.first
        val measured = selected.second
        val weatherBounds = referenceStore.historyBounds(reference.key) ?: return null
        val from = max(measured.first().timestamp, weatherBounds.first)
        val to = min(measured.last().timestamp, weatherBounds.last)
        if (to - from < 5L * 24L * INERTIA_HOUR_MS) return null

        val outside = outsideHourly(reference.key, from - 3L * INERTIA_HOUR_MS, to)
        if (outside.size < 120) return null
        val outMap = outside.associateBy { it.first }
        val indoor = measured.filter { it.timestamp in from..to }
        if (indoor.size < 120) return null
        val smooth = smoothAir(indoor.map { it.temperature })
        val hours = indoor.mapIndexedNotNull { index, p ->
            val outsideT = outsideAt(outMap, p.timestamp) ?: return@mapIndexedNotNull null
            InertiaHour(p.timestamp, p.temperature, p.humidity, outsideT, smooth[index])
        }
        if (hours.size < 120) return null

        val best = search(hours) ?: fallback(hours)
        val confidence = confidence(best)
        val points = hours.mapIndexed { index, h ->
            SamplePoint(
                sensorId = THERMAL_INERTIA_SENSOR_ID,
                timestamp = h.timestamp,
                temperature = round2(best.mass[index]),
                humidity = h.humidity,
                source = PointSource.RECONSTRUCTED,
                confidence = confidence
            )
        }
        if (points.isEmpty()) return null

        val trend = trendPerDay(hours, best.mass)
        val currentAir = hours.last().smoothAir
        val currentFlux = best.kMass * (best.mass.last() - currentAir)
        val diagnostics = ThermalInertiaDiagnostics(
            sourceSensorId = sensor.id,
            sourceRoom = sensor.room,
            currentC = round2(best.mass.last()),
            trendCPerDay = trend,
            tauHours = best.tauHours,
            couplingPerHour = best.kMass,
            confidence = confidence,
            cleanHours = best.cleanHours,
            plateauHours = best.plateauHours,
            fitRmse = best.rmse,
            currentFluxCPerHour = currentFlux
        )
        return ThermalInertiaEstimate(points, diagnostics).also {
            cachedKey = key
            cached = it
        }
    }

    private fun measuredHourly(sensorId: Long): List<SamplePoint> {
        PointSourceStore.ensure(db.readableDatabase)
        val out = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT (p.timestamp / 3600000) * 3600000 AS bucket,
                   AVG(p.temperature), AVG(p.humidity)
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source='measured')
            GROUP BY bucket
            ORDER BY bucket
            """.trimIndent(),
            arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) {
                out += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2), PointSource.MEASURED, 1.0)
            }
        }
        return out
    }

    private fun outsideHourly(referenceKey: String, from: Long, to: Long): List<Pair<Long, Double>> =
        referenceStore.query(referenceKey, from, to)
            .filter { it.source != PointSource.FORECAST }
            .groupBy { bucket(it.timestamp) }
            .map { (ts, values) ->
                val priority = values.maxOf { it.source.priority }
                val best = values.filter { it.source.priority == priority }
                ts to best.map { it.temperature }.average()
            }
            .sortedBy { it.first }

    private fun outsideAt(map: Map<Long, Pair<Long, Double>>, timestamp: Long): Double? {
        val b = bucket(timestamp)
        map[b]?.let { return it.second }
        return listOfNotNull(map[b - INERTIA_HOUR_MS], map[b + INERTIA_HOUR_MS])
            .minByOrNull { abs(it.first - timestamp) }?.second
    }

    private fun smoothAir(values: List<Double>): List<Double> = values.indices.map { i ->
        val from = max(0, i - 2)
        val to = min(values.lastIndex, i + 2)
        val window = (from..to).map { values[it] }.sorted()
        if (window.size % 2 == 1) window[window.size / 2]
        else (window[window.size / 2 - 1] + window[window.size / 2]) / 2.0
    }

    private fun masks(hours: List<InertiaHour>): Pair<BooleanArray, BooleanArray> {
        val clean = BooleanArray(hours.size)
        val plateau = BooleanArray(hours.size)
        for (i in 2 until hours.size) {
            val dt = (hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
            val prevDt = (hours[i - 1].timestamp - hours[i - 2].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
            if (dt !in 0.75..2.5 || prevDt !in 0.75..2.5) continue
            val slope = (hours[i].smoothAir - hours[i - 1].smoothAir) / dt
            val previousSlope = (hours[i - 1].smoothAir - hours[i - 2].smoothAir) / prevDt
            val accel = slope - previousSlope
            val humidityJump = abs(hours[i].humidity - hours[i - 1].humidity) / dt
            val rawSlope = abs(hours[i].air - hours[i - 1].air) / dt
            val ok = rawSlope <= 0.90 && abs(slope) <= 0.70 && abs(accel) <= 0.60 && humidityJump <= 15.0
            clean[i] = ok
            plateau[i] = ok && abs(slope) <= 0.08 && abs(hours[i].outside - hours[i].smoothAir) >= 1.8 &&
                abs(slope) <= abs(previousSlope) + 0.03
        }
        return clean to plateau
    }

    private fun search(hours: List<InertiaHour>): InertiaCandidate? {
        val (clean, plateau) = masks(hours)
        val taus = doubleArrayOf(48.0, 72.0, 96.0, 120.0, 168.0, 240.0, 336.0, 480.0, 720.0)
        val outsideWeights = doubleArrayOf(0.08, 0.15, 0.25, 0.35)
        var best: InertiaCandidate? = null
        for (tau in taus) {
            for (outsideWeight in outsideWeights) {
                val mass = propagate(hours, tau, outsideWeight, plateau)
                val rows = mutableListOf<DoubleArray>()
                for (i in 2 until hours.size) {
                    if (!clean[i]) continue
                    val dt = (hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()
                    if (dt !in 0.75..2.5) continue
                    val y = (hours[i].smoothAir - hours[i - 1].smoothAir) / dt
                    rows += doubleArrayOf(
                        hours[i - 1].outside - hours[i - 1].smoothAir,
                        mass[i - 1] - hours[i - 1].smoothAir,
                        y
                    )
                }
                if (rows.size < 80) continue
                val split = (rows.size * 0.75).toInt().coerceIn(60, rows.size - 20)
                val coeff = fitTwo(rows.take(split)) ?: continue
                val kOut = coeff.first
                val kMass = coeff.second
                if (kOut !in 0.0..0.25 || kMass !in 0.001..0.20) continue
                val validation = rows.drop(split)
                val rmse = sqrt(validation.map { r ->
                    val e = kOut * r[0] + kMass * r[1] - r[2]
                    e * e
                }.average())
                val plateauIndices = hours.indices.filter { plateau[it] }
                val plateauError = plateauIndices.map { i -> abs(mass[i] - hours[i].smoothAir) }.averageOr(1.5)
                val jitter = (1 until mass.size).map { i -> abs(mass[i] - mass[i - 1]) }.averageOr(0.0)
                val score = rmse + 0.06 * plateauError + 0.45 * max(0.0, jitter - 0.065)
                val candidate = InertiaCandidate(
                    tau, outsideWeight, mass, kOut, kMass, rmse, score,
                    clean.count { it }, plateau.count { it }
                )
                if (best == null || candidate.score < best!!.score) best = candidate
            }
        }
        return best
    }

    private fun fallback(hours: List<InertiaHour>): InertiaCandidate {
        val (clean, plateau) = masks(hours)
        val tau = 168.0
        val mass = propagate(hours, tau, 0.15, plateau)
        return InertiaCandidate(
            tauHours = tau,
            outsideWeight = 0.15,
            mass = mass,
            kOutside = 0.02,
            kMass = 0.012,
            rmse = 0.80,
            score = 9.0,
            cleanHours = clean.count { it },
            plateauHours = plateau.count { it }
        )
    }

    private fun propagate(
        hours: List<InertiaHour>,
        tauHours: Double,
        outsideWeight: Double,
        plateau: BooleanArray
    ): DoubleArray {
        val mass = DoubleArray(hours.size)
        mass[0] = hours[0].smoothAir * 0.78 + hours[0].outside * 0.22
        for (i in 1 until hours.size) {
            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())
                .coerceIn(0.5, 24.0)
            val target = hours[i - 1].smoothAir * (1.0 - outsideWeight) + hours[i - 1].outside * outsideWeight
            val alpha = 1.0 - exp(-dt / tauHours)
            var next = mass[i - 1] + alpha * (target - mass[i - 1])
            if (plateau[i]) {
                // Tangente/plateau = observation indirecte faible, jamais une contrainte dure.
                val observationGain = min(0.10, 0.025 * dt)
                next += observationGain * (hours[i].smoothAir - next)
            }
            mass[i] = next.coerceIn(-5.0, 50.0)
        }
        return mass
    }

    private fun fitTwo(rows: List<DoubleArray>): Pair<Double, Double>? {
        var a11 = 0.02
        var a12 = 0.0
        var a22 = 0.02
        var b1 = 0.0
        var b2 = 0.0
        rows.forEach { r ->
            val x1 = r[0]
            val x2 = r[1]
            val y = r[2]
            a11 += x1 * x1
            a12 += x1 * x2
            a22 += x2 * x2
            b1 += x1 * y
            b2 += x2 * y
        }
        val det = a11 * a22 - a12 * a12
        if (abs(det) < 1e-9) return null
        val k1 = (b1 * a22 - b2 * a12) / det
        val k2 = (a11 * b2 - a12 * b1) / det
        if (!k1.isFinite() || !k2.isFinite()) return null
        return k1 to k2
    }

    private fun confidence(candidate: InertiaCandidate): Double {
        val dataFactor = (candidate.cleanHours / 720.0).coerceIn(0.0, 1.0)
        val plateauFactor = (candidate.plateauHours / 40.0).coerceIn(0.0, 1.0)
        val errorFactor = (1.0 - candidate.rmse / 0.55).coerceIn(0.0, 1.0)
        return (0.08 + 0.44 * errorFactor + 0.28 * dataFactor + 0.20 * plateauFactor).coerceIn(0.08, 0.95)
    }

    private fun trendPerDay(hours: List<InertiaHour>, mass: DoubleArray): Double {
        if (mass.size < 2) return 0.0
        val last = hours.last().timestamp
        val target = last - 24L * INERTIA_HOUR_MS
        val index = hours.indices.minByOrNull { abs(hours[it].timestamp - target) } ?: 0
        val elapsed = ((last - hours[index].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble()).coerceAtLeast(1.0)
        return (mass.last() - mass[index]) * 24.0 / elapsed
    }

    private fun weatherSignature(referenceKey: String): String? {
        return db.readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp), MAX(updated_at)
            FROM weather_reference_samples
            WHERE reference_key=? AND source<>'forecast'
            """.trimIndent(),
            arrayOf(referenceKey)
        ).use { c ->
            if (!c.moveToFirst() || c.getLong(0) <= 0L || c.isNull(1) || c.isNull(2)) null
            else "${c.getLong(0)}:${c.getLong(1)}:${c.getLong(2)}:${if (c.isNull(3)) 0L else c.getLong(3)}"
        }
    }

    private fun bucket(ts: Long): Long = (ts / INERTIA_HOUR_MS) * INERTIA_HOUR_MS
    private fun round2(v: Double): Double = kotlin.math.round(v * 100.0) / 100.0
    private fun List<Double>.averageOr(fallback: Double): Double = if (isEmpty()) fallback else average()
}
'''
write_text(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    inertia_engine,
    "Moteur observationnel inertie",
)

experiment_ui = r'''package com.fabdata.app

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.util.Locale
import kotlin.math.max

@Composable
fun ThermalInertiaExperimentCard(estimate: ThermalInertiaEstimate?) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(13.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            Text("Température inertielle estimée · expérimental", fontWeight = FontWeight.Bold)
            Text(
                "Observation uniquement : mesures intérieures réelles + météo explicative. Cette courbe ne participe ni à la reconstruction ni à la prévision.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            val d = estimate?.diagnostics
            if (d == null) {
                Text(
                    "En attente d'une plage commune suffisamment longue entre mesures réelles et référence météo.",
                    style = MaterialTheme.typography.bodySmall
                )
            } else {
                Text(String.format(Locale.FRANCE, "État inertiel actuel : %.1f °C", d.currentC), fontWeight = FontWeight.SemiBold)
                Text("Tendance : ${d.trendLabel}", style = MaterialTheme.typography.bodySmall)
                Text(
                    "τ ≈ ${formatTau(d.tauHours)} · couplage air ↔ masse ${d.couplingLabel} · confiance ${d.confidenceLabel} ${(d.confidence * 100).toInt()} %",
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    String.format(
                        Locale.FRANCE,
                        "Flux signé actuel : %+.3f °C/h · %s · basé sur %s",
                        d.currentFluxCPerHour,
                        d.fluxLabel,
                        d.sourceRoom
                    ),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    "Diagnostic : ${d.cleanHours} h propres · ${d.plateauHours} plateau(x) · RMSE dérivée ${String.format(Locale.FRANCE, "%.3f", d.fitRmse)} °C/h",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
fun ThermalBusyOverlay(
    progressText: String?,
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    showTemp: Map<Long, Boolean>,
    bounds: LongRange?,
    modifier: Modifier = Modifier
) {
    val transition = rememberInfiniteTransition(label = "thermal-work")
    val angle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(1400, easing = LinearEasing)),
        label = "thermal-gear"
    )
    val colors = listOf(
        MaterialTheme.colorScheme.primary,
        MaterialTheme.colorScheme.tertiary,
        MaterialTheme.colorScheme.secondary,
        MaterialTheme.colorScheme.error
    )

    Card(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.97f))
    ) {
        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(
                    Icons.Default.Settings,
                    contentDescription = "Calcul thermique en cours",
                    modifier = Modifier.size(26.dp).graphicsLayer { rotationZ = angle },
                    tint = MaterialTheme.colorScheme.primary
                )
                Column(Modifier.weight(1f)) {
                    Text("FabData calcule…", fontWeight = FontWeight.Bold)
                    Text(
                        progressText ?: "Traitement thermique en cours",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2
                    )
                }
            }

            val b = bounds
            val visible = if (b == null) emptyList() else sensors
                .filter { showTemp[it.id] == true }
                .flatMap { sensor -> sampleMap[sensor.id].orEmpty().filter { it.timestamp in b } }
            if (b != null && visible.size >= 2) {
                val low = visible.minOf { it.temperature }
                val high = visible.maxOf { it.temperature }
                val range = (high - low).coerceAtLeast(0.5)
                val span = (b.last - b.first).coerceAtLeast(1L)
                Canvas(
                    Modifier.fillMaxWidth().height(68.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f), RoundedCornerShape(10.dp))
                ) {
                    sensors.filter { showTemp[it.id] == true }.forEachIndexed { colorIndex, sensor ->
                        val pts = sampleMap[sensor.id].orEmpty().filter { it.timestamp in b }.sortedBy { it.timestamp }
                        if (pts.size >= 2) {
                            val path = Path()
                            var prev: SamplePoint? = null
                            pts.forEach { p ->
                                val x = ((p.timestamp - b.first).toDouble() / span.toDouble()).toFloat() * size.width
                                val y = size.height - (((p.temperature - low) / range).toFloat() * size.height)
                                val gap = prev?.let { p.timestamp - it.timestamp } ?: 0L
                                if (prev == null || gap > 6L * 60L * 60L * 1000L) path.moveTo(x, y) else path.lineTo(x, y)
                                prev = p
                            }
                            drawPath(
                                path,
                                colors[colorIndex % colors.size].copy(alpha = 0.86f),
                                style = Stroke(width = 1.8.dp.toPx())
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun formatTau(hours: Double): String = if (hours >= 48.0) {
    val days = hours / 24.0
    String.format(Locale.FRANCE, "%.1f jours", days)
} else {
    String.format(Locale.FRANCE, "%.0f h", hours)
}
'''
write_text(
    "app/src/main/java/com/fabdata/app/ThermalExperimentUi.kt",
    experiment_ui,
    "UI inertie + overlay calcul",
)

# MainActivity : station dynamique cohérente, calcul inertiel en lecture seule et overlay fixe.
replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val overviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>,
    val lyonReconstructedSamples: List<SamplePoint>
)''',
    '''private data class LoadedData(
    val sensors: List<Sensor>,
    val globalBounds: LongRange?,
    val viewBounds: LongRange?,
    val samples: Map<Long, List<SamplePoint>>,
    val overviewSamples: Map<Long, List<SamplePoint>>,
    val stats: Map<Long, SensorStats>,
    val annotations: List<AnnotationItem>,
    val allAnnotations: List<AnnotationItem>,
    val lyonReconstructedSamples: List<SamplePoint>,
    val inertiaEstimate: ThermalInertiaEstimate?
)''',
    "LoadedData inertie",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''    val curveStyleStore = remember { CurveStyleStore(context) }
    val remoteSensorStore = remember { RemoteSensorStore(context) }
''',
    '''    val curveStyleStore = remember { CurveStyleStore(context) }
    val weatherReferenceStore = remember { WeatherReferenceStore(db) }
    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }
    val remoteSensorStore = remember { RemoteSensorStore(context) }
''',
    "Services inertie mémorisés",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''    var lyonReconstructedSamples by remember { mutableStateOf<List<SamplePoint>>(emptyList()) }
    var statsMap by remember { mutableStateOf<Map<Long, SensorStats>>(emptyMap()) }
''',
    '''    var lyonReconstructedSamples by remember { mutableStateOf<List<SamplePoint>>(emptyList()) }
    var inertiaEstimate by remember { mutableStateOf<ThermalInertiaEstimate?>(null) }
    var statsMap by remember { mutableStateOf<Map<Long, SensorStats>>(emptyMap()) }
''',
    "État inertie écran principal",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''    var thermalBusy by remember { mutableStateOf(false) }
    var selectedTimestamp by remember { mutableStateOf<Long?>(null) }
''',
    '''    var thermalBusy by remember { mutableStateOf(false) }
    var thermalProgressText by remember { mutableStateOf<String?>(null) }
    var selectedTimestamp by remember { mutableStateOf<Long?>(null) }
''',
    "Texte progression fixe",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''            val selectedWeatherReference = WeatherReferenceCatalog.byKey(WeatherReferencePrefs(context).selectedKey())
            val weatherReferenceStore = WeatherReferenceStore(db)
            val weatherBounds = weatherReferenceStore.historyBounds(selectedWeatherReference.key)
''',
    '''            val selectedWeatherReference = WeatherReferencePrefs(context).selectedReference()
            val weatherBounds = weatherReferenceStore.historyBounds(selectedWeatherReference.key)
''',
    "Station dynamique cohérente dans le chargement",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList())''',
    '''                LoadedData(s, all, null, emptyMap(), emptyMap(), emptyMap(), emptyList(), allNotes, emptyList(), null)''',
    "LoadedData vide inertie",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                LoadedData(
                    s, all, chosen, samples, overviewWithReference, stat,
                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed
                )''',
    '''                val inertia = runCatching { inertiaEstimator.estimate(selectedWeatherReference) }.getOrNull()
                LoadedData(
                    s, all, chosen, samples, overviewWithReference, stat,
                    db.annotations(chosen.first, chosen.last), allNotes, lyonReconstructed, inertia
                )''',
    "Calcul inertiel observationnel au chargement",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''        lyonReconstructedSamples = loaded.lyonReconstructedSamples
        overviewSampleMap = loaded.overviewSamples
''',
    '''        lyonReconstructedSamples = loaded.lyonReconstructedSamples
        inertiaEstimate = loaded.inertiaEstimate
        overviewSampleMap = loaded.overviewSamples
''',
    "Affectation inertie chargée",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''        if (!showHumidity.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            showHumidity[LYON_RECONSTRUCTED_SENSOR_ID] = false
        }
        busy = false
''',
    '''        if (!showHumidity.containsKey(LYON_RECONSTRUCTED_SENSOR_ID)) {
            showHumidity[LYON_RECONSTRUCTED_SENSOR_ID] = false
        }
        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true
        showHumidity[THERMAL_INERTIA_SENSOR_ID] = false
        busy = false
''',
    "Visibilité inertie par défaut",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''    val chartSensors = sensors + lyonReconstructedSensor
    val chartSampleMap = sampleMap + (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples)
''',
    '''    val inertiaVisible = viewBounds?.let { b -> inertiaEstimate?.window(b.first, b.last).orEmpty() }.orEmpty()
    val inertiaOverview = globalBounds?.let { b -> inertiaEstimate?.window(b.first, b.last, 1200).orEmpty() }.orEmpty()
    val inertiaSensor = Sensor(
        id = THERMAL_INERTIA_SENSOR_ID,
        stableKey = THERMAL_INERTIA_STABLE_KEY,
        name = "Température inertielle estimée",
        room = "Température inertielle estimée",
        colorIndex = 4,
        latestTimestamp = inertiaEstimate?.points?.lastOrNull()?.timestamp
    )
    val chartSensors = sensors + lyonReconstructedSensor + inertiaSensor
    val chartSampleMap = sampleMap +
        (LYON_RECONSTRUCTED_SENSOR_ID to lyonReconstructedSamples) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)
    val chartOverviewSampleMap = overviewSampleMap + (THERMAL_INERTIA_SENSOR_ID to inertiaOverview)
''',
    "Pseudo-sonde inertielle graphique",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    ''') { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(14.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {''',
    ''') { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(
                    start = 14.dp,
                    top = 14.dp,
                    end = 14.dp,
                    bottom = if (thermalBusy) 176.dp else 14.dp
                ),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {''',
    "Conteneur overlay thermique fixe",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                    ThermalReferenceCard(
                        db = db,
                        lyonLab = lyonLab,
                        credentials = meteoCredentials,
                        dataVersion = reloadToken,
                        onDataChanged = { reloadToken++ },
                        onBusyChanged = { thermalBusy = it }
                    )
                }

                item {
                    SourceAwareExportCard(db)
                }
''',
    '''                    ThermalReferenceCard(
                        db = db,
                        lyonLab = lyonLab,
                        credentials = meteoCredentials,
                        dataVersion = reloadToken,
                        onDataChanged = { reloadToken++ },
                        onBusyChanged = { thermalBusy = it },
                        onProgressChanged = { thermalProgressText = it }
                    )
                }

                item {
                    ThermalInertiaExperimentCard(inertiaEstimate)
                }

                item {
                    SourceAwareExportCard(db)
                }
''',
    "Carte inertie + progression",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                    CurvePersonalizationCard(
                        sensors = chartSensors,
                        onEdit = { key, label -> styleEditKey = key to label }
                    )''',
    '''                    CurvePersonalizationCard(
                        sensors = chartSensors.filter { it.id != THERMAL_INERTIA_SENSOR_ID },
                        onEdit = { key, label -> styleEditKey = key to label }
                    )''',
    "Style inertie fixe distinct",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                        sampleMap = overviewSampleMap,''',
    '''                        sampleMap = chartOverviewSampleMap,''',
    "Vue globale avec inertie",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                item { Spacer(Modifier.height(72.dp)) }
            }
        }
    }

    if (settingsOpen) {''',
    '''                item { Spacer(Modifier.height(72.dp)) }
            }

            if (thermalBusy) {
                ThermalBusyOverlay(
                    progressText = thermalProgressText,
                    sensors = chartSensors,
                    sampleMap = chartSampleMap,
                    showTemp = showTemp,
                    bounds = viewBounds,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(horizontal = 14.dp, vertical = 82.dp)
                )
            }
        }
    }

    if (settingsOpen) {''',
    "Overlay engrenage + courbe fixe",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                        val displayRoom = when {
                            sensor.id == LYON_RECONSTRUCTED_SENSOR_ID -> "Lyon reconstruit"
                            sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon brut · officiel/secours"
                            else -> sensor.room
                        }''',
    '''                        val displayRoom = when {
                            sensor.id == LYON_RECONSTRUCTED_SENSOR_ID -> "Lyon reconstruit"
                            sensor.id == THERMAL_INERTIA_SENSOR_ID -> "Température inertielle estimée · expérimental"
                            sensor.stableKey == LyonWeatherSync.STABLE_KEY -> "Lyon brut · officiel/secours"
                            else -> sensor.room
                        }''',
    "Libellé série inertielle",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                    Text("%", style = MaterialTheme.typography.labelMedium)
                    Checkbox(
                        checked = showHumidity[sensor.id] == true,
                        onCheckedChange = { showHumidity[sensor.id] = it }
                    )
                    if (sensor.id != LYON_RECONSTRUCTED_SENSOR_ID) {
                        IconButton(onClick = { onEdit(sensor) }) {
                            Icon(Icons.Default.Edit, contentDescription = "Modifier la pièce")
                        }
                    } else {
                        Spacer(Modifier.size(48.dp))
                    }''',
    '''                    if (sensor.id != THERMAL_INERTIA_SENSOR_ID) {
                        Text("%", style = MaterialTheme.typography.labelMedium)
                        Checkbox(
                            checked = showHumidity[sensor.id] == true,
                            onCheckedChange = { showHumidity[sensor.id] = it }
                        )
                    } else {
                        Spacer(Modifier.size(48.dp))
                    }
                    if (sensor.id != LYON_RECONSTRUCTED_SENSOR_ID && sensor.id != THERMAL_INERTIA_SENSOR_ID) {
                        IconButton(onClick = { onEdit(sensor) }) {
                            Icon(Icons.Default.Edit, contentDescription = "Modifier la pièce")
                        }
                    } else {
                        Spacer(Modifier.size(48.dp))
                    }''',
    "Série inertielle sans humidité ni édition capteur",
)

replace_once(
    "app/src/main/java/com/fabdata/app/MainActivity.kt",
    '''                        val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                            p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS''',
    '''                        val breakHere = (
                            sensor.stableKey == LyonWeatherSync.STABLE_KEY || sensor.id == THERMAL_INERTIA_SENSOR_ID
                        ) && p.timestamp - prev.timestamp > LYON_DETAIL_GAP_MS''',
    "Coupure des trous de la courbe inertielle",
)

print("v0.14.0 inertial experiment patch complete")
