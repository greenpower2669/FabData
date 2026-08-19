from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = path.read_text(encoding="utf-8")

if "savedDraft?.dateText" in text and "dateText = dateText" in text:
    print("FabData v0.6 raw date draft patch already applied")
    raise SystemExit(0)

old_date = '''    var dateText by remember(initial?.id, initialTimestamp) {
        mutableStateOf(formatEpoch(baseTimestamp, formatter))
    }
'''
new_date = '''    var dateText by remember(initial?.id, initialTimestamp) {
        mutableStateOf(savedDraft?.dateText?.takeIf { it.isNotBlank() } ?: formatEpoch(baseTimestamp, formatter))
    }
'''
if old_date not in text:
    raise SystemExit("dateText initialization not found")
text = text.replace(old_date, new_date)

old_draft = '''            AnnotationDraft(
                timestamp = ts,
                title = title,
                note = note,
                sensorId = sensorId,
                roomName = roomName,
                type = type
            )'''
new_draft = '''            AnnotationDraft(
                timestamp = ts,
                dateText = dateText,
                title = title,
                note = note,
                sensorId = sensorId,
                roomName = roomName,
                type = type
            )'''
if old_draft not in text:
    raise SystemExit("AnnotationDraft creation not found")
text = text.replace(old_draft, new_draft)

path.write_text(text, encoding="utf-8")
print("FabData v0.6 incomplete date text persistence applied")
