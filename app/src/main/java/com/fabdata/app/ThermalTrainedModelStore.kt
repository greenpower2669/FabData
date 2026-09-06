package com.fabdata.app

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
