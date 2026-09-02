from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# 1) Version
# -----------------------------------------------------------------------------
gradle_path = "app/build.gradle.kts"
gradle = read(gradle_path)
gradle = gradle.replace('versionCode = 23\n        versionName = "0.11.0"', 'versionCode = 24\n        versionName = "0.12.0"')
write(gradle_path, gradle)
print("v0.12.0 / code 24")


# -----------------------------------------------------------------------------
# 2) Forecast mode persisted beside the thermal building profile.
# -----------------------------------------------------------------------------
profile_path = "app/src/main/java/com/fabdata/app/ThermalProfile.kt"
profile = read(profile_path)
if "enum class ForecastHorizonMode" not in profile:
    profile = profile.replace(
        '''enum class ThermalExposure(val label: String) {
    LOW("Faible"),
    MEDIUM("Moyenne"),
    HIGH("Forte")
}
''',
        '''enum class ThermalExposure(val label: String) {
    LOW("Faible"),
    MEDIUM("Moyenne"),
    HIGH("Forte")
}

enum class ForecastHorizonMode(val label: String, val maxHours: Int) {
    H3("3 h", 3),
    H6("6 h", 6),
    AUTO("Auto", 24)
}
''',
        1,
    )
if "fun forecastMode()" not in profile:
    profile = profile.replace(
        '''    fun reset(): ThermalBuildingProfile = ThermalBuildingProfile().also(::save)
}''',
        '''    fun forecastMode(): ForecastHorizonMode = runCatching {
        ForecastHorizonMode.valueOf(prefs.getString("forecast_mode", ForecastHorizonMode.AUTO.name)!!)
    }.getOrDefault(ForecastHorizonMode.AUTO)

    fun saveForecastMode(mode: ForecastHorizonMode) {
        prefs.edit().putString("forecast_mode", mode.name).apply()
    }

    fun reset(): ThermalBuildingProfile = ThermalBuildingProfile().also(::save)
}''',
        1,
    )
write(profile_path, profile)
print("ThermalProfile: horizon 3h/6h/Auto")


# -----------------------------------------------------------------------------
# 3) Point provenance: persist forecast sigma + historical analogue count.
#    Any MEASURED arrival invalidates all later forecasts for that sensor.
# -----------------------------------------------------------------------------
point_path = "app/src/main/java/com/fabdata/app/PointSourceLayer.kt"
point = read(point_path)
point = replace_once(
    point,
    '''data class PointProvenance(
    val source: PointSource,
    val confidence: Double? = null,
    val referenceKey: String? = null,
    val referenceStationId: String? = null,
    val referenceCity: String? = null,
    val calibrationFrom: Long? = null,
    val calibrationTo: Long? = null,
    val modelVersion: String? = null
)''',
    '''data class PointProvenance(
    val source: PointSource,
    val confidence: Double? = null,
    val referenceKey: String? = null,
    val referenceStationId: String? = null,
    val referenceCity: String? = null,
    val calibrationFrom: Long? = null,
    val calibrationTo: Long? = null,
    val modelVersion: String? = null,
    val sigmaC: Double? = null,
    val analogCount: Int? = null
)''',
    "PointSource provenance",
)
point = point.replace('const val MODEL_VERSION = "thermal-rc-mass-2"', 'const val MODEL_VERSION = "thermal-rc-mass-3"')

if "sigma_c REAL" not in point:
    point = point.replace(
        '''                confidence REAL,
                reference_key TEXT,''',
        '''                confidence REAL,
                sigma_c REAL,
                analog_count INTEGER,
                reference_key TEXT,''',
        1,
    )

if "ensureColumn(db, \"sigma_c\"" not in point:
    point = point.replace(
        '''        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_time ON point_sources(sensor_id, timestamp)")
    }

    fun sourceFor''',
        '''        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_time ON point_sources(sensor_id, timestamp)")
        ensureColumn(db, "sigma_c", "REAL")
        ensureColumn(db, "analog_count", "INTEGER")
    }

    private fun ensureColumn(db: SQLiteDatabase, name: String, type: String) {
        val exists = db.rawQuery("PRAGMA table_info(point_sources)", null).use { c ->
            var found = false
            while (c.moveToNext()) {
                if (c.getString(c.getColumnIndexOrThrow("name")) == name) { found = true; break }
            }
            found
        }
        if (!exists) db.execSQL("ALTER TABLE point_sources ADD COLUMN $name $type")
    }

    fun sourceFor''',
        1,
    )

point = replace_once(
    point,
    '''            SELECT source, confidence, reference_key, reference_station_id, reference_city,
                   calibration_from, calibration_to, model_version''',
    '''            SELECT source, confidence, reference_key, reference_station_id, reference_city,
                   calibration_from, calibration_to, model_version, sigma_c, analog_count''',
    "PointSource select metadata",
)
point = replace_once(
    point,
    '''                calibrationTo = if (c.isNull(6)) null else c.getLong(6),
                modelVersion = if (c.isNull(7)) null else c.getString(7)
            )''',
    '''                calibrationTo = if (c.isNull(6)) null else c.getLong(6),
                modelVersion = if (c.isNull(7)) null else c.getString(7),
                sigmaC = if (c.isNull(8)) null else c.getDouble(8),
                analogCount = if (c.isNull(9)) null else c.getInt(9)
            )''',
    "PointSource decode metadata",
)

if "invalidateForecastsAfterMeasured(db, sensorId, timestamp)" not in point:
    point = point.replace(
        '''        db.writableDatabase.delete(
            "point_sources",
            "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
    }

    fun setProvenance''',
        '''        db.writableDatabase.delete(
            "point_sources",
            "sensor_id=? AND timestamp=?",
            arrayOf(sensorId.toString(), timestamp.toString())
        )
        // Une vraie mesure change l'état connu : tout forecast situé après elle
        // appartient désormais à un ancien état du monde et doit disparaître.
        invalidateForecastsAfterMeasured(db, sensorId, timestamp)
    }

    private fun invalidateForecastsAfterMeasured(db: FabDataDb, sensorId: Long, timestamp: Long) {
        ensure(db.writableDatabase)
        val future = mutableListOf<Long>()
        db.readableDatabase.rawQuery(
            "SELECT timestamp FROM point_sources WHERE sensor_id=? AND source='forecast' AND timestamp>?",
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c -> while (c.moveToNext()) future += c.getLong(0) }
        future.forEach { ts ->
            db.writableDatabase.delete("samples", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))
            db.writableDatabase.delete("point_sources", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))
        }
    }

    fun setProvenance''',
        1,
    )

if 'put("sigma_c"' not in point:
    point = point.replace(
        '''            provenance.confidence?.let { put("confidence", it.coerceIn(0.0, 1.0)) }
            provenance.referenceKey?.let { put("reference_key", it) }''',
        '''            provenance.confidence?.let { put("confidence", it.coerceIn(0.0, 1.0)) }
            provenance.sigmaC?.let { put("sigma_c", it.coerceIn(0.0, 20.0)) }
            provenance.analogCount?.let { put("analog_count", it.coerceAtLeast(0)) }
            provenance.referenceKey?.let { put("reference_key", it) }''',
        1,
    )

if "fun reconstructedBounds" not in point:
    point = point.replace(
        '''    fun measuredCount(db: FabDataDb, sensorId: Long, from: Long, to: Long): Int {''',
        '''    fun reconstructedBounds(db: FabDataDb, sensorId: Long): LongRange? {
        ensure(db.readableDatabase)
        db.readableDatabase.rawQuery(
            "SELECT MIN(timestamp), MAX(timestamp) FROM point_sources WHERE sensor_id=? AND source='reconstructed'",
            arrayOf(sensorId.toString())
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    fun measuredCount(db: FabDataDb, sensorId: Long, from: Long, to: Long): Int {''',
        1,
    )
write(point_path, point)
print("PointSource: sigma/analogues + invalidation forecast")


# -----------------------------------------------------------------------------
# 4) Data layer: expose uncertainty to chart + inspector.
# -----------------------------------------------------------------------------
data_path = "app/src/main/java/com/fabdata/app/DataLayer.kt"
data = read(data_path)
data = replace_once(
    data,
    '''data class SamplePoint(
    val sensorId: Long,
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val source: PointSource = PointSource.MEASURED,
    val confidence: Double? = null
)''',
    '''data class SamplePoint(
    val sensorId: Long,
    val timestamp: Long,
    val temperature: Double,
    val humidity: Double,
    val source: PointSource = PointSource.MEASURED,
    val confidence: Double? = null,
    val uncertaintyC: Double? = null,
    val analogCount: Int? = null
)''',
    "SamplePoint",
)
data = replace_once(
    data,
    '''            SELECT p.timestamp, p.temperature, p.humidity, ps.source, ps.confidence
            FROM samples p''',
    '''            SELECT p.timestamp, p.temperature, p.humidity, ps.source, ps.confidence, ps.sigma_c, ps.analog_count
            FROM samples p''',
    "querySamples select",
)
data = replace_once(
    data,
    '''                    PointSource.fromDb(if (c.isNull(3)) null else c.getString(3)),
                    if (c.isNull(4)) null else c.getDouble(4)
                )''',
    '''                    PointSource.fromDb(if (c.isNull(3)) null else c.getString(3)),
                    if (c.isNull(4)) null else c.getDouble(4),
                    if (c.isNull(5)) null else c.getDouble(5),
                    if (c.isNull(6)) null else c.getInt(6)
                )''',
    "querySamples decode",
)
write(data_path, data)
print("DataLayer: incertitude exposée au graphe")


# -----------------------------------------------------------------------------
# 5) Thermal engine: adaptive forecast + analogues + auto refresh of existing
#    reconstructed segments after new MEASURED data.
# -----------------------------------------------------------------------------
engine_path = "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
engine = read(engine_path)

engine = replace_once(
    engine,
    '''data class ThermalWriteSummary(
    val reconstructed: Int,
    val forecast: Int,
    val skippedSensors: Int,
    val raccords: Int = 0,
    val maxRaccordDrift: Double = 0.0,
    val diagnostic: String? = null
)''',
    '''data class ThermalWriteSummary(
    val reconstructed: Int,
    val forecast: Int,
    val skippedSensors: Int,
    val raccords: Int = 0,
    val maxRaccordDrift: Double = 0.0,
    val diagnostic: String? = null,
    val forecastHorizonHours: Int = 0,
    val maxForecastSigma: Double = 0.0,
    val analogCount: Int = 0
)''',
    "ThermalWriteSummary",
)

if "private data class ForecastAnalogStats" not in engine:
    engine = engine.replace(
        '''private data class TrainingRow(
    val timestamp: Long,
    val tin: Double,
    val nextTin: Double,
    val tout: Double,
    val toutAvg6: Double,
    val hourOfDay: Int,
    val features: DoubleArray,
    val delta: Double
)
''',
        '''private data class TrainingRow(
    val timestamp: Long,
    val tin: Double,
    val nextTin: Double,
    val tout: Double,
    val toutAvg6: Double,
    val hourOfDay: Int,
    val features: DoubleArray,
    val delta: Double
)

private data class ForecastAnalogStats(
    val meanDelta: Double? = null,
    val sigma: Double? = null,
    val count: Int = 0
)
''',
        1,
    )

start_marker = "    /** Prévision courte automatique H+6, toujours recalculée depuis la dernière vraie mesure. */"
end_marker = "    private fun reconstructBeforeFirst("
if "fun refreshExistingReconstructions" not in engine:
    start = engine.find(start_marker)
    end = engine.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("ThermalEngine: fonction forecast introuvable")
    replacement = r'''    /**
     * Une nouvelle vraie mesure invalide déjà les forecasts via PointSourceStore.
     * Si la sonde possédait un historique reconstruit consentie auparavant, on le
     * recalcule avec le modèle enrichi sans toucher aux points MEASURED.
     */
    fun refreshExistingReconstructions(
        reference: WeatherReference,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        sensorId: Long? = null
    ): ThermalWriteSummary {
        var total = 0
        var skipped = 0
        var raccords = 0
        var maxDrift = 0.0
        var diagnostic: String? = null
        physicalSensors().filter { sensorId == null || it.id == sensorId }.forEach { sensor ->
            val existing = PointSourceStore.reconstructedBounds(db, sensor.id) ?: return@forEach
            val measured = measuredHourly(sensor.id)
            val first = measured.firstOrNull() ?: return@forEach
            if (existing.first < first.timestamp) {
                val span = (first.timestamp - existing.first).coerceAtLeast(THERMAL_DAY_MS)
                val days = ((span + THERMAL_DAY_MS - 1L) / THERMAL_DAY_MS).toInt().coerceIn(1, MAX_HISTORY_DAYS)
                val r = reconstructHistory(reference, days, sensor.id, profile)
                total += r.reconstructed
                skipped += r.skippedSensors
                raccords += r.raccords
                maxDrift = max(maxDrift, r.maxRaccordDrift)
                if (diagnostic == null && r.diagnostic != null) diagnostic = r.diagnostic
            } else {
                val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()
                if (model == null || !model.acceptable) { skipped++; return@forEach }
                val r = fillInteriorGapsForward(sensor, model, reference, profile)
                total += r.created
                raccords += r.raccords
                maxDrift = max(maxDrift, r.maxDrift)
                if (diagnostic == null && r.diagnostic != null) diagnostic = r.diagnostic
            }
        }
        return ThermalWriteSummary(total, 0, skipped, raccords, maxDrift, diagnostic)
    }

    /**
     * Prévision adaptative. La courbe centrale reste RC + masse thermique.
     * L'incertitude combine validation du modèle, météo et dispersion de situations
     * historiques analogues. En Auto, on peut aller jusqu'à H+24 mais on s'arrête
     * dès que sigma dépasse 1,5 °C après les trois premières heures.
     */
    fun refreshForecasts(
        reference: WeatherReference,
        sensorId: Long? = null,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        mode: ForecastHorizonMode = ForecastHorizonMode.AUTO
    ): ThermalWriteSummary {
        var total = 0
        var skipped = 0
        var furthest = 0
        var maxSigma = 0.0
        var bestAnalogCount = 0

        physicalSensors().filter { sensorId == null || it.id == sensorId }.forEach { sensor ->
            val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()
            if (model == null || !model.acceptable) { skipped++; return@forEach }
            val measured = measuredHourly(sensor.id)
            val latest = measured.lastOrNull() ?: run { skipped++; return@forEach }
            val recent = measured.takeLast(5)
            PointSourceStore.deleteForecastsAtOrAfter(db, sensor.id, latest.timestamp + 1L)

            val from = latest.timestamp - 18L * THERMAL_HOUR_MS
            val to = latest.timestamp + (mode.maxHours + 1L) * THERMAL_HOUR_MS
            val outside = referenceHourly(reference.key, from, to, includeForecast = true)
            val outMap = outside.associateBy { hourBucket(it.timestamp) }
            if (outside.none { it.timestamp > latest.timestamp }) { skipped++; return@forEach }

            val slopes = recent.zipWithNext().mapNotNull { (a, b) ->
                val dt = (b.timestamp - a.timestamp).toDouble() / THERMAL_HOUR_MS.toDouble()
                if (dt <= 0.0 || dt > 2.5) null else (b.temperature - a.temperature) / dt
            }
            val recentSlope = slopes.takeLast(3).averageOrZero()
            val curvature = if (slopes.size >= 2) slopes.last() - slopes[slopes.lastIndex - 1] else 0.0

            var currentT = latest.temperature
            var currentH = latest.humidity
            var currentMass = estimateCurrentMass(profile, measured, outMap)

            for (horizon in 1..mode.maxHours) {
                val ts = hourBucket(latest.timestamp) + horizon * THERMAL_HOUR_MS
                val extTs = ts - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs) ?: break
                val weatherPoint = outMap[hourBucket(ts)]
                val outHum = weatherPoint?.humidity ?: currentH
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
                val hour = Instant.ofEpochMilli(ts - THERMAL_HOUR_MS).atZone(zone).hour

                val modelDelta = massAwareDelta(model.coefficients, currentT, currentMass, tout, avg6, hour, profile)
                val momentum = (recentSlope + 0.45 * curvature) * exp(-(horizon - 1).toDouble() / 1.7)
                val rawNext = currentT + (modelDelta + 0.30 * momentum).coerceIn(-1.2, 1.2)

                val analog = forecastAnalogs(measured, latest, horizon, recentSlope)
                val analogueReliability = (analog.count / 12.0).coerceIn(0.0, 1.0)
                val analogueCoherence = analog.sigma?.let { (1.0 - it / 1.5).coerceIn(0.0, 1.0) } ?: 0.0
                val analogueWeight = 0.28 * analogueReliability * analogueCoherence
                val cumulativeRaw = rawNext - latest.temperature
                val analogueTarget = analog.meanDelta
                val adjustedNext = if (analogueTarget != null) {
                    rawNext + analogueWeight * (analogueTarget - cumulativeRaw)
                } else rawNext
                val delta = (adjustedNext - currentT).coerceIn(-1.2, 1.2)

                val validationSigma =
                    model.metrics.rmse * 0.45 * sqrt(horizon.toDouble()) +
                    model.longHorizonRmse * 0.10 * (horizon.toDouble() / 6.0)
                val historicalSigma = analog.sigma ?: (validationSigma * 1.25)
                val mixedSigma = validationSigma * (1.0 - 0.55 * analogueReliability) +
                    historicalSigma * (0.55 * analogueReliability)
                val weatherConfidence = weatherPoint?.confidence?.coerceIn(0.20, 1.0) ?: 0.65
                val weatherSigma = (1.0 - weatherConfidence) * (0.35 + 0.055 * horizon)
                val sigma = sqrt(mixedSigma * mixedSigma + weatherSigma * weatherSigma).coerceIn(0.08, 3.0)

                // Trois heures minimum pour un modèle validé ; ensuite arrêt honnête si l'incertitude explose.
                if (horizon > 3 && sigma > 1.50) break

                val nextMass = advanceMass(profile, currentT, currentMass, avg6)
                currentT += delta
                currentMass = nextMass
                currentH += 0.08 * (outHum - currentH)
                val confidence = (
                    model.confidence * exp(-sigma / 1.45) * (0.72 + 0.28 * weatherConfidence)
                ).coerceIn(0.08, model.confidence)

                val result = PointSourceStore.upsertByPriority(
                    db, sensor.id, ts, round2(currentT), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.FORECAST, confidence, sigma, analog.count)
                )
                if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) total++
                furthest = max(furthest, horizon)
                maxSigma = max(maxSigma, sigma)
                bestAnalogCount = max(bestAnalogCount, analog.count)
            }
        }
        return ThermalWriteSummary(
            reconstructed = 0,
            forecast = total,
            skippedSensors = skipped,
            forecastHorizonHours = furthest,
            maxForecastSigma = maxSigma,
            analogCount = bestAnalogCount
        )
    }

    private fun forecastAnalogs(
        measured: List<HourPoint>,
        latest: HourPoint,
        horizon: Int,
        currentSlope: Double
    ): ForecastAnalogStats {
        if (measured.size < 24) return ForecastAnalogStats()
        val byHour = measured.associateBy { hourBucket(it.timestamp) }
        val latestBucket = hourBucket(latest.timestamp)
        val latestHour = Instant.ofEpochMilli(latest.timestamp).atZone(zone).hour
        val candidates = mutableListOf<Pair<Double, Double>>()

        measured.forEach { candidate ->
            val ts = hourBucket(candidate.timestamp)
            // Garde une vraie séparation entre l'état actuel et les analogues d'apprentissage.
            if (ts >= latestBucket - (horizon + 12L) * THERMAL_HOUR_MS) return@forEach
            val previous = byHour[ts - THERMAL_HOUR_MS] ?: return@forEach
            val future = byHour[ts + horizon * THERMAL_HOUR_MS] ?: return@forEach
            val candidateSlope = candidate.temperature - previous.temperature
            val candidateHour = Instant.ofEpochMilli(candidate.timestamp).atZone(zone).hour
            val rawHourDiff = abs(candidateHour - latestHour)
            val hourDiff = min(rawHourDiff, 24 - rawHourDiff)

            val score =
                abs(candidate.temperature - latest.temperature) / 1.20 +
                abs(candidateSlope - currentSlope) / 0.45 +
                hourDiff / 6.0
            if (score <= 3.2) candidates += score to (future.temperature - candidate.temperature)
        }

        val chosen = candidates.sortedBy { it.first }.take(16).map { it.second }
        if (chosen.size < 3) return ForecastAnalogStats(count = chosen.size)
        val mean = chosen.average()
        val variance = chosen.sumOf { (it - mean) * (it - mean) } / chosen.size.toDouble()
        return ForecastAnalogStats(mean, sqrt(variance).coerceAtLeast(0.03), chosen.size)
    }

'''
    engine = engine[:start] + replacement + engine[end:]

old_prov = '''    private fun provenance(model: ThermalModel, reference: WeatherReference, source: PointSource, confidence: Double) = PointProvenance(
        source = source,
        confidence = confidence,
        referenceKey = reference.key,
        referenceStationId = reference.stationId,
        referenceCity = reference.city,
        calibrationFrom = model.calibrationFrom,
        calibrationTo = model.calibrationTo,
        modelVersion = PointSourceStore.MODEL_VERSION
    )'''
new_prov = '''    private fun provenance(
        model: ThermalModel,
        reference: WeatherReference,
        source: PointSource,
        confidence: Double,
        sigmaC: Double? = null,
        analogCount: Int? = null
    ) = PointProvenance(
        source = source,
        confidence = confidence,
        referenceKey = reference.key,
        referenceStationId = reference.stationId,
        referenceCity = reference.city,
        calibrationFrom = model.calibrationFrom,
        calibrationTo = model.calibrationTo,
        modelVersion = PointSourceStore.MODEL_VERSION,
        sigmaC = sigmaC,
        analogCount = analogCount
    )'''
engine = replace_once(engine, old_prov, new_prov, "ThermalEngine provenance")
write(engine_path, engine)
print("ThermalEngine: forecast adaptatif + analogues + recalcul historique")


# -----------------------------------------------------------------------------
# 6) Thermal UI: 3h / 6h / Auto; auto refresh calculated data after imports.
# -----------------------------------------------------------------------------
ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)
if "var forecastMode by remember" not in ui:
    ui = ui.replace(
        '''    val profileStore = remember { ThermalProfileStore(context) }
    var profile by remember { mutableStateOf(profileStore.load()) }
    val scope = rememberCoroutineScope()''',
        '''    val profileStore = remember { ThermalProfileStore(context) }
    var profile by remember { mutableStateOf(profileStore.load()) }
    var forecastMode by remember { mutableStateOf(profileStore.forecastMode()) }
    val scope = rememberCoroutineScope()''',
        1,
    )

ui = ui.replace(
    '''                val to = maxOf(bounds.last, System.currentTimeMillis() + 7L * 60L * 60L * 1000L)''',
    '''                val to = maxOf(bounds.last, System.currentTimeMillis() + (forecastMode.maxHours + 2L) * 60L * 60L * 1000L)''',
    1,
)
ui = replace_once(
    ui,
    '''                val thermalStatus = engine.status(reference, selectedSensorId, profile)
                val forecast = if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    engine.refreshForecasts(reference, selectedSensorId ?: thermalStatus.preferred?.sensor?.id, profile)
                } else ThermalWriteSummary(0, 0, 0)''',
    '''                val thermalStatus = engine.status(reference, selectedSensorId, profile)
                val activeSensor = selectedSensorId ?: thermalStatus.preferred?.sensor?.id
                if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    // Si un historique calculé existait déjà, une nouvelle mesure réelle
                    // l'enrichit automatiquement sans jamais modifier les points MEASURED.
                    engine.refreshExistingReconstructions(reference, profile, activeSensor)
                }
                val forecast = if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    engine.refreshForecasts(reference, activeSensor, profile, forecastMode)
                } else ThermalWriteSummary(0, 0, 0)''',
    "ThermalUi refresh",
)
ui = replace_once(
    ui,
    '''                info = "${sync.label} · ${sync.measured} réel(s) · ${sync.reconstructed} reconstruit(s) · H+6 ${forecast.forecast} point(s)"''',
    '''                val horizon = forecast.forecastHorizonHours.takeIf { it > 0 }?.let { "H+$it" } ?: "—"
                val sigma = forecast.maxForecastSigma.takeIf { it > 0.0 }?.let { " · σ max ${fmt(it)} °C" }.orEmpty()
                val analogues = forecast.analogCount.takeIf { it > 0 }?.let { " · $it analogues" }.orEmpty()
                info = "${sync.label} · ${sync.measured} réel(s) · ${sync.reconstructed} reconstruit(s) · prévision $horizon ${forecast.forecast} point(s)$sigma$analogues"''',
    "ThermalUi info",
)
ui = ui.replace(
    '''                status = runCatching { engine.status(reference, selectedSensorId) }.getOrNull()''',
    '''                status = runCatching { engine.status(reference, selectedSensorId, profile) }.getOrNull()''',
    1,
)
ui = ui.replace(
    '''    // Prévision H+6 automatique après changement de données/référence.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile) {''',
    '''    // Toute nouvelle vraie donnée invalide d'abord l'ancien futur, puis ce cycle
    // recalcule historique calculé existant + nouvelle prévision depuis l'état réel.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {''',
    1,
)

if 'Text("Prévision adaptative"' not in ui:
    anchor = '''            OutlinedButton(
                onClick = { weatherHistoryDialog = true },'''
    forecast_card = '''            Card(shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("Prévision adaptative", fontWeight = FontWeight.SemiBold)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        ForecastHorizonMode.entries.forEach { mode ->
                            FilterChip(
                                selected = forecastMode == mode,
                                onClick = {
                                    forecastMode = mode
                                    profileStore.saveForecastMode(mode)
                                },
                                label = { Text(mode.label) }
                            )
                        }
                    }
                    Text(
                        "Auto peut prolonger jusqu'à H+24. Les points d'incertitude s'espacent avec l'horizon et la prévision s'arrête après H+3 si σ dépasse 1,5 °C. Une nouvelle mesure réelle efface immédiatement l'ancien futur puis le recalcule.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

'''
    if anchor not in ui:
        raise SystemExit("ThermalUi: ancre météo introuvable")
    ui = ui.replace(anchor, forecast_card + anchor, 1)
write(ui_path, ui)
print("ThermalUi: sélecteur forecast et boucle d'invalidation")


# -----------------------------------------------------------------------------
# 7) Main chart + inspector: forecast cloud alternates +sigma/-sigma and becomes
#    progressively sparser; cursor tells the user sigma/confidence/analogues.
# -----------------------------------------------------------------------------
main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)
main = replace_once(
    main,
    '''            .filter { it.timestamp in visibleFrom..visibleTo }
            .map { it.temperature }

        val humidityValues''',
    '''            .filter { it.timestamp in visibleFrom..visibleTo }
            .flatMap { p ->
                if (p.source == PointSource.FORECAST && p.uncertaintyC != null) {
                    listOf(p.temperature, p.temperature + p.uncertaintyC, p.temperature - p.uncertaintyC)
                } else listOf(p.temperature)
            }

        val humidityValues''',
    "Main chart temperature range",
)

if "val forecastCloud = points.filter" not in main:
    main = main.replace(
        '''                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        val alpha = when (p.source) { PointSource.MEASURED -> 1f; PointSource.RECONSTRUCTED -> 0.78f; PointSource.FORECAST -> 0.60f }
                        drawCircle(color.copy(alpha = color.alpha * alpha), 2.2.dp.toPx(), Offset(mapX(p.timestamp), mapTemp(p.temperature)))
                    }
                }
            }

            if (showHumidity[sensor.id] == true && points.size >= 2) {''',
        '''                if (prefs.showPoints || zoom > 18f) {
                    points.forEach { p ->
                        val alpha = when (p.source) { PointSource.MEASURED -> 1f; PointSource.RECONSTRUCTED -> 0.78f; PointSource.FORECAST -> 0.60f }
                        drawCircle(color.copy(alpha = color.alpha * alpha), 2.2.dp.toPx(), Offset(mapX(p.timestamp), mapTemp(p.temperature)))
                    }
                }

                // Nuage d'incertitude : +σ, -σ, +σ... Les marqueurs deviennent
                // volontairement plus rares quand l'horizon s'éloigne.
                val forecastCloud = points.filter { it.source == PointSource.FORECAST && it.uncertaintyC != null }
                forecastCloud.forEachIndexed { index, p ->
                    val horizon = index + 1
                    val stride = when {
                        horizon <= 6 -> 1
                        horizon <= 12 -> 2
                        else -> 3
                    }
                    if ((horizon - 1) % stride == 0) {
                        val sigma = p.uncertaintyC!!.coerceIn(0.0, 8.0)
                        val cloudValue = p.temperature + if (index % 2 == 0) sigma else -sigma
                        val confidenceAlpha = ((p.confidence ?: 0.35) * 0.72).toFloat().coerceIn(0.16f, 0.58f)
                        drawCircle(
                            color.copy(alpha = color.alpha * confidenceAlpha),
                            (2.1f + min(1.8, sigma).toFloat()).dp.toPx(),
                            Offset(mapX(p.timestamp), mapTemp(cloudValue))
                        )
                    }
                }
            }

            if (showHumidity[sensor.id] == true && points.size >= 2) {''',
        1,
    )

if "σ ${String.format" not in main:
    main = main.replace(
        '''                Row(Modifier.fillMaxWidth()) {
                    Text(sensor.room, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                    if (showTemp[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f °C", it.temperature) } ?: "—",
                            Modifier.width(78.dp)
                        )
                    }
                    if (showHumidity[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f %%", it.humidity) } ?: "—",
                            Modifier.width(72.dp)
                        )
                    }
                }
            }''',
        '''                Row(Modifier.fillMaxWidth()) {
                    Text(sensor.room, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                    if (showTemp[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f °C", it.temperature) } ?: "—",
                            Modifier.width(78.dp)
                        )
                    }
                    if (showHumidity[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f %%", it.humidity) } ?: "—",
                            Modifier.width(72.dp)
                        )
                    }
                }
                if (point?.source == PointSource.FORECAST) {
                    val sigmaText = point.uncertaintyC?.let { "σ ${String.format(Locale.FRANCE, "%.2f", it)} °C" } ?: "σ —"
                    val confidenceText = point.confidence?.let { "confiance ${(it * 100).toInt()} %" } ?: "confiance —"
                    val analogText = point.analogCount?.let { "$it analogues historiques" } ?: "analogues insuffisants"
                    Text(
                        "Prévision · $sigmaText · $confidenceText · $analogText",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }''',
        1,
    )
write(main_path, main)
print("MainActivity: nuage σ + inspecteur")

print("FabData v0.12.0 patch ready")
