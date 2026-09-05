from pathlib import Path

THERMAL_UI = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')
GRADLE = Path('app/build.gradle.kts')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, got {count}')
    return text.replace(old, new, 1)

text = THERMAL_UI.read_text()

text = replace_once(
    text,
    '''private data class RationalizeResult(
    val removed: Int,
    val reconstructed: Int,
    val forecasts: Int,
    val skipped: Int,
    val alreadyCoherent: Boolean,
    val reason: String
)
''',
    '''private data class RationalizeResult(
    val removed: Int,
    val reconstructed: Int,
    val forecasts: Int,
    val skipped: Int,
    val alreadyCoherent: Boolean,
    val reason: String
)

/**
 * Runtime thermique construit hors du thread UI.
 *
 * La carte thermique vit dans un LazyColumn : elle n'est composée qu'au moment où
 * l'utilisateur descend dessus. Avant v0.19.3, cette première composition construisait
 * plusieurs objets qui ouvrent/initialisent SQLite dans leurs constructeurs. Sur une base
 * réelle occupée par un recalcul/sync, le thread UI pouvait attendre le verrou SQLite et
 * Android proposait de fermer l'application (ANR).
 */
private data class ThermalUiRuntime(
    val manager: WeatherReferenceManager,
    val engine: ThermalEngine,
    val coherenceStore: ThermalCoherenceStore
)
''',
    'runtime data class'
)

old_top = '''    val context = LocalContext.current
    val prefs = remember { WeatherReferencePrefs(context) }
    val manager = remember { WeatherReferenceManager(context, db, lyonLab, credentials) }
    val engine = remember { ThermalEngine(db, manager.store()) }
    val coherenceStore = remember { ThermalCoherenceStore(db) }
    val profileStore = remember { ThermalProfileStore(context) }
    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }
    val modelSensorPrefs = remember {
        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)
    }
    var profile by remember { mutableStateOf(profileStore.load()) }
    var forecastMode by remember { mutableStateOf(profileStore.forecastMode()) }
    val scope = rememberCoroutineScope()

    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
'''
new_top = '''    val context = LocalContext.current
    val prefs = remember { WeatherReferencePrefs(context) }
    val profileStore = remember { ThermalProfileStore(context) }
    val historyDebtStore = remember { ThermalHistoryDebtStore(context) }
    val modelSensorPrefs = remember {
        context.getSharedPreferences("fabdata_thermal_model", android.content.Context.MODE_PRIVATE)
    }
    var profile by remember { mutableStateOf(profileStore.load()) }
    var forecastMode by remember { mutableStateOf(profileStore.forecastMode()) }
    val scope = rememberCoroutineScope()

    // IMPORTANT v0.19.3 : aucun constructeur DB-bound n'est exécuté pendant la
    // composition de cette carte LazyColumn. Le premier scroll ne peut donc plus
    // bloquer le thread UI sur un verrou/PRAGMA/CREATE TABLE SQLite.
    var runtime by remember(db) { mutableStateOf<ThermalUiRuntime?>(null) }
    var runtimeError by remember(db) { mutableStateOf<String?>(null) }
    LaunchedEffect(db) {
        val built = withContext(Dispatchers.IO) {
            runCatching {
                val manager = WeatherReferenceManager(context, db, lyonLab, credentials)
                val engine = ThermalEngine(db, manager.store())
                val coherenceStore = ThermalCoherenceStore(db)
                ThermalUiRuntime(manager, engine, coherenceStore)
            }
        }
        built.fold(
            onSuccess = {
                runtime = it
                runtimeError = null
            },
            onFailure = {
                runtimeError = it.message ?: "Initialisation thermique impossible"
            }
        )
    }

    val readyRuntime = runtime
    if (readyRuntime == null) {
        Card(shape = RoundedCornerShape(20.dp)) {
            Column(
                Modifier.fillMaxWidth().padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text("Référence météo & moteur thermique", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    runtimeError ?: "Initialisation thermique en arrière-plan…",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (runtimeError == null) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error
                )
            }
        }
        return
    }
    val manager = readyRuntime.manager
    val engine = readyRuntime.engine
    val coherenceStore = readyRuntime.coherenceStore

    var selectedKey by remember { mutableStateOf(prefs.selectedKey()) }
'''
text = replace_once(text, old_top, new_top, 'defer DB-bound runtime construction')

text = replace_once(
    text,
    '''            onFailure = { error ->
                status = runCatching { engine.status(reference, selectedSensorId, profile) }.getOrNull()
                info = error.message ?: "Référence météo indisponible"
            }
''',
    '''            onFailure = { error ->
                // Même le fallback d'état peut recalibrer/hacher beaucoup de points : jamais sur UI.
                status = withContext(Dispatchers.IO) {
                    runCatching { engine.status(reference, selectedSensorId, profile) }.getOrNull()
                }
                info = error.message ?: "Référence météo indisponible"
            }
''',
    'refresh fallback status off main'
)

text = replace_once(
    text,
    '''                                val firstReal = coherenceStore.firstMeasuredTimestamp(debt.sensorId)
                                val days = firstReal?.let { (((it - debt.from).coerceAtLeast(24L * 60L * 60L * 1000L)) / (24L * 60L * 60L * 1000L)).toInt() }
''',
    '''                                val firstReal = withContext(Dispatchers.IO) {
                                    coherenceStore.firstMeasuredTimestamp(debt.sensorId)
                                }
                                val days = firstReal?.let { (((it - debt.from).coerceAtLeast(24L * 60L * 60L * 1000L)) / (24L * 60L * 60L * 1000L)).toInt() }
''',
    'debt lookup off main'
)

THERMAL_UI.write_text(text)

gradle = GRADLE.read_text()
gradle = replace_once(gradle, 'versionCode = 38', 'versionCode = 39', 'version code')
gradle = replace_once(gradle, 'versionName = "0.19.2"', 'versionName = "0.19.3"', 'version name')
GRADLE.write_text(gradle)

print('v0.19.3 applied: lazy thermal card DB runtime is initialized entirely on Dispatchers.IO')
