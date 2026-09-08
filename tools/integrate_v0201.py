from pathlib import Path


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f'{label}: anchor missing')
    return text.replace(old, new, 1)


def main():
    # DB v6: engine-specific training policy table. Migration is additive only.
    data = Path('app/src/main/java/com/fabdata/app/DataLayer.kt')
    t = data.read_text()
    t = t.replace('SQLiteOpenHelper(context, "fabdata.db", null, 5)', 'SQLiteOpenHelper(context, "fabdata.db", null, 6)')
    create_anchor = '        ThermalWallSolarModelStore.ensure(db)\n'
    if 'ThermalTrainingPolicyStore.ensure(db)' not in t:
        t = replace_once(
            t, create_anchor,
            create_anchor + '        ThermalTrainingPolicyStore.ensure(db)\n',
            'DataLayer onCreate policy'
        )
    upgrade_anchor = '''        if (oldVersion < 5) {
            // v0.20 : rôles de sondes + pans de mur + modèles solaires, migration additive uniquement.
            ThermalWallConfigStore.ensure(db)
            ThermalWallSolarModelStore.ensure(db)
        }
'''
    upgrade_new = upgrade_anchor + '''        if (oldVersion < 6) {
            // v0.20.1 : sélections d’apprentissage séparées inertie / solaire.
            ThermalTrainingPolicyStore.ensure(db)
        }
'''
    if 'if (oldVersion < 6)' not in t:
        t = replace_once(t, upgrade_anchor, upgrade_new, 'DataLayer onUpgrade v6')
    data.write_text(t)

    # Main thermal model: selections now really gate BOTH fit and validation rows.
    engine = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt')
    t = engine.read_text()
    field_anchor = '    private val wallConfigStore = ThermalWallConfigStore(db)\n'
    if 'private val trainingPolicyStore = ThermalTrainingPolicyStore(db)' not in t:
        t = replace_once(
            t, field_anchor,
            field_anchor + '    private val trainingPolicyStore = ThermalTrainingPolicyStore(db)\n',
            'ThermalEngine policy field'
        )
    best_anchor = '        var best: ThermalModel? = null\n'
    policy_block = '''        // User selections are training masks, never data deletion. Legacy inertia
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

        var best: ThermalModel? = null
'''
    if 'fun trainingTimestampAccepted(timestamp: Long)' not in t:
        t = replace_once(t, best_anchor, policy_block, 'ThermalEngine policy block')
    old_rows = '            val rows = buildTrainingRows(measured, outMap, inertiaMap, medianDeltas, lag)\n'
    new_rows = '''            val rows = buildTrainingRows(measured, outMap, inertiaMap, medianDeltas, lag)
                .filter { trainingTimestampAccepted(it.timestamp) }
'''
    if new_rows not in t:
        t = replace_once(t, old_rows, new_rows, 'ThermalEngine row filter')
    engine.write_text(t)

    # Bi-mass estimator: same policy, but converted to exclusions so latent state
    # continues propagating through ignored periods.
    inertia = Path('app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt')
    t = inertia.read_text()
    field_anchor = '    private val wallConfigStore = ThermalWallConfigStore(db)\n'
    if 'private val trainingPolicyStore = ThermalTrainingPolicyStore(db)' not in t:
        t = replace_once(
            t, field_anchor,
            field_anchor + '    private val trainingPolicyStore = ThermalTrainingPolicyStore(db)\n',
            'Inertia policy field'
        )
    old_key = '        val trainingMaskSignature = trainingMaskStore.signature(sensorId)\n        val key = "$measuredRevision|${reference.key}|$weatherSignature|${sensorId ?: -1L}|$includeHistory|$trainingMaskSignature"\n'
    new_key = '''        val trainingMaskSignature = trainingMaskStore.signature(sensorId)
        val trainingPolicySignature = trainingPolicyStore.signature(ThermalTrainingTarget.INERTIA)
        val key = "$measuredRevision|${reference.key}|$weatherSignature|${sensorId ?: -1L}|$includeHistory|$trainingMaskSignature|$trainingPolicySignature"
'''
    if new_key not in t:
        t = replace_once(t, old_key, new_key, 'Inertia cache policy signature')
    old_manual = '        val manualExclusions = trainingMaskStore.query(sensor.id, from, to)\n        val best = search(hours, manualExclusions) ?: fallback(hours, manualExclusions)\n'
    new_manual = '''        val manualExclusions = trainingMaskStore.query(sensor.id, from, to) +
            trainingPolicyStore.asExclusions(ThermalTrainingTarget.INERTIA, from, to, sensor.id)
        val best = search(hours, manualExclusions) ?: fallback(hours, manualExclusions)
'''
    if new_manual not in t:
        t = replace_once(t, old_manual, new_manual, 'Inertia policy exclusions')
    old_project = '        val exclusions = ThermalTrainingMaskStore(db).query(model.sensorId, from, to)\n'
    new_project = '''        val exclusions = ThermalTrainingMaskStore(db).query(model.sensorId, from, to) +
            trainingPolicyStore.asExclusions(ThermalTrainingTarget.INERTIA, from, to, model.sensorId)
'''
    if new_project not in t:
        t = replace_once(t, old_project, new_project, 'Inertia projected policy')
    inertia.write_text(t)

    # Solar facade trainer uses its own independent time policy.
    solar = Path('app/src/main/java/com/fabdata/app/ThermalWallSolarService.kt')
    t = solar.read_text()
    field_anchor = '    private val trainer = ThermalWallSolarTrainer()\n'
    if 'private val trainingPolicyStore = ThermalTrainingPolicyStore(db)' not in t:
        t = replace_once(
            t, field_anchor,
            field_anchor + '    private val trainingPolicyStore = ThermalTrainingPolicyStore(db)\n',
            'Solar policy field'
        )
    old_measured = '        val measured = measuredPoints(sensor.id)\n        require(measured.size >= 6) { "Au moins 6 heures réelles sont nécessaires" }\n'
    new_measured = '''        val measured = measuredPoints(sensor.id)
            .filter { trainingPolicyStore.accepts(ThermalTrainingTarget.SOLAR, it.timestamp) }
        require(measured.size >= 6) { "Au moins 6 heures réelles sélectionnées sont nécessaires" }
'''
    if new_measured not in t:
        t = replace_once(t, old_measured, new_measured, 'Solar measured policy')
    solar.write_text(t)

    # Backup v3: one real backup restores data + exact weather + model + topology + selections.
    backup = Path('app/src/main/java/com/fabdata/app/BackupLayer.kt')
    t = backup.read_text()
    t = t.replace('const val FORMAT_VERSION = "2"', 'const val FORMAT_VERSION = "3"')
    t = t.replace('formatVersion !in setOf("1", FORMAT_VERSION)', 'formatVersion !in setOf("1", "2", FORMAT_VERSION)')
    records_anchor = '            val records = splitCsvRecords(reader.readText())\n'
    if 'val v3Support = FabDataBackupV3Support(context, db)' not in t:
        t = replace_once(
            t, records_anchor,
            records_anchor + '            val v3Support = FabDataBackupV3Support(context, db)\n',
            'Backup v3 import support'
        )
    old_else = '                            else -> invalid++\n'
    new_else = '''                            else -> {
                                val rowMap = header.mapIndexed { i, name ->
                                    name.trim() to fields.getOrNull(i).orEmpty()
                                }.toMap()
                                if (!v3Support.importRecord(record, rowMap)) invalid++
                            }
'''
    if new_else not in t:
        t = replace_once(t, old_else, new_else, 'Backup v3 record fallback')
    export_close = '        }\n\n        return FabDataBackupExportResult(sensorCount, measurementCount, eventCount)\n'
    export_new = '''            // v3 state is appended after the ordinary human-readable records.
            FabDataBackupV3Support(context, db).writeExtraRows(writer)
        }

        return FabDataBackupExportResult(sensorCount, measurementCount, eventCount)
'''
    if 'writeExtraRows(writer)' not in t:
        # use the last matching writer close before the export return
        pos = t.rfind(export_close)
        if pos < 0:
            raise SystemExit('Backup export close anchor missing')
        t = t[:pos] + export_new + t[pos + len(export_close):]
    backup.write_text(t)

    # Global selection menu: keep old inertia actions, add solar and the requested
    # third "exclusive" choice, with explicit engine target.
    main = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
    t = main.read_text()
    # One save/export entry only: the top toolbar backup is now the canonical v3 backup.
    t = t.replace('''                item {
                    SourceAwareExportCard(db)
                }

''', '')
    signature_old = '''    onUseForInertia: (LongRange) -> Unit,
    onExcludeFromInertia: (LongRange) -> Unit,
    onZoomRange: (LongRange) -> Unit
'''
    signature_new = '''    onUseForInertia: (LongRange) -> Unit,
    onExcludeFromInertia: (LongRange) -> Unit,
    onTrainingPolicy: (LongRange, ThermalTrainingTarget, ThermalTrainingRangeMode) -> Unit,
    onZoomRange: (LongRange) -> Unit
'''
    if signature_new not in t:
        if signature_old not in t:
            raise SystemExit('MainActivity overview signature anchor missing')
        t = t.replace(signature_old, signature_new)

    call_anchor = '                        onZoomRange = { range ->\n'
    policy_call = '''                        onTrainingPolicy = { range, target, mode ->
                            scope.launch {
                                busy = true
                                withContext(Dispatchers.IO) {
                                    ThermalTrainingPolicyStore(db).apply(target, mode, range.first, range.last)
                                }
                                if (target == ThermalTrainingTarget.INERTIA || target == ThermalTrainingTarget.BOTH) {
                                    trainedModelStore.markDirty("Sélection d’apprentissage inertiel modifiée")
                                }
                                reloadToken++
                                busy = false
                                val targetLabel = when (target) {
                                    ThermalTrainingTarget.INERTIA -> "inertie / sol"
                                    ThermalTrainingTarget.SOLAR -> "solaire / mur"
                                    ThermalTrainingTarget.BOTH -> "inertie + solaire"
                                }
                                val modeLabel = when (mode) {
                                    ThermalTrainingRangeMode.INCLUDE -> "zone utilisée"
                                    ThermalTrainingRangeMode.EXCLUDE -> "zone exclue"
                                    ThermalTrainingRangeMode.EXCLUSIVE -> "zone exclusive"
                                }
                                snackbar.showSnackbar("$modeLabel · $targetLabel · RAW conservées")
                            }
                        },
                        onZoomRange = { range ->
'''
    if 'onTrainingPolicy = { range, target, mode ->' not in t:
        if call_anchor not in t:
            raise SystemExit('MainActivity policy call anchor missing')
        t = t.replace(call_anchor, policy_call, 1)

    # Shorter labels are more readable on phone; the extra entries make engine choice explicit.
    t = t.replace('Text("Utiliser cette zone pour entraîner l\'inertie")', 'Text("Utiliser · inertie / sol")')
    t = t.replace('Text("Exclure cette zone du modèle d\'inertie")', 'Text("Exclure · inertie / sol")')

    zoom_item = '''                                DropdownMenuItem(
                                    text = { Text("Utiliser cette zone comme nouveau zoom") },
'''
    extra_items = '''                                DropdownMenuItem(
                                    text = { Text("Utiliser · solaire / mur") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onTrainingPolicy(selectedRange, ThermalTrainingTarget.SOLAR, ThermalTrainingRangeMode.INCLUDE)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Exclure · solaire / mur") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onTrainingPolicy(selectedRange, ThermalTrainingTarget.SOLAR, ThermalTrainingRangeMode.EXCLUDE)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Exclusivement · inertie / sol") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onTrainingPolicy(selectedRange, ThermalTrainingTarget.INERTIA, ThermalTrainingRangeMode.EXCLUSIVE)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Exclusivement · solaire / mur") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onTrainingPolicy(selectedRange, ThermalTrainingTarget.SOLAR, ThermalTrainingRangeMode.EXCLUSIVE)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
                                DropdownMenuItem(
                                    text = { Text("Exclusivement · les deux moteurs") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onTrainingPolicy(selectedRange, ThermalTrainingTarget.BOTH, ThermalTrainingRangeMode.EXCLUSIVE)
                                        rangeStart = null
                                        rangeEnd = null
                                    }
                                )
''' + zoom_item
    if 'Text("Exclusivement · les deux moteurs")' not in t:
        if zoom_item not in t:
            raise SystemExit('MainActivity menu zoom anchor missing')
        t = t.replace(zoom_item, extra_items)
    main.write_text(t)

    # Basic regression guards.
    assert 'FORMAT_VERSION = "3"' in backup.read_text()
    assert 'writeExtraRows(writer)' in backup.read_text()
    assert 'trainingTimestampAccepted' in engine.read_text()
    assert 'asExclusions(ThermalTrainingTarget.INERTIA' in inertia.read_text()
    assert 'ThermalTrainingTarget.SOLAR' in solar.read_text()
    assert 'Exclusivement · les deux moteurs' in main.read_text()
    assert 'SourceAwareExportCard(db)' not in main.read_text()
    print('v0.20.1 training + backup integration patches OK')


if __name__ == '__main__':
    main()
