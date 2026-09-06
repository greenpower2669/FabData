from pathlib import Path
import re

ROOT = Path('.')


def read(path):
    return (ROOT / path).read_text()


def write(path, text):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f'missing anchor: {label}')
    return text.replace(old, new, 1)

# -----------------------------------------------------------------------------
# Version
# -----------------------------------------------------------------------------
build_path = 'app/build.gradle.kts'
build = read(build_path)
build = replace_once(build, 'versionCode = 43', 'versionCode = 44', 'versionCode')
build = replace_once(build, 'versionName = "0.19.7"', 'versionName = "0.19.8"', 'versionName')
write(build_path, build)

# -----------------------------------------------------------------------------
# Persisted trained model: one explicit training, then cheap reuse.
# -----------------------------------------------------------------------------
store_path = 'app/src/main/java/com/fabdata/app/ThermalTrainedModelStore.kt'
store = r'''package com.fabdata.app

import android.content.Context
import java.security.MessageDigest

/**
 * v0.19.8: the thermal model is an explicit persisted artefact.
 * New MEASURED points do not retrain it. A user training action replaces it.
 * A selection-mask change marks it dirty so the UI asks for an explicit retrain.
 */
class ThermalTrainedModelStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_thermal_trained_model", Context.MODE_PRIVATE)

    companion object {
        private const val SCHEMA = 1
    }

    fun save(model: ThermalModel) {
        prefs.edit()
            .putInt("schema", SCHEMA)
            .putString("engine_model_version", PointSourceStore.MODEL_VERSION)
            .putBoolean("dirty", false)
            .remove("dirty_reason")
            .putLong("sensor_id", model.sensorId)
            .putString("sensor_name", model.sensorName)
            .putString("room", model.room)
            .putString("reference_key", model.referenceKey)
            .putString("reference_station_id", model.referenceStationId)
            .putString("reference_city", model.referenceCity)
            .putInt("lag_hours", model.lagHours)
            .putString("coefficients", model.coefficients.joinToString(","))
            .putLong("calibration_from", model.calibrationFrom)
            .putLong("calibration_to", model.calibrationTo)
            .putInt("usable_points", model.usablePoints)
            .putInt("real_days", model.realDays)
            .putString("mae", model.metrics.mae.toString())
            .putString("rmse", model.metrics.rmse.toString())
            .putString("bias", model.metrics.bias.toString())
            .putString("max_error", model.metrics.maxError.toString())
            .putInt("validation_points", model.metrics.validationPoints)
            .putString("long_rmse", model.longHorizonRmse.toString())
            .putString("confidence", model.confidence.toString())
            .putString("tau_hours", model.tauHours.toString())
            .putString("surface_tau", model.inertiaSurfaceTauHours.toString())
            .putString("deep_tau", model.inertiaDeepTauHours.toString())
            .putString("deep_share", model.inertiaDeepShare.toString())
            .putString("outside_weight", model.inertiaOutsideWeight.toString())
            .putString("coupling", model.inertiaCouplingPerHour.toString())
            .putString("inertia_fit_rmse", model.inertiaFitRmse.toString())
            .putInt("inertia_clean_hours", model.inertiaCleanHours)
            .putInt("inertia_plateau_hours", model.inertiaPlateauHours)
            .putString("inertia_tangent_penalty", model.inertiaTangentPenalty.toString())
            .putInt("inertia_regime_hours", model.inertiaRegimeHours)
            .putLong("trained_at", System.currentTimeMillis())
            .apply()
    }

    fun markDirty(reason: String) {
        prefs.edit()
            .putBoolean("dirty", true)
            .putString("dirty_reason", reason)
            .apply()
    }

    fun isDirty(): Boolean = prefs.getBoolean("dirty", false)
    fun dirtyReason(): String? = prefs.getString("dirty_reason", null)

    fun loadUsable(referenceKey: String, sensorId: Long? = null): ThermalModel? {
        if (isDirty()) return null
        val model = loadAny() ?: return null
        if (model.referenceKey != referenceKey) return null
        if (sensorId != null && model.sensorId != sensorId) return null
        return model
    }

    fun loadAny(): ThermalModel? {
        if (prefs.getInt("schema", -1) != SCHEMA) return null
        if (prefs.getString("engine_model_version", null) != PointSourceStore.MODEL_VERSION) return null
        if (!prefs.contains("sensor_id")) return null
        return runCatching {
            fun d(key: String, fallback: Double = 0.0): Double =
                prefs.getString(key, null)?.toDoubleOrNull() ?: fallback
            val coeff = prefs.getString("coefficients", null)
                ?.split(',')?.mapNotNull { it.toDoubleOrNull() }?.toDoubleArray()
                ?.takeIf { it.isNotEmpty() } ?: return null
            ThermalModel(
                sensorId = prefs.getLong("sensor_id", -1L),
                sensorName = prefs.getString("sensor_name", "Sonde") ?: "Sonde",
                room = prefs.getString("room", "Pièce") ?: "Pièce",
                referenceKey = prefs.getString("reference_key", "") ?: "",
                referenceStationId = prefs.getString("reference_station_id", "") ?: "",
                referenceCity = prefs.getString("reference_city", "") ?: "",
                lagHours = prefs.getInt("lag_hours", 0),
                coefficients = coeff,
                calibrationFrom = prefs.getLong("calibration_from", 0L),
                calibrationTo = prefs.getLong("calibration_to", 0L),
                usablePoints = prefs.getInt("usable_points", 0),
                realDays = prefs.getInt("real_days", 0),
                metrics = ThermalMetrics(
                    mae = d("mae", 99.0),
                    rmse = d("rmse", 99.0),
                    bias = d("bias", 99.0),
                    maxError = d("max_error", 99.0),
                    validationPoints = prefs.getInt("validation_points", 0)
                ),
                longHorizonRmse = d("long_rmse", 99.0),
                confidence = d("confidence", 0.0),
                tauHours = d("tau_hours", 336.0),
                inertiaSurfaceTauHours = d("surface_tau", 48.0),
                inertiaDeepTauHours = d("deep_tau", 336.0),
                inertiaDeepShare = d("deep_share", 0.72),
                inertiaOutsideWeight = d("outside_weight", 0.15),
                inertiaCouplingPerHour = d("coupling", 0.012),
                inertiaFitRmse = d("inertia_fit_rmse", 0.80),
                inertiaCleanHours = prefs.getInt("inertia_clean_hours", 0),
                inertiaPlateauHours = prefs.getInt("inertia_plateau_hours", 0),
                inertiaTangentPenalty = d("inertia_tangent_penalty", 0.0),
                inertiaRegimeHours = prefs.getInt("inertia_regime_hours", 0)
            )
        }.getOrNull()
    }
}

fun ThermalModel.stableSignature(): String {
    val digest = MessageDigest.getInstance("SHA-256")
    fun put(v: String) {
        digest.update(v.toByteArray(Charsets.UTF_8))
        digest.update(0)
    }
    put("trained-model-v1")
    put(sensorId.toString())
    put(referenceKey)
    put(referenceStationId)
    put(lagHours.toString())
    coefficients.forEach { put(java.lang.Double.doubleToRawLongBits(it).toString()) }
    put(java.lang.Double.doubleToRawLongBits(inertiaSurfaceTauHours).toString())
    put(java.lang.Double.doubleToRawLongBits(inertiaDeepTauHours).toString())
    put(java.lang.Double.doubleToRawLongBits(inertiaDeepShare).toString())
    put(java.lang.Double.doubleToRawLongBits(inertiaOutsideWeight).toString())
    return digest.digest().joinToString("") { "%02x".format(it) }
}
'''
write(store_path, store)

# -----------------------------------------------------------------------------
# ThermalEngine: persist all learned inertia parameters, explicit training, cheap forecast.
# -----------------------------------------------------------------------------
engine_path = 'app/src/main/java/com/fabdata/app/ThermalEngine.kt'
engine = read(engine_path)
engine = replace_once(
    engine,
    '    val confidence: Double,\n    val tauHours: Double\n)',
    '''    val confidence: Double,
    val tauHours: Double,
    val inertiaSurfaceTauHours: Double = 48.0,
    val inertiaDeepTauHours: Double = 336.0,
    val inertiaDeepShare: Double = 0.72,
    val inertiaOutsideWeight: Double = 0.15,
    val inertiaCouplingPerHour: Double = 0.012,
    val inertiaFitRmse: Double = 0.80,
    val inertiaCleanHours: Int = 0,
    val inertiaPlateauHours: Int = 0,
    val inertiaTangentPenalty: Double = 0.0,
    val inertiaRegimeHours: Int = 0
)''',
    'ThermalModel persisted inertia fields'
)

insert_before_calibrate = r'''
    /** Cheap status: never calibrates. The persisted model is the sole trained model. */
    fun statusFromTrainedModel(
        reference: WeatherReference,
        selectedSensorId: Long? = null,
        trainedModel: ThermalModel? = null
    ): ThermalStatus {
        val sensors = physicalSensors()
        val statuses = sensors.map { sensor ->
            val linked = trainedModel?.takeIf {
                it.sensorId == sensor.id && it.referenceKey == reference.key
            }
            ThermalSensorStatus(
                sensor = sensor,
                realDays = linked?.realDays ?: 0,
                model = linked,
                measuredHours = linked?.usablePoints ?: 0,
                ignoredHours = 0
            )
        }
        val preferred = statuses.firstOrNull { it.sensor.id == selectedSensorId }
            ?: trainedModel?.let { m -> statuses.firstOrNull { it.sensor.id == m.sensorId } }
            ?: statuses.firstOrNull()
        val message = when {
            trainedModel == null -> "Modèle thermique non entraîné · lancer Entraîner modèle"
            trainedModel.referenceKey != reference.key -> "Référence météo différente · réentraînement manuel requis"
            selectedSensorId != null && trainedModel.sensorId != selectedSensorId -> "Sonde modèle différente · réentraînement manuel requis"
            else -> "Modèle figé chargé · aucun réentraînement automatique"
        }
        return ThermalStatus(reference, statuses, preferred, message)
    }

    /** Explicit, user-triggered training. This is the only normal path that calls calibrate. */
    fun trainModel(
        reference: WeatherReference,
        sensorId: Long? = null,
        profile: ThermalBuildingProfile = ThermalBuildingProfile()
    ): ThermalModel {
        val sensors = physicalSensors()
        val sensor = sensorId?.let { wanted -> sensors.firstOrNull { it.id == wanted } }
            ?: sensors.maxByOrNull { measuredHourly(it.id).size }
            ?: error("Aucune sonde physique à entraîner")
        return calibrate(sensor, reference, profile, preferLongHorizon = true)
    }

'''
engine = replace_once(engine, '    fun calibrate(\n', insert_before_calibrate + '    fun calibrate(\n', 'insert explicit training methods')

engine = replace_once(
    engine,
    '                metrics, driftRmse, confidence, inertia.diagnostics.tauHours\n            )',
    '''                metrics, driftRmse, confidence, inertia.diagnostics.tauHours,
                inertiaSurfaceTauHours = inertia.diagnostics.surfaceTauHours,
                inertiaDeepTauHours = inertia.diagnostics.deepTauHours,
                inertiaDeepShare = inertia.diagnostics.deepShare,
                inertiaOutsideWeight = inertia.diagnostics.outsideWeight,
                inertiaCouplingPerHour = inertia.diagnostics.couplingPerHour,
                inertiaFitRmse = inertia.diagnostics.fitRmse,
                inertiaCleanHours = inertia.diagnostics.cleanHours,
                inertiaPlateauHours = inertia.diagnostics.plateauHours,
                inertiaTangentPenalty = inertia.diagnostics.tangentPenalty,
                inertiaRegimeHours = inertia.diagnostics.regimeHours
            )''',
    'capture inertia fit in ThermalModel'
)

engine = replace_once(
    engine,
    '        mode: ForecastHorizonMode = ForecastHorizonMode.AUTO\n    ): ThermalWriteSummary {',
    '        mode: ForecastHorizonMode = ForecastHorizonMode.AUTO,\n        precalibratedModel: ThermalModel? = null\n    ): ThermalWriteSummary {',
    'forecast pre-trained signature'
)
engine = replace_once(
    engine,
    '            val model = runCatching { calibrate(sensor, reference, profile, preferLongHorizon = true) }.getOrNull()\n            if (model == null || !model.acceptableForForecast) { skipped++; return@forEach }\n            val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n                ?: run { skipped++; return@forEach }\n            val measured = measuredHourly(sensor.id)',
    '''            val model = precalibratedModel?.takeIf {
                it.sensorId == sensor.id && it.referenceKey == reference.key
            }
            if (model == null || !model.acceptableForForecast) { skipped++; return@forEach }
            val measured = measuredHourly(sensor.id)''',
    'forecast no automatic calibration/inertia fit'
)
engine = replace_once(
    engine,
    '            val from = latest.timestamp - 18L * THERMAL_HOUR_MS',
    '            val from = latest.timestamp - 7L * 24L * THERMAL_HOUR_MS',
    'forecast recent mass window'
)
engine = replace_once(
    engine,
    '                reference, profile, sensor.id, PointSource.FORECAST, mode\n            )',
    '                reference, profile, sensor.id, PointSource.FORECAST, mode, model\n            )',
    'forecast model fingerprint'
)
engine = replace_once(
    engine,
    '            var currentMass = inertia.points.minByOrNull { abs(it.timestamp - latest.timestamp) }\n                ?.temperature ?: inertia.diagnostics.currentC',
    '            var currentMass = estimateCurrentMassFromModel(model, measured, outMap)',
    'forecast cheap current mass'
)
engine = replace_once(
    engine,
    '                val nextMass = advanceInertiaMass(inertia.diagnostics, currentT, currentMass, avg6)',
    '                val nextMass = advanceInertiaMass(model, currentT, currentMass, avg6)',
    'forecast frozen mass parameters'
)

# Model-aware fingerprints for history where a local model variable is available.
engine = engine.replace(
    'reference, profile, sensor.id, PointSource.RECONSTRUCTED\n            )',
    'reference, profile, sensor.id, PointSource.RECONSTRUCTED, trainedModel = model\n            )'
)

# rebuildCalculatedExtent can accept the persisted model without recalibrating.
engine = replace_once(
    engine,
    '        previousBounds: LongRange,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ThermalWriteSummary {',
    '        previousBounds: LongRange,\n        progress: ((ThermalProgress) -> Unit)? = null,\n        precalibratedModel: ThermalModel? = null\n    ): ThermalWriteSummary {',
    'rebuild pre-trained signature'
)
engine = replace_once(
    engine,
    '            return reconstructHistory(reference, days, sensor.id, profile, progress = progress)',
    '            return reconstructHistory(reference, days, sensor.id, profile, precalibratedModel = precalibratedModel, progress = progress)',
    'rebuild passes persisted model'
)
# Limit this replacement to the first calibration after rebuildCalculatedExtent marker.
marker = '    fun rebuildCalculatedExtent('
pos = engine.find(marker)
if pos < 0:
    raise SystemExit('missing rebuild function')
sub = engine[pos:]
old = '        val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()\n            ?: return ThermalWriteSummary(0, 0, 1, diagnostic = "Modèle non recalibrable")'
new = '''        val model = precalibratedModel?.takeIf {
            it.sensorId == sensor.id && it.referenceKey == reference.key
        } ?: runCatching { calibrate(sensor, reference, profile) }.getOrNull()
            ?: return ThermalWriteSummary(0, 0, 1, diagnostic = "Modèle non disponible")'''
if old not in sub:
    raise SystemExit('missing rebuild model anchor')
sub = sub.replace(old, new, 1)
engine = engine[:pos] + sub

helper_anchor = '    private fun advanceInertiaMass(\n        diagnostics: ThermalInertiaDiagnostics,'
helper = r'''    private fun advanceInertiaMass(
        model: ThermalModel,
        indoor: Double,
        mass: Double,
        outsideAvg: Double
    ): Double {
        val w = model.inertiaOutsideWeight.coerceIn(0.02, 0.45)
        val target = indoor * (1.0 - w) + outsideAvg * w
        val share = model.inertiaDeepShare.coerceIn(0.45, 0.90)
        val alphaSurface = 1.0 - exp(-1.0 / model.inertiaSurfaceTauHours.coerceAtLeast(6.0))
        val alphaDeep = 1.0 - exp(-1.0 / model.inertiaDeepTauHours.coerceAtLeast(24.0))
        val alpha = ((1.0 - share) * alphaSurface + share * alphaDeep).coerceIn(0.0001, 0.25)
        return mass + alpha * (target - mass)
    }

    private fun estimateCurrentMassFromModel(
        model: ThermalModel,
        measured: List<HourPoint>,
        outside: Map<Long, HourPoint>
    ): Double {
        val recent = measured.takeLast(7 * 24).ifEmpty { measured }
        var mass = recent.firstOrNull()?.temperature ?: 22.0
        recent.forEach { p ->
            val out = outsideAt(outside, p.timestamp) ?: return@forEach
            val avg6 = outsideAverage(outside, p.timestamp, 6) ?: out
            mass = advanceInertiaMass(model, p.temperature, mass, avg6)
        }
        return mass
    }

'''
engine = replace_once(engine, helper_anchor, helper + helper_anchor, 'insert frozen mass helpers')
write(engine_path, engine)

# -----------------------------------------------------------------------------
# Thermal inertia: cheap projection from frozen trained parameters; no grid search on load.
# -----------------------------------------------------------------------------
inertia_path = 'app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt'
inertia = read(inertia_path)
project_method = r'''    /**
     * v0.19.8: render the learned bi-mass model without fitting it again.
     * This is intentionally O(n) propagation only; no parameter search runs during chart loading.
     */
    fun projectTrained(reference: WeatherReference, model: ThermalModel): ThermalInertiaEstimate? {
        if (model.referenceKey != reference.key) return null
        val sensor = db.sensors().firstOrNull { it.id == model.sensorId } ?: return null
        val measured = measuredHourly(model.sensorId)
        if (measured.size < 2) return null
        val weatherBounds = referenceStore.historyBounds(reference.key) ?: return null
        val from = max(measured.first().timestamp, weatherBounds.first)
        val to = min(measured.last().timestamp, weatherBounds.last)
        if (to <= from) return null
        val outside = outsideHourly(reference.key, from - 3L * INERTIA_HOUR_MS, to)
        val outMap = outside.associateBy { it.first }
        val indoor = measured.filter { it.timestamp in from..to }
        if (indoor.size < 2) return null
        val smooth = smoothAir(indoor.map { it.temperature })
        val hours = indoor.mapIndexedNotNull { index, p ->
            val outsideT = outsideAt(outMap, p.timestamp) ?: return@mapIndexedNotNull null
            InertiaHour(p.timestamp, p.temperature, p.humidity, outsideT, smooth[index])
        }
        if (hours.size < 2) return null

        val mass = propagateDisplay(
            hours,
            model.inertiaSurfaceTauHours,
            model.inertiaDeepTauHours,
            model.inertiaDeepShare,
            model.inertiaOutsideWeight
        )
        val exclusions = ThermalTrainingMaskStore(db).query(model.sensorId, from, to)
        val plateau = masks(hours, exclusions).second
        val surface = propagateSurfaceDisplay(
            hours,
            model.inertiaSurfaceTauHours,
            model.inertiaDeepTauHours,
            model.inertiaOutsideWeight,
            plateau
        )
        val confidence = model.confidence.coerceIn(0.08, 0.95)
        val hiddenPoints = hours.mapIndexed { i, h ->
            SamplePoint(
                THERMAL_INERTIA_SENSOR_ID, h.timestamp, mass[i], h.humidity,
                PointSource.RECONSTRUCTED, confidence
            )
        }
        val visiblePoints = hours.mapIndexed { i, h ->
            SamplePoint(
                THERMAL_INERTIA_SENSOR_ID, h.timestamp, surface[i], h.humidity,
                PointSource.RECONSTRUCTED, confidence
            )
        }
        val trend = trendPerDay(hours, mass)
        val currentAir = hours.last().smoothAir
        val currentFlux = model.inertiaCouplingPerHour * (mass.last() - currentAir)
        val diagnostics = ThermalInertiaDiagnostics(
            sourceSensorId = model.sensorId,
            sourceRoom = sensor.room,
            currentC = round2(mass.last()),
            trendCPerDay = trend,
            tauHours = model.tauHours,
            couplingPerHour = model.inertiaCouplingPerHour,
            outsideWeight = model.inertiaOutsideWeight,
            confidence = confidence,
            cleanHours = model.inertiaCleanHours,
            plateauHours = model.inertiaPlateauHours,
            fitRmse = model.inertiaFitRmse,
            currentFluxCPerHour = currentFlux,
            tangentPenalty = model.inertiaTangentPenalty,
            regimeHours = model.inertiaRegimeHours,
            surfaceTauHours = model.inertiaSurfaceTauHours,
            deepTauHours = model.inertiaDeepTauHours,
            deepShare = model.inertiaDeepShare
        )
        return ThermalInertiaEstimate(hiddenPoints, diagnostics, visiblePoints)
    }

'''
inertia = replace_once(inertia, '    fun estimate(reference: WeatherReference, sensorId: Long? = null, includeHistory: Boolean = true): ThermalInertiaEstimate? {', project_method + '    fun estimate(reference: WeatherReference, sensorId: Long? = null, includeHistory: Boolean = true): ThermalInertiaEstimate? {', 'insert cheap trained projection')
write(inertia_path, inertia)

# -----------------------------------------------------------------------------
# Coherence fingerprints include the persisted model identity.
# -----------------------------------------------------------------------------
coh_path = 'app/src/main/java/com/fabdata/app/ThermalCoherence.kt'
coh = read(coh_path)
coh = replace_once(
    coh,
    '        source: PointSource,\n        forecastMode: ForecastHorizonMode? = null\n    ): ThermalDependencyFingerprint {',
    '        source: PointSource,\n        forecastMode: ForecastHorizonMode? = null,\n        trainedModel: ThermalModel? = null\n    ): ThermalDependencyFingerprint {',
    'fingerprint model arg'
)
coh = replace_once(
    coh,
    '            "thermal-dependency-v1",\n            source.dbValue,',
    '            "thermal-dependency-v2",\n            source.dbValue,',
    'dependency v2'
)
coh = replace_once(
    coh,
    '            weather,\n            mode\n        )',
    '            weather,\n            mode,\n            trainedModel?.stableSignature() ?: "no-trained-model"\n        )',
    'dependency includes model signature'
)
coh = replace_once(
    coh,
    '        source: PointSource,\n        forecastMode: ForecastHorizonMode? = null\n    ): ThermalCurveCoherence? {',
    '        source: PointSource,\n        forecastMode: ForecastHorizonMode? = null,\n        trainedModel: ThermalModel? = null\n    ): ThermalCurveCoherence? {',
    'inspect model arg'
)
coh = replace_once(
    coh,
    '        val expected = dependencyFingerprint(reference, profile, sensorId, source, forecastMode)',
    '        val expected = dependencyFingerprint(reference, profile, sensorId, source, forecastMode, trainedModel)',
    'inspect passes model'
)
write(coh_path, coh)

# -----------------------------------------------------------------------------
# MainActivity: loading only projects frozen model; selection marks model dirty.
# -----------------------------------------------------------------------------
main_path = 'app/src/main/java/com/fabdata/app/MainActivity.kt'
main = read(main_path)
main = replace_once(
    main,
    '    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }',
    '    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }\n    val trainedModelStore = remember { ThermalTrainedModelStore(context) }',
    'MainActivity trained model store'
)
main = replace_once(
    main,
    '''                val inertia = runCatching {
                    inertiaEstimator.estimate(selectedWeatherReference, modelSensorId, includeHistory = true)
                }.getOrNull()''',
    '''                val trainedModel = trainedModelStore.loadUsable(selectedWeatherReference.key, modelSensorId)
                val inertia = trainedModel?.let { model ->
                    runCatching { inertiaEstimator.projectTrained(selectedWeatherReference, model) }.getOrNull()
                }''',
    'chart load no inertia retraining'
)
main = replace_once(
    main,
    '                                        ThermalTrainingMaskStore(db).includeRange(sensorId, range.first, range.last)\n                                    }\n                                    reloadToken++',
    '                                        ThermalTrainingMaskStore(db).includeRange(sensorId, range.first, range.last)\n                                    }\n                                    if (changed > 0) trainedModelStore.markDirty("Sélection d’apprentissage modifiée")\n                                    reloadToken++',
    'selection include dirties model'
)
main = replace_once(
    main,
    '                                    snackbar.showSnackbar(\n                                        if (changed > 0) "Zone réintégrée à l\'entraînement inertiel"\n                                        else "Zone déjà utilisée pour l\'entraînement inertiel"\n                                    )',
    '                                    snackbar.showSnackbar(\n                                        if (changed > 0) "Zone réintégrée · modèle à réentraîner"\n                                        else "Zone déjà utilisée pour l\'entraînement"\n                                    )',
    'selection include message'
)
main = replace_once(
    main,
    '                                        ThermalTrainingMaskStore(db).addMerged(\n                                            sensorId,\n                                            range.first,\n                                            range.last,\n                                            "Sélection bandeau global"\n                                        )\n                                    }\n                                    reloadToken++',
    '                                        ThermalTrainingMaskStore(db).addMerged(\n                                            sensorId,\n                                            range.first,\n                                            range.last,\n                                            "Sélection bandeau global"\n                                        )\n                                    }\n                                    trainedModelStore.markDirty("Sélection d’apprentissage modifiée")\n                                    reloadToken++',
    'selection exclude dirties model'
)
main = replace_once(
    main,
    '                                    snackbar.showSnackbar("Zone exclue de l\'entraînement inertiel · RAW conservées")',
    '                                    snackbar.showSnackbar("Zone exclue · RAW conservées · modèle à réentraîner")',
    'selection exclude message'
)
write(main_path, main)

# -----------------------------------------------------------------------------
# Live coordinator: weather + future only. Never rebuild past and never calibrate.
# -----------------------------------------------------------------------------
live_path = 'app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt'
live = read(live_path)
live = replace_once(
    live,
    '    val modelPrefs = remember {\n        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)\n    }',
    '    val modelPrefs = remember {\n        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)\n    }\n    val trainedModelStore = remember { ThermalTrainedModelStore(context) }',
    'live trained store'
)
# Remove automatic historical rebuild block and use frozen model for forecast.
pattern = re.compile(r'''\n\s*val rebuildExisting = rebuildFromMeasured \|\| referenceChanged\n\n\s*if \(rebuildExisting\) \{.*?\n\s*\}\n\s*engine\.refreshForecasts\(reference, selectedSensorId, profile, mode\)''', re.S)
replacement = '''
                // v0.19.8: measured arrivals never retrain and never recalculate the past.
                // Live mode only refreshes the future with the explicitly trained model.
                if (referenceChanged) {
                    trainedModelStore.markDirty("Référence météo modifiée")
                }
                val trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                if (trainedModel != null) {
                    engine.refreshForecasts(
                        reference, trainedModel.sensorId, profile, mode,
                        precalibratedModel = trainedModel
                    )
                }'''
live, count = pattern.subn('\n' + replacement, live, count=1)
if count != 1:
    raise SystemExit(f'live historical auto block replacement count={count}')
write(live_path, live)

# -----------------------------------------------------------------------------
# Thermal UI: explicit training button, blinking when empty/dirty, no auto past.
# -----------------------------------------------------------------------------
ui_path = 'app/src/main/java/com/fabdata/app/ThermalUi.kt'
ui = read(ui_path)
ui = replace_once(ui, 'import androidx.compose.foundation.layout.Arrangement', 'import androidx.compose.animation.core.RepeatMode\nimport androidx.compose.animation.core.animateFloat\nimport androidx.compose.animation.core.infiniteRepeatable\nimport androidx.compose.animation.core.rememberInfiniteTransition\nimport androidx.compose.animation.core.tween\nimport androidx.compose.foundation.layout.Arrangement', 'animation imports')
ui = replace_once(ui, 'import androidx.compose.ui.Modifier', 'import androidx.compose.ui.Modifier\nimport androidx.compose.ui.graphics.graphicsLayer', 'graphicsLayer import')
ui = replace_once(
    ui,
    '    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }',
    '    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }\n    val trainedModelStore = remember { ThermalTrainedModelStore(context) }',
    'UI model store'
)
ui = replace_once(
    ui,
    '    val reference = remember(selectedKey) { prefs.selectedReference() }',
    '    val reference = remember(selectedKey) { prefs.selectedReference() }\n    var trainedModel by remember { mutableStateOf<ThermalModel?>(null) }',
    'UI trained model state'
)
# reload persisted model cheaply when visible inputs change
reload_anchor = '    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }\n\n    fun refreshDebtState()'
reload_code = '''    var continuationWork by remember { mutableStateOf<ThermalHistoryWork?>(null) }

    LaunchedEffect(selectedKey, selectedSensorId, dataVersion) {
        trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
        status = engine.statusFromTrainedModel(reference, selectedSensorId, trainedModel)
    }

    fun refreshDebtState()'''
ui = replace_once(ui, reload_anchor, reload_code, 'reload trained model effect')

# process final history chunk uses persisted model, never status/calibrate.
old = '''                if (advanced.nextChunk >= advanced.totalChunks) {
                    val checked = engine.status(reference, advanced.sensorId, profile)
                    if (!checked.canReconstruct) error(checked.message)
                    val activeModel = checked.preferred?.model?.takeIf { it.sensorId == advanced.sensorId }
                    val summary = engine.reconstructHistory('''
new = '''                if (advanced.nextChunk >= advanced.totalChunks) {
                    val activeModel = trainedModelStore.loadUsable(reference.key, advanced.sensorId)
                        ?: error("Modèle vide ou à réentraîner")
                    val summary = engine.reconstructHistory('''
ui = replace_once(ui, old, new, 'history chunk frozen model')

# beginHistoryWork: no status calibration.
pattern = re.compile(r'''    suspend fun beginHistoryWork\(days: Int, reason: String\) \{\n        val checked = withContext\(Dispatchers\.IO\) \{ engine\.status\(reference, selectedSensorId, profile\) \}\n        if \(!checked\.canReconstruct\) \{ info = checked\.message; return \}\n        val activeId = selectedSensorId \?: checked\.preferred\?\.sensor\?\.id \?: run \{ info = "Aucune sonde modèle"; return \}''')
replacement = '''    suspend fun beginHistoryWork(days: Int, reason: String) {
        val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
            ?: run { info = "Modèle vide ou à réentraîner"; return }
        val activeId = activeModel.sensorId'''
ui, count = pattern.subn(replacement, ui, count=1)
if count != 1:
    raise SystemExit('beginHistoryWork replacement failed')

# refresh: passive status, no existing-history rebuild, frozen future.
ui = replace_once(
    ui,
    '                val thermalStatus = engine.status(reference, selectedSensorId, profile)',
    '                val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)\n                val thermalStatus = engine.statusFromTrainedModel(reference, selectedSensorId, activeModel)',
    'refresh passive status'
)
pattern = re.compile(r'''\n\s*if \(rebuildHistoryFromNewMeasured && thermalStatus\.sensors\.any \{ it\.model\?\.acceptableForHistory == true \}\) \{.*?\n\s*\}\n\s*val forecast = if \(thermalStatus\.sensors\.any \{ it\.model\?\.acceptableForForecast == true \}\) \{\n\s*engine\.refreshForecasts\(reference, activeSensor, profile, forecastMode\)\n\s*\} else ThermalWriteSummary\(0, 0, 0\)''', re.S)
replacement = '''
                // v0.19.8: refresh never recalculates the past and never retrains.
                val forecast = if (activeModel?.acceptableForForecast == true) {
                    engine.refreshForecasts(
                        reference, activeModel.sensorId, profile, forecastMode,
                        precalibratedModel = activeModel
                    )
                } else ThermalWriteSummary(0, 0, 0)'''
ui, count = pattern.subn('\n' + replacement, ui, count=1)
if count != 1:
    raise SystemExit(f'UI refresh auto-past replacement count={count}')

# Add explicit training coroutine before rationalizeCurves.
train_fn = r'''    suspend fun trainPersistedModel() {
        if (busy) return
        busy = true
        info = "Entraînement du modèle · préparation des mesures réelles…"
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val bounds = db.physicalMeasuredBounds() ?: error("Aucune mesure réelle")
                manager.ensureLocalCache(
                    reference,
                    bounds.first - 18L * 60L * 60L * 1000L,
                    bounds.last
                )
                val model = engine.trainModel(reference, selectedSensorId, profile)
                trainedModelStore.save(model)
                model
            }
        }
        result.fold(
            onSuccess = { model ->
                trainedModel = model
                selectedSensorId = model.sensorId
                modelSensorPrefs.edit().putLong("selected_sensor_id", model.sensorId).apply()
                status = engine.statusFromTrainedModel(reference, model.sensorId, model)
                val k = model.coefficients.firstOrNull() ?: 0.0
                info = "Modèle entraîné une fois · k ${fmt(k)} · Δ ${model.lagHours} h · futur prêt"
                suppressNextAuto = true
                onDataChanged()
            },
            onFailure = { error ->
                info = error.message ?: "Entraînement impossible"
            }
        )
        busy = false
    }

'''
ui = replace_once(ui, '    suspend fun rationalizeCurves(\n', train_fn + '    suspend fun rationalizeCurves(\n', 'insert explicit train UI function')

# Rationalize is manual and must use the persisted model identity.
ui = replace_once(
    ui,
    '            runCatching {\n                val measuredBounds = db.physicalMeasuredBounds()',
    '            runCatching {\n                val activeModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)\n                    ?: error("Modèle vide ou à réentraîner")\n                val measuredBounds = db.physicalMeasuredBounds()',
    'rationalize requires trained model'
)
ui = ui.replace(
    'coherenceStore.calculatedSensorIds().mapNotNull { id ->\n                    coherenceStore.inspect(reference, targetProfile, id, PointSource.RECONSTRUCTED)\n                }',
    'coherenceStore.calculatedSensorIds().filter { it == activeModel.sensorId }.mapNotNull { id ->\n                    coherenceStore.inspect(reference, targetProfile, id, PointSource.RECONSTRUCTED, trainedModel = activeModel)\n                }'
)
ui = ui.replace(
    'coherenceStore.calculatedSensorIds().mapNotNull { id ->\n                    coherenceStore.inspect(reference, targetProfile, id, PointSource.FORECAST, forecastMode)\n                }',
    'coherenceStore.calculatedSensorIds().filter { it == activeModel.sensorId }.mapNotNull { id ->\n                    coherenceStore.inspect(reference, targetProfile, id, PointSource.FORECAST, forecastMode, activeModel)\n                }'
)
ui = replace_once(
    ui,
    '                        reference, targetProfile, state.sensorId, recentStart..previousBounds.last, progressCallback\n                    )',
    '                        reference, targetProfile, state.sensorId, recentStart..previousBounds.last, progressCallback,\n                        precalibratedModel = activeModel\n                    )',
    'rationalize rebuild frozen model'
)
ui = replace_once(
    ui,
    '                    val rebuilt = engine.refreshForecasts(reference, state.sensorId, targetProfile, forecastMode)',
    '                    val rebuilt = engine.refreshForecasts(reference, state.sensorId, targetProfile, forecastMode, precalibratedModel = activeModel)',
    'rationalize forecast frozen model'
)

# Reference changes: no automatic rationalization; model becomes explicit retrain warning.
ui = replace_once(
    ui,
    '                referenceChanged -> rationalizeCurves("Référence météo modifiée", profile, manual = false)',
    '''                referenceChanged -> {
                    trainedModelStore.markDirty("Référence météo modifiée")
                    trainedModel = null
                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)
                    info = "Référence météo modifiée · modèle à réentraîner · aucun calcul du passé lancé"
                }''',
    'reference change no auto past'
)
# Initial refresh remains light; measured changes only announce future refresh.
ui = ui.replace('info = "Nouvelle mesure réelle détectée · synchronisation globale en cours…"', 'info = "Nouvelle mesure réelle détectée · futur actualisé sans réentraîner le modèle"')

# Profile change: dirty model, no auto rationalize.
ui = replace_once(
    ui,
    '                    suppressNextAuto = true\n                    scope.launch { rationalizeCurves("Profil bâtiment modifié", next, manual = false) }',
    '                    trainedModelStore.markDirty("Profil bâtiment modifié")\n                    trainedModel = null\n                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)\n                    info = "Profil modifié · modèle à réentraîner manuellement"',
    'profile change manual retrain'
)
ui = replace_once(
    ui,
    '                    suppressNextAuto = true\n                    scope.launch { rationalizeCurves("Profil bâtiment réinitialisé", next, manual = false) }',
    '                    trainedModelStore.markDirty("Profil bâtiment réinitialisé")\n                    trainedModel = null\n                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)\n                    info = "Profil réinitialisé · modèle à réentraîner manuellement"',
    'profile reset manual retrain'
)

# Prominent persisted fragmented-load resume warning near top of the card.
header_anchor = '''            Text(
                "Lyon reste le secours par défaut. Auto protection peut choisir la station historiquement la plus chaude du secteur ; une seule station charge ses séries à la fois.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
'''
header_extra = header_anchor + '''
            val interruptedWork = historyDebtStore.loadWork()
            if (interruptedWork != null) {
                Button(
                    onClick = {
                        scope.launch {
                            historyDebtStore.resumeWork()
                            continuationWork = null
                            processNextHistoryChunk()
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("⚠ Reprendre chargement morcelé · ${interruptedWork.nextChunk}/${interruptedWork.totalChunks}")
                }
            }
'''
ui = replace_once(ui, header_anchor, header_extra, 'top fragmented-load warning')

# Put model training next to history extension; blink if no usable model.
old_button = '''            OutlinedButton(
                onClick = { weatherHistoryDialog = true },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text("Étendre historique météo + bâtiment") }
'''
new_button = '''            val trainingRequired = trainedModel == null
            val blinkTransition = rememberInfiniteTransition(label = "model-training-blink")
            val trainAlpha by blinkTransition.animateFloat(
                initialValue = 0.45f,
                targetValue = 1.0f,
                animationSpec = infiniteRepeatable(tween(650), RepeatMode.Reverse),
                label = "model-training-alpha"
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { weatherHistoryDialog = true },
                    enabled = !busy && trainedModel != null,
                    modifier = Modifier.weight(1f)
                ) { Text("Étendre historique") }
                Button(
                    onClick = { scope.launch { trainPersistedModel() } },
                    enabled = !busy,
                    modifier = Modifier.weight(1f).graphicsLayer(alpha = if (trainingRequired) trainAlpha else 1f)
                ) { Text(if (trainingRequired) "⚠ Entraîner modèle" else "Réentraîner modèle") }
            }
            Text(
                if (trainingRequired) {
                    trainedModelStore.dirtyReason()?.let { "Modèle à entraîner · $it" }
                        ?: "Modèle vide : aucun calcul du passé ne part automatiquement."
                } else {
                    "Modèle figé : réutilisé pour le futur jusqu'à un réentraînement explicite."
                },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
'''
ui = replace_once(ui, old_button, new_button, 'training button row')
write(ui_path, ui)

print('v0.19.8 manual persistent training patch applied')
