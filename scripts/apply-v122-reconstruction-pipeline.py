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
gradle = gradle.replace('versionCode = 25\n        versionName = "0.12.1"', 'versionCode = 26\n        versionName = "0.12.2"')
write(gradle_path, gradle)
print("v0.12.2 / code 26")


# -----------------------------------------------------------------------------
# 2) PointSourceStore: schema check once per SQLite handle + batch writes.
#    This removes thousands of PRAGMA/autocommit operations during a 90-day run.
# -----------------------------------------------------------------------------
point_path = "app/src/main/java/com/fabdata/app/PointSourceLayer.kt"
point = read(point_path)

point = replace_once(
    point,
    "import android.database.sqlite.SQLiteDatabase\n",
    "import android.database.sqlite.SQLiteDatabase\nimport java.util.Collections\nimport java.util.WeakHashMap\n",
    "PointSource imports",
)

point = replace_once(
    point,
    "enum class PriorityWriteResult { INSERTED, REPLACED, UNCHANGED, REJECTED }\n",
    '''enum class PriorityWriteResult { INSERTED, REPLACED, UNCHANGED, REJECTED }\n\ndata class PriorityPointWrite(\n    val sensorId: Long,\n    val timestamp: Long,\n    val temperature: Double,\n    val humidity: Double,\n    val provenance: PointProvenance\n)\n''',
    "PriorityPointWrite",
)

old_store_prefix = '''object PointSourceStore {
    const val MODEL_VERSION = "thermal-rc-mass-3"

    fun ensure(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS point_sources (
                sensor_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                source TEXT NOT NULL,
                confidence REAL,
                sigma_c REAL,
                analog_count INTEGER,
                reference_key TEXT,
                reference_station_id TEXT,
                reference_city TEXT,
                calibration_from INTEGER,
                calibration_to INTEGER,
                model_version TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(sensor_id, timestamp),
                FOREIGN KEY(sensor_id) REFERENCES sensors(id) ON DELETE CASCADE
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_time ON point_sources(sensor_id, timestamp)")
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
'''
new_store_prefix = '''object PointSourceStore {
    const val MODEL_VERSION = "thermal-rc-mass-3"

    // v0.12.2 : une migration additive n'a besoin d'être vérifiée qu'une seule fois
    // par handle SQLite. WeakHashMap évite de retenir une base fermée en mémoire.
    private val ensuredDatabases = Collections.synchronizedMap(WeakHashMap<SQLiteDatabase, Boolean>())

    fun ensure(db: SQLiteDatabase) {
        synchronized(ensuredDatabases) {
            if (ensuredDatabases[db] == true) return
        }
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS point_sources (
                sensor_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                source TEXT NOT NULL,
                confidence REAL,
                sigma_c REAL,
                analog_count INTEGER,
                reference_key TEXT,
                reference_station_id TEXT,
                reference_city TEXT,
                calibration_from INTEGER,
                calibration_to INTEGER,
                model_version TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(sensor_id, timestamp),
                FOREIGN KEY(sensor_id) REFERENCES sensors(id) ON DELETE CASCADE
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_time ON point_sources(sensor_id, timestamp)")
        ensureColumn(db, "sigma_c", "REAL")
        ensureColumn(db, "analog_count", "INTEGER")
        synchronized(ensuredDatabases) { ensuredDatabases[db] = true }
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
'''
point = replace_once(point, old_store_prefix, new_store_prefix, "PointSource ensure cache")

old_existing = '''        val existing = db.readableDatabase.rawQuery(
            "SELECT temperature, humidity FROM samples WHERE sensor_id=? AND timestamp=? LIMIT 1",
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) null else c.getDouble(0) to c.getDouble(1)
        }

        if (existing == null) {'''
new_existing = '''        val existing = db.readableDatabase.rawQuery(
            """
            SELECT p.temperature, p.humidity, ps.source
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND p.timestamp=? LIMIT 1
            """.trimIndent(),
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) null
            else Triple(c.getDouble(0), c.getDouble(1), PointSource.fromDb(if (c.isNull(2)) null else c.getString(2)))
        }

        if (existing == null) {'''
point = replace_once(point, old_existing, new_existing, "PointSource joined lookup")
point = replace_once(
    point,
    '''        val existingSource = sourceFor(db, sensorId, timestamp)
        if (provenance.source.priority < existingSource.priority) {''',
    '''        val existingSource = existing.third
        if (provenance.source.priority < existingSource.priority) {''',
    "PointSource existing source",
)
point = point.replace("existing.first - temperature", "existing.first - temperature", 1)
point = point.replace("existing.second - humidity", "existing.second - humidity", 1)

batch_marker = '''    fun deleteForecastsAtOrAfter(db: FabDataDb, sensorId: Long, timestamp: Long) {'''
if "fun upsertBatchByPriority(" not in point:
    batch_code = '''    /**
     * Écrit les points calculés par petits lots transactionnels. Un historique de 90 jours
     * passe ainsi d'environ 2000 commits SQLite à quelques commits seulement.
     * Le callback est appelé APRES chaque commit afin que l'UI puisse afficher la progression.
     */
    fun upsertBatchByPriority(
        db: FabDataDb,
        points: List<PriorityPointWrite>,
        chunkSize: Int = 256,
        onChunkCommitted: ((processed: Int, changed: Int) -> Unit)? = null
    ): Int {
        if (points.isEmpty()) return 0
        ensure(db.writableDatabase)
        val size = chunkSize.coerceIn(32, 1024)
        var processed = 0
        var changed = 0
        points.chunked(size).forEach { chunk ->
            db.inTransaction {
                chunk.forEach { p ->
                    val result = upsertByPriority(
                        db, p.sensorId, p.timestamp, p.temperature, p.humidity, p.provenance
                    )
                    if (result == PriorityWriteResult.INSERTED || result == PriorityWriteResult.REPLACED) changed++
                }
            }
            processed += chunk.size
            onChunkCommitted?.invoke(processed, changed)
        }
        return changed
    }

'''
    if batch_marker not in point:
        raise SystemExit("PointSource batch marker introuvable")
    point = point.replace(batch_marker, batch_code + batch_marker, 1)

write(point_path, point)
print("PointSource: ensure cache + batch transactionnel 256")


# -----------------------------------------------------------------------------
# 3) Thermal engine: keep EXACT RC/mass equations, reuse prevalidated calibration,
#    calculate first, then write in committed chunks with progress callbacks.
# -----------------------------------------------------------------------------
engine_path = "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
engine = read(engine_path)

summary_block = '''data class ThermalWriteSummary(
    val reconstructed: Int,
    val forecast: Int,
    val skippedSensors: Int,
    val raccords: Int = 0,
    val maxRaccordDrift: Double = 0.0,
    val diagnostic: String? = null,
    val forecastHorizonHours: Int = 0,
    val maxForecastSigma: Double = 0.0,
    val analogCount: Int = 0
)
'''
if "data class ThermalProgress(" not in engine:
    engine = replace_once(
        engine,
        summary_block,
        summary_block + '''\ndata class ThermalProgress(\n    val stage: String,\n    val processed: Int = 0,\n    val total: Int = 0,\n    val changed: Int = 0\n)\n''',
        "ThermalProgress",
    )

engine = replace_once(
    engine,
    '''    fun reconstructHistory(
        reference: WeatherReference,
        requestedDays: Int,
        sensorId: Long? = null,
        profile: ThermalBuildingProfile = ThermalBuildingProfile()
    ): ThermalWriteSummary {''',
    '''    fun reconstructHistory(
        reference: WeatherReference,
        requestedDays: Int,
        sensorId: Long? = null,
        profile: ThermalBuildingProfile = ThermalBuildingProfile(),
        precalibratedModel: ThermalModel? = null,
        progress: ((ThermalProgress) -> Unit)? = null
    ): ThermalWriteSummary {''',
    "reconstructHistory signature",
)

engine = replace_once(
    engine,
    '''        val targets = physicalSensors().filter { sensorId == null || it.id == sensorId }
        targets.forEach { sensor ->
            val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()''',
    '''        PointSourceStore.ensure(db.writableDatabase)
        val targets = physicalSensors().filter { sensorId == null || it.id == sensorId }
        targets.forEach { sensor ->
            progress?.invoke(ThermalProgress("Calibration · ${sensor.room}"))
            val model = precalibratedModel?.takeIf {
                it.sensorId == sensor.id && it.referenceKey == reference.key
            } ?: runCatching { calibrate(sensor, reference, profile) }.getOrNull()''',
    "reconstructHistory calibration reuse",
)

engine = replace_once(
    engine,
    '''            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap, profile)''',
    '''            progress?.invoke(ThermalProgress("État initial · ${sensor.room}"))
            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap, profile, progress)''',
    "reconstruct before progress",
)
engine = replace_once(
    engine,
    '''            val gaps = fillInteriorGapsForward(sensor, model, reference, profile)''',
    '''            val gaps = fillInteriorGapsForward(sensor, model, reference, profile, progress)''',
    "reconstruct gaps progress",
)

new_before = r'''    private fun reconstructBeforeFirst(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        first: HourPoint,
        startAt: Long,
        outside: Map<Long, HourPoint>,
        profile: ThermalBuildingProfile,
        progress: ((ThermalProgress) -> Unit)? = null
    ): ForwardFillSummary {
        val start = hourBucket(startAt)
        val firstHour = hourBucket(first.timestamp)
        if (start >= firstHour) return ForwardFillSummary(diagnostic = "Période historique vide.")

        val initial = estimateInitialStateForward(model, first, start, firstHour, outside, profile)
            ?: return ForwardFillSummary(diagnostic = "Impossible d'initialiser un état air/masse thermique plausible avec ${reference.city}.")

        var current = initial.first
        var currentH = initial.second
        var currentMass = initial.third
        var ts = start
        var stopDiagnostic: String? = null
        val writes = ArrayList<PriorityPointWrite>(((firstHour - start) / THERMAL_HOUR_MS).toInt().coerceAtLeast(0))

        // Calcul pur d'abord : aucune écriture SQLite dans la boucle RC.
        while (ts < firstHour) {
            val horizonDays = (first.timestamp - ts).toDouble() / THERMAL_DAY_MS.toDouble()
            val confidence = (model.confidence * (1.0 - 0.0065 * horizonDays)).coerceIn(0.20, model.confidence)
            writes += PriorityPointWrite(
                sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
            )

            val extTs = ts - model.lagHours * THERMAL_HOUR_MS
            val ext = outsideAt(outside, extTs)
            if (ext == null) {
                stopDiagnostic = "Propagation arrêtée : météo extérieure absente vers ${Instant.ofEpochMilli(ts).atZone(zone).toLocalDateTime()}."
                break
            }
            val extAvg6 = outsideAverage(outside, extTs, 6) ?: ext
            val stepHour = Instant.ofEpochMilli(ts).atZone(zone).hour
            val delta = massAwareDelta(model.coefficients, current, currentMass, ext, extAvg6, stepHour, profile)
                .coerceIn(-1.2, 1.2)
            val next = current + delta
            if (!plausibleIndoor(next)) {
                stopDiagnostic = "Propagation arrêtée avant dérive physique abusive (${round2(next)} °C)."
                break
            }
            val nextMass = advanceMass(profile, current, currentMass, extAvg6)
            val outHum = outside[hourBucket(ts)]?.humidity ?: currentH
            currentH += 0.08 * (outHum - currentH)
            current = next
            currentMass = nextMass
            ts += THERMAL_HOUR_MS
        }

        val created = PointSourceStore.upsertBatchByPriority(db, writes, 256) { processed, changed ->
            progress?.invoke(
                ThermalProgress("Écriture historique · ${sensor.room}", processed, writes.size, changed)
            )
        }
        if (stopDiagnostic != null) return ForwardFillSummary(created, 0, 0.0, stopDiagnostic)

        val drift = abs(current - first.temperature)
        return ForwardFillSummary(
            created, 1, drift,
            "État masse initiale ${round2(initial.third)} °C · ${profile.summary()}"
        )
    }

'''
pattern_before = re.compile(
    r'''    private fun reconstructBeforeFirst\(.*?\n    \}\n\n    private fun estimateInitialStateForward\(''',
    re.S,
)
match = pattern_before.search(engine)
if not match:
    if "val writes = ArrayList<PriorityPointWrite>" not in engine:
        raise SystemExit("ThermalEngine reconstructBeforeFirst introuvable")
else:
    engine = engine[:match.start()] + new_before + "    private fun estimateInitialStateForward(" + engine[match.end():]

new_gaps = r'''    private fun fillInteriorGapsForward(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        profile: ThermalBuildingProfile,
        progress: ((ThermalProgress) -> Unit)? = null
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
        var raccords = 0
        var maxDrift = 0.0
        val writes = ArrayList<PriorityPointWrite>()

        measured.zipWithNext().forEach { (left, right) ->
            val gapHours = ((right.timestamp - left.timestamp) / THERMAL_HOUR_MS).toInt()
            if (gapHours !in 2..(14 * 24)) return@forEach
            var current = left.temperature
            var currentH = left.humidity
            var currentMass = left.temperature
            var completed = true

            for (step in 1 until gapHours) {
                val previousTs = hourBucket(left.timestamp) + (step - 1) * THERMAL_HOUR_MS
                val ts = previousTs + THERMAL_HOUR_MS
                val extTs = previousTs - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs)
                if (tout == null) {
                    completed = false
                    break
                }
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
                val hour = Instant.ofEpochMilli(previousTs).atZone(zone).hour
                val delta = massAwareDelta(model.coefficients, current, currentMass, tout, avg6, hour, profile)
                    .coerceIn(-1.2, 1.2)
                val predicted = current + delta
                if (!plausibleIndoor(predicted)) { completed = false; break }
                val nextMass = advanceMass(profile, current, currentMass, avg6)
                current = predicted
                currentMass = nextMass
                val outHum = outMap[hourBucket(ts)]?.humidity ?: currentH
                currentH += 0.08 * (outHum - currentH)
                val confidence = (model.confidence * 0.82).coerceIn(0.20, 0.85)
                writes += PriorityPointWrite(
                    sensor.id, ts, round2(current), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.RECONSTRUCTED, confidence)
                )
            }

            if (completed) {
                val previousTs = hourBucket(right.timestamp) - THERMAL_HOUR_MS
                val extTs = previousTs - model.lagHours * THERMAL_HOUR_MS
                val tout = outsideAt(outMap, extTs)
                val avg6 = if (tout != null) outsideAverage(outMap, extTs, 6) ?: tout else null
                if (tout != null && avg6 != null) {
                    val hour = Instant.ofEpochMilli(previousTs).atZone(zone).hour
                    val projectedAtRight = current + massAwareDelta(
                        model.coefficients, current, currentMass, tout, avg6, hour, profile
                    ).coerceIn(-1.2, 1.2)
                    if (plausibleIndoor(projectedAtRight)) {
                        raccords++
                        maxDrift = max(maxDrift, abs(projectedAtRight - right.temperature))
                    }
                }
            }
        }

        val created = PointSourceStore.upsertBatchByPriority(db, writes, 256) { processed, changed ->
            progress?.invoke(ThermalProgress("Comblement des trous · ${sensor.room}", processed, writes.size, changed))
        }
        return ForwardFillSummary(created, raccords, maxDrift)
    }

'''
pattern_gaps = re.compile(
    r'''    private fun fillInteriorGapsForward\(.*?\n    \}\n\n    private fun validateLongHorizon\(''',
    re.S,
)
match = pattern_gaps.search(engine)
if not match:
    if "val writes = ArrayList<PriorityPointWrite>()" not in engine:
        raise SystemExit("ThermalEngine fillInteriorGapsForward introuvable")
else:
    engine = engine[:match.start()] + new_gaps + "    private fun validateLongHorizon(" + engine[match.end():]

write(engine_path, engine)
print("ThermalEngine: calcul RC inchangé, écritures groupées + modèle prévalidé + progression")


# -----------------------------------------------------------------------------
# 4) UI: expose progress, progressively reload committed chunks, and prevent the
#    automatic refresh loop from starting another thermal job while reconstruction runs.
# -----------------------------------------------------------------------------
ui_path = "app/src/main/java/com/fabdata/app/ThermalUi.kt"
ui = read(ui_path)
ui = replace_once(
    ui,
    '''    dataVersion: Int,
    onDataChanged: () -> Unit
) {''',
    '''    dataVersion: Int,
    onDataChanged: () -> Unit,
    onBusyChanged: (Boolean) -> Unit = {}
) {''',
    "ThermalReferenceCard busy callback",
)

busy_state = '''    var busy by remember { mutableStateOf(false) }
'''
if "LaunchedEffect(busy) { onBusyChanged(busy) }" not in ui:
    ui = replace_once(
        ui,
        busy_state,
        busy_state + '''\n    LaunchedEffect(busy) { onBusyChanged(busy) }\n''',
        "Thermal busy effect",
    )

ui = replace_once(
    ui,
    '''    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        val currentMeasuredRevision = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }''',
    '''    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {
        // Les rechargements progressifs du graphe ne doivent jamais lancer un second moteur.
        if (busy) return@LaunchedEffect
        val currentMeasuredRevision = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }''',
    "Thermal auto refresh busy guard",
)

ui = replace_once(
    ui,
    '''                    scope.launch {
                        busy = true
                        val result = withContext(Dispatchers.IO) {
                            runCatching {
                                // Ordre strict v0.10.3 : la référence visible/RC est préparée AVANT tout.''',
    '''                    scope.launch {
                        busy = true
                        info = "Reconstruction · préparation météo…"
                        val result = withContext(Dispatchers.IO) {
                            runCatching {
                                // Ordre strict v0.10.3 : la référence visible/RC est préparée AVANT tout.''',
    "Thermal history initial progress",
)

old_call = '''                                val checked = engine.status(reference, selectedSensorId, profile)
                                if (!checked.canReconstruct) error(checked.message)
                                engine.reconstructHistory(reference, historyDays, selectedSensorId ?: checked.preferred?.sensor?.id, profile)'''
new_call = '''                                val checked = engine.status(reference, selectedSensorId, profile)
                                if (!checked.canReconstruct) error(checked.message)
                                val activeId = selectedSensorId ?: checked.preferred?.sensor?.id
                                val activeModel = checked.preferred?.model?.takeIf { it.sensorId == activeId }
                                engine.reconstructHistory(
                                    reference = reference,
                                    requestedDays = historyDays,
                                    sensorId = activeId,
                                    profile = profile,
                                    precalibratedModel = activeModel
                                ) { p ->
                                    scope.launch {
                                        info = if (p.total > 0) {
                                            val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                                            "${p.stage} · $percent % · ${p.changed} point(s) écrit(s)"
                                        } else p.stage
                                        // Le callback arrive après un commit SQLite de 256 points :
                                        // la courbe peut donc montrer la reconstruction sans attendre la fin.
                                        if (p.total > 0 && p.processed > 0) {
                                            suppressNextAuto = true
                                            onDataChanged()
                                        }
                                    }
                                }'''
ui = replace_once(ui, old_call, new_call, "Thermal history prevalidated + progress")
write(ui_path, ui)
print("ThermalUi: progression + rechargement par lots + anti double-run")


# -----------------------------------------------------------------------------
# 5) Main UI: pause the 180 ms animated-style tick while thermal reconstruction is busy.
# -----------------------------------------------------------------------------
main_path = "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = read(main_path)
main = replace_once(
    main,
    '''    var busy by remember { mutableStateOf(false) }
    var selectedTimestamp''',
    '''    var busy by remember { mutableStateOf(false) }
    var thermalBusy by remember { mutableStateOf(false) }
    var selectedTimestamp''',
    "Main thermal busy state",
)
main = replace_once(
    main,
    '''    LaunchedEffect(Unit) {
        while (true) {
            styleTick = System.currentTimeMillis()
            delay(180L)
        }
    }''',
    '''    LaunchedEffect(Unit) {
        while (true) {
            if (!thermalBusy) styleTick = System.currentTimeMillis()
            delay(if (thermalBusy) 900L else 180L)
        }
    }''',
    "Main style tick pause",
)
main = replace_once(
    main,
    '''                        dataVersion = reloadToken,
                        onDataChanged = { reloadToken++ }
                    )''',
    '''                        dataVersion = reloadToken,
                        onDataChanged = { reloadToken++ },
                        onBusyChanged = { thermalBusy = it }
                    )''',
    "Main ThermalReferenceCard callback",
)
write(main_path, main)
print("MainActivity: animations de courbe suspendues pendant le calcul thermique")

print("FabData v0.12.2 reconstruction pipeline patch applied")
