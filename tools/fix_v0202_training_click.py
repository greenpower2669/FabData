from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


def main():
    # --- ThermalEngine: apply the user's inertia policy BEFORE deciding which
    # weather span/calibration inventory is required. This is important when an
    # EXCLUSIVE window is intentionally chosen while unrelated historical weather
    # outside that window is incomplete.
    engine = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt')
    t = engine.read_text()

    old = '''        val measured = measuredHourly(sensor.id)
        val realDays = distinctDays(measured)
        require(realDays >= MIN_REAL_DAYS) { "Moins de 16 jours réels exploitables" }
        require(measured.size >= 180) { "Pas assez de points horaires réels" }

        val from = measured.first().timestamp - 18L * THERMAL_HOUR_MS
        val to = measured.last().timestamp
        val outside = referenceHourly(reference.key, from, to, includeForecast = false)
        require(outside.size >= 120) { "Référence météo extérieure insuffisante" }
        require(referenceCoverageReady(outside, from, to)) {
            "Référence météo extérieure incomplète : reconstruire/compléter ${reference.city} avant de calibrer le bâtiment"
        }
        val outMap = outside.associateBy { hourBucket(it.timestamp) }
        val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)
            ?: error("Température inertielle estimée indisponible pour ${sensor.room}")
        val inertiaMap = inertia.points.associateBy { hourBucket(it.timestamp) }
        val medianDeltas = buildingMedianDeltaByHour(measured.first().timestamp, measured.last().timestamp)

        // User selections are training masks, never data deletion. Legacy inertia
        // exclusions stay valid; v0.20.1 adds a positive EXCLUSIVE whitelist per engine.
        val legacyTrainingExclusions = ThermalTrainingMaskStore(db).query(
            sensor.id, measured.first().timestamp, measured.last().timestamp
        )
        val inertiaPolicy = trainingPolicyStore.ranges(ThermalTrainingTarget.INERTIA)
        fun trainingTimestampAccepted(timestamp: Long): Boolean {
            if (legacyTrainingExclusions.any { it.contains(timestamp) }) return false
            if (inertiaPolicy.any { it.mode == ThermalTrainingRangeMode.EXCLUDE && it.contains(timestamp) }) return false
            val exclusive = inertiaPolicy.filter { it.mode == ThermalTrainingRangeMode.EXCLUSIVE && it.enabled }
            return exclusive.isEmpty() || exclusive.any { it.contains(timestamp) }
        }
'''
    new = '''        val measured = measuredHourly(sensor.id)
        require(measured.size >= 2) { "Pas assez de mesures réelles" }

        // Resolve the user's training policy first. The selected policy controls the
        // calibration inventory AND the weather span required for training. Data outside
        // the policy remain in the database and can still be used later for propagation.
        val legacyTrainingExclusions = ThermalTrainingMaskStore(db).query(
            sensor.id, measured.first().timestamp, measured.last().timestamp
        )
        val inertiaPolicy = trainingPolicyStore.ranges(ThermalTrainingTarget.INERTIA)
        fun trainingTimestampAccepted(timestamp: Long): Boolean {
            if (legacyTrainingExclusions.any { it.contains(timestamp) }) return false
            if (inertiaPolicy.any { it.mode == ThermalTrainingRangeMode.EXCLUDE && it.contains(timestamp) }) return false
            val exclusive = inertiaPolicy.filter { it.mode == ThermalTrainingRangeMode.EXCLUSIVE && it.enabled }
            return exclusive.isEmpty() || exclusive.any { it.contains(timestamp) }
        }

        val acceptedMeasured = measured.filter { trainingTimestampAccepted(it.timestamp) }
        val realDays = distinctDays(acceptedMeasured)
        require(realDays >= MIN_REAL_DAYS) {
            "Sélection inertielle trop courte : $realDays jour(s) réel(s) retenu(s), minimum $MIN_REAL_DAYS jours"
        }
        require(acceptedMeasured.size >= 180) {
            "Sélection inertielle insuffisante : ${acceptedMeasured.size} point(s) horaires retenus, minimum 180"
        }

        val selectedFrom = acceptedMeasured.first().timestamp
        val selectedTo = acceptedMeasured.last().timestamp
        val from = selectedFrom - 18L * THERMAL_HOUR_MS
        val to = selectedTo
        val outside = referenceHourly(reference.key, from, to, includeForecast = false)
        require(outside.size >= 120) { "Référence météo extérieure insuffisante sur la sélection" }
        require(referenceCoverageReady(outside, from, to)) {
            "Référence météo extérieure incomplète sur la sélection : actualiser ${reference.city} puis réessayer"
        }
        val outMap = outside.associateBy { hourBucket(it.timestamp) }
        val inertia = inertiaEstimator.estimate(reference, sensor.id, includeHistory = false)
            ?: error("Température inertielle estimée indisponible pour ${sensor.room} sur la sélection")
        val inertiaMap = inertia.points.associateBy { hourBucket(it.timestamp) }
        val medianDeltas = buildingMedianDeltaByHour(selectedFrom, selectedTo)
'''
    t = replace_once(t, old, new, 'calibrate policy/weather ordering')

    t = replace_once(
        t,
        '        var best: ThermalModel? = null\n        for (lag in 0..12) {\n',
        '        var best: ThermalModel? = null\n        var maxUsableRows = 0\n        for (lag in 0..12) {\n',
        'max usable rows declaration'
    )
    t = replace_once(
        t,
        '''            val rows = buildTrainingRows(measured, outMap, inertiaMap, medianDeltas, lag)
                .filter { trainingTimestampAccepted(it.timestamp) }
            if (rows.size < 120) continue
''',
        '''            val rows = buildTrainingRows(measured, outMap, inertiaMap, medianDeltas, lag)
                .filter { trainingTimestampAccepted(it.timestamp) }
            maxUsableRows = maxOf(maxUsableRows, rows.size)
            if (rows.size < 120) continue
''',
        'usable row counter'
    )
    t = replace_once(
        t,
        '        return best ?: error("Aucun facteur de projection inertielle stable n\'a passé la calibration")\n',
        '''        return best ?: if (maxUsableRows < 120) {
            error("Sélection inertielle trop courte après garde-fous : $maxUsableRows h utilisables, minimum 120 h")
        } else {
            error("Aucun facteur de projection inertielle stable n'a passé la calibration sur la sélection")
        }
''',
        'calibration failure detail'
    )
    engine.write_text(t)

    # --- Thermal UI: the tap did run, but failures were written into Text(info) far
    # above the training button. Put progress/success/failure directly under the button
    # so a failed training can never look like a dead button.
    ui = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')
    t = ui.read_text()
    t = replace_once(
        t,
        '    var info by remember { mutableStateOf("État thermique prêt") }\n',
        '    var info by remember { mutableStateOf("État thermique prêt") }\n    var trainingFeedback by remember { mutableStateOf<String?>(null) }\n',
        'training feedback state'
    )
    t = replace_once(
        t,
        '''        busy = true
        info = "Entraînement du modèle · préparation des mesures réelles…"
''',
        '''        busy = true
        trainingFeedback = "⏳ Entraînement en cours…"
        info = "Entraînement du modèle · préparation des mesures réelles…"
''',
        'training started feedback'
    )
    t = replace_once(
        t,
        '''            onSuccess = { model ->
                trainedModel = model
''',
        '''            onSuccess = { model ->
                trainingFeedback = "✓ Modèle entraîné · ${model.usablePoints} h utilisées · ${model.realDays} j"
                trainedModel = model
''',
        'training success feedback'
    )
    t = replace_once(
        t,
        '''            onFailure = { error ->
                info = error.message ?: "Entraînement impossible"
            }
''',
        '''            onFailure = { error ->
                val message = error.message ?: "Entraînement impossible"
                info = message
                trainingFeedback = "⚠ $message"
            }
''',
        'training failure feedback'
    )
    feedback_anchor = '''            OutlinedButton(
                onClick = { inertiaHistoryDialog = true },
'''
    feedback_block = '''            trainingFeedback?.let { feedback ->
                Text(
                    feedback,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (feedback.startsWith("✓")) MaterialTheme.colorScheme.primary
                    else if (feedback.startsWith("⚠")) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.onSurfaceVariant
                )
            }

''' + feedback_anchor
    t = replace_once(t, feedback_anchor, feedback_block, 'inline training feedback')
    ui.write_text(t)

    print('v0.20.2 training feedback + selected-range calibration patch applied')


if __name__ == '__main__':
    main()
