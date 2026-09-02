package com.fabdata.app

import android.content.Context
import kotlin.math.sqrt

enum class ThermalInertia(val label: String) {
    LIGHT("Faible"),
    MEDIUM("Moyenne"),
    HEAVY("Forte")
}

enum class ThermalExposure(val label: String) {
    LOW("Faible"),
    MEDIUM("Moyenne"),
    HIGH("Forte")
}

enum class ForecastHorizonMode(val label: String, val maxHours: Int) {
    H3("3 h", 3),
    H6("6 h", 6),
    AUTO("Auto", 24)
}

data class ThermalBuildingProfile(
    val surfaceM2: Double = 70.0,
    val floor: Int = 4,
    val insulation: String = "D",
    val inertia: ThermalInertia = ThermalInertia.MEDIUM,
    val exposure: ThermalExposure = ThermalExposure.MEDIUM,
    val initialMassOverrideC: Double? = null
) {
    fun normalized(): ThermalBuildingProfile = copy(
        surfaceM2 = surfaceM2.coerceIn(15.0, 400.0),
        floor = floor.coerceIn(0, 50),
        insulation = insulation.uppercase().takeIf { it in listOf("A", "B", "C", "D", "E", "F", "G") } ?: "D",
        initialMassOverrideC = initialMassOverrideC?.coerceIn(5.0, 40.0)
    )

    /** Plus l'indice est mauvais, plus l'extérieur agit vite sur la masse du logement. */
    fun insulationExchangeFactor(): Double = when (insulation.uppercase()) {
        "A" -> 0.62
        "B" -> 0.74
        "C" -> 0.86
        "D" -> 1.00
        "E" -> 1.15
        "F" -> 1.32
        "G" -> 1.50
        else -> 1.00
    }

    fun massTauHours(): Double {
        val inertiaFactor = when (inertia) {
            ThermalInertia.LIGHT -> 0.55
            ThermalInertia.MEDIUM -> 1.00
            ThermalInertia.HEAVY -> 1.85
        }
        val sizeFactor = sqrt(surfaceM2.coerceAtLeast(20.0) / 70.0).coerceIn(0.60, 2.20)
        val retention = when (insulation.uppercase()) {
            "A" -> 1.35
            "B" -> 1.22
            "C" -> 1.10
            "D" -> 1.00
            "E" -> 0.90
            "F" -> 0.80
            "G" -> 0.70
            else -> 1.00
        }
        return (72.0 * inertiaFactor * sizeFactor * retention).coerceIn(18.0, 260.0)
    }

    fun massOutdoorWeight(): Double {
        val exposureFactor = when (exposure) {
            ThermalExposure.LOW -> 0.78
            ThermalExposure.MEDIUM -> 1.00
            ThermalExposure.HIGH -> 1.28
        }
        // Effet volontairement modéré : l'étage seul ne dit pas si l'on est sous toiture.
        val floorFactor = (1.0 + (floor - 4) * 0.012).coerceIn(0.88, 1.20)
        return (0.12 * insulationExchangeFactor() * exposureFactor * floorFactor).coerceIn(0.05, 0.34)
    }

    fun massCoupling(): Double {
        val inertiaFactor = when (inertia) {
            ThermalInertia.LIGHT -> 0.60
            ThermalInertia.MEDIUM -> 1.00
            ThermalInertia.HEAVY -> 1.45
        }
        val sizeFactor = sqrt(surfaceM2.coerceAtLeast(20.0) / 70.0).coerceIn(0.70, 1.70)
        return (0.022 * inertiaFactor / sizeFactor).coerceIn(0.010, 0.050)
    }

    /** Amplifie ou amortit la charge saisonnière calculée autour de J-30. */
    fun seasonalTrendGain(): Double {
        val inertiaFactor = when (inertia) {
            ThermalInertia.LIGHT -> 0.42
            ThermalInertia.MEDIUM -> 0.72
            ThermalInertia.HEAVY -> 1.05
        }
        val exchange = insulationExchangeFactor().coerceIn(0.65, 1.45)
        return (inertiaFactor * (0.82 + 0.18 * exchange)).coerceIn(0.25, 1.25)
    }

    fun summary(): String = buildString {
        append("${surfaceM2.toInt()} m² · étage $floor · isolation ${insulation.uppercase()} · inertie ${inertia.label.lowercase()}")
        append(" · exposition ${exposure.label.lowercase()}")
        if (initialMassOverrideC == null) append(" · état initial auto")
        else append(" · état initial ${String.format(java.util.Locale.FRANCE, "%.1f", initialMassOverrideC)} °C")
    }
}

class ThermalProfileStore(context: Context) {
    private val prefs = context.getSharedPreferences("fabdata_thermal_profile", Context.MODE_PRIVATE)

    fun load(): ThermalBuildingProfile = ThermalBuildingProfile(
        surfaceM2 = java.lang.Double.longBitsToDouble(
            prefs.getLong("surface_bits", java.lang.Double.doubleToRawLongBits(70.0))
        ),
        floor = prefs.getInt("floor", 4),
        insulation = prefs.getString("insulation", "D") ?: "D",
        inertia = runCatching { ThermalInertia.valueOf(prefs.getString("inertia", ThermalInertia.MEDIUM.name)!!) }
            .getOrDefault(ThermalInertia.MEDIUM),
        exposure = runCatching { ThermalExposure.valueOf(prefs.getString("exposure", ThermalExposure.MEDIUM.name)!!) }
            .getOrDefault(ThermalExposure.MEDIUM),
        initialMassOverrideC = if (prefs.getBoolean("initial_override_enabled", false)) {
            java.lang.Double.longBitsToDouble(
                prefs.getLong("initial_override_bits", java.lang.Double.doubleToRawLongBits(22.0))
            )
        } else null
    ).normalized()

    fun save(raw: ThermalBuildingProfile) {
        val p = raw.normalized()
        prefs.edit()
            .putLong("surface_bits", java.lang.Double.doubleToRawLongBits(p.surfaceM2))
            .putInt("floor", p.floor)
            .putString("insulation", p.insulation)
            .putString("inertia", p.inertia.name)
            .putString("exposure", p.exposure.name)
            .putBoolean("initial_override_enabled", p.initialMassOverrideC != null)
            .apply {
                if (p.initialMassOverrideC != null) {
                    putLong("initial_override_bits", java.lang.Double.doubleToRawLongBits(p.initialMassOverrideC))
                }
            }
            .apply()
    }

    fun forecastMode(): ForecastHorizonMode = runCatching {
        ForecastHorizonMode.valueOf(prefs.getString("forecast_mode", ForecastHorizonMode.AUTO.name)!!)
    }.getOrDefault(ForecastHorizonMode.AUTO)

    fun saveForecastMode(mode: ForecastHorizonMode) {
        prefs.edit().putString("forecast_mode", mode.name).apply()
    }

    fun reset(): ThermalBuildingProfile = ThermalBuildingProfile().also(::save)
}
