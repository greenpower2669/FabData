from pathlib import Path

UI = Path('app/src/main/java/com/fabdata/app/ThermalUi.kt')
text = UI.read_text(encoding='utf-8')
text = text.replace('import androidx.compose.foundation.layout.weight\n', '')
UI.write_text(text, encoding='utf-8')
print('FabData v0.10 Compose RowScope weight import fixed')
