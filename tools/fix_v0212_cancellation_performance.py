from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# FabOperationRegistry: turn the visible cancel request into a real cooperative
# cancellation point that workers can honor between bounded operations.
# ---------------------------------------------------------------------------
p = Path("app/src/main/java/com/fabdata/app/FabOperationRegistry.kt")
t = p.read_text(encoding="utf-8")

t = replace_once(
    t,
    "import kotlinx.coroutines.delay\n",
    "import kotlinx.coroutines.CancellationException\nimport kotlinx.coroutines.delay\n",
    "registry cancellation import",
)

t = replace_once(
    t,
    """    @Synchronized
    fun cancelRequested(id: Long?): Boolean {
        if (id == null) return false
        return operations.firstOrNull { it.id == id }?.state == FabOperationState.CANCEL_REQUESTED
    }

""",
    """    @Synchronized
    fun cancelRequested(id: Long?): Boolean {
        if (id == null) return false
        return operations.firstOrNull { it.id == id }?.state == FabOperationState.CANCEL_REQUESTED
    }

    /**
     * Point de contrôle coopératif. Une pression sur Annuler ne reste plus un simple
     * état visuel : les traitements bornés appellent cette méthode entre deux blocs
     * SQLite/réseau et quittent réellement leur coroutine.
     */
    @Synchronized
    fun ensureNotCancelled(id: Long?) {
        if (id == null) return
        if (operations.firstOrNull { it.id == id }?.state == FabOperationState.CANCEL_REQUESTED) {
            throw CancellationException("FabData operation cancellation requested")
        }
    }

""",
    "registry cooperative cancellation",
)
p.write_text(t, encoding="utf-8")


# ---------------------------------------------------------------------------
# PointSourceLayer: replace the whole-history correlated scan + row-by-row
# deletes by an indexed, set-based and optionally bounded cleanup.
# ---------------------------------------------------------------------------
p = Path("app/src/main/java/com/fabdata/app/PointSourceLayer.kt")
t = p.read_text(encoding="utf-8")

t = replace_once(
    t,
    '        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_time ON point_sources(sensor_id, timestamp)")\n',
    '        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_time ON point_sources(sensor_id, timestamp)")\n'
    '        db.execSQL("CREATE INDEX IF NOT EXISTS idx_point_sources_source_time ON point_sources(source, timestamp)")\n',
    "point source cleanup index",
)

old = """    fun reconcileMeasuredDominance(db: FabDataDb): Int {
        ensure(db.writableDatabase)
        val stale = mutableListOf<Pair<Long, Long>>()
        db.readableDatabase.rawQuery(
            \"\"\"
            SELECT c.sensor_id, c.timestamp
            FROM point_sources c
            WHERE c.source<>'measured'
              AND EXISTS (
                SELECT 1
                FROM samples m
                LEFT JOIN point_sources mp ON mp.sensor_id=m.sensor_id AND mp.timestamp=m.timestamp
                WHERE m.sensor_id=c.sensor_id
                  AND (m.timestamp / 3600000)=(c.timestamp / 3600000)
                  AND (mp.source IS NULL OR mp.source='measured')
              )
            \"\"\".trimIndent(), null
        ).use { c -> while (c.moveToNext()) stale += c.getLong(0) to c.getLong(1) }
        if (stale.isEmpty()) return 0
        db.inTransaction {
            stale.forEach { (sensorId, ts) ->
                db.writableDatabase.delete("samples", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))
                db.writableDatabase.delete("point_sources", "sensor_id=? AND timestamp=?", arrayOf(sensorId.toString(), ts.toString()))
            }
        }
        return stale.size
    }
"""

new = """    fun reconcileMeasuredDominance(db: FabDataDb): Int =
        reconcileMeasuredDominance(db, Long.MIN_VALUE, Long.MAX_VALUE)

    /**
     * Réparation de dominance bornée et set-based.
     *
     * L'ancienne version matérialisait toute la liste historique puis exécutait deux
     * DELETE par point. Sur une grosse base elle pouvait conserver SQLite pendant des
     * minutes/heures et bloquer simultanément l'affichage. Ici SQLite identifie puis
     * supprime le lot en une seule transaction, et le live peut limiter la fenêtre.
     */
    fun reconcileMeasuredDominance(db: FabDataDb, from: Long, to: Long): Int {
        require(to >= from) { "Période de réconciliation invalide" }
        ensure(db.writableDatabase)
        val sql = db.writableDatabase
        val args = arrayOf(from.toString(), to.toString())
        sql.beginTransaction()
        return try {
            val deleted = sql.delete(
                "samples",
                \"\"\"
                rowid IN (
                    SELECT stale.rowid
                    FROM point_sources c
                    JOIN samples stale
                      ON stale.sensor_id=c.sensor_id AND stale.timestamp=c.timestamp
                    WHERE c.source<>'measured'
                      AND c.timestamp BETWEEN ? AND ?
                      AND EXISTS (
                          SELECT 1
                          FROM samples m
                          LEFT JOIN point_sources mp
                            ON mp.sensor_id=m.sensor_id AND mp.timestamp=m.timestamp
                          WHERE m.sensor_id=c.sensor_id
                            AND m.timestamp BETWEEN
                                ((c.timestamp / 3600000) * 3600000)
                                AND (((c.timestamp / 3600000) * 3600000) + 3599999)
                            AND (mp.source IS NULL OR mp.source='measured')
                      )
                )
                \"\"\".trimIndent(),
                args
            )

            // Les samples viennent d'être retirés : enlève leurs provenances devenues
            // orphelines, toujours dans la même fenêtre et sans boucle Kotlin.
            sql.delete(
                "point_sources",
                \"\"\"
                rowid IN (
                    SELECT c.rowid
                    FROM point_sources c
                    WHERE c.source<>'measured'
                      AND c.timestamp BETWEEN ? AND ?
                      AND NOT EXISTS (
                          SELECT 1 FROM samples s
                          WHERE s.sensor_id=c.sensor_id AND s.timestamp=c.timestamp
                      )
                )
                \"\"\".trimIndent(),
                args
            )
            sql.setTransactionSuccessful()
            deleted
        } finally {
            sql.endTransaction()
        }
    }
"""
t = replace_once(t, old, new, "set based physical dominance cleanup")
p.write_text(t, encoding="utf-8")


# ---------------------------------------------------------------------------
# WeatherReferenceLayer: same repair for weather history. The live refresh now
# cleans only its recent 36 h working set instead of rescanning every year.
# ---------------------------------------------------------------------------
p = Path("app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt")
t = p.read_text(encoding="utf-8")

t = replace_once(
    t,
    '            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_weather_reference_time ON weather_reference_samples(reference_key, timestamp)")\n',
    '            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_weather_reference_time ON weather_reference_samples(reference_key, timestamp)")\n'
    '            sql.execSQL("CREATE INDEX IF NOT EXISTS idx_weather_reference_source_time ON weather_reference_samples(reference_key, source, timestamp)")\n',
    "weather cleanup index",
)

old = """    fun reconcileMeasuredDominance(referenceKey: String): Int {
        val stale = mutableListOf<Long>()
        db.readableDatabase.rawQuery(
            \"\"\"
            SELECT c.timestamp
            FROM weather_reference_samples c
            WHERE c.reference_key=? AND c.source<>'measured'
              AND EXISTS (
                SELECT 1 FROM weather_reference_samples m
                WHERE m.reference_key=c.reference_key AND m.source='measured'
                  AND (m.timestamp / 3600000)=(c.timestamp / 3600000)
              )
            \"\"\".trimIndent(), arrayOf(referenceKey)
        ).use { c -> while (c.moveToNext()) stale += c.getLong(0) }
        stale.forEach { ts ->
            db.writableDatabase.delete(
                "weather_reference_samples",
                "reference_key=? AND timestamp=? AND source<>'measured'",
                arrayOf(referenceKey, ts.toString())
            )
        }
        return stale.size
    }
"""
new = """    fun reconcileMeasuredDominance(referenceKey: String): Int =
        reconcileMeasuredDominance(referenceKey, Long.MIN_VALUE, Long.MAX_VALUE)

    /**
     * Nettoyage météo borné. SQLite supprime directement les lignes calculées dont
     * l'heure possède une mesure réelle, sans rapatrier toute l'histoire en Kotlin.
     */
    fun reconcileMeasuredDominance(referenceKey: String, from: Long, to: Long): Int {
        require(to >= from) { "Période météo invalide" }
        return db.writableDatabase.delete(
            "weather_reference_samples",
            \"\"\"
            rowid IN (
                SELECT c.rowid
                FROM weather_reference_samples c
                WHERE c.reference_key=?
                  AND c.source<>'measured'
                  AND c.timestamp BETWEEN ? AND ?
                  AND EXISTS (
                      SELECT 1
                      FROM weather_reference_samples m
                      WHERE m.reference_key=c.reference_key
                        AND m.source='measured'
                        AND m.timestamp BETWEEN
                            ((c.timestamp / 3600000) * 3600000)
                            AND (((c.timestamp / 3600000) * 3600000) + 3599999)
                  )
            )
            \"\"\".trimIndent(),
            arrayOf(referenceKey, from.toString(), to.toString())
        )
    }
"""
t = replace_once(t, old, new, "set based weather dominance cleanup")

# There are two intentional call sites: historical selected-range refresh, then
# lightweight recent refresh. Keep both bounded to their actual work windows.
t = replace_once(
    t,
    "        store.reconcileMeasuredDominance(reference.key)\n        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n        val actual = store.query(reference.key, from, minOf(to, System.currentTimeMillis()))\n",
    "        store.reconcileMeasuredDominance(reference.key, from, minOf(to, System.currentTimeMillis()))\n        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n        val actual = store.query(reference.key, from, minOf(to, System.currentTimeMillis()))\n",
    "bounded selected weather cleanup",
)
t = replace_once(
    t,
    "        reconstructShortGaps(reference.key, from, now)\n        store.reconcileMeasuredDominance(reference.key)\n        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n",
    "        reconstructShortGaps(reference.key, from, now)\n        store.reconcileMeasuredDominance(reference.key, from, now)\n        val forecast = runCatching { refreshForecast(reference) }.getOrDefault(0)\n",
    "bounded recent weather cleanup",
)
p.write_text(t, encoding="utf-8")


# ---------------------------------------------------------------------------
# LiveUpdateCoordinator: no global repair at focus, cancellation checks around
# every blocking phase, and preserve parent coroutine cancellation semantics.
# ---------------------------------------------------------------------------
p = Path("app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt")
t = p.read_text(encoding="utf-8")

t = replace_once(
    t,
    "import kotlinx.coroutines.delay\nimport kotlinx.coroutines.withContext\n",
    "import kotlinx.coroutines.currentCoroutineContext\nimport kotlinx.coroutines.delay\nimport kotlinx.coroutines.isActive\nimport kotlinx.coroutines.withContext\n",
    "live cancellation imports",
)

old = """            withContext(Dispatchers.IO) {
                // Important : le focus ne choisit jamais une autre station.
                // La référence ne peut changer que depuis l'écran de choix explicite.
                val reference = referenceForOperation
                FabOperationRegistry.update(operationId, "${reference.label} · météo récente…")

                if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                    if (credentials.hasCredential()) {
                        runCatching { meteoOfficial.syncSixMinute24h() }
                    } else {
                        runCatching { lyonWeather.syncToday() }
                    }
                }

                PointSourceStore.reconcileMeasuredDominance(db)
                manager.refreshRecent(reference)
                if (FabOperationRegistry.cancelRequested(operationId)) return@withContext

                FabOperationRegistry.update(operationId, "${reference.label} · prévision / cohérence…")
                val profile = profileStore.load()
                val mode = profileStore.forecastMode()
                val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }

                // v0.19.8+ : seul le modèle explicitement entraîné et persisté peut servir au live.
                // Une nouvelle mesure ne le remplace pas et aucun historique n'est recalculé ici.
                val trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                if (trainedModel != null) {
                    engine.refreshForecasts(
                        reference, trainedModel.sensorId, profile, mode,
                        precalibratedModel = trainedModel
                    )
                }
            }
"""
new = """            withContext(Dispatchers.IO) {
                // Important : le focus ne choisit jamais une autre station.
                // La référence ne peut changer que depuis l'écran de choix explicite.
                val reference = referenceForOperation
                FabOperationRegistry.ensureNotCancelled(operationId)
                FabOperationRegistry.update(operationId, "${reference.label} · météo récente…")

                if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
                    if (credentials.hasCredential()) {
                        runCatching { meteoOfficial.syncSixMinute24h() }
                    } else {
                        runCatching { lyonWeather.syncToday() }
                    }
                }

                FabOperationRegistry.ensureNotCancelled(operationId)
                val dominanceNow = System.currentTimeMillis()
                val recentFrom = dominanceNow - 48L * 60L * 60L * 1000L
                val recentTo = dominanceNow + 12L * 60L * 60L * 1000L
                FabOperationRegistry.update(operationId, "${reference.label} · cohérence récente…")
                // v0.21.2 : jamais de réparation historique globale au focus.
                PointSourceStore.reconcileMeasuredDominance(db, recentFrom, recentTo)

                FabOperationRegistry.ensureNotCancelled(operationId)
                FabOperationRegistry.update(operationId, "${reference.label} · référence récente…")
                manager.refreshRecent(reference)
                FabOperationRegistry.ensureNotCancelled(operationId)

                FabOperationRegistry.update(operationId, "${reference.label} · prévision / cohérence…")
                val profile = profileStore.load()
                val mode = profileStore.forecastMode()
                val selectedSensorId = modelPrefs.getLong("selected_sensor_id", -1L).takeIf { it >= 0L }

                // v0.19.8+ : seul le modèle explicitement entraîné et persisté peut servir au live.
                // Une nouvelle mesure ne le remplace pas et aucun historique n'est recalculé ici.
                val trainedModel = trainedModelStore.loadUsable(reference.key, selectedSensorId)
                if (trainedModel != null) {
                    FabOperationRegistry.ensureNotCancelled(operationId)
                    engine.refreshForecasts(
                        reference, trainedModel.sensorId, profile, mode,
                        precalibratedModel = trainedModel
                    )
                    FabOperationRegistry.ensureNotCancelled(operationId)
                }
            }
"""
t = replace_once(t, old, new, "bounded live update")

t = replace_once(
    t,
    """        } catch (cancel: CancellationException) {
            FabOperationRegistry.cancelled(operationId, "Routine remplacée / composition quittée")
            throw cancel
""",
    """        } catch (cancel: CancellationException) {
            val userRequested = FabOperationRegistry.cancelRequested(operationId)
            FabOperationRegistry.cancelled(
                operationId,
                if (userRequested) "Mise à jour automatique arrêtée" else "Routine remplacée / composition quittée"
            )
            // Un clic utilisateur termine seulement CE passage. Une vraie annulation du
            // LaunchedEffect (composition/lifecycle) doit continuer à se propager.
            if (!userRequested || !currentCoroutineContext().isActive) throw cancel
            false
""",
    "live cancellation catch",
)
p.write_text(t, encoding="utf-8")


# ---------------------------------------------------------------------------
# MainActivity: serialize reloads, expose a real cancel button, add checkpoints
# and stage-level diagnostics. The existing v0.21.1 true LOD cascade is preserved.
# ---------------------------------------------------------------------------
p = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
t = p.read_text(encoding="utf-8")

t = replace_once(
    t,
    "import kotlinx.coroutines.Dispatchers\nimport kotlinx.coroutines.delay\nimport kotlinx.coroutines.launch\nimport kotlinx.coroutines.withContext\n",
    "import kotlinx.coroutines.CancellationException\nimport kotlinx.coroutines.Dispatchers\nimport kotlinx.coroutines.delay\nimport kotlinx.coroutines.launch\nimport kotlinx.coroutines.sync.Mutex\nimport kotlinx.coroutines.sync.withLock\nimport kotlinx.coroutines.withContext\n",
    "main cancellation imports",
)

t = replace_once(
    t,
    "    val scope = rememberCoroutineScope()\n    val snackbar = remember { SnackbarHostState() }\n",
    "    val scope = rememberCoroutineScope()\n    val reloadMutex = remember { Mutex() }\n    val snackbar = remember { SnackbarHostState() }\n",
    "reload mutex state",
)

t = replace_once(
    t,
    """    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {
        val reloadStarted = System.currentTimeMillis()
        val reloadOperation = FabOperationRegistry.tryStart(
            "ui-reload", "Actualisation affichage", "Lecture des courbes…", cancellable = false
        )
        try {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            val s = db.sensors()
""",
    """    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {
        reloadMutex.withLock {
        val reloadStarted = System.currentTimeMillis()
        val reloadOperation = FabOperationRegistry.tryStart(
            "ui-reload", "Actualisation affichage", "Lecture des courbes…", cancellable = true
        )
        var reloadSucceeded = false
        try {
        busy = true
        val loaded = withContext(Dispatchers.IO) {
            FabOperationRegistry.ensureNotCancelled(reloadOperation)
            FabOperationRegistry.update(reloadOperation, "Capteurs & bornes…")
            val s = db.sensors()
            FabOperationRegistry.ensureNotCancelled(reloadOperation)
""",
    "serialized cancellable ui reload",
)

t = replace_once(
    t,
    """            val allNotes = db.annotationsAll()
            if (chosen == null || all == null) {
""",
    """            FabOperationRegistry.ensureNotCancelled(reloadOperation)
            FabOperationRegistry.update(reloadOperation, "Annotations & fenêtre…")
            val allNotes = db.annotationsAll()
            FabOperationRegistry.ensureNotCancelled(reloadOperation)
            if (chosen == null || all == null) {
""",
    "ui annotations checkpoint",
)

t = replace_once(
    t,
    "                val samples = s.associate { sensor ->\n",
    """                val samples = s.mapIndexed { sensorIndex, sensor ->
                    FabOperationRegistry.ensureNotCancelled(reloadOperation)
                    FabOperationRegistry.update(
                        reloadOperation,
                        "Détail RAW · ${sensorIndex + 1}/${s.size}",
                        sensorIndex + 1,
                        s.size
                    )
""",
    "ui raw progress start",
)

t = replace_once(
    t,
    """                    sensor.id to value
                }
                // v0.10.3 : cette couche EST la série météo effectivement consommée par le RC.
""",
    """                    sensor.id to value
                }.toMap()
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                // v0.10.3 : cette couche EST la série météo effectivement consommée par le RC.
""",
    "ui raw progress end",
)

t = replace_once(
    t,
    """                fun physicalLod(bucketMs: Long, range: LongRange): Map<Long, List<SamplePoint>> =
                    s.associate { sensor ->
                        sensor.id to db.querySamplesLod(sensor.id, range.first, range.last, bucketMs)
                    }
""",
    """                fun physicalLod(bucketMs: Long, range: LongRange): Map<Long, List<SamplePoint>> =
                    s.associate { sensor ->
                        FabOperationRegistry.ensureNotCancelled(reloadOperation)
                        sensor.id to db.querySamplesLod(sensor.id, range.first, range.last, bucketMs)
                    }
""",
    "ui lod checkpoints",
)

t = replace_once(
    t,
    """                val gigaOverview = physicalLod(OVERVIEW_LOD_MONTH_MS, all) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_MONTH_MS, all))
                val navigatorOverview = physicalLod(OVERVIEW_LOD_DAY_MS, navigatorScope) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS, navigatorScope))
                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS, explorationScope) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS, explorationScope))
""",
    """                FabOperationRegistry.update(reloadOperation, "Global · LOD mois…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val gigaOverview = physicalLod(OVERVIEW_LOD_MONTH_MS, all) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_MONTH_MS, all))

                FabOperationRegistry.update(reloadOperation, "Zoom large · LOD jour…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val navigatorOverview = physicalLod(OVERVIEW_LOD_DAY_MS, navigatorScope) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_DAY_MS, navigatorScope))

                FabOperationRegistry.update(reloadOperation, "Sélection · LOD 6 h…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val explorationOverview = physicalLod(OVERVIEW_LOD_6H_MS, explorationScope) +
                    (LYON_RECONSTRUCTED_SENSOR_ID to weatherLod(OVERVIEW_LOD_6H_MS, explorationScope))
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
""",
    "ui lod stage diagnostics",
)

t = replace_once(
    t,
    """                val trainedModel = trainedModelStore.loadUsable(selectedWeatherReference.key, modelSensorId)
                val inertia = trainedModel?.let { model ->
""",
    """                val trainedModel = trainedModelStore.loadUsable(selectedWeatherReference.key, modelSensorId)
                FabOperationRegistry.update(reloadOperation, "Sol inertiel · projection…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val inertia = trainedModel?.let { model ->
""",
    "ui inertia stage",
)

t = replace_once(
    t,
    """                fun withInertiaLod(
                    base: Map<Long, List<SamplePoint>>,
""",
    """                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                fun withInertiaLod(
                    base: Map<Long, List<SamplePoint>>,
""",
    "ui post inertia checkpoint",
)

t = replace_once(
    t,
    """        sensors = loaded.sensors
        globalBounds = loaded.globalBounds
""",
    """        FabOperationRegistry.ensureNotCancelled(reloadOperation)
        sensors = loaded.sensors
        globalBounds = loaded.globalBounds
""",
    "ui apply checkpoint",
)

t = replace_once(
    t,
    """        busy = false
        } finally {
            busy = false
            FabOperationRegistry.finish(
                reloadOperation,
                "Affichage prêt · ${System.currentTimeMillis() - reloadStarted} ms"
            )
        }
    }
""",
    """        busy = false
        reloadSucceeded = true
        } catch (cancel: CancellationException) {
            FabOperationRegistry.cancelled(reloadOperation, "Actualisation affichage annulée")
            throw cancel
        } catch (error: Throwable) {
            FabOperationRegistry.fail(
                reloadOperation,
                error.message ?: "Actualisation affichage impossible"
            )
            throw error
        } finally {
            busy = false
            if (reloadSucceeded) {
                FabOperationRegistry.finish(
                    reloadOperation,
                    "Affichage prêt · ${System.currentTimeMillis() - reloadStarted} ms"
                )
            }
        }
        }
    }
""",
    "ui cancellation finish",
)
p.write_text(t, encoding="utf-8")


# ---------------------------------------------------------------------------
# Version bump.
# ---------------------------------------------------------------------------
p = Path("app/build.gradle.kts")
t = p.read_text(encoding="utf-8")
t = replace_once(t, '        versionCode = 47\n        versionName = "0.21.1"\n',
                 '        versionCode = 48\n        versionName = "0.21.2"\n',
                 "version bump")
p.write_text(t, encoding="utf-8")

print("FabData v0.21.2 cancellation/performance patch applied")
