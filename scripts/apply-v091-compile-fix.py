from pathlib import Path

LAB = Path('app/src/main/java/com/fabdata/app/LyonLabLayer.kt')
text = LAB.read_text(encoding='utf-8')

# Compose 2026 exposes Modifier.weight through Row/Column scopes; importing the
# internal extension explicitly makes the Kotlin compiler reject the file.
text = text.replace('import androidx.compose.foundation.layout.weight\n', '')

# ModalBottomSheet is still annotated ExperimentalMaterial3Api in this Compose BOM.
if 'import androidx.compose.material3.ExperimentalMaterial3Api\n' not in text:
    text = text.replace(
        'import androidx.compose.material3.CardDefaults\n',
        'import androidx.compose.material3.CardDefaults\nimport androidx.compose.material3.ExperimentalMaterial3Api\n',
        1
    )

marker = '@Composable\nfun LyonDetailSheet('
if '@OptIn(ExperimentalMaterial3Api::class)\n@Composable\nfun LyonDetailSheet(' not in text:
    if marker not in text:
        raise SystemExit('v0.9.1: LyonDetailSheet marker not found')
    text = text.replace(
        marker,
        '@OptIn(ExperimentalMaterial3Api::class)\n' + marker,
        1
    )

LAB.write_text(text, encoding='utf-8')
print('FabData v0.9.0 Lyon Compose compile fixes applied')
