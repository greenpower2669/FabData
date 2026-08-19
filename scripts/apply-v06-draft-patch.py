from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = path.read_text(encoding="utf-8")

if "Brouillon sauvegardé automatiquement" in text:
    print("FabData v0.6 draft patch already applied")
    raise SystemExit(0)

text = text.replace(
    "    val backup = remember { FabDataBackup(context, db) }\n    val prefsStore = remember { FabPrefs(context) }",
    "    val backup = remember { FabDataBackup(context, db) }\n    val draftStore = remember { AnnotationDraftStore(context) }\n    val prefsStore = remember { FabPrefs(context) }",
)

old_call = '''        AnnotationDialog(
            initialTimestamp = ts,
            initial = editingAnnotation,
            sensors = sensors,
            onDismiss = {'''
new_call = '''        AnnotationDialog(
            initialTimestamp = ts,
            initial = editingAnnotation,
            sensors = sensors,
            draftStore = draftStore,
            onDismiss = {'''
if old_call not in text:
    raise SystemExit("AnnotationDialog call not found")
text = text.replace(old_call, new_call)

old_sig = '''private fun AnnotationDialog(
    initialTimestamp: Long,
    initial: AnnotationItem?,
    sensors: List<Sensor>,
    onDismiss: () -> Unit,'''
new_sig = '''private fun AnnotationDialog(
    initialTimestamp: Long,
    initial: AnnotationItem?,
    sensors: List<Sensor>,
    draftStore: AnnotationDraftStore,
    onDismiss: () -> Unit,'''
if old_sig not in text:
    raise SystemExit("AnnotationDialog signature not found")
text = text.replace(old_sig, new_sig)

old_state = '''    val formatter = remember { DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm") }
    var dateText by remember(initial?.id, initialTimestamp) {
        mutableStateOf(formatEpoch(initial?.timestamp ?: initialTimestamp, formatter))
    }
    var title by remember(initial?.id) { mutableStateOf(initial?.title.orEmpty()) }
    var note by remember(initial?.id) { mutableStateOf(initial?.note.orEmpty()) }
    var sensorId by remember(initial?.id) { mutableStateOf(initial?.sensorId) }
    var roomName by remember(initial?.id) {
        mutableStateOf(initial?.roomName ?: initial?.sensorId?.let { id -> sensors.firstOrNull { it.id == id }?.room }.orEmpty())
    }
    var type by remember(initial?.id) { mutableStateOf(initial?.type.orEmpty()) }
    var sensorMenu by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf(false) }

    AlertDialog('''

new_state = '''    val formatter = remember { DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm") }
    val draftKey = remember(initial?.id) { initial?.id?.let { "edit_$it" } ?: "new" }
    val savedDraft = remember(draftKey, initialTimestamp) { draftStore.load(draftKey) }
    val baseTimestamp = savedDraft?.timestamp ?: initial?.timestamp ?: initialTimestamp
    var dateText by remember(initial?.id, initialTimestamp) {
        mutableStateOf(formatEpoch(baseTimestamp, formatter))
    }
    var title by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.title ?: initial?.title.orEmpty())
    }
    var note by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.note ?: initial?.note.orEmpty())
    }
    var sensorId by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.sensorId ?: initial?.sensorId)
    }
    var roomName by remember(initial?.id, initialTimestamp) {
        mutableStateOf(
            savedDraft?.roomName
                ?: initial?.roomName
                ?: initial?.sensorId?.let { id -> sensors.firstOrNull { it.id == id }?.room }
                .orEmpty()
        )
    }
    var type by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.type ?: initial?.type.orEmpty())
    }
    var sensorMenu by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf(false) }

    LaunchedEffect(dateText, title, note, sensorId, roomName, type, draftKey) {
        val ts = parseLocalDate(dateText, formatter) ?: baseTimestamp
        draftStore.save(
            draftKey,
            AnnotationDraft(
                timestamp = ts,
                title = title,
                note = note,
                sensorId = sensorId,
                roomName = roomName,
                type = type
            )
        )
    }

    AlertDialog('''

if old_state not in text:
    raise SystemExit("AnnotationDialog state block not found")
text = text.replace(old_state, new_state)

old_column = '''            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                OutlinedTextField('''
new_column = '''            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    "Brouillon sauvegardé automatiquement",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary
                )
                OutlinedTextField('''
if old_column not in text:
    raise SystemExit("AnnotationDialog column block not found")
text = text.replace(old_column, new_column)

old_save = '''                } else {
                    onSave(
                        initial?.id,
                        ts,
                        title,
                        note,
                        sensorId,
                        roomName.trim().ifBlank { null },
                        type.trim().ifBlank { null }
                    )
                }
            }) {'''
new_save = '''                } else {
                    draftStore.clear(draftKey)
                    onSave(
                        initial?.id,
                        ts,
                        title,
                        note,
                        sensorId,
                        roomName.trim().ifBlank { null },
                        type.trim().ifBlank { null }
                    )
                }
            }) {'''
if old_save not in text:
    raise SystemExit("AnnotationDialog save block not found")
text = text.replace(old_save, new_save)

path.write_text(text, encoding="utf-8")
print("FabData v0.6 annotation draft autosave patch applied")
