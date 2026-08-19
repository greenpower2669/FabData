from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = path.read_text(encoding="utf-8")

# Idempotence: once the source is patched and committed, later CI runs do nothing.
if "Exporter / sauvegarder FabData" in text:
    print("FabData v0.5 MainActivity patch already applied")
    raise SystemExit(0)

text = text.replace(
    "import androidx.compose.material.icons.filled.FileOpen\nimport androidx.compose.material.icons.filled.Refresh",
    "import androidx.compose.material.icons.filled.FileOpen\nimport androidx.compose.material.icons.filled.FileDownload\nimport androidx.compose.material.icons.filled.Refresh",
)

text = text.replace(
    "    val importer = remember { CsvImporter(context, db) }\n    val prefsStore = remember { FabPrefs(context) }",
    "    val importer = remember { CsvImporter(context, db) }\n    val backup = remember { FabDataBackup(context, db) }\n    val prefsStore = remember { FabPrefs(context) }",
)

old_picker = '''    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            scope.launch {
                busy = true
                val results = withContext(Dispatchers.IO) {
                    uris.map { uri -> runCatching { importer.import(uri) } }
                }
                val ok = results.mapNotNull { it.getOrNull() }
                val errors = results.count { it.isFailure }
                val added = ok.sumOf { it.added }
                val duplicates = ok.sumOf { it.duplicates }
                val invalid = ok.sumOf { it.invalid }
                busy = false
                reloadToken++
                snackbar.showSnackbar(
                    "Import : $added ajoutées · $duplicates déjà présentes · $invalid invalides" +
                        if (errors > 0) " · $errors fichier(s) en erreur" else ""
                )
            }
        }
    }
'''

new_picker = '''    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        if (uri != null) {
            scope.launch {
                busy = true
                val result = withContext(Dispatchers.IO) { runCatching { backup.export(uri) } }
                busy = false
                snackbar.showSnackbar(
                    result.fold(
                        onSuccess = {
                            "Sauvegarde créée : ${it.measurements} mesures · ${it.events} événement(s) · ${it.sensors} capteur(s)"
                        },
                        onFailure = { "Sauvegarde impossible : ${it.message ?: "erreur inconnue"}" }
                    )
                )
            }
        }
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isNotEmpty()) {
            scope.launch {
                busy = true
                val results = withContext(Dispatchers.IO) {
                    uris.map { uri ->
                        runCatching {
                            backup.importIfBackup(uri) ?: importer.import(uri).toFabDataImportSummary()
                        }
                    }
                }
                val ok = results.mapNotNull { it.getOrNull() }
                val errors = results.count { it.isFailure }
                val measuresAdded = ok.sumOf { it.measurementsAdded }
                val measuresDuplicates = ok.sumOf { it.measurementsDuplicates }
                val eventsAdded = ok.sumOf { it.eventsAdded }
                val eventsDuplicates = ok.sumOf { it.eventsDuplicates }
                val invalid = ok.sumOf { it.invalid }
                busy = false
                reloadToken++
                snackbar.showSnackbar(
                    "Import : $measuresAdded mesure(s) ajoutée(s) · $measuresDuplicates déjà présente(s) · " +
                        "$eventsAdded événement(s) restauré(s) · $eventsDuplicates événement(s) déjà présent(s) · " +
                        "$invalid invalide(s)" + if (errors > 0) " · $errors fichier(s) en erreur" else ""
                )
            }
        }
    }
'''

if old_picker not in text:
    raise SystemExit("Picker block not found; refusing unsafe patch")
text = text.replace(old_picker, new_picker)

old_initial = '''    LaunchedEffect(initialImport, initialHandled) {
        if (!initialHandled && initialImport != null) {
            initialHandled = true
            busy = true
            val result = withContext(Dispatchers.IO) { runCatching { importer.import(initialImport) } }
            busy = false
            reloadToken++
            snackbar.showSnackbar(
                result.fold(
                    onSuccess = { "${it.added} mesure(s) ajoutée(s), ${it.duplicates} déjà présentes" },
                    onFailure = { "Import impossible : ${it.message ?: "format inconnu"}" }
                )
            )
        }
    }
'''

new_initial = '''    LaunchedEffect(initialImport, initialHandled) {
        if (!initialHandled && initialImport != null) {
            initialHandled = true
            busy = true
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    backup.importIfBackup(initialImport) ?: importer.import(initialImport).toFabDataImportSummary()
                }
            }
            busy = false
            reloadToken++
            snackbar.showSnackbar(
                result.fold(
                    onSuccess = {
                        "Import : ${it.measurementsAdded} mesure(s) ajoutée(s) · ${it.measurementsDuplicates} déjà présente(s) · " +
                            "${it.eventsAdded} événement(s) restauré(s) · ${it.eventsDuplicates} déjà présent(s)"
                    },
                    onFailure = { "Import impossible : ${it.message ?: "format inconnu"}" }
                )
            )
        }
    }
'''

if old_initial not in text:
    raise SystemExit("Initial import block not found; refusing unsafe patch")
text = text.replace(old_initial, new_initial)

old_actions = '''                    IconButton(onClick = {
                        picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel"))
                    }) { Icon(Icons.Default.FileOpen, contentDescription = "Importer des CSV") }
                    IconButton(onClick = { reloadToken++ }) {
'''

new_actions = '''                    IconButton(onClick = {
                        picker.launch(arrayOf("text/*", "application/csv", "application/vnd.ms-excel"))
                    }) { Icon(Icons.Default.FileOpen, contentDescription = "Importer des CSV") }
                    IconButton(onClick = {
                        exportLauncher.launch("FabData_sauvegarde.csv")
                    }) {
                        Icon(Icons.Default.FileDownload, contentDescription = "Exporter / sauvegarder FabData")
                    }
                    IconButton(onClick = { reloadToken++ }) {
'''

if old_actions not in text:
    raise SystemExit("Top app bar actions block not found; refusing unsafe patch")
text = text.replace(old_actions, new_actions)

path.write_text(text, encoding="utf-8")
print("FabData v0.5 MainActivity backup/export patch applied")
