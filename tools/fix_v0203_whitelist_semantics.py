from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


def replace_all_required(text: str, old: str, new: str, label: str, minimum: int = 1) -> str:
    count = text.count(old)
    if count < minimum:
        if new in text:
            return text
        raise SystemExit(f"missing anchor: {label} (found {count})")
    return text.replace(old, new)


def main():
    # ------------------------------------------------------------------
    # Training policy semantics
    # EXCLUSIVE is kept as a persisted enum value for backward compatibility,
    # but its user-facing meaning is now an operation:
    #   "exclude everything except THIS zone".
    # It therefore RESETS the positive whitelist to the current single zone.
    # Later INCLUDE actions add more zones to the whitelist, one selection at a time.
    # ------------------------------------------------------------------
    policy = Path('app/src/main/java/com/fabdata/app/ThermalTrainingPolicy.kt')
    t = policy.read_text()

    t = replace_once(
        t,
        ''' * EXCLUSIVE is a positive whitelist: as soon as one exclusive range exists for an
 * engine, every timestamp outside the union of those ranges is ignored for fitting.
 * EXCLUDE always wins. INCLUDE removes exclusions; when an exclusive whitelist is
 * already active it also adds the selected range to that whitelist.
''',
        ''' * EXCLUSIVE is kept as the persisted name for compatibility, but it is an operation,
 * not a third per-zone state: "exclude everything except this zone". Applying it resets
 * the positive whitelist to the current single selection. Once that whitelist mode is
 * active, INCLUDE adds another selected zone to the whitelist, one selection at a time.
 * EXCLUDE removes/blocks a selected slice. Everything outside the whitelist is ignored.
''',
        'policy semantics comment'
    )

    t = replace_once(
        t,
        '''                ThermalTrainingRangeMode.INCLUDE -> includeRange(actual, from, to)
                ThermalTrainingRangeMode.EXCLUDE -> addMerged(actual, ThermalTrainingRangeMode.EXCLUDE, from, to)
                ThermalTrainingRangeMode.EXCLUSIVE -> addMerged(actual, ThermalTrainingRangeMode.EXCLUSIVE, from, to)
''',
        '''                ThermalTrainingRangeMode.INCLUDE -> includeRange(actual, from, to)
                ThermalTrainingRangeMode.EXCLUDE -> addMerged(actual, ThermalTrainingRangeMode.EXCLUDE, from, to)
                ThermalTrainingRangeMode.EXCLUSIVE -> startOnlySelected(actual, from, to)
''',
        'exclusive dispatch'
    )

    anchor = '''    private fun includeRange(target: ThermalTrainingTarget, from: Long, to: Long) {
'''
    new_block = '''    /**
     * Activates/restarts "only selected zones" mode with exactly the current range.
     * This is deliberately NOT additive: the wording "exclude everything except this
     * zone" means this selection becomes the new base whitelist. The user can then make
     * another single selection and use INCLUDE to add it to the allowed union.
     */
    private fun startOnlySelected(target: ThermalTrainingTarget, from: Long, to: Long) {
        val start = minOf(from, to)
        val end = maxOf(from, to)
        val sql = db.writableDatabase
        val now = System.currentTimeMillis()
        sql.beginTransaction()
        try {
            // Reset only the whitelist rows for this engine; explicit exclusions outside
            // the new allowed range may stay because they are irrelevant while whitelist
            // mode is active. Any exclusion overlapping the chosen range is removed below.
            sql.delete(
                "thermal_training_policy",
                "target=? AND mode=?",
                arrayOf(target.name, ThermalTrainingRangeMode.EXCLUSIVE.name)
            )
            insert(target, ThermalTrainingRangeMode.EXCLUSIVE, start, end, now, now)
            sql.setTransactionSuccessful()
        } finally {
            sql.endTransaction()
        }
        // The selected base zone must really be usable: clear any old explicit exclusion
        // that intersects it. RAW data are never touched.
        removeSlice(target, ThermalTrainingRangeMode.EXCLUDE, start, end)
    }

''' + anchor
    t = replace_once(t, anchor, new_block, 'startOnlySelected helper')
    policy.write_text(t)

    # ------------------------------------------------------------------
    # UI wording + unify inertia actions on the new engine-specific policy store.
    # There is only one dragged range at a time. Repeating the gesture is how the user
    # adds another allowed zone after starting the whitelist mode.
    # ------------------------------------------------------------------
    main = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
    t = main.read_text()

    t = replace_all_required(
        t,
        '"↔ Glisse horizontalement dans le bandeau puis choisis l\'action. Tu peux recommencer pour plusieurs zones."',
        '"↔ Une seule zone à la fois : glisse, valide l\'action, puis refais une sélection pour en ajouter une autre."',
        'single-selection help text'
    )

    # Inertia INCLUDE/EXCLUDE used the old legacy mask callbacks. Route them through the
    # same policy store as SOLAR so all three operations have one coherent semantics.
    t = replace_all_required(
        t,
        '''text = { Text("Utiliser · inertie / sol") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onUseForInertia(selectedRange)
''',
        '''text = { Text("Ajouter / utiliser cette zone · inertie / sol") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onTrainingPolicy(selectedRange, ThermalTrainingTarget.INERTIA, ThermalTrainingRangeMode.INCLUDE)
''',
        'inertia include menu'
    )
    t = replace_all_required(
        t,
        '''text = { Text("Exclure · inertie / sol") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onExcludeFromInertia(selectedRange)
''',
        '''text = { Text("Retirer / exclure cette zone · inertie / sol") },
                                    onClick = {
                                        rangeMenuOpen = false
                                        onTrainingPolicy(selectedRange, ThermalTrainingTarget.INERTIA, ThermalTrainingRangeMode.EXCLUDE)
''',
        'inertia exclude menu'
    )

    t = replace_all_required(
        t,
        'Text("Utiliser · solaire / mur")',
        'Text("Ajouter / utiliser cette zone · solaire / mur")',
        'solar include label'
    )
    t = replace_all_required(
        t,
        'Text("Exclure · solaire / mur")',
        'Text("Retirer / exclure cette zone · solaire / mur")',
        'solar exclude label'
    )
    t = replace_all_required(
        t,
        'Text("Exclusivement · inertie / sol")',
        'Text("Exclure tout sauf cette zone · inertie / sol")',
        'inertia whitelist reset label'
    )
    t = replace_all_required(
        t,
        'Text("Exclusivement · solaire / mur")',
        'Text("Exclure tout sauf cette zone · solaire / mur")',
        'solar whitelist reset label'
    )
    t = replace_all_required(
        t,
        'Text("Exclusivement · les deux moteurs")',
        'Text("Exclure tout sauf cette zone · les deux moteurs")',
        'both whitelist reset label'
    )

    t = replace_all_required(
        t,
        '''ThermalTrainingRangeMode.INCLUDE -> "zone utilisée"
                                    ThermalTrainingRangeMode.EXCLUDE -> "zone exclue"
                                    ThermalTrainingRangeMode.EXCLUSIVE -> "zone exclusive"
''',
        '''ThermalTrainingRangeMode.INCLUDE -> "zone ajoutée / utilisée"
                                    ThermalTrainingRangeMode.EXCLUDE -> "zone retirée / exclue"
                                    ThermalTrainingRangeMode.EXCLUSIVE -> "tout le reste exclu · cette zone devient la base"
''',
        'snackbar mode wording'
    )

    main.write_text(t)
    print('v0.20.3 whitelist semantics patch applied')


if __name__ == '__main__':
    main()
