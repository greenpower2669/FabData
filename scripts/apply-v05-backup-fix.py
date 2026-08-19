from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/BackupLayer.kt")
text = path.read_text(encoding="utf-8")

if "splitCsvRecords(reader.readText())" in text:
    print("FabData v0.5 backup parser fix already applied")
    raise SystemExit(0)

old_loop = '''            db.inTransaction {
                reader.forEachLine { rawLine ->
                    val line = rawLine.trimEnd('\\r')
                    if (line.isBlank()) return@forEachLine
'''
new_loop = '''            val records = splitCsvRecords(reader.readText())
            db.inTransaction {
                records.forEach { line ->
                    if (line.isBlank()) return@forEach
'''
if old_loop not in text:
    raise SystemExit("Backup import loop not found; refusing unsafe patch")
text = text.replace(old_loop, new_loop)
text = text.replace("return@forEachLine", "return@forEach")

old_event_sensor = '''                                val sensorId = if (stableKey.isBlank()) {
                                    null
                                } else {
                                    val sensor = db.getOrCreateSensor(stableKey, sensorName)
                                    db.updateSensor(sensor.id, sensorName, room, color)
                                    sensor.id
                                }
'''
new_event_sensor = '''                                val sensorId = if (stableKey.isBlank()) {
                                    null
                                } else {
                                    // La ligne SENSOR/SAMPLE porte le vrai paramétrage de la pièce.
                                    // Un événement peut avoir un libellé de lieu différent : il ne doit
                                    // donc jamais écraser le nom de pièce du capteur au réimport.
                                    db.getOrCreateSensor(stableKey, sensorName).id
                                }
'''
if old_event_sensor not in text:
    raise SystemExit("EVENT sensor block not found; refusing unsafe patch")
text = text.replace(old_event_sensor, new_event_sensor)

marker = '''    private fun splitCsv(line: String, delimiter: Char): List<String> {
'''
helper = '''    /**
     * Découpe le document en enregistrements CSV sans casser une note contenant
     * des retours à la ligne entre guillemets.
     */
    private fun splitCsvRecords(text: String): List<String> {
        val out = mutableListOf<String>()
        val row = StringBuilder()
        var quoted = false
        var i = 0
        while (i < text.length) {
            val ch = text[i]
            when {
                ch == '"' -> {
                    row.append(ch)
                    if (quoted && i + 1 < text.length && text[i + 1] == '"') {
                        row.append('"')
                        i++
                    } else {
                        quoted = !quoted
                    }
                }
                (ch == '\\n' || ch == '\\r') && !quoted -> {
                    if (ch == '\\r' && i + 1 < text.length && text[i + 1] == '\\n') i++
                    if (row.isNotEmpty()) {
                        out += row.toString()
                        row.clear()
                    }
                }
                else -> row.append(ch)
            }
            i++
        }
        if (row.isNotEmpty()) out += row.toString()
        return out
    }

'''
if marker not in text:
    raise SystemExit("splitCsv marker not found; refusing unsafe patch")
text = text.replace(marker, helper + marker)

path.write_text(text, encoding="utf-8")
print("FabData v0.5 multiline backup parser and event-room fix applied")
