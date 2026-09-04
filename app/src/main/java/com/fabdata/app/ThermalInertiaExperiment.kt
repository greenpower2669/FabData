package com.fabdata.app

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
    val outsideWeight: Double,
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
 * Estimateur inertiel couplé v0.15.
 *
 * - les paramètres sont appris uniquement sur les points intérieurs MEASURED ;
 * - les périodes perturbées/douteuses sont exclues par les masques mais restent visibles ;
 * - la météo sert de variable explicative lente ;
 * - l'estimateur ne persiste aucune donnée et ne modifie jamais les points MEASURED ;
 * - T_mass devient une entrée obligatoire du modèle d'historique et de prévision.
 *
 * T_mass est un état latent lent. Plusieurs constantes de temps et couplages extérieurs
 * sont testés sur les seules mesures propres, puis ces paramètres peuvent être propagés
 * sur l'historique sans réentraîner le modèle sur ses propres sorties.
 */
class ThermalInertiaEstimator(
    private val db: FabDataDb,
    private val referenceStore: WeatherReferenceStore
) {
    private var cachedKey: String? = null
    private var cached: ThermalInertiaEstimate? = null

    fun estimate(reference: WeatherReference, sensorId: Long? = null, includeHistory: Boolean = true): ThermalInertiaEstimate? {
        val measuredRevision = db.physicalMeasuredRevision() ?: return null
        val weatherSignature = weatherSignature(reference.key) ?: return null
        val key = "$measuredRevision|${reference.key}|$weatherSignature|${sensorId ?: -1L}|$includeHistory"
        if (key == cachedKey) return cached

        val sensors = db.sensors().filter { s ->
            (sensorId == null || s.id == sensorId) &&
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

        // Les paramètres (tau, couplages, poids extérieur) viennent EXCLUSIVEMENT
        // des heures MEASURED propres ci-dessus. Pour l'affichage historique, on
        // peut ensuite propager cet état lent sur la chronologie intérieure déjà
        // reconstruite : cela ne réentraîne jamais le modèle sur ses propres sorties.
        val outputHours: List<InertiaHour>
        val outputMass: DoubleArray
        if (includeHistory) {
            val fullIndoor = allHourly(sensor.id)
            val fullFrom = max(fullIndoor.firstOrNull()?.timestamp ?: from, weatherBounds.first)
            val fullTo = min(fullIndoor.lastOrNull()?.timestamp ?: to, weatherBounds.last)
            val fullOutside = outsideHourly(reference.key, fullFrom - 3L * INERTIA_HOUR_MS, fullTo)
            val fullOutMap = fullOutside.associateBy { it.first }
            val inRange = fullIndoor.filter { it.timestamp in fullFrom..fullTo }
            val fullSmooth = smoothAir(inRange.map { it.temperature })
            val built = inRange.mapIndexedNotNull { index, p ->
                val outsideT = outsideAt(fullOutMap, p.timestamp) ?: return@mapIndexedNotNull null
                InertiaHour(p.timestamp, p.temperature, p.humidity, outsideT, fullSmooth[index])
            }
            if (built.size >= 120) {
                outputHours = built
                outputMass = propagateDisplay(built, best.tauHours, best.outsideWeight)
            } else {
                outputHours = hours
                outputMass = best.mass
            }
        } else {
            outputHours = hours
            outputMass = best.mass
        }

        val points = outputHours.mapIndexed { index, h ->
            SamplePoint(
                sensorId = THERMAL_INERTIA_SENSOR_ID,
                timestamp = h.timestamp,
                temperature = round2(outputMass[index]),
                humidity = h.humidity,
                source = PointSource.RECONSTRUCTED,
                confidence = confidence
            )
        }
        if (points.isEmpty()) return null

        val trend = trendPerDay(outputHours, outputMass)
        val currentAir = outputHours.last().smoothAir
        val currentFlux = best.kMass * (outputMass.last() - currentAir)
        val diagnostics = ThermalInertiaDiagnostics(
            sourceSensorId = sensor.id,
            sourceRoom = sensor.room,
            currentC = round2(best.mass.last()),
            trendCPerDay = trend,
            tauHours = best.tauHours,
            couplingPerHour = best.kMass,
            outsideWeight = best.outsideWeight,
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


    private fun allHourly(sensorId: Long): List<SamplePoint> {
        PointSourceStore.ensure(db.readableDatabase)
        val raw = mutableListOf<SamplePoint>()
        db.readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity, ps.source
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source<>'forecast')
            ORDER BY p.timestamp
            """.trimIndent(),
            arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) {
                val source = PointSource.fromDb(if (c.isNull(3)) null else c.getString(3))
                raw += SamplePoint(sensorId, c.getLong(0), c.getDouble(1), c.getDouble(2), source, 1.0)
            }
        }
        return raw.groupBy { bucket(it.timestamp) }.map { (ts, values) ->
            val priority = values.maxOf { it.source.priority }
            val best = values.filter { it.source.priority == priority }
            SamplePoint(
                sensorId, ts, best.map { it.temperature }.average(), best.map { it.humidity }.average(),
                best.first().source, best.mapNotNull { it.confidence }.averageOr(1.0)
            )
        }.sortedBy { it.timestamp }
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


    private fun propagateDisplay(
        hours: List<InertiaHour>,
        tauHours: Double,
        outsideWeight: Double
    ): DoubleArray {
        val mass = DoubleArray(hours.size)
        mass[0] = hours[0].smoothAir * 0.78 + hours[0].outside * 0.22
        for (i in 1 until hours.size) {
            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())
                .coerceIn(0.5, 24.0)
            val target = hours[i - 1].smoothAir * (1.0 - outsideWeight) +
                hours[i - 1].outside * outsideWeight
            val alpha = 1.0 - exp(-dt / tauHours.coerceAtLeast(24.0))
            mass[i] = (mass[i - 1] + alpha * (target - mass[i - 1])).coerceIn(-5.0, 50.0)
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
