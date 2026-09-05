from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing expected block in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))

# Version + provenance marker: old reconstructions must be rationalized once.
replace_once(
    "app/build.gradle.kts",
    '        versionCode = 42\n        versionName = "0.19.6"',
    '        versionCode = 43\n        versionName = "0.19.7"'
)
replace_once(
    "app/src/main/java/com/fabdata/app/PointSourceLayer.kt",
    'const val MODEL_VERSION = "thermal-zero-bimass-6"',
    'const val MODEL_VERSION = "thermal-ground-observable-7"'
)

# Inertia estimator: keep the energy-weighted building mass for the engine, but expose
# a distinct surface/ground trace computed only from the MEASURED interval.
inertia = "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt"
replace_once(
    inertia,
    '''data class ThermalInertiaEstimate(\n    val points: List<SamplePoint>,\n    val diagnostics: ThermalInertiaDiagnostics\n) {''',
    '''data class ThermalInertiaEstimate(\n    /** Energy-weighted building mass. Internal engine state: never chart this directly. */\n    val points: List<SamplePoint>,\n    val diagnostics: ThermalInertiaDiagnostics,\n    /** Observable surface / ground equivalent, defined only on the real MEASURED interval. */\n    val surfacePoints: List<SamplePoint> = emptyList()\n) {'''
)
replace_once(
    inertia,
    '''        val points = outputHours.mapIndexed { index, h ->\n            SamplePoint(\n                sensorId = THERMAL_INERTIA_SENSOR_ID,\n                timestamp = h.timestamp,\n                // Keep full latent precision: rounding the state itself can visually erase a small\n                // but physically real tangent change. Labels/diagnostics may still be rounded.\n                temperature = outputMass[index],\n                humidity = h.humidity,\n                source = PointSource.RECONSTRUCTED,\n                confidence = confidence\n            )\n        }\n        if (points.isEmpty()) return null''',
    '''        val points = outputHours.mapIndexed { index, h ->\n            SamplePoint(\n                sensorId = THERMAL_INERTIA_SENSOR_ID,\n                timestamp = h.timestamp,\n                // Hidden building state keeps full precision for the engine.\n                temperature = outputMass[index],\n                humidity = h.humidity,\n                source = PointSource.RECONSTRUCTED,\n                confidence = confidence\n            )\n        }\n        if (points.isEmpty()) return null\n\n        // What we display during the real period is NOT the hidden building mass.\n        // It is the superficial thermal layer (surface / ground equivalent) which is\n        // directly downstream of that mass and of the current forcing. It is deliberately\n        // built from MEASURED hours only, so the visible purple trace stops at the last\n        // real observation instead of leaking the hidden mass into reconstructed history.\n        val realPlateau = masks(hours, manualExclusions).second\n        val surfaceValues = propagateSurfaceDisplay(\n            hours, best.surfaceTauHours, best.deepTauHours, best.outsideWeight, realPlateau\n        )\n        val surfacePoints = hours.mapIndexed { index, h ->\n            SamplePoint(\n                sensorId = THERMAL_INERTIA_SENSOR_ID,\n                timestamp = h.timestamp,\n                temperature = surfaceValues[index],\n                humidity = h.humidity,\n                source = PointSource.RECONSTRUCTED,\n                confidence = confidence\n            )\n        }'''
)
replace_once(
    inertia,
    '''        return ThermalInertiaEstimate(points, diagnostics).also {''',
    '''        return ThermalInertiaEstimate(points, diagnostics, surfacePoints).also {'''
)
replace_once(
    inertia,
    '''    private fun propagateDisplay(\n        hours: List<InertiaHour>,\n        surfaceTauHours: Double,\n        deepTauHours: Double,\n        deepShare: Double,\n        outsideWeight: Double\n    ): DoubleArray = propagateTwoMass(\n        hours = hours,\n        surfaceTauHours = surfaceTauHours,\n        deepTauHours = deepTauHours,\n        deepShare = deepShare,\n        outsideWeight = outsideWeight,\n        plateau = null\n    )\n''',
    '''    private fun propagateDisplay(\n        hours: List<InertiaHour>,\n        surfaceTauHours: Double,\n        deepTauHours: Double,\n        deepShare: Double,\n        outsideWeight: Double\n    ): DoubleArray = propagateTwoMass(\n        hours = hours,\n        surfaceTauHours = surfaceTauHours,\n        deepTauHours = deepTauHours,\n        deepShare = deepShare,\n        outsideWeight = outsideWeight,\n        plateau = null\n    )\n\n    /**\n     * Surface / sol équivalent visible. La profondeur reste totalement cachée : elle\n     * n'intervient ici que comme réservoir qui tire la couche superficielle.\n     */\n    private fun propagateSurfaceDisplay(\n        hours: List<InertiaHour>,\n        surfaceTauHours: Double,\n        deepTauHours: Double,\n        outsideWeight: Double,\n        plateau: BooleanArray?\n    ): DoubleArray {\n        val surfaceValues = DoubleArray(hours.size)\n        if (hours.isEmpty()) return surfaceValues\n        val w = outsideWeight.coerceIn(0.02, 0.45)\n        var surface = forcingValue(hours[0], w)\n        var deep = hours[0].smoothAir * 0.88 + hours[0].outside * 0.12\n        surfaceValues[0] = surface\n\n        for (i in 1 until hours.size) {\n            val dt = ((hours[i].timestamp - hours[i - 1].timestamp).toDouble() / INERTIA_HOUR_MS.toDouble())\n                .coerceIn(0.5, 24.0)\n            val forcing = forcingValue(hours[i - 1], w)\n            val surfaceTarget = 0.82 * forcing + 0.18 * deep\n            val alphaSurface = 1.0 - exp(-dt / surfaceTauHours.coerceAtLeast(6.0))\n            var nextSurface = surface + alphaSurface * (surfaceTarget - surface)\n            if (plateau?.getOrNull(i) == true) {\n                val observationGain = min(0.06, 0.015 * dt)\n                nextSurface += observationGain * (hours[i].smoothAir - nextSurface)\n            }\n            val alphaDeep = 1.0 - exp(-dt / deepTauHours.coerceAtLeast(surfaceTauHours * 2.5))\n            val nextDeep = deep + alphaDeep * (nextSurface - deep)\n            surface = nextSurface.coerceIn(-5.0, 50.0)\n            deep = nextDeep.coerceIn(-5.0, 50.0)\n            surfaceValues[i] = surface\n        }\n        return surfaceValues\n    }\n'''
)

# Main chart: restore a real-period-only surface/ground line. Never expose points (hidden mass).
main = "app/src/main/java/com/fabdata/app/MainActivity.kt"
replace_once(
    main,
    '''        // v0.19.6: la masse thermique du bâtiment reste un état caché du modèle.\n        // La courbe reconstruite de la sonde représente la surface/sol équivalent ;\n        // on ne superpose donc plus l'état profond sur le graphe principal.\n        showTemp[THERMAL_INERTIA_SENSOR_ID] = false\n        showHumidity[THERMAL_INERTIA_SENSOR_ID] = false''',
    '''        // v0.19.7: on montre la surface/sol inertiel sur la période MEASURED uniquement.\n        // La masse énergétique profonde reste cachée et n'est jamais branchée au graphe.\n        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true\n        showHumidity[THERMAL_INERTIA_SENSOR_ID] = false'''
)
replace_once(
    main,
    '''    // Les deux pseudo-capteurs météo sont uniquement des vues de la référence sélectionnée.\n    // Aucun doublon n'est persisté et les anciennes clés internes restent compatibles.\n    // v0.19.6 : ThermalInertiaEstimate reste consommé par le moteur thermique mais n'est\n    // plus exposé comme pseudo-capteur. La masse bâtiment sera réservée à une future vue Topo.\n    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }\n    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor\n    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +\n        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples)\n    val overviewReference = overviewSampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()\n    val chartOverviewSampleMap = overviewSampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (WEATHER_OFFICIAL_SENSOR_ID to overviewReference.filter { it.source == PointSource.MEASURED }.map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +\n        (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference.filter { it.source == PointSource.RECONSTRUCTED })''',
    '''    // Les deux pseudo-capteurs météo sont uniquement des vues de la référence sélectionnée.\n    // Aucun doublon n'est persisté et les anciennes clés internes restent compatibles.\n    // v0.19.7 : seule la couche superficielle/sol issue des heures MEASURED est visible.\n    // inertiaEstimate.points reste la masse bâtiment cachée et n'entre jamais ici.\n    val inertiaVisible = viewBounds?.let { b ->\n        inertiaEstimate?.surfacePoints?.filter { it.timestamp in b }.orEmpty()\n    }.orEmpty()\n    val inertiaOverview = globalBounds?.let { b ->\n        inertiaEstimate?.surfacePoints?.filter { it.timestamp in b }.orEmpty().let { selected ->\n            if (selected.size <= 1200) selected else {\n                val step = ((selected.size + 1199) / 1200).coerceAtLeast(1)\n                selected.filterIndexed { index, _ -> index % step == 0 }\n            }\n        }\n    }.orEmpty()\n    val inertiaSensor = Sensor(\n        id = THERMAL_INERTIA_SENSOR_ID,\n        stableKey = THERMAL_INERTIA_STABLE_KEY,\n        name = "Sol inertiel estimé",\n        room = "Surface / sol équivalent · réel",\n        colorIndex = 4,\n        latestTimestamp = inertiaEstimate?.surfacePoints?.lastOrNull()?.timestamp\n    )\n    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }\n    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + inertiaSensor\n    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +\n        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)\n    val overviewReference = overviewSampleMap[LYON_RECONSTRUCTED_SENSOR_ID].orEmpty()\n    val chartOverviewSampleMap = overviewSampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +\n        (WEATHER_OFFICIAL_SENSOR_ID to overviewReference.filter { it.source == PointSource.MEASURED }.map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +\n        (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference.filter { it.source == PointSource.RECONSTRUCTED }) +\n        (THERMAL_INERTIA_SENSOR_ID to inertiaOverview)'''
)

# Reconstruction: observable ground is derived from hidden mass at the SAME timestamp.
# The learned lag belongs to the outside->ground projection only; hidden building mass
# continues to use the actual current forcing, never the lagged outside series.
engine = "app/src/main/java/com/fabdata/app/ThermalEngine.kt"
start = Path(engine).read_text()
old_a = start.index("    private fun reconstructBeforeFirst(")
old_b = start.index("    private fun fillInteriorGapsForward(", old_a)
new_before = r'''    private fun reconstructBeforeFirst(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        first: HourPoint,
        startAt: Long,
        outside: Map<Long, HourPoint>,
        profile: ThermalBuildingProfile,
        inertia: ThermalInertiaEstimate,
        fingerprint: ThermalDependencyFingerprint,
        progress: ((ThermalProgress) -> Unit)? = null
    ): ForwardFillSummary {
        val start = hourBucket(startAt)
        val firstHour = hourBucket(first.timestamp)
        if (start >= firstHour) return ForwardFillSummary(diagnostic = "Période historique vide.")

        // La masse bâtiment est l'état caché. On ne cherche plus une température de sonde
        // initiale artificielle pour la faire raccorder au réel : le sol visible découle
        // directement de cette masse et du transfert extérieur appris.
        var currentMass = initialMassTemperature(profile, start, firstHour, outside)
            ?: return ForwardFillSummary(diagnostic = "Impossible d'initialiser la masse thermique cachée avec ${reference.city}.")
        var currentH = outside[hourBucket(start)]?.humidity ?: first.humidity
        var currentGround = projectObservableGround(model, currentMass, outside, start, profile)
            ?: return ForwardFillSummary(diagnostic = "Impossible de projeter le sol équivalent au début de la période.")
        var ts = start
        var stopDiagnostic: String? = null
        val writes = ArrayList<PriorityPointWrite>(((firstHour - start) / THERMAL_HOUR_MS).toInt().coerceAtLeast(0))

        while (ts < firstHour) {
            val projected = projectObservableGround(model, currentMass, outside, ts, profile)
            if (projected == null || !plausibleIndoor(projected)) {
                stopDiagnostic = "Propagation arrêtée : projection sol impossible vers ${Instant.ofEpochMilli(ts).atZone(zone).toLocalDateTime()}."
                break
            }
            currentGround = projected
            val horizonDays = (first.timestamp - ts).toDouble() / THERMAL_DAY_MS.toDouble()
            val confidence = (model.confidence * (1.0 - 0.0065 * horizonDays)).coerceIn(0.20, model.confidence)
            writes += PriorityPointWrite(
                sensor.id, ts, round2(currentGround), round2(currentH.coerceIn(0.0, 100.0)),
                provenance(model, reference, PointSource.RECONSTRUCTED, confidence, fingerprint)
            )

            // La masse cachée évolue avec le forçage physique ACTUEL. Le lag appris ne
            // s'applique qu'à la projection du sol observable.
            val massOutside = outsideAverage(outside, ts, 6)
                ?: outsideAt(outside, ts)
                ?: run {
                    stopDiagnostic = "Propagation arrêtée : météo extérieure absente vers ${Instant.ofEpochMilli(ts).atZone(zone).toLocalDateTime()}."
                    break
                }
            currentMass = advanceInertiaMass(inertia.diagnostics, currentGround, currentMass, massOutside)
            val outHum = outside[hourBucket(ts)]?.humidity ?: currentH
            currentH += 0.08 * (outHum - currentH)
            ts += THERMAL_HOUR_MS
        }

        val created = PointSourceStore.upsertBatchByPriority(db, writes, 256) { processed, changed ->
            progress?.invoke(ThermalProgress("Écriture sol reconstruit · ${sensor.room}", processed, writes.size, changed))
        }
        if (stopDiagnostic != null) return ForwardFillSummary(created, 0, 0.0, stopDiagnostic)

        val projectedAtFirst = projectObservableGround(model, currentMass, outside, firstHour, profile)
        val drift = projectedAtFirst?.let { abs(it - first.temperature) } ?: 0.0
        return ForwardFillSummary(
            created, if (projectedAtFirst != null) 1 else 0, drift,
            "Sol reconstruit depuis masse bâtiment cachée · τ ${round2(inertia.diagnostics.tauHours)} h · lag ${model.lagHours} h"
        )
    }

    private fun projectObservableGround(
        model: ThermalModel,
        hiddenMass: Double,
        outside: Map<Long, HourPoint>,
        timestamp: Long,
        profile: ThermalBuildingProfile
    ): Double? {
        val extTs = timestamp - model.lagHours * THERMAL_HOUR_MS
        val tout = outsideAt(outside, extTs) ?: return null
        val avg6 = outsideAverage(outside, extTs, 6) ?: tout
        val hour = Instant.ofEpochMilli(timestamp).atZone(zone).hour
        val deltaFromMass = massAwareDelta(
            model.coefficients,
            hiddenMass,
            hiddenMass,
            tout,
            avg6,
            hour,
            profile
        )
        val ground = hiddenMass + deltaFromMass
        return ground.takeIf { plausibleIndoor(it) }
    }

'''
Path(engine).write_text(start[:old_a] + new_before + start[old_b:])

text = Path(engine).read_text()
old_a = text.index("    private fun fillInteriorGapsForward(")
old_b = text.index("    private fun validateLongHorizon(", old_a)
new_gaps = r'''    private fun fillInteriorGapsForward(
        sensor: Sensor,
        model: ThermalModel,
        reference: WeatherReference,
        profile: ThermalBuildingProfile,
        inertia: ThermalInertiaEstimate,
        fingerprint: ThermalDependencyFingerprint,
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
            var currentH = left.humidity
            var currentMass = inertia.points
                .minByOrNull { abs(it.timestamp - left.timestamp) }
                ?.takeIf { abs(it.timestamp - left.timestamp) <= 3L * THERMAL_HOUR_MS }
                ?.temperature ?: left.temperature
            var currentGround = projectObservableGround(model, currentMass, outMap, hourBucket(left.timestamp), profile)
                ?: left.temperature
            var completed = true

            for (step in 1 until gapHours) {
                val previousTs = hourBucket(left.timestamp) + (step - 1) * THERMAL_HOUR_MS
                val ts = previousTs + THERMAL_HOUR_MS

                // First advance ONLY the hidden building state with current physical forcing.
                val massOutside = outsideAverage(outMap, previousTs, 6)
                    ?: outsideAt(outMap, previousTs)
                if (massOutside == null) {
                    completed = false
                    break
                }
                currentMass = advanceInertiaMass(
                    inertia.diagnostics, currentGround, currentMass, massOutside
                )

                // Then derive the observable ground at its own timestamp. This removes the
                // accidental extra +1 h phase shift that existed in v0.19.5/v0.19.6.
                val predicted = projectObservableGround(model, currentMass, outMap, ts, profile)
                if (predicted == null || !plausibleIndoor(predicted)) {
                    completed = false
                    break
                }
                currentGround = predicted
                val outHum = outMap[hourBucket(ts)]?.humidity ?: currentH
                currentH += 0.08 * (outHum - currentH)
                val confidence = (model.confidence * 0.82).coerceIn(0.20, 0.85)
                writes += PriorityPointWrite(
                    sensor.id, ts, round2(currentGround), round2(currentH.coerceIn(0.0, 100.0)),
                    provenance(model, reference, PointSource.RECONSTRUCTED, confidence, fingerprint)
                )
            }

            if (completed) {
                val previousTs = hourBucket(right.timestamp) - THERMAL_HOUR_MS
                val massOutside = outsideAverage(outMap, previousTs, 6)
                    ?: outsideAt(outMap, previousTs)
                if (massOutside != null) {
                    val massAtRight = advanceInertiaMass(
                        inertia.diagnostics, currentGround, currentMass, massOutside
                    )
                    val projectedAtRight = projectObservableGround(
                        model, massAtRight, outMap, hourBucket(right.timestamp), profile
                    )
                    if (projectedAtRight != null && plausibleIndoor(projectedAtRight)) {
                        raccords++
                        maxDrift = max(maxDrift, abs(projectedAtRight - right.temperature))
                    }
                }
            }
        }

        val created = PointSourceStore.upsertBatchByPriority(db, writes, 256) { processed, changed ->
            progress?.invoke(ThermalProgress("Comblement sol reconstruit · ${sensor.room}", processed, writes.size, changed))
        }
        return ForwardFillSummary(created, raccords, maxDrift)
    }

'''
Path(engine).write_text(text[:old_a] + new_gaps + text[old_b:])

# UI wording: visible purple line is ground/surface, hidden building remains diagnostic only.
ui = "app/src/main/java/com/fabdata/app/ThermalExperimentUi.kt"
replace_once(
    ui,
    '"La courbe reconstruite visible représente la surface / le sol équivalent. La masse thermique du bâtiment reste un état caché appris uniquement sur les points MEASURED propres ; elle sert au calcul mais n’est plus tracée sur le graphe principal."',
    '"Sur les données réelles, la courbe Sol inertiel estimé montre la couche superficielle. Hors réel, FabData reconstruit cette même grandeur à partir de la masse thermique cachée du bâtiment et du transfert extérieur appris. La masse profonde reste diagnostic interne."'
)

print("v0.19.7 ground-observable reconstruction patch applied")
