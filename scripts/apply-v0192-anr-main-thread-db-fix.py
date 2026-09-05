from pathlib import Path

MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')
GRADLE = Path('app/build.gradle.kts')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, got {count}')
    return text.replace(old, new, 1)

text = MAIN.read_text()

text = replace_once(
    text,
    '    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }\n'
    '    val thermalTrainingMaskStore = remember { ThermalTrainingMaskStore(db) }\n',
    '    val inertiaEstimator = remember { ThermalInertiaEstimator(db, weatherReferenceStore) }\n',
    'remove main-thread mask store construction'
)

text = replace_once(
    text,
    '''                                    val changed = withContext(Dispatchers.IO) {
                                        thermalTrainingMaskStore.includeRange(sensorId, range.first, range.last)
                                    }
''',
    '''                                    val changed = withContext(Dispatchers.IO) {
                                        // ThermalTrainingMaskStore initialise SQLite dans son constructeur.
                                        // Le créer ici empêche tout accès DB synchrone pendant la composition UI.
                                        ThermalTrainingMaskStore(db).includeRange(sensorId, range.first, range.last)
                                    }
''',
    'move include store construction to IO'
)

text = replace_once(
    text,
    '''                                    withContext(Dispatchers.IO) {
                                        thermalTrainingMaskStore.addMerged(
                                            sensorId,
                                            range.first,
                                            range.last,
                                            "Sélection bandeau global"
                                        )
                                    }
''',
    '''                                    withContext(Dispatchers.IO) {
                                        // Même garde-fou pour l'exclusion : création du store + écriture hors UI.
                                        ThermalTrainingMaskStore(db).addMerged(
                                            sensorId,
                                            range.first,
                                            range.last,
                                            "Sélection bandeau global"
                                        )
                                    }
''',
    'move exclude store construction to IO'
)

MAIN.write_text(text)

gradle = GRADLE.read_text()
gradle = replace_once(gradle, 'versionCode = 37', 'versionCode = 38', 'version code')
gradle = replace_once(gradle, 'versionName = "0.19.1"', 'versionName = "0.19.2"', 'version name')
GRADLE.write_text(gradle)

print('v0.19.2 ANR fix applied: no ThermalTrainingMaskStore construction during UI composition')
