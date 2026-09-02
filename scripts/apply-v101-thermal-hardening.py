from pathlib import Path

DATA = Path('app/src/main/java/com/fabdata/app/DataLayer.kt')
UI = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')

# Compose 2026 exposes weight as a RowScope/ColumnScope member extension.
# Importing androidx.compose.foundation.layout.weight resolves to an internal symbol.
text = UI.read_text(encoding='utf-8')
clean = text.replace('import androidx.compose.foundation.layout.weight\n', '')
if clean != text:
    UI.write_text(clean, encoding='utf-8')

# Any legacy/live caller of insertSample() represents a REAL measurement.
# If an exact timestamp was previously reconstructed/forecast, promote/replace it.
text = DATA.read_text(encoding='utf-8')
old = '''        val inserted = writableDatabase.insertWithOnConflict(
            "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
        ) != -1L
        if (inserted) PointSourceStore.markMeasured(this, sensorId, timestamp)
        return inserted
'''
new = '''        val inserted = writableDatabase.insertWithOnConflict(
            "samples", null, values, SQLiteDatabase.CONFLICT_IGNORE
        ) != -1L
        if (inserted) {
            PointSourceStore.markMeasured(this, sensorId, timestamp)
            return true
        }
        val existingSource = PointSourceStore.sourceFor(this, sensorId, timestamp)
        if (existingSource != PointSource.MEASURED) {
            val measuredValues = ContentValues().apply {
                put("temperature", temperature)
                put("humidity", humidity)
            }
            writableDatabase.update(
                "samples", measuredValues,
                "sensor_id=? AND timestamp=?",
                arrayOf(sensorId.toString(), timestamp.toString())
            )
            PointSourceStore.markMeasured(this, sensorId, timestamp)
            return true
        }
        return false
'''
if new not in text:
    if old not in text:
        raise SystemExit('v0.10.1: insertSample v0.10 block missing')
    text = text.replace(old, new, 1)
    DATA.write_text(text, encoding='utf-8')

print('FabData v0.10.1 priority/live-measure + Compose hardening applied')
