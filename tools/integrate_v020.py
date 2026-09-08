from pathlib import Path


def main():
    # Database v5: additive thermal roles/walls/model tables + trigger for future CSV sensors.
    data = Path('app/src/main/java/com/fabdata/app/DataLayer.kt')
    t = data.read_text()
    t = t.replace('SQLiteOpenHelper(context, "fabdata.db", null, 4)', 'SQLiteOpenHelper(context, "fabdata.db", null, 5)')
    create_anchor = '        WeatherReferenceStore.ensure(db)\n'
    create_add = (
        '        WeatherReferenceStore.ensure(db)\n'
        '        ThermalWallConfigStore.ensure(db)\n'
        '        ThermalWallSolarModelStore.ensure(db)\n'
    )
    if create_add not in t:
        if create_anchor not in t:
            raise SystemExit('DataLayer onCreate anchor missing')
        t = t.replace(create_anchor, create_add, 1)
    upgrade_anchor = '''        if (oldVersion < 4) {
            // v0.10 : métadonnées additives uniquement. Les anciennes lignes restent measured par défaut.
            PointSourceStore.ensure(db)
            WeatherReferenceStore.ensure(db)
        }
'''
    upgrade_add = upgrade_anchor + '''        if (oldVersion < 5) {
            // v0.20 : rôles de sondes + pans de mur + modèles solaires, migration additive uniquement.
            ThermalWallConfigStore.ensure(db)
            ThermalWallSolarModelStore.ensure(db)
        }
'''
    if 'if (oldVersion < 5)' not in t:
        if upgrade_anchor not in t:
            raise SystemExit('DataLayer onUpgrade anchor missing')
        t = t.replace(upgrade_anchor, upgrade_add, 1)
    legacy_filter = "WHERE s.stable_key NOT LIKE 'meteo-%'\n              AND s.stable_key NOT LIKE 'http-get-%'"
    role_filter = "WHERE s.id IN (SELECT sensor_id FROM sensor_thermal_config WHERE role='INDOOR')"
    count = t.count(legacy_filter)
    if count:
        t = t.replace(legacy_filter, role_filter)
        print('DataLayer role-aware physical filters:', count)
    data.write_text(t)

    # ThermalEngine: only INDOOR sensors can be model targets / building median participants.
    engine = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt')
    t = engine.read_text()
    anchor = '    private val coherenceStore = ThermalCoherenceStore(db)\n'
    add = anchor + '    private val wallConfigStore = ThermalWallConfigStore(db)\n'
    if 'private val wallConfigStore = ThermalWallConfigStore(db)' not in t:
        if anchor not in t:
            raise SystemExit('ThermalEngine field anchor missing')
        t = t.replace(anchor, add, 1)
    old = '''    private fun physicalSensors(): List<Sensor> = db.sensors().filter { s ->
        !s.stableKey.startsWith("meteo-") && !s.stableKey.startsWith("http-get-") && s.id >= 0L
    }
'''
    new = '''    private fun physicalSensors(): List<Sensor> = wallConfigStore.indoorSensors()
'''
    if old in t:
        t = t.replace(old, new, 1)
    elif new not in t:
        raise SystemExit('ThermalEngine physicalSensors anchor missing')
    engine.write_text(t)

    # Hidden/observable inertial mass uses only INDOOR sensors too.
    inertia = Path('app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt')
    t = inertia.read_text()
    anchor = '    private var cachedKey: String? = null\n'
    add = '    private val wallConfigStore = ThermalWallConfigStore(db)\n' + anchor
    if 'private val wallConfigStore = ThermalWallConfigStore(db)' not in t:
        if anchor not in t:
            raise SystemExit('Inertia field anchor missing')
        t = t.replace(anchor, add, 1)
    old = '''        val sensors = db.sensors().filter { s ->
            (sensorId == null || s.id == sensorId) &&
                s.id >= 0L && !s.stableKey.startsWith("meteo-") && !s.stableKey.startsWith("http-get-")
        }
'''
    new = '''        val sensors = wallConfigStore.indoorSensors().filter { s ->
            sensorId == null || s.id == sensorId
        }
'''
    if old in t:
        t = t.replace(old, new, 1)
    elif new not in t:
        raise SystemExit('Inertia sensor selector anchor missing')
    inertia.write_text(t)

    # Rationalisation stays on indoor calculated curves.
    coherence = Path('app/src/main/java/com/fabdata/app/ThermalCoherence.kt')
    t = coherence.read_text()
    old = '''            JOIN sensors s ON s.id=ps.sensor_id
            WHERE ps.source IN ('reconstructed','forecast')
              AND ps.sensor_id>=0
              AND s.stable_key NOT LIKE 'meteo-%'
              AND s.stable_key NOT LIKE 'http-get-%'
'''
    new = '''            JOIN sensors s ON s.id=ps.sensor_id
            JOIN sensor_thermal_config tc ON tc.sensor_id=s.id
            WHERE ps.source IN ('reconstructed','forecast')
              AND ps.sensor_id>=0
              AND tc.role='INDOOR'
'''
    if old in t:
        t = t.replace(old, new, 1)
    elif new not in t:
        raise SystemExit('ThermalCoherence selector anchor missing')
    coherence.write_text(t)

    # New menu sits directly after the existing building profile customisation.
    ui = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')
    t = ui.read_text()
    forecast_anchor = '''            Card(shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("Prévision adaptative", fontWeight = FontWeight.SemiBold)
'''
    wall_card = '''            ThermalWallSettingsCard(
                db = db,
                reference = reference,
                enabled = !busy,
                onChanged = {
                    trainedModelStore.markDirty("Sondes ou pans extérieurs modifiés")
                    trainedModel = null
                    status = engine.statusFromTrainedModel(reference, selectedSensorId, null)
                    info = "Configuration thermique modifiée · réentraînement intérieur manuel requis"
                }
            )

''' + forecast_anchor
    if 'ThermalWallSettingsCard(' not in t:
        if forecast_anchor not in t:
            raise SystemExit('ThermalUi insertion anchor missing')
        t = t.replace(forecast_anchor, wall_card, 1)
    ui.write_text(t)

    # Missing extension import in standalone Compose UI.
    wall_ui = Path('app/src/main/java/com/fabdata/app/ThermalWallSettingsUi.kt')
    t = wall_ui.read_text()
    if 'import androidx.compose.foundation.layout.weight\n' not in t:
        t = t.replace(
            'import androidx.compose.foundation.layout.size\n',
            'import androidx.compose.foundation.layout.size\nimport androidx.compose.foundation.layout.weight\n'
        )
    wall_ui.write_text(t)

    assert 'wallConfigStore.indoorSensors()' in engine.read_text()
    assert 'ThermalWallSettingsCard(' in ui.read_text()
    assert 'THERMAL_INERTIA_SENSOR_ID' in Path('app/src/main/java/com/fabdata/app/MainActivity.kt').read_text()
    assert 'MEASURED' in Path('app/src/main/java/com/fabdata/app/PointSourceLayer.kt').read_text()
    print('v0.20 integration patches OK')


if __name__ == '__main__':
    main()
