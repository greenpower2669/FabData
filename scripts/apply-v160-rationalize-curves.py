#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str, label: str):
    p = ROOT / path
    text = p.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable dans {path}")
    p.write_text(text.replace(old, new, 1))


def insert_before(path: str, anchor: str, block: str, label: str):
    p = ROOT / path
    text = p.read_text()
    if block.strip() in text:
        return
    if anchor not in text:
        raise SystemExit(f"{label}: ancre introuvable dans {path}")
    p.write_text(text.replace(anchor, block + anchor, 1))


def replace_n(path: str, old: str, new: str, expected: int, label: str):
    p = ROOT / path
    text = p.read_text()
    if new in text and old not in text:
        return
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: {count} occurrence(s), attendu {expected} dans {path}")
    p.write_text(text.replace(old, new))


# -----------------------------------------------------------------------------
# 0. Journal minimal de cohérence : réutilise point_sources, pas de nouveau log.
# -----------------------------------------------------------------------------
coherence = r'''package com.fabdata.app

import java.security.MessageDigest

/** Empreinte minimale attachée aux points calculés. */
data class ThermalDependencyFingerprint(
    val profileHash: String,
    val dependencyHash: String
)

data class ThermalCurveCoherence(
    val sensorId: Long,
    val source: PointSource,
    val bounds: LongRange,
    val expected: ThermalDependencyFingerprint,
    val totalPoints: Int,
    val stalePoints: Int,
    val unknownPoints: Int
) {
    val current: Boolean get() = stalePoints == 0
}

/**
 * v0.16 : cohérence des courbes calculées.
 *
 * Le journal est volontairement minuscule : les colonnes profile_hash et dependency_hash
 * vivent dans point_sources, à côté de source/model_version/updated_at déjà existants.
 * Une ancienne sauvegarde sans empreinte reste lisible ; elle est simplement "inconnue"
 * lors d'une rationalisation manuelle et sera alors recalculée par sécurité.
 */
class ThermalCoherenceStore(private val db: FabDataDb) {
    init {
        PointSourceStore.ensure(db.writableDatabase)
        WeatherReferenceStore.ensure(db.writableDatabase)
    }

    fun profileHash(raw: ThermalBuildingProfile): String {
        val p = raw.normalized()
        return hashStrings(
            "profile-v1",
            java.lang.Double.doubleToRawLongBits(p.surfaceM2).toString(),
            p.floor.toString(),
            p.insulation.uppercase(),
            p.inertia.name,
            p.exposure.name,
            p.initialMassOverrideC?.let { java.lang.Double.doubleToRawLongBits(it).toString() } ?: "auto"
        )
    }

    fun dependencyFingerprint(
        reference: WeatherReference,
        profile: ThermalBuildingProfile,
        sensorId: Long,
        source: PointSource,
        forecastMode: ForecastHorizonMode? = null
    ): ThermalDependencyFingerprint {
        require(source != PointSource.MEASURED) { "Une mesure réelle n'a pas d'empreinte calculée" }
        val pHash = profileHash(profile)
        val measured = measuredHash(sensorId)
        val weather = weatherHash(reference.key, includeForecast = source == PointSource.FORECAST)
        val mode = if (source == PointSource.FORECAST) (forecastMode ?: ForecastHorizonMode.AUTO).name else "history"
        val dependency = hashStrings(
            "thermal-dependency-v1",
            source.dbValue,
            PointSourceStore.MODEL_VERSION,
            reference.key,
            reference.stationId,
            pHash,
            measured,
            weather,
            mode
        )
        return ThermalDependencyFingerprint(pHash, dependency)
    }

    fun inspect(
        reference: WeatherReference,
        profile: ThermalBuildingProfile,
        sensorId: Long,
        source: PointSource,
        forecastMode: ForecastHorizonMode? = null
    ): ThermalCurveCoherence? {
        require(source != PointSource.MEASURED)
        val expected = dependencyFingerprint(reference, profile, sensorId, source, forecastMode)
        return db.readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp),
                   SUM(CASE WHEN COALESCE(dependency_hash,'')<>? OR COALESCE(profile_hash,'')<>? THEN 1 ELSE 0 END),
                   SUM(CASE WHEN dependency_hash IS NULL OR profile_hash IS NULL THEN 1 ELSE 0 END)
            FROM point_sources
            WHERE sensor_id=? AND source=?
            """.trimIndent(),
            arrayOf(expected.dependencyHash, expected.profileHash, sensorId.toString(), source.dbValue)
        ).use { c ->
            if (!c.moveToFirst() || c.getInt(0) <= 0 || c.isNull(1) || c.isNull(2)) return null
            ThermalCurveCoherence(
                sensorId = sensorId,
                source = source,
                bounds = c.getLong(1)..c.getLong(2),
                expected = expected,
                totalPoints = c.getInt(0),
                stalePoints = if (c.isNull(3)) 0 else c.getInt(3),
                unknownPoints = if (c.isNull(4)) 0 else c.getInt(4)
            )
        }
    }

    fun calculatedSensorIds(): List<Long> {
        val out = mutableListOf<Long>()
        db.readableDatabase.rawQuery(
            """
            SELECT DISTINCT ps.sensor_id
            FROM point_sources ps
            JOIN sensors s ON s.id=ps.sensor_id
            WHERE ps.source IN ('reconstructed','forecast')
              AND ps.sensor_id>=0
              AND s.stable_key NOT LIKE 'meteo-%'
              AND s.stable_key NOT LIKE 'http-get-%'
            ORDER BY ps.sensor_id
            """.trimIndent(), null
        ).use { c -> while (c.moveToNext()) out += c.getLong(0) }
        return out
    }

    fun firstMeasuredTimestamp(sensorId: Long): Long? {
        return db.readableDatabase.rawQuery(
            """
            SELECT MIN(p.timestamp)
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source='measured')
            """.trimIndent(), arrayOf(sensorId.toString())
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0)) null else c.getLong(0)
        }
    }

    fun hasStampedCalculatedPoints(): Boolean {
        return db.readableDatabase.rawQuery(
            "SELECT 1 FROM point_sources WHERE source IN ('reconstructed','forecast') AND dependency_hash IS NOT NULL LIMIT 1",
            null
        ).use { it.moveToFirst() }
    }

    private fun measuredHash(sensorId: Long): String {
        val digest = MessageDigest.getInstance("SHA-256")
        put(digest, "measured-v1")
        db.readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source='measured')
            ORDER BY p.timestamp
            """.trimIndent(), arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) {
                put(digest, c.getLong(0).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(1)).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(2)).toString())
            }
        }
        return hex(digest.digest())
    }

    private fun weatherHash(referenceKey: String, includeForecast: Boolean): String {
        val digest = MessageDigest.getInstance("SHA-256")
        put(digest, if (includeForecast) "weather-all-v1" else "weather-history-v1")
        val sql = if (includeForecast) {
            """
            SELECT timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
            WHERE reference_key=?
            ORDER BY timestamp
            """.trimIndent()
        } else {
            """
            SELECT timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
            WHERE reference_key=? AND source<>'forecast'
            ORDER BY timestamp
            """.trimIndent()
        }
        db.readableDatabase.rawQuery(sql, arrayOf(referenceKey)).use { c ->
            while (c.moveToNext()) {
                put(digest, c.getLong(0).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(1)).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(2)).toString())
                put(digest, c.getString(3))
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(4)).toString())
            }
        }
        return hex(digest.digest())
    }

    private fun hashStrings(vararg values: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        values.forEach { put(digest, it) }
        return hex(digest.digest())
    }

    private fun put(digest: MessageDigest, value: String) {
        digest.update(value.toByteArray(Charsets.UTF_8))
        digest.update(0)
    }

    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }
}
'''
coherence_path = ROOT / "app/src/main/java/com/fabdata/app/ThermalCoherence.kt"
if not coherence_path.exists() or coherence_path.read_text() != coherence:
    coherence_path.write_text(coherence)


# -----------------------------------------------------------------------------
# 1. Étendre la provenance existante + suppression sûre par source calculée.
# -----------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''    val modelVersion: String? = null,\n    val sigmaC: Double? = null,\n    val analogCount: Int? = null\n)''',
    '''    val modelVersion: String? = null,\n    val sigmaC: Double? = null,\n    val analogCount: Int? = null,\n    val profileHash: String? = null,\n    val dependencyHash: String? = null\n)''',
    "provenance fingerprints"
)

replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''                model_version TEXT,\n                updated_at INTEGER NOT NULL,''',
    '''                model_version TEXT,\n                profile_hash TEXT,\n                dependency_hash TEXT,\n                updated_at INTEGER NOT NULL,''',
    "point_sources fingerprint columns"
)

replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''        ensureColumn(db, "sigma_c", "REAL")\n        ensureColumn(db, "analog_count", "INTEGER")''',
    '''        ensureColumn(db, "sigma_c", "REAL")\n        ensureColumn(db, "analog_count", "INTEGER")\n        ensureColumn(db, "profile_hash", "TEXT")\n        ensureColumn(db, "dependency_hash", "TEXT")''',
    "ensure fingerprint columns"
)

replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''                   calibration_from, calibration_to, model_version, sigma_c, analog_count\n            FROM point_sources''',
    '''                   calibration_from, calibration_to, model_version, sigma_c, analog_count,\n                   profile_hash, dependency_hash\n            FROM point_sources''',
    "read fingerprint columns"
)

replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''                modelVersion = if (c.isNull(7)) null else c.getString(7),\n                sigmaC = if (c.isNull(8)) null else c.getDouble(8),\n                analogCount = if (c.isNull(9)) null else c.getInt(9)\n            )''',
    '''                modelVersion = if (c.isNull(7)) null else c.getString(7),\n                sigmaC = if (c.isNull(8)) null else c.getDouble(8),\n                analogCount = if (c.isNull(9)) null else c.getInt(9),\n                profileHash = if (c.isNull(10)) null else c.getString(10),\n                dependencyHash = if (c.isNull(11)) null else c.getString(11)\n            )''',
    "map fingerprint columns"
)

replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''            provenance.modelVersion?.let { put("model_version", it) }\n            put("updated_at", System.currentTimeMillis())''',
    '''            provenance.modelVersion?.let { put("model_version", it) }\n            provenance.profileHash?.let { put("profile_hash", it) }\n            provenance.dependencyHash?.let { put("dependency_hash", it) }\n            put("updated_at", System.currentTimeMillis())''',
    "write fingerprint columns"
)

# Même valeur calculée, nouvelle provenance : mettre à jour l'empreinte sans toucher aux valeurs.
replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''        if (provenance.source.priority == existingSource.priority && sameValues) {\n            // La vraie mesure doit quand même effacer une ancienne provenance calculée.\n            if (provenance.source == PointSource.MEASURED) markMeasured(db, sensorId, timestamp)\n            return PriorityWriteResult.UNCHANGED\n        }''',
    '''        if (provenance.source.priority == existingSource.priority && sameValues) {\n            // La vraie mesure doit quand même effacer une ancienne provenance calculée.\n            // Pour un point calculé inchangé numériquement, la provenance doit malgré tout\n            // suivre les paramètres/dépendances qui viennent réellement de le recalculer.\n            if (provenance.source == PointSource.MEASURED) markMeasured(db, sensorId, timestamp)\n            else setProvenance(db, sensorId, timestamp, provenance)\n            return PriorityWriteResult.UNCHANGED\n        }''',
    "refresh calculated provenance"
)

insert_before(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''    fun reconstructedBounds(db: FabDataDb, sensorId: Long): LongRange? {''',
    '''    fun sourceBounds(db: FabDataDb, sensorId: Long, source: PointSource): LongRange? {\n        require(source != PointSource.MEASURED) { "Les mesures réelles ne passent jamais par sourceBounds calculé" }\n        ensure(db.readableDatabase)\n        db.readableDatabase.rawQuery(\n            "SELECT MIN(timestamp), MAX(timestamp) FROM point_sources WHERE sensor_id=? AND source=?",\n            arrayOf(sensorId.toString(), source.dbValue)\n        ).use { c ->\n            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null\n            return c.getLong(0)..c.getLong(1)\n        }\n    }\n\n    /** Supprime exclusivement une couche calculée. MEASURED est interdit par contrat. */\n    fun deleteBySource(db: FabDataDb, sensorId: Long, source: PointSource): Int {\n        require(source != PointSource.MEASURED) { "Une mesure réelle ne peut jamais être invalidée" }\n        ensure(db.writableDatabase)\n        val timestamps = mutableListOf<Long>()\n        db.readableDatabase.rawQuery(\n            "SELECT timestamp FROM point_sources WHERE sensor_id=? AND source=? ORDER BY timestamp",\n            arrayOf(sensorId.toString(), source.dbValue)\n        ).use { c -> while (c.moveToNext()) timestamps += c.getLong(0) }\n        if (timestamps.isEmpty()) return 0\n        db.inTransaction {\n            timestamps.forEach { ts ->\n                db.writableDatabase.delete(\n                    "samples", "sensor_id=? AND timestamp=?",\n                    arrayOf(sensorId.toString(), ts.toString())\n                )\n                db.writableDatabase.delete(\n                    "point_sources", "sensor_id=? AND timestamp=? AND source=?",\n                    arrayOf(sensorId.toString(), ts.toString(), source.dbValue)\n                )\n            }\n        }\n        return timestamps.size\n    }\n\n''',
    "safe calculated deletion"
)

replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    '''    fun reconstructedBounds(db: FabDataDb, sensorId: Long): LongRange? {\n        ensure(db.readableDatabase)\n        db.readableDatabase.rawQuery(\n            "SELECT MIN(timestamp), MAX(timestamp) FROM point_sources WHERE sensor_id=? AND source='reconstructed'",\n            arrayOf(sensorId.toString())\n        ).use { c ->\n            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null\n            return c.getLong(0)..c.getLong(1)\n        }\n    }''',
    '''    fun reconstructedBounds(db: FabDataDb, sensorId: Long): LongRange? =\n        sourceBounds(db, sensorId, PointSource.RECONSTRUCTED)''',
    "reuse sourceBounds"
)


# -----------------------------------------------------------------------------
# 2. Le moteur garde ses équations ; on injecte seulement l'empreinte dans sa provenance.
# -----------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''    private val zone = ZoneId.of("Europe/Paris")\n    private val inertiaEstimator = ThermalInertiaEstimator(db, referenceStore)''',
    '''    private val zone = ZoneId.of("Europe/Paris")\n    private val inertiaEstimator = ThermalInertiaEstimator(db, referenceStore)\n    private val coherenceStore = ThermalCoherenceStore(db)''',
    "engine coherence store"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            val outMap = outside.associateBy { hourBucket(it.timestamp) }\n\n            progress?.invoke(ThermalProgress("État initial · ${sensor.room}"))\n            val before = reconstructBeforeFirst(sensor, model, reference, first, startAt, outMap, profile, inertia, progress)''',
    '''            val outMap = outside.associateBy { hourBucket(it.timestamp) }\n            val fingerprint = coherenceStore.dependencyFingerprint(\n                reference, profile, sensor.id, PointSource.RECONSTRUCTED\n            )\n\n            progress?.invoke(ThermalProgress("État initial · ${sensor.room}"))\n            val before = reconstructBeforeFirst(\n                sensor, model, reference, first, startAt, outMap, profile, inertia, fingerprint, progress\n            )''',
    "history fingerprint"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            val gaps = fillInteriorGapsForward(sensor, model, reference, profile, inertia, progress)''',
    '''            val gaps = fillInteriorGapsForward(\n                sensor, model, reference, profile, inertia, fingerprint, progress\n            )''',
    "history gap fingerprint"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        inertia: ThermalInertiaEstimate,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {''',
    '''        inertia: ThermalInertiaEstimate,\n        fingerprint: ThermalDependencyFingerprint,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {''',
    "before-first fingerprint parameter"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        profile: ThermalBuildingProfile,\n        inertia: ThermalInertiaEstimate,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {\n        val measured = measuredHourly(sensor.id)''',
    '''        profile: ThermalBuildingProfile,\n        inertia: ThermalInertiaEstimate,\n        fingerprint: ThermalDependencyFingerprint,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ForwardFillSummary {\n        val measured = measuredHourly(sensor.id)''',
    "gap fingerprint parameter"
)

replace_n(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''provenance(model, reference, PointSource.RECONSTRUCTED, confidence)''',
    '''provenance(model, reference, PointSource.RECONSTRUCTED, confidence, fingerprint)''',
    2,
    "reconstruction provenance fingerprints"
)

# Forecast : empreinte calculée une fois par sonde, après chargement de la météo incluant H+.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''            val outMap = outside.associateBy { hourBucket(it.timestamp) }\n            if (outside.none { it.timestamp > latest.timestamp }) { skipped++; return@forEach }''',
    '''            val outMap = outside.associateBy { hourBucket(it.timestamp) }\n            if (outside.none { it.timestamp > latest.timestamp }) { skipped++; return@forEach }\n            val fingerprint = coherenceStore.dependencyFingerprint(\n                reference, profile, sensor.id, PointSource.FORECAST, mode\n            )''',
    "forecast fingerprint"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''                    provenance(model, reference, PointSource.FORECAST, confidence, sigma, analog.count)''',
    '''                    provenance(model, reference, PointSource.FORECAST, confidence, fingerprint, sigma, analog.count)''',
    "forecast provenance fingerprint"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        source: PointSource,\n        confidence: Double,\n        sigmaC: Double? = null,''',
    '''        source: PointSource,\n        confidence: Double,\n        fingerprint: ThermalDependencyFingerprint,\n        sigmaC: Double? = null,''',
    "provenance fingerprint argument"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''        modelVersion = PointSourceStore.MODEL_VERSION,\n        sigmaC = sigmaC,\n        analogCount = analogCount''',
    '''        modelVersion = PointSourceStore.MODEL_VERSION,\n        sigmaC = sigmaC,\n        analogCount = analogCount,\n        profileHash = fingerprint.profileHash,\n        dependencyHash = fingerprint.dependencyHash''',
    "provenance fingerprint fields"
)

# Ancien chemin de rafraîchissement des trous : lui donner aussi une empreinte courante.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''                val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n                    ?: run { skipped++; return@forEach }\n                val r = fillInteriorGapsForward(sensor, model, reference, profile, inertia)''',
    '''                val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n                    ?: run { skipped++; return@forEach }\n                val fingerprint = coherenceStore.dependencyFingerprint(\n                    reference, profile, sensor.id, PointSource.RECONSTRUCTED\n                )\n                val r = fillInteriorGapsForward(sensor, model, reference, profile, inertia, fingerprint)''',
    "legacy refresh fingerprint"
)

# Helper ciblé utilisé après suppression d'une reconstruction périmée.
insert_before(
    "app/src/main/java/com/fabdata/app/ThermalEngine.kt",
    '''    /**\n     * Une nouvelle vraie mesure invalide déjà les forecasts via PointSourceStore.''',
    '''    /**\n     * Reconstruit exactement le type d'étendue qui existait avant invalidation :\n     * historique avant la première vraie mesure, ou seulement trous intérieurs.\n     * Le moteur mathématique reste celui de reconstructHistory/fillInteriorGapsForward.\n     */\n    fun rebuildCalculatedExtent(\n        reference: WeatherReference,\n        profile: ThermalBuildingProfile,\n        sensorId: Long,\n        previousBounds: LongRange,\n        progress: ((ThermalProgress) -> Unit)? = null\n    ): ThermalWriteSummary {\n        val sensor = physicalSensors().firstOrNull { it.id == sensorId }\n            ?: return ThermalWriteSummary(0, 0, 1, diagnostic = "Sonde thermique introuvable")\n        val measured = measuredHourly(sensor.id)\n        val first = measured.firstOrNull()\n            ?: return ThermalWriteSummary(0, 0, 1, diagnostic = "Aucune mesure réelle")\n        if (previousBounds.first < first.timestamp) {\n            val span = (first.timestamp - previousBounds.first).coerceAtLeast(THERMAL_DAY_MS)\n            val days = ((span + THERMAL_DAY_MS - 1L) / THERMAL_DAY_MS).toInt()\n                .coerceIn(1, MAX_HISTORY_DAYS)\n            return reconstructHistory(reference, days, sensor.id, profile, progress = progress)\n        }\n\n        val model = runCatching { calibrate(sensor, reference, profile) }.getOrNull()\n            ?: return ThermalWriteSummary(0, 0, 1, diagnostic = "Modèle non recalibrable")\n        if (!model.acceptableForHistory) {\n            return ThermalWriteSummary(0, 0, 1, diagnostic = "Modèle non validé pour l'historique")\n        }\n        val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)\n            ?: return ThermalWriteSummary(0, 0, 1, diagnostic = "Inertie indisponible")\n        val fingerprint = coherenceStore.dependencyFingerprint(\n            reference, profile, sensor.id, PointSource.RECONSTRUCTED\n        )\n        val r = fillInteriorGapsForward(sensor, model, reference, profile, inertia, fingerprint, progress)\n        return ThermalWriteSummary(r.created, 0, 0, r.raccords, r.maxDrift, r.diagnostic)\n    }\n\n''',
    "rebuild existing extent"
)


# -----------------------------------------------------------------------------
# 3. UI thermique : rationaliseur commun + invalidation automatique du profil.
# -----------------------------------------------------------------------------
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''    val engine = remember { ThermalEngine(db, manager.store()) }\n    val profileStore = remember { ThermalProfileStore(context) }''',
    '''    val engine = remember { ThermalEngine(db, manager.store()) }\n    val coherenceStore = remember { ThermalCoherenceStore(db) }\n    val profileStore = remember { ThermalProfileStore(context) }''',
    "ui coherence store"
)

replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''    var profileDialog by remember { mutableStateOf(false) }\n    var measuredRevision by remember { mutableStateOf<String?>(null) }''',
    '''    var profileDialog by remember { mutableStateOf(false) }\n    var measuredRevision by remember { mutableStateOf<String?>(null) }\n    var coherenceBaselineReady by remember { mutableStateOf(false) }\n    var observedReferenceKey by remember { mutableStateOf(selectedKey) }\n    var observedDataVersion by remember { mutableIntStateOf(dataVersion) }''',
    "coherence baseline state"
)

# Ajouter le rationaliseur après refresh(), avant le LaunchedEffect existant.
insert_before(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''    // v0.12.1 : dataVersion peut aussi changer pour des écritures calculées ou l'UI.''',
    r'''    suspend fun rationalizeCurves(
        reason: String,
        targetProfile: ThermalBuildingProfile = profile,
        manual: Boolean = false
    ) {
        if (busy) return
        busy = true
        info = "Rationalisation · analyse des dépendances…"
        val progressCallback: (ThermalProgress) -> Unit = { p ->
            scope.launch {
                info = if (p.total > 0) {
                    val percent = (100 * p.processed / p.total.coerceAtLeast(1)).coerceIn(0, 100)
                    "Rationalisation · ${p.stage} · $percent %"
                } else "Rationalisation · ${p.stage}"
            }
        }
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val measuredBounds = db.physicalMeasuredBounds() ?: db.physicalSensorBounds()
                    ?: error("Aucune donnée intérieure")
                val hourMs = 60L * 60L * 1000L
                val dayMs = 24L * hourMs

                // En automatique on remet d'abord la petite fenêtre météo courante à jour.
                // En manuel, on examine strictement l'état présent : une base déjà cohérente
                // ne doit pas être rendue artificiellement périmée par un téléchargement.
                if (!manual) {
                    manager.ensureLocalCache(
                        reference,
                        measuredBounds.first - 18L * hourMs,
                        maxOf(measuredBounds.last, System.currentTimeMillis() + (forecastMode.maxHours + 2L) * hourMs)
                    )
                }

                fun reconStates() = coherenceStore.calculatedSensorIds().mapNotNull { id ->
                    coherenceStore.inspect(reference, targetProfile, id, PointSource.RECONSTRUCTED)
                }
                fun forecastStates() = coherenceStore.calculatedSensorIds().mapNotNull { id ->
                    coherenceStore.inspect(reference, targetProfile, id, PointSource.FORECAST, forecastMode)
                }

                var staleRecon = reconStates().filterNot { it.current }
                var staleForecast = forecastStates().filterNot { it.current }

                // Si une reconstruction ancienne est réellement périmée, préparer sa profondeur
                // AVANT toute suppression. On garde ainsi les vraies mesures et les sources sûres
                // tant que les dépendances nécessaires au recalcul ne sont pas prêtes.
                val maxHistoryDays = staleRecon.mapNotNull { state ->
                    val firstReal = coherenceStore.firstMeasuredTimestamp(state.sensorId) ?: return@mapNotNull null
                    if (state.bounds.first >= firstReal) 0
                    else (((firstReal - state.bounds.first) + dayMs - 1L) / dayMs).toInt().coerceIn(1, 1098)
                }.maxOrNull() ?: 0
                if (maxHistoryDays > 0) {
                    info = "Rationalisation · préparation météo ${thermalHistoryLabel(maxHistoryDays)}…"
                    val prepared = manager.prepareHistory(reference, maxHistoryDays)
                    if (!prepared.coverage.ready) {
                        error("Référence ${reference.city} incomplète : aucune courbe existante n'a été supprimée")
                    }
                    // La préparation peut elle-même avoir amélioré la référence : recalculer les hashes.
                    staleRecon = reconStates().filterNot { it.current }
                    staleForecast = forecastStates().filterNot { it.current }
                }

                if (staleRecon.isEmpty() && staleForecast.isEmpty()) {
                    return@runCatching RationalizeResult(0, 0, 0, 0, true, reason)
                }

                var removed = 0
                var reconstructed = 0
                var forecasts = 0
                var skipped = 0

                staleRecon.forEach { state ->
                    val previousBounds = state.bounds
                    removed += PointSourceStore.deleteBySource(db, state.sensorId, PointSource.RECONSTRUCTED)
                    val rebuilt = engine.rebuildCalculatedExtent(
                        reference, targetProfile, state.sensorId, previousBounds, progressCallback
                    )
                    reconstructed += rebuilt.reconstructed
                    skipped += rebuilt.skippedSensors
                }

                // Une reconstruction n'entre jamais dans l'apprentissage (MEASURED only), donc
                // le hash du forecast ne dépend pas des points reconstruits. On peut traiter ensuite.
                staleForecast.forEach { state ->
                    removed += PointSourceStore.deleteBySource(db, state.sensorId, PointSource.FORECAST)
                    val rebuilt = engine.refreshForecasts(reference, state.sensorId, targetProfile, forecastMode)
                    forecasts += rebuilt.forecast
                    skipped += rebuilt.skippedSensors
                }

                RationalizeResult(removed, reconstructed, forecasts, skipped, false, reason)
            }
        }
        busy = false
        result.fold(
            onSuccess = { r ->
                info = if (r.alreadyCoherent) {
                    "Courbes déjà cohérentes · aucune donnée calculée supprimée"
                } else {
                    "Rationalisation terminée · ${r.removed} périmée(s) retirée(s) · ${r.reconstructed} historique(s) écrit(s) · ${r.forecasts} prévision(s) · ${r.skipped} refus"
                }
                suppressNextAuto = true
                onDataChanged()
            },
            onFailure = { error ->
                info = error.message ?: "Rationalisation impossible"
            }
        )
    }

''',
    "rationalize function"
)

# Petit résultat local, placé au niveau fichier avant le composable.
insert_before(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''@Composable\nfun ThermalReferenceCard(''',
    '''private data class RationalizeResult(\n    val removed: Int,\n    val reconstructed: Int,\n    val forecasts: Int,\n    val skipped: Int,\n    val alreadyCoherent: Boolean,\n    val reason: String\n)\n\n''',
    "rationalize result"
)

# Remplacer l'effet auto : premier affichage conservateur, ensuite changements amont rationalisés.
old_effect_start = '''    // v0.12.1 : dataVersion peut aussi changer pour des écritures calculées ou l'UI.\n    // On ne recalcule le passé que si COUNT/MIN/MAX des vraies mesures a réellement changé.\n    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {\n        // Les rechargements progressifs du graphe ne doivent jamais lancer un second moteur.\n        if (busy) return@LaunchedEffect\n        val currentMeasuredRevision = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }\n        val measuredChanged = measuredRevision != null && currentMeasuredRevision != measuredRevision\n        measuredRevision = currentMeasuredRevision\n        if (suppressNextAuto) {\n            suppressNextAuto = false\n        } else {\n            refresh(\n                allHistory = false,\n                triggerChartReload = true,\n                rebuildHistoryFromNewMeasured = measuredChanged\n            )\n        }\n    }'''
new_effect = '''    // v0.16 : le premier affichage ne détruit jamais une ancienne sauvegarde inconnue.\n    // Après cette baseline, mesure/référence changée = chaîne aval rationalisée.\n    LaunchedEffect(dataVersion, selectedKey, selectedSensorId, profile, forecastMode) {\n        if (busy) return@LaunchedEffect\n        val currentMeasuredRevision = withContext(Dispatchers.IO) { db.physicalMeasuredRevision() }\n        val measuredChanged = measuredRevision != null && currentMeasuredRevision != measuredRevision\n        val referenceChanged = coherenceBaselineReady && selectedKey != observedReferenceKey\n        val dataChanged = coherenceBaselineReady && dataVersion != observedDataVersion\n        measuredRevision = currentMeasuredRevision\n        observedReferenceKey = selectedKey\n        observedDataVersion = dataVersion\n\n        if (!coherenceBaselineReady) {\n            coherenceBaselineReady = true\n            refresh(allHistory = false, triggerChartReload = true)\n        } else if (suppressNextAuto) {\n            suppressNextAuto = false\n        } else {\n            val stamped = withContext(Dispatchers.IO) { coherenceStore.hasStampedCalculatedPoints() }\n            if (measuredChanged || referenceChanged || (dataChanged && stamped)) {\n                val why = when {\n                    measuredChanged -> "Nouvelles mesures réelles"\n                    referenceChanged -> "Référence météo modifiée"\n                    else -> "Données sources modifiées"\n                }\n                rationalizeCurves(why, profile, manual = false)\n            } else {\n                refresh(allHistory = false, triggerChartReload = true)\n            }\n        }\n    }'''
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    old_effect_start,
    new_effect,
    "automatic rationalization effect"
)

# Bouton manuel juste avant les réglages avancés.
insert_before(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''            Card(shape = RoundedCornerShape(14.dp)) {\n                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {\n                    Text("Profil thermique du bâtiment", fontWeight = FontWeight.SemiBold)''',
    '''            Button(\n                onClick = { scope.launch { rationalizeCurves("Rationalisation manuelle", profile, manual = true) } },\n                enabled = !busy,\n                modifier = Modifier.fillMaxWidth()\n            ) { Text("Rationaliser les courbes") }\n            Text(\n                "Vérifie les empreintes des calculs, conserve le réel et les résultats encore cohérents, puis ne reconstruit que ce qui est périmé ou incertain.",\n                style = MaterialTheme.typography.labelSmall,\n                color = MaterialTheme.colorScheme.onSurfaceVariant\n            )\n\n''',
    "manual rationalize button"
)

# Profil bâtiment : déclencher immédiatement la même chaîne, avec le nouveau profil exact.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''            onSave = { updated ->\n                profile = updated.normalized()\n                profileStore.save(profile)\n                profileDialog = false\n            },\n            onReset = {\n                profile = profileStore.reset()\n                profileDialog = false\n            }''',
    '''            onSave = { updated ->\n                val next = updated.normalized()\n                val changed = next != profile\n                profile = next\n                profileStore.save(next)\n                profileDialog = false\n                if (changed) {\n                    suppressNextAuto = true\n                    scope.launch { rationalizeCurves("Profil bâtiment modifié", next, manual = false) }\n                }\n            },\n            onReset = {\n                val next = profileStore.reset()\n                val changed = next != profile\n                profile = next\n                profileDialog = false\n                if (changed) {\n                    suppressNextAuto = true\n                    scope.launch { rationalizeCurves("Profil bâtiment réinitialisé", next, manual = false) }\n                }\n            }''',
    "profile automatic invalidation"
)


# -----------------------------------------------------------------------------
# 4. Ergonomie : monitoring d'abord, sans modifier les callbacks des deux périodes.
# -----------------------------------------------------------------------------
main_path = ROOT / "app/src/main/java/com/fabdata/app/MainActivity.kt"
main = main_path.read_text()

# Retirer TimeTabs du sommet : il appartient au graphe détaillé, pas au bandeau global.
top_tabs_start = main.find('''            item {\n                TimeTabs(preset = preset, onSelect = {''')
top_tabs_end_anchor = '''\n\n            if (sensors.isEmpty()) {'''
if top_tabs_start >= 0:
    top_tabs_end = main.find(top_tabs_end_anchor, top_tabs_start)
    if top_tabs_end < 0:
        raise SystemExit("Fin du TimeTabs supérieur introuvable")
    main = main[:top_tabs_start] + main[top_tabs_end + 2:]

region_start_marker = '''                item {\n                    SensorSourcesCard('''
region_end_marker = '''\n\n                selectedAnnotation?.let { note ->'''
region_start = main.find(region_start_marker)
region_end = main.find(region_end_marker, region_start)
if region_start < 0 or region_end < 0:
    raise SystemExit("Région monitoring/outil introuvable")
region = main[region_start:region_end]
markers = [
    '                item {\n                    SensorSourcesCard(',
    '                item {\n                    ThermalReferenceCard(',
    '                item {\n                    ThermalInertiaExperimentCard(',
    '                item {\n                    SourceAwareExportCard(',
    '                item {\n                    SeriesSelector(',
    '                item {\n                    CurvePersonalizationCard(',
    '                item {\n                    HistoryOverviewCard(',
    '                item {\n                    ChartCard(',
]
positions = []
for marker in markers:
    pos = region.find(marker)
    if pos < 0:
        raise SystemExit(f"Bloc UI introuvable: {marker.strip()}")
    positions.append(pos)
if positions != sorted(positions):
    raise SystemExit("Ordre UI v0.15 inattendu")
blocks = {}
for i, marker in enumerate(markers):
    start = positions[i]
    end = positions[i + 1] if i + 1 < len(positions) else len(region)
    blocks[marker] = region[start:end].strip('\n')

detail_tabs = r'''                item {
                    TimeTabs(preset = preset, onSelect = {
                        preset = it
                        windowCenterTimestamp = selectedTimestamp
                            ?: viewBounds?.let { b -> b.first + (b.last - b.first) / 2L }
                        selectedAnnotation = null
                    })
                }'''

new_region = '\n\n'.join([
    blocks[markers[6]],        # Vue globale + SES boutons 6/12/24/36/48m
    detail_tabs,               # boutons 1h/24h/48h/sem/mois JUSTE au-dessus du graphe
    blocks[markers[7]],        # graphe détaillé
    blocks[markers[0]],        # sondes/stations
    blocks[markers[4]],        # superposition / sélection courbes
    blocks[markers[1]],        # moteur thermique + profil + rationalisation
    blocks[markers[2]],        # inertie expérimentale
    blocks[markers[3]],        # export source-aware
    blocks[markers[5]],        # personnalisation
])
main = main[:region_start] + new_region + main[region_end:]
main_path.write_text(main)


# -----------------------------------------------------------------------------
# 5. Version Android.
# -----------------------------------------------------------------------------
replace_once(
    "app/build.gradle.kts",
    '''        versionCode = 30\n        versionName = "0.15.0"''',
    '''        versionCode = 31\n        versionName = "0.16.0"''',
    "v0.16 version"
)


# -----------------------------------------------------------------------------
# 6. Garde-fous statiques de génération.
# -----------------------------------------------------------------------------
point = (ROOT / "app/src/main/java/com/fabdata/app/PointSourceLayer.kt").read_text()
ui = (ROOT / "app/src/main/java/com/fabdata/app/ThermalUi.kt").read_text()
engine = (ROOT / "app/src/main/java/com/fabdata/app/ThermalEngine.kt").read_text()
main = main_path.read_text()

checks = [
    ("PointSourceLayer", 'MEASURED("measured", 3)'),
    ("PointSourceLayer", 'RECONSTRUCTED("reconstructed", 2)'),
    ("PointSourceLayer", 'FORECAST("forecast", 1)'),
    ("PointSourceLayer", 'require(source != PointSource.MEASURED) { "Une mesure réelle ne peut jamais être invalidée" }'),
    ("PointSourceLayer", 'dependency_hash TEXT'),
    ("ThermalUi", 'Text("Rationaliser les courbes")'),
    ("ThermalUi", 'rationalizeCurves("Profil bâtiment modifié"'),
    ("ThermalEngine", 'dependencyFingerprint('),
    ("MainActivity", 'PreviewPreset.entries.forEach'),
    ("MainActivity", 'TimePreset.entries.forEach'),
]
lookup = {"PointSourceLayer": point, "ThermalUi": ui, "ThermalEngine": engine, "MainActivity": main}
for label, needle in checks:
    if needle not in lookup[label]:
        raise SystemExit(f"Invariant v0.16 absent dans {label}: {needle}")

# Les deux contrôles de période restent distincts et le détail est adjacent au graphe.
overview_pos = main.find('HistoryOverviewCard(')
tabs_pos = main.find('TimeTabs(preset = preset', overview_pos)
chart_pos = main.find('ChartCard(', tabs_pos)
sources_pos = main.find('SensorSourcesCard(', chart_pos)
if not (0 <= overview_pos < tabs_pos < chart_pos < sources_pos):
    raise SystemExit("Ordre ergonomique v0.16 invalide")

# Les couches réelles/import/export ne sont volontairement pas patchées par ce script.
print("FabData v0.16 rationalization + monitoring-first patch applied")
