from pathlib import Path

ENGINE = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt')
UI = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')
WEATHER = Path('app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f'v0.10.1: anchor missing: {label}')
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# ThermalEngine: same RC model, safer orchestration and FORWARD reconstruction.
# ---------------------------------------------------------------------------
text = ENGINE.read_text(encoding='utf-8')
text = text.replace('private const val MIN_REAL_DAYS = 15', 'private const val MIN_REAL_DAYS = 16')

old = '''data class ThermalSensorStatus(
    val sensor: Sensor,
    val realDays: Int,
    val model: ThermalModel?
)

data class ThermalStatus(
    val reference: WeatherReference,
    val sensors: List<ThermalSensorStatus>,
    val preferred: ThermalSensorStatus?,
    val message: String
) {
    val canReconstruct: Boolean get() = sensors.any { it.model?.acceptable == true }
}

data class ThermalWriteSummary(
    val reconstructed: Int,
    val forecast: Int,
    val skippedSensors: Int
)
'''
new = '''data class ThermalSensorStatus(
    val sensor: Sensor,
    val realDays: Int,
    val model: ThermalModel?,
    val measuredHours: Int = 0,
    val ignoredHours: Int = 0
) {
    val retainedRatio: Double
        get() {
            val transitions = (measuredHours - 1).coerceAtLeast(1)
            return ((transitions - ignoredHours).coerceAtLeast(0)).toDouble() / transitions.toDouble()
        }
}

data class ThermalStatus(
    val reference: WeatherReference,
    val sensors: List<ThermalSensorStatus>,
    val preferred: ThermalSensorStatus?,
    val message: String
) {
    // Le tourniquet pilote réellement la sonde active : si elle ne passe pas les garde-fous,
    // la reconstruction reste désactivée même si une autre sonde serait acceptable.
    val canReconstruct: Boolean get() = preferred?.model?.acceptable == true
}

data class ThermalWriteSummary(
    val reconstructed: Int,
    val forecast: Int,
    val skippedSensors: Int,
    val raccords: Int = 0,
    val maxRaccordDrift: Double = 0.0
)

private data class ForwardFillSummary(
    val created: Int = 0,
    val raccords: Int = 0,
    val maxDrift: Double = 0.0
)
'''
text = replace_once(text, old, new, 'thermal status data classes')

old = '''    fun status(reference: WeatherReference): ThermalStatus {
        val candidates = physicalSensors().map { sensor ->
            val real = measuredHourly(sensor.id)
            val days = distinctDays(real)
            val model = if (days >= MIN_REAL_DAYS) runCatching { calibrate(sensor, reference) }.getOrNull() else null
            ThermalSensorStatus(sensor, days, model)
        }
        val preferred = candidates.sortedWith(
            compareBy<ThermalSensorStatus> { preferenceRank(it.sensor.room) }
                .thenByDescending { it.realDays }
        ).firstOrNull()
        val enough = candidates.any { it.realDays >= MIN_REAL_DAYS }
        val message = if (!enough) {
            "FabData ne dispose pas encore de suffisamment de mesures pour apprendre correctement l'inertie thermique du bâtiment. Il est préférable d'attendre davantage de données plutôt que de produire une reconstruction incertaine."
        } else if (candidates.none { it.model?.acceptable == true }) {
            "Les données sont assez longues, mais la validation rétrospective n'est pas encore assez bonne pour autoriser une reconstruction fiable."
        } else {
            "Modèle thermique RC validé. Les périodes perturbées sont écartées autant que possible avant calibration."
        }
        return ThermalStatus(reference, candidates, preferred, message)
    }
'''
new = '''    fun status(reference: WeatherReference, selectedSensorId: Long? = null): ThermalStatus {
        val candidates = physicalSensors().map { sensor ->
            val real = measuredHourly(sensor.id)
            val days = distinctDays(real)
            val model = if (days >= MIN_REAL_DAYS) runCatching { calibrate(sensor, reference) }.getOrNull() else null
            val transitions = (real.size - 1).coerceAtLeast(0)
            val usable = model?.usablePoints?.coerceAtMost(transitions) ?: 0
            ThermalSensorStatus(
                sensor = sensor,
                realDays = days,
                model = model,
                measuredHours = real.size,
                ignoredHours = (transitions - usable).coerceAtLeast(0)
            )
        }
        // Par défaut : la courbe qui garde le plus de données après filtrage des perturbations.
        // Salle de bain / chambre sud-est ne servent plus que de départage en cas d'égalité.
        val automatic = candidates
            .filter { it.model?.acceptable == true }
            .sortedWith(
                compareByDescending<ThermalSensorStatus> { it.retainedRatio }
                    .thenByDescending { it.realDays }
                    .thenBy { preferenceRank(it.sensor.room) }
            )
            .firstOrNull()
            ?: candidates.sortedWith(
                compareByDescending<ThermalSensorStatus> { it.realDays }
                    .thenBy { preferenceRank(it.sensor.room) }
            ).firstOrNull()
        val preferred = candidates.firstOrNull { it.sensor.id == selectedSensorId } ?: automatic
        val enough = candidates.any { it.realDays >= MIN_REAL_DAYS }
        val message = if (!enough) {
            "FabData ne dispose pas encore d'au moins 16 jours de mesures réelles exploitables. Il est préférable d'attendre davantage de données plutôt que de produire une reconstruction incertaine."
        } else if (candidates.none { it.model?.acceptable == true }) {
            "Les données sont assez longues, mais la validation rétrospective n'est pas encore assez bonne pour autoriser une reconstruction fiable."
        } else {
            "Modèle thermique RC validé. FabData utilise toutes les données réelles propres disponibles au-delà du minimum de 16 jours."
        }
        return ThermalStatus(reference, candidates, preferred, message)
    }
'''
text = replace_once(text, old, new, 'status selector')

text = text.replace('require(realDays >= MIN_REAL_DAYS) { "Moins de 15 jours réels exploitables" }',
                    'require(realDays >= MIN_REAL_DAYS) { "Moins de 16 jours réels exploitables" }')

old = '''        val outside = referenceHourly(reference.key, from, to, includeForecast = false)
        require(outside.size >= 120) { "Référence météo extérieure insuffisante" }
        val outMap = outside.associateBy { hourBucket(it.timestamp) }
'''
new = '''        val outside = referenceHourly(reference.key, from, to, includeForecast = false)
        require(outside.size >= 120) { "Référence météo extérieure insuffisante" }
        require(referenceCoverageReady(outside, from, to)) {
            "Référence météo extérieure incomplète : reconstruire/compléter ${reference.city} avant de calibrer le bâtiment"
        }
        val outMap = outside.associateBy { hourBucket(it.timestamp) }
'''
text = replace_once(text, old, new, 'reference coverage before calibration')

start = text.find('    /** Reconstruction consentie : jusqu\'à 90 jours avant la première mesure réelle + petits trous internes. */\n    fun reconstructHistory(')
end = text.find('    /** Prévision courte automatique H+6', start)
if start < 0 or end < 0:
    if 'FORWARD depuis le point le plus ancien' not in text:
        raise SystemExit('v0.10.1: reconstructHistory block not found')
else:
    new_block = '''    /**
     * Reconstruction consentie, FORWARD depuis le point le plus ancien.
     * Le modèle RC n'est pas inversé. Lyon (réel + reconstruit) pilote la propagation,
     * puis chaque vraie mesure intérieure sert de raccord observable et non de correction cachée.
     */
    fun reconstructHistory(
        reference: WeatherReference,
        requestedDays: Int,
        sensorId: Long? = null
    ): ThermalWriteSummary {
        val days = requestedDays.coerceIn(1, MAX_HISTORY_DAYS)
        var total = 0
        var skipped = 0
        var raccords = 0
        var maxDrift = 0.0
        val targets = physicalSensors().filter { sensorId == null || it.id == sensorId }
        targets.forEach { sensor ->
            val model = runCatching { calibrate(sensor, reference) }.getOrNull()
            if (model == null || !model.acceptable) {
                skipped++
                return@forEach
            }
            val measured = measuredHourly(sensor.id)
            if (measured.isEmpty()) { skipped++; return@forEach }
            val first = measured.first()
            val refBounds = referenceStore.bounds(reference.key) ?: run { skipped++; return@forEach }
            val requestedStart = first.timestamp - days.toLong() * THERMAL_DAY_MS
            val startAt = max(requestedStart, refBounds.first)
            if (startAt >= first.timestamp) { skipped++; return@forEach }

            val outside = referenceHourly(
                reference.key,
                startAt - 18L * THERMAL_HOUR_MS,
                measured.last().timestamp,
                includeForecast = false
            )
            if (outside.size < 24 || !referenceCoverageReady(outside, startAt, first.timestamp)) {
                skipped++
                return@forEach
            }
            val outMap = outside.associateBy { hourBucket(it.timestamp) }

            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap)
            total += before.created
            raccords += before.raccords
            maxDrift = max(maxDrift, before.maxDrift)

            val gaps = fillInteriorGapsForward(sensor, model, reference)
            total += gaps.created
            raccords += gaps.raccords
            maxDrift = max(maxDrift, gaps.maxDrift)
        }
        return ThermalWriteSummary(total, 0, skipped, raccords, maxDrift)
    }

'''
    text = text[:start] + new_block + text[end:]

# Forecast selector: preserve default null for compatibility but let UI drive one model.
text = text.replace(
    '    fun refreshForecasts(reference: WeatherReference): ThermalWriteSummary {\n        var total = 0\n        var skipped = 0\n        physicalSensors().forEach { sensor ->',
    '    fun refreshForecasts(reference: WeatherReference, sensorId: Long? = null): ThermalWriteSummary {\n        var total = 0\n        var skipped = 0\n        physicalSensors().filter { sensorId == null || it.id == sensorId }.forEach { sensor ->'
)

start = text.find('    private fun fillInteriorGaps(')
end = text.find('    private fun provenance(', start)
if start < 0 or end < 0:
    if 'fillInteriorGapsForward' not in text:
        raise SystemExit('v0.10.1: fillInteriorGaps block not found')
else:
    helpers = '''    private fun reconstructBeforeFirst(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        first: HourPoint,
        startAt: Long,
        outside: Map<Long, HourPoint>
    ): ForwardFillSummary {
        val start = hourBucket(startAt)
        val firstHour = hourBucket(first.timestamp)
        val extStart = start - model.lagHours * THERMAL_HOUR_MS
        val tout = outsideAt(outside, extStart) ?: return ForwardFillSummary()
        val avg6 = outsideAverage(outside, extStart, 6) ?: tout
        val hour = Instant.ofEpochMilli(start).atZone(zone).hour
        var current = equilibriumTemperature(model.coefficients, tout, avg6, hour)
            ?: return ForwardFillSummary()
        if (!plausibleIndoor(current)) return ForwardFillSummary()
        var currentH = outside[hourBucket(start)]?.humidity ?: first.humidity
        var created = 0
        var ts = start

        while (ts < firstHour) {
            val horizonDays = (first.timestamp - ts).toDouble() / THERMAL_DAY_MS.toDouble()
            val confidence = (model.confidence * (1.0 - 0.0065 * horizonDays)).coerceIn(0.20, model.confidence)
            val write = PointSourceStore.upsertByPriority(
                db, sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
            )
            if (write == PriorityWriteResult.INSERTED || write == PriorityWriteResult.REPLACED) created++

            val extTs = ts - model.lagHours * THERMAL_HOUR_MS
            val ext = outsideAt(outside, extTs) ?: break
            val extAvg6 = outsideAverage(outside, extTs, 6) ?: ext
            val stepHour = Instant.ofEpochMilli(ts).atZone(zone).hour
            val next = current + predictDelta(model.coefficients, current, ext, extAvg6, stepHour)
            if (!plausibleIndoor(next)) break
            val outHum = outside[hourBucket(ts)]?.humidity ?: currentH
            currentH += 0.08 * (outHum - currentH)
            current = next
            ts += THERMAL_HOUR_MS
        }

        // On ne corrige PAS la trajectoire pour rejoindre la mesure : l'écart est le diagnostic.
        val reached = ts >= firstHour
        val drift = if (reached) abs(current - first.temperature) else 0.0
        return ForwardFillSummary(created, if (reached) 1 else 0, drift)
    }

    private fun fillInteriorGapsForward(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference
    ): ForwardFillSummary {
        val measured = measuredHourly(sensor.id)
        if (measured.size < 2) return ForwardFillSummary()
        val out = referenceHourly(
            reference.key,
            measured.first().timestamp - 18L * THERMAL_HOUR_MS,
            measured.last().timestamp,
            false
        )
        val outMap = out.associateBy { hourBucket(it.timestamp) }
        var created = 0
        var raccords = 0
        var maxDrift = 0.0

        measured.zipWithNext().forEach { (left, right) ->
            val gapHours = ((right.timestamp - left.timestamp) / THERMAL_HOUR_MS).toInt()
            if (gapHours !in 2..(14 * 24)) return@forEach
            var current = left.temperature
            var currentH = left.humidity
            var completed = true

            for (step in 1 until gapHours) {
                val previousTs = hourBucket(left.timestamp) + (step - 1) * THERMAL_HOUR_MS
                val ts = previousTs + THERMAL_HOUR_MS
                val extTs = previousTs - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs) ?: run { completed = false; break }
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
                val hour = Instant.ofEpochMilli(previousTs).atZone(zone).hour
                val predicted = current + predictDelta(model.coefficients, current, tout, avg6, hour)
                if (!plausibleIndoor(predicted)) { completed = false; break }
                current = predicted
                val outHum = outMap[hourBucket(ts)]?.humidity ?: currentH
                currentH += 0.08 * (outHum - currentH)
                val confidence = (model.confidence * 0.82).coerceIn(0.20, 0.85)
                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) created++
            }

            if (completed) {
                // Projection d'une heure supplémentaire jusqu'au vrai point de droite,
                // uniquement pour mesurer la dérive avant le raccord réel.
                val previousTs = hourBucket(right.timestamp) - THERMAL_HOUR_MS
                val extTs = previousTs - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs)
                val avg6 = if (tout != null) outsideAverage(outMap, extTs, 6) ?: tout else null
                if (tout != null && avg6 != null) {
                    val hour = Instant.ofEpochMilli(previousTs).atZone(zone).hour
                    val projectedAtRight = current + predictDelta(model.coefficients, current, tout, avg6, hour)
                    if (plausibleIndoor(projectedAtRight)) {
                        raccords++
                        maxDrift = max(maxDrift, abs(projectedAtRight - right.temperature))
                    }
                }
            }
        }
        return ForwardFillSummary(created, raccords, maxDrift)
    }

    private fun equilibriumTemperature(coeff: DoubleArray, tout: Double, avg6: Double, hour: Int): Double? {
        val exchange = coeff[0] + coeff[1]
        if (!exchange.isFinite() || abs(exchange) < 0.002) return null
        val seasonal = coeff[2] * sin(2.0 * PI * hour / 24.0) +
            coeff[3] * cos(2.0 * PI * hour / 24.0) + coeff[4]
        val value = (coeff[0] * tout + coeff[1] * avg6 + seasonal) / exchange
        return value.takeIf { it.isFinite() }
    }

    private fun plausibleIndoor(value: Double): Boolean = value.isFinite() && value in -5.0..50.0

    private fun referenceCoverageReady(points: List<HourPoint>, from: Long, to: Long): Boolean {
        if (to <= from) return false
        val start = hourBucket(from)
        val end = hourBucket(to)
        val expected = (((end - start) / THERMAL_HOUR_MS) + 1L).coerceAtLeast(1L)
        val buckets = points.asSequence()
            .map { hourBucket(it.timestamp) }
            .filter { it in start..end }
            .distinct()
            .sorted()
            .toList()
        if (buckets.isEmpty()) return false
        val coverage = buckets.size.toDouble() / expected.toDouble()
        val maxGapHours = buckets.zipWithNext().maxOfOrNull { (a, b) ->
            ((b - a) / THERMAL_HOUR_MS).toInt()
        } ?: 1
        return coverage >= 0.90 && maxGapHours <= 3
    }

'''
    text = text[:start] + helpers + text[end:]

ENGINE.write_text(text, encoding='utf-8')

# ---------------------------------------------------------------------------
# Weather reference: detect holes, not only start/end bounds, before modelling.
# ---------------------------------------------------------------------------
text = WEATHER.read_text(encoding='utf-8')
old = '''        val needsHistory = existing.size < 24 || store.bounds(reference.key)?.let { it.first > from || it.last < minOf(to, System.currentTimeMillis()) } != false
        return if (needsHistory) {
'''
new = '''        val historyEnd = minOf(to, System.currentTimeMillis())
        val needsHistory = existing.size < 24 ||
            store.bounds(reference.key)?.let { it.first > from || it.last < historyEnd } != false ||
            hasMaterialHourlyGaps(existing, from, historyEnd)
        return if (needsHistory) {
'''
text = replace_once(text, old, new, 'weather cache gap detection')

anchor = '    private fun reconstructShortGaps(referenceKey: String, from: Long, to: Long): Int {'
if 'private fun hasMaterialHourlyGaps(' not in text:
    if anchor not in text:
        raise SystemExit('v0.10.1: weather helper anchor missing')
    helper = '''    private fun hasMaterialHourlyGaps(
        points: List<WeatherReferencePoint>,
        from: Long,
        to: Long
    ): Boolean {
        if (to <= from) return true
        val start = roundHour(from)
        val end = roundHour(to)
        val buckets = points.asSequence()
            .filter { it.source != PointSource.FORECAST }
            .map { roundHour(it.timestamp) }
            .filter { it in start..end }
            .distinct()
            .sorted()
            .toList()
        if (buckets.isEmpty()) return true
        val expected = (((end - start) / hourMs) + 1L).coerceAtLeast(1L)
        val coverage = buckets.size.toDouble() / expected.toDouble()
        val maxGap = buckets.zipWithNext().maxOfOrNull { (a, b) -> ((b - a) / hourMs).toInt() } ?: 1
        return coverage < 0.90 || maxGap > 3
    }

'''
    text = text.replace(anchor, helper + anchor, 1)
WEATHER.write_text(text, encoding='utf-8')

# ---------------------------------------------------------------------------
# UI: carousel for model sensor + force reference preparation before history.
# ---------------------------------------------------------------------------
text = UI.read_text(encoding='utf-8')
text = replace_once(
    text,
    '    var suppressNextAuto by remember { mutableStateOf(false) }\n',
    '    var suppressNextAuto by remember { mutableStateOf(false) }\n    var selectedSensorId by remember { mutableStateOf<Long?>(null) }\n',
    'selected model sensor state'
)

text = text.replace('                val thermalStatus = engine.status(reference)',
                    '                val thermalStatus = engine.status(reference, selectedSensorId)')
text = text.replace(
    '                    engine.refreshForecasts(reference)\n',
    '                    engine.refreshForecasts(reference, selectedSensorId ?: thermalStatus.preferred?.sensor?.id)\n'
)

old = '''                status = thermalStatus
                info = "${sync.label} · ${sync.measured} réel(s) · ${sync.reconstructed} reconstruit(s) · H+6 ${forecast.forecast} point(s)"
'''
new = '''                status = thermalStatus
                if (selectedSensorId == null || thermalStatus.sensors.none { it.sensor.id == selectedSensorId }) {
                    selectedSensorId = thermalStatus.preferred?.sensor?.id
                }
                info = "${sync.label} · ${sync.measured} réel(s) · ${sync.reconstructed} reconstruit(s) · H+6 ${forecast.forecast} point(s)"
'''
text = replace_once(text, old, new, 'selected sensor initialization')
text = text.replace('status = runCatching { engine.status(reference) }.getOrNull()',
                    'status = runCatching { engine.status(reference, selectedSensorId) }.getOrNull()')
text = text.replace('LaunchedEffect(dataVersion, selectedKey) {', 'LaunchedEffect(dataVersion, selectedKey, selectedSensorId) {')

old = '''                val preferred = s.preferred
                if (preferred != null) {
                    Text(
                        "Calibration prioritaire : ${preferred.sensor.room} · ${preferred.realDays} jour(s) réels",
                        fontWeight = FontWeight.SemiBold
                    )
                }
                val model = preferred?.model
'''
new = '''                val preferred = s.preferred
                if (preferred != null) {
                    val selectable = s.sensors.filter { it.realDays >= 16 }.ifEmpty { s.sensors }
                    val index = selectable.indexOfFirst { it.sensor.id == preferred.sensor.id }.coerceAtLeast(0)
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedButton(
                            onClick = {
                                if (selectable.isNotEmpty()) {
                                    val next = (index - 1 + selectable.size) % selectable.size
                                    selectedSensorId = selectable[next].sensor.id
                                }
                            },
                            enabled = !busy && selectable.size > 1
                        ) { Text("◀") }
                        Column(Modifier.weight(1f)) {
                            Text("Sonde du modèle", style = MaterialTheme.typography.labelMedium)
                            Text(
                                "${preferred.sensor.room} · ${preferred.realDays} jour(s) réels",
                                fontWeight = FontWeight.SemiBold
                            )
                            Text(
                                "Conservé ${(preferred.retainedRatio * 100).toInt()} % · ignoré ${preferred.ignoredHours} h",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        OutlinedButton(
                            onClick = {
                                if (selectable.isNotEmpty()) {
                                    val next = (index + 1) % selectable.size
                                    selectedSensorId = selectable[next].sensor.id
                                }
                            },
                            enabled = !busy && selectable.size > 1
                        ) { Text("▶") }
                    }
                }
                val model = preferred?.model
'''
text = replace_once(text, old, new, 'model sensor carousel')

text = text.replace(
    '"Garde-fou : moins de 15 jours réels = aucune reconstruction historique. La prévision H+6 reste distincte et diminue en confiance avec l\'horizon."',
    '"Garde-fou : moins de 16 jours réels = aucune reconstruction historique. Au-delà, toutes les données réelles propres disponibles sont utilisées."'
)

old = '''                        val result = withContext(Dispatchers.IO) {
                            runCatching { engine.reconstructHistory(reference, historyDays) }
                        }
'''
new = '''                        val result = withContext(Dispatchers.IO) {
                            runCatching {
                                // Ordre strict : construire d'abord la référence extérieure complète,
                                // puis seulement lancer le modèle intérieur dans le sens du temps.
                                val bounds = db.physicalSensorBounds() ?: db.globalTimeBounds()
                                    ?: error("Aucune donnée intérieure")
                                val from = bounds.first - historyDays.toLong() * 24L * 60L * 60L * 1000L - 18L * 60L * 60L * 1000L
                                val to = maxOf(bounds.last, System.currentTimeMillis() + 7L * 60L * 60L * 1000L)
                                manager.refreshSelected(reference, from, to)
                                val checked = engine.status(reference, selectedSensorId)
                                if (!checked.canReconstruct) error(checked.message)
                                engine.reconstructHistory(reference, historyDays, selectedSensorId ?: checked.preferred?.sensor?.id)
                            }
                        }
'''
text = replace_once(text, old, new, 'reference first historical reconstruction')

old = '''                                info = "Historique : ${it.reconstructed} point(s) reconstruits · ${it.skippedSensors} sonde(s) refusée(s) par les garde-fous"
'''
new = '''                                info = "Historique : ${it.reconstructed} point(s) · ${it.raccords} raccord(s) · dérive max ${fmt(it.maxRaccordDrift)} °C · ${it.skippedSensors} refus"
'''
text = replace_once(text, old, new, 'raccord diagnostics')

UI.write_text(text, encoding='utf-8')

print('FabData v0.10.1 forward reconstruction patch applied')
