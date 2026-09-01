from pathlib import Path

MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")

text = MAIN.read_text(encoding="utf-8")
original = text

# Newer preview versions (v0.8.6+) preserve the v0.8.5 tap/double-tap contract
# but have different help text and gesture bodies. Treat them as already applied.
if (
    "private fun HistoryOverviewCard(" in text
    and "selectedTimestamp: Long?" in text
    and "onSelectTimestamp: (Long) -> Unit" in text
    and "onNavigate: (Long) -> Unit" in text
    and "onNavigate(ts)" in text
):
    print("FabData v0.8.5 preview double-tap navigation already preserved by newer preview")
    raise SystemExit(0)

old_call = '''                    HistoryOverviewCard(
                        sensors = sensors,
                        sampleMap = overviewSampleMap,
                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        onSelect = { ts ->
                            preset = TimePreset.TWO_DAYS
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        }
                    )
'''
new_call = '''                    HistoryOverviewCard(
                        sensors = sensors,
                        sampleMap = overviewSampleMap,
                        historyBounds = globalBounds,
                        viewBounds = viewBounds,
                        selectedTimestamp = selectedTimestamp,
                        onSelectTimestamp = { ts ->
                            // Un simple tap ne modifie PAS la fenêtre principale.
                            // Il déplace uniquement la sélection dans la mini-vue.
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        },
                        onNavigate = { ts ->
                            // Le double-tap recentre le graphe principal autour du point
                            // en conservant le preset/zoom temporel actuellement choisi.
                            windowCenterTimestamp = ts
                            selectedTimestamp = ts
                            selectedAnnotation = null
                        }
                    )
'''
if "onSelectTimestamp = { ts ->" not in text or "HistoryOverviewCard(" not in text:
    if old_call not in text:
        raise SystemExit("v0.8.5: HistoryOverviewCard call block not found")
    text = text.replace(old_call, new_call, 1)

old_sig = '''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,
    viewBounds: LongRange?,
    onSelect: (Long) -> Unit
) {
'''
new_sig = '''private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,
    viewBounds: LongRange?,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit,
    onNavigate: (Long) -> Unit
) {
'''
if "selectedTimestamp: Long?,\n    onSelectTimestamp: (Long) -> Unit,\n    onNavigate: (Long) -> Unit" not in text:
    if old_sig not in text:
        raise SystemExit("v0.8.5: HistoryOverviewCard signature not found")
    text = text.replace(old_sig, new_sig, 1)

old_help = '''                "Tap sur l’historique = afficher 48 h autour de ce point",
'''
new_help = '''                "Tap = sélectionner · double tap = recentrer le graphe avec le zoom courant",
'''
if new_help not in text:
    if old_help not in text:
        raise SystemExit("v0.8.5: preview help text not found")
    text = text.replace(old_help, new_help, 1)

old_colors = '''                val highlight = MaterialTheme.colorScheme.primary
                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)
'''
new_colors = '''                val highlight = MaterialTheme.colorScheme.primary
                val selectionColor = MaterialTheme.colorScheme.tertiary
                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)
'''
if "val selectionColor = MaterialTheme.colorScheme.tertiary" not in text:
    if old_colors not in text:
        raise SystemExit("v0.8.5: preview color anchor not found")
    text = text.replace(old_colors, new_colors, 1)

old_pointer = '''                        .pointerInput(bounds, viewBounds) {
                            detectTapGestures { p ->
                                val frac = (p.x / size.width.toFloat()).coerceIn(0f, 1f)
                                onSelect(bounds.first + (span * frac).toLong())
                            }
                        }
'''
new_pointer = '''                        .pointerInput(bounds, viewBounds) {
                            detectTapGestures(
                                onDoubleTap = { p ->
                                    val frac = (p.x / size.width.toFloat()).coerceIn(0f, 1f)
                                    val ts = bounds.first + (span * frac).toLong()
                                    onSelectTimestamp(ts)
                                    onNavigate(ts)
                                },
                                onTap = { p ->
                                    val frac = (p.x / size.width.toFloat()).coerceIn(0f, 1f)
                                    val ts = bounds.first + (span * frac).toLong()
                                    onSelectTimestamp(ts)
                                }
                            )
                        }
'''
if "onNavigate(ts)" not in text:
    if old_pointer not in text:
        raise SystemExit("v0.8.5: preview pointer block not found")
    text = text.replace(old_pointer, new_pointer, 1)

old_tail = '''                    viewBounds?.let { visible ->
                        val left = (((visible.first - bounds.first).toDouble() / span.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        val right = (((visible.last - bounds.first).toDouble() / span.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        if (right > left) {
                            drawRect(
                                highlight.copy(alpha = 0.14f),
                                topLeft = Offset(left, 0f),
                                size = androidx.compose.ui.geometry.Size(right - left, size.height)
                            )
                            drawLine(highlight.copy(alpha = 0.8f), Offset(left, 0f), Offset(left, size.height), 2f)
                            drawLine(highlight.copy(alpha = 0.8f), Offset(right, 0f), Offset(right, size.height), 2f)
                        }
                    }
'''
new_tail = old_tail + '''                    selectedTimestamp?.takeIf { it in bounds }?.let { selected ->
                        val x = (((selected - bounds.first).toDouble() / span.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        drawLine(
                            selectionColor.copy(alpha = 0.95f),
                            Offset(x, 0f),
                            Offset(x, size.height),
                            2.dp.toPx()
                        )
                        drawCircle(
                            selectionColor,
                            radius = 4.dp.toPx(),
                            center = Offset(x, size.height / 2f)
                        )
                    }
'''
if "selectedTimestamp?.takeIf { it in bounds }" not in text:
    if old_tail not in text:
        raise SystemExit("v0.8.5: preview highlight block not found")
    text = text.replace(old_tail, new_tail, 1)

if text != original:
    MAIN.write_text(text, encoding="utf-8")

print("FabData v0.8.5 preview double-tap navigation patch applied")
