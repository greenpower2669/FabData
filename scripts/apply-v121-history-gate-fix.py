from pathlib import Path

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
if 'versionName = "0.12.1"' not in gradle:
    gradle = gradle.replace(
        'versionCode = 24\n        versionName = "0.12.0"',
        'versionCode = 25\n        versionName = "0.12.1"',
        1,
    )
write(gradle_path, gradle)
print("v0.12.1 / code 25")


# -----------------------------------------------------------------------------
# 2) A compact revision of REAL interior data only.
#    It changes when an import adds a real point or promotes a calculated point
#    to MEASURED, even if the global min/max timestamps stay unchanged.
# -----------------------------------------------------------------------------
data_path = "app/src/main/java/com/fabdata/app/DataLayer.kt"
data = read(data_path)
if "fun physicalMeasuredRevision()" not in data:
    anchor = '''    fun existingSampleTimestamps(sensorId: Long, from: Long, to: Long): Set<Long> {'''
    addition = '''    /**
     * Révision compacte des seules vraies mesures intérieures.
     * Utilisée par le moteur thermique pour distinguer une vraie arrivée de données
     * d'un simple changement d'UI, de profil ou de mode de prévision.
     */
    fun physicalMeasuredRevision(): String? {
        PointSourceStore.ensure(readableDatabase)
        readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(p.timestamp), MAX(p.timestamp)
            FROM samples p
            JOIN sensors s ON s.id = p.sensor_id
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE s.stable_key NOT LIKE 'meteo-%'
              AND s.stable_key NOT LIKE 'http-get-%'
              AND (ps.source IS NULL OR ps.source='measured')
            """.trimIndent(), null
        ).use { c ->
            if (!c.moveToFirst() || c.getLong(0) <= 0L || c.isNull(1) || c.isNull(2)) return null
            return "${c.getLong(0)}:${c.getLong(1)}:${c.getLong(2)}"
        }
    }

'''
    if anchor not in data:
        raise SystemExit("DataLayer: ancre existingSampleTimestamps introuvable")
    data = data.replace(anchor, addition + anchor, 1)
write(data_path, data)
print("DataLayer: measured revision")


# -----------------------------------------------------------------------------
# 3) Split HISTORY and FORECAST gates.
#    History restores the v0.11 acceptance logic and model ranking by RMSE.
#    Long-horizon drift remains a forecast-only safety gate.
# -----------------------------------------------------------------------------
engine_path = "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
engine = read(engine_path)

old_model_gate = '''    val acceptable: Boolean
        get() = realDays >= MIN_REAL_DAYS && usablePoints >= 120 && metrics.rmse <= 2.0 && metrics.mae <= 1.5 &&
            longHorizonRmse <= 2.5 && confidence >= 0.35
}'''
new_model_gate = '''    /**
     * Confiance historique compatible v0.11 : la dérive libre ne doit jamais
     * empêcher de reconstruire le passé lorsqu'un modèle court terme était valide.
     */
    val historyConfidence: Double
        get() {
            val dataFactor = min(1.0, realDays / 35.0) * min(1.0, usablePoints / 500.0)
            val errorFactor = (1.0 - metrics.rmse / 2.8).coerceIn(0.0, 1.0)
            val biasFactor = (1.0 - abs(metrics.bias) / 1.3).coerceIn(0.0, 1.0)
            return (0.15 + 0.50 * errorFactor + 0.20 * biasFactor + 0.15 * dataFactor).coerceIn(0.0, 1.0)
        }

    val acceptableForHistory: Boolean
        get() = realDays >= MIN_REAL_DAYS && usablePoints >= 120 &&
            metrics.rmse <= 2.0 && metrics.mae <= 1.5 && historyConfidence >= 0.35

    val acceptableForForecast: Boolean
        get() = acceptableForHistory && longHorizonRmse <= 2.5 && confidence >= 0.35

    // Compatibilité interne : tout ancien appel restant doit être prudent et viser le futur.
    val acceptable: Boolean get() = acceptableForForecast
}'''
engine = replace_once(engine, old_model_gate, new_model_gate, "ThermalModel gates")

engine = replace_once(
    engine,
    '''    val canReconstruct: Boolean get() = preferred?.model?.acceptable == true''',
    '''    val canReconstruct: Boolean get() = preferred?.model?.acceptableForHistory == true
    val canForecast: Boolean get() = preferred?.model?.acceptableForForecast == true''',
    "ThermalStatus gates",
)

engine = engine.replace(
    '.filter { it.model?.acceptable == true }',
    '.filter { it.model?.acceptableForHistory == true }',
)
engine = engine.replace(
    'candidates.none { it.model?.acceptable == true }',
    'candidates.none { it.model?.acceptableForHistory == true }',
)

old_signature = '''    fun calibrate(sensor: Sensor, reference: WeatherReference, profile: ThermalBuildingProfile = ThermalBuildingProfile()): ThermalModel {'''
new_signature = '''    fun calibrate(
        sensor: Sensor,
        reference: WeatherReference,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        preferLongHorizon: Boolean = false
    ): ThermalModel {'''
engine = replace_once(engine, old_signature, new_signature, "calibrate signature")

old_best = '''            if (best == null || (model.metrics.rmse + 0.35 * model.longHorizonRmse) <
                (best!!.metrics.rmse + 0.35 * best!!.longHorizonRmse)) best = model'''
new_best = '''            val better = if (best == null) {
                true
            } else if (preferLongHorizon) {
                (model.metrics.rmse + 0.35 * model.longHorizonRmse) <
                    (best!!.metrics.rmse + 0.35 * best!!.longHorizonRmse)
            } else {
                // Historique : comportement v0.11, meilleur RMSE court terme.
                model.metrics.rmse < best!!.metrics.rmse
            }
            if (better) best = model'''
engine = replace_once(engine, old_best, new_best, "calibrate model ranking")

# All historical paths must use the historical gate first.
engine = engine.replace('if (model == null || !model.acceptable) {', 'if (model == null || !model.acceptableForHistory) {')
engine = engine.replace('if (model == null || !model.acceptable) { skipped++; return@forEach }', 'if (model == null || !model.acceptableForHistory) { skipped++; return@forEach }')

# Forecast path gets its own long-horizon model selection and gate.
forecast_marker = '''    fun refreshForecasts('''
if forecast_marker not in engine:
    raise SystemExit("ThermalEngine: refreshForecasts introuvable")
head, tail = engine.split(forecast_marker, 1)
tail = tail.replace(
    'val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()',
    'val model = runCatching { calibrate(sensor, reference, profile, preferLongHorizon = true) }.getOrNull()',
    1,
)
tail = tail.replace(
    'if (model == null || !model.acceptableForHistory) { skipped++; return@forEach }',
    'if (model == null || !model.acceptableForForecast) { skipped++; return@forEach }',
    1,
)
engine = head + forecast_marker + tail

write(engine_path, engine)
print("ThermalEngine: history / forecast gates separated")


# -----------------------------------------------------------------------------
# 4) UI refresh: history recomputation only when REAL measured revision changes.
#    Forecast still refreshes on mode/profile/reference changes.
# -----------------------------------------------------------------------------
ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)

if "var measuredRevision" not in ui:
    ui = replace_once(
        ui,
        '''    var profileDialog by remember { mutableStateOf(false) }''',
        '''    var profileDialog by remember { mutableStateOf(false) }
    var measuredRevision by remember { mutableStateOf<String?>(null) }''',
        "ThermalUi measured revision state",
    )

ui = replace_once(
    ui,
    '''    suspend fun refresh(allHistory: Boolean, triggerChartReload: Boolean) {''',
    '''    suspend fun refresh(
        allHistory: Boolean,
        triggerChartReload: Boolean,
        rebuildHistoryFromNewMeasured: Boolean = false
    ) {''',
    "ThermalUi refresh signature",
)

old_refresh_block = '''                if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    // Si un historique calculé existait déjà, une nouvelle mesure réelle
                    // l'enrichit automatiquement sans jamais modifier les points MEASURED.
                    engine.refreshExistingReconstructions(reference, profile, activeSensor)
                }
                val forecast = if (thermalStatus.sensors.any { it.model?.acceptable == true }) {
                    engine.refreshForecasts(reference, activeSensor, profile, forecastMode)
                } else ThermalWriteSummary(0, 0, 0)'''
new_refresh_block = '''                if (rebuildHistoryFromNewMeasured && thermalStatus.sensors.any { it.model?.acceptableForHistory == true }) {
                    // v0.12.1 : recalcul du passé uniquement après une vraie variation
                    // du jeu de mesures MEASURED, jamais sur un simple changement d'UI.
                    engine.refreshExistingReconstructions(reference, profile, activeSensor)
                }
                val forecast = if (thermalStatus.sensors.any { it.model?.acceptableForForecast == true }) {
                    engine.refreshForecasts(reference, activeSensor, profile, forecastMode)
                } else ThermalWriteSummary(0, 0, 0)'''
ui = replace_once(ui, old_refresh_block, new_refresh_block, "ThermalUi refresh gates")

old_effect = '''    // Toute nouvelle vraie donnée invalide d'abord l'ancien futur, puis ce cycle
    // recalcule historique calculé existant + nouvelle prévision depuis l'état réel.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        if (suppressNextAuto) {
            suppressNextAuto = false
        } else {
            refresh(allHistory = false, triggerChartReload = true)
        }
    }'''
new_effect = '''    // v0.12.1 : dataVersion peut aussi changer pour des écritures calculées ou l'UI.
    // On ne recalcule le passé que si COUNT/MIN/MAX des vraies mesures a réellement changé.
    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        val currentMeasuredRevision = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }
        val measuredChanged = measuredRevision != null && currentMeasuredRevision != measuredRevision
        measuredRevision = currentMeasuredRevision
        if (suppressNextAuto) {
            suppressNextAuto = false
        } else {
            refresh(
                allHistory = false,
                triggerChartReload = true,
                rebuildHistoryFromNewMeasured = measuredChanged
            )
        }
    }'''
ui = replace_once(ui, old_effect, new_effect, "ThermalUi measured-only effect")

write(ui_path, ui)
print("ThermalUi: measured-only history refresh")

print("FabData v0.12.1 history gate fix applied")
