from pathlib import Path


def replace_required(path: str, old: str, new: str, already: str | None = None) -> None:
    p = Path(path)
    text = p.read_text()
    if already and already in text:
        return
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1))


# v0.21.8 — semantic UI fix after the deep audit:
# FORECAST_RECONSTRUCTED_SENSOR_ID and THERMAL_INERTIA_SENSOR_ID were both -6902900104L.
# That made their checkbox state, sample map, LOD maps and style map share the same key.
# Keep the historical thermal ID (-104) stable and move only the newer forecast pseudo-sensor.
replace_required(
    "app/build.gradle.kts",
    '        versionCode = 53\n        versionName = "0.21.7"',
    '        versionCode = 54\n        versionName = "0.21.8"',
    '        versionCode = 54\n        versionName = "0.21.8"',
)

replace_required(
    "app/src/main/java/com/fabdata/app/ForecastSelectableCurves.kt",
    'const val FORECAST_RECONSTRUCTED_SENSOR_ID = -6902900104L\n',
    '// -6902900104L is reserved by THERMAL_INERTIA_SENSOR_ID. Synthetic IDs must stay unique.\n'
    'const val FORECAST_RECONSTRUCTED_SENSOR_ID = -6902900106L\n',
    'const val FORECAST_RECONSTRUCTED_SENSOR_ID = -6902900106L',
)

# Small-screen accessibility/readability fix seen in the same audit: the status label was
# squeezed to a few characters per line by three action buttons in the same Row.
main_path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
main = main_path.read_text()
old = '''            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Source météo", fontWeight = FontWeight.SemiBold)
                    Text(
                        if (lyon?.latestTimestamp != null) "Synchronisation disponible" else "En attente de données",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (showLyonSpecificTools) {
                    TextButton(onClick = onOpenLyon) { Text("Détail") }
                    TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }
                }
                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
            }'''
new = '''            Column(
                Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Column(Modifier.fillMaxWidth()) {
                    Text("Source météo", fontWeight = FontWeight.SemiBold)
                    Text(
                        if (lyon?.latestTimestamp != null) "Synchronisation disponible" else "En attente de données",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    if (showLyonSpecificTools) {
                        TextButton(onClick = onOpenLyon) { Text("Détail") }
                        TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }
                    }
                    OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
                }
            }'''
marker = 'Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),\n                    horizontalArrangement = Arrangement.spacedBy(6.dp),\n                    verticalAlignment = Alignment.CenterVertically\n                ) {\n                    if (showLyonSpecificTools)'
if marker not in main:
    if old not in main:
        raise SystemExit("missing SensorSourcesCard narrow-screen layout anchor")
    main = main.replace(old, new, 1)
main_path.write_text(main)
