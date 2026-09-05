from pathlib import Path

MAIN = Path('app/src/main/java/com/fabdata/app/MainActivity.kt')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, got {count}')
    return text.replace(old, new, 1)


text = MAIN.read_text()

old_states = '''                var rangeSelectionMode by rememberSaveable { mutableStateOf(false) }
                var rangeStart by remember { mutableStateOf<Long?>(null) }
                var rangeEnd by remember { mutableStateOf<Long?>(null) }
                var rangeMenuOpen by remember { mutableStateOf(false) }
'''
new_states = old_states + '''                val helpContext = LocalContext.current
                val helpPrefs = remember {
                    helpContext.getSharedPreferences("fabdata_context_help", Context.MODE_PRIVATE)
                }
                var helpOpen by rememberSaveable { mutableStateOf(false) }
                var tipOpen by rememberSaveable {
                    mutableStateOf(
                        !helpPrefs.getBoolean("range_tip_dismissed", false) &&
                            !helpPrefs.getBoolean("range_selection_used", false)
                    )
                }
                var demoOpen by rememberSaveable { mutableStateOf(false) }
                var demoStep by rememberSaveable { mutableIntStateOf(0) }
                var demoReplayToken by rememberSaveable { mutableIntStateOf(0) }

                LaunchedEffect(demoOpen, demoReplayToken) {
                    if (demoOpen) {
                        demoStep = 0
                        delay(850L)
                        demoStep = 1
                        delay(850L)
                        demoStep = 2
                        delay(850L)
                        demoStep = 3
                    }
                }
'''
text = replace_once(text, old_states, new_states, 'context help states')

old_controls = '''                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    AssistChip(
                        onClick = {
                            rangeSelectionMode = !rangeSelectionMode
                            rangeMenuOpen = false
                            rangeStart = null
                            rangeEnd = null
                        },
                        label = {
                            Text(if (rangeSelectionMode) "✓ Sélection active" else "Sélectionner une période")
                        }
                    )
                }
                if (rangeSelectionMode) {
                    Text(
                        "Glisse horizontalement dans le bandeau puis choisis l'action. Tu peux recommencer pour plusieurs zones.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
'''
new_controls = '''                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    AssistChip(
                        onClick = {
                            rangeSelectionMode = !rangeSelectionMode
                            rangeMenuOpen = false
                            rangeStart = null
                            rangeEnd = null
                            if (rangeSelectionMode) {
                                helpOpen = false
                                demoOpen = false
                            }
                        },
                        label = {
                            Text(if (rangeSelectionMode) "✓ Sélection active" else "Sélectionner une période")
                        }
                    )
                    OutlinedButton(
                        onClick = {
                            helpOpen = !helpOpen
                            tipOpen = false
                            if (!helpOpen) demoOpen = false
                        }
                    ) { Text("? Aide") }
                    OutlinedButton(
                        onClick = {
                            tipOpen = !tipOpen
                            helpOpen = false
                            demoOpen = false
                        }
                    ) { Text("! Astuce") }
                }
                if (rangeSelectionMode) {
                    Text(
                        "↔ Glisse horizontalement dans le bandeau puis choisis l'action. Tu peux recommencer pour plusieurs zones.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }

                if (helpOpen) {
                    Card(
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.38f)
                        )
                    ) {
                        Column(
                            Modifier.fillMaxWidth().padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            Text("? Sélection des périodes", fontWeight = FontWeight.Bold)
                            Text(
                                "Active Sélectionner une période, puis glisse directement dans le bandeau du haut. " +
                                    "La zone reste visible et une petite liste d'actions s'ouvre à droite.",
                                style = MaterialTheme.typography.bodySmall
                            )
                            Text(
                                "Le graphe principal ne change pas : son appui long reste réservé au zoom 48 h.",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Row(
                                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                TextButton(onClick = {
                                    demoOpen = true
                                    demoReplayToken++
                                }) { Text("▶ Voir la démonstration") }
                                TextButton(onClick = {
                                    helpOpen = false
                                    demoOpen = false
                                }) { Text("Fermer") }
                            }
                            if (demoOpen) {
                                RangeSelectionHelpDemo(
                                    step = demoStep,
                                    onReplay = { demoReplayToken++ },
                                    onNext = { demoStep = (demoStep + 1).coerceAtMost(3) }
                                )
                            }
                        }
                    }
                }

                if (tipOpen) {
                    Card(
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.34f)
                        )
                    ) {
                        Column(
                            Modifier.fillMaxWidth().padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(7.dp)
                        ) {
                            Text("! Astuce du jour", fontWeight = FontWeight.Bold)
                            Text(
                                "Si tu connais une période avec climatisation, fenêtre ouverte, chauffage inhabituel ou autre événement extérieur, " +
                                    "sélectionne-la ici puis choisis Exclure du modèle d'inertie. Les RAW restent intactes.",
                                style = MaterialTheme.typography.bodySmall
                            )
                            Row(
                                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                TextButton(onClick = {
                                    rangeSelectionMode = true
                                    tipOpen = false
                                    helpOpen = false
                                }) { Text("Essayer maintenant") }
                                TextButton(onClick = {
                                    tipOpen = false
                                    helpPrefs.edit().putBoolean("range_tip_dismissed", true).apply()
                                }) { Text("Ne plus afficher") }
                            }
                        }
                    }
                }
'''
text = replace_once(text, old_controls, new_controls, 'help controls')

old_drag_end = '''                                    onDragEnd = {
                                        val a = rangeStart
                                        val b = rangeEnd
                                        if (a != null && b != null && kotlin.math.abs(b - a) >= 60L * 60L * 1000L) {
                                            rangeMenuOpen = true
                                        } else {
                                            rangeStart = null
                                            rangeEnd = null
                                        }
                                    },
'''
new_drag_end = '''                                    onDragEnd = {
                                        val a = rangeStart
                                        val b = rangeEnd
                                        if (a != null && b != null && kotlin.math.abs(b - a) >= 60L * 60L * 1000L) {
                                            rangeMenuOpen = true
                                            tipOpen = false
                                            helpPrefs.edit().putBoolean("range_selection_used", true).apply()
                                        } else {
                                            rangeStart = null
                                            rangeEnd = null
                                        }
                                    },
'''
text = replace_once(text, old_drag_end, new_drag_end, 'selection usage tracking')

marker = '''@Composable
private fun ChartCard(
'''
helper = '''@Composable
private fun RangeSelectionHelpDemo(
    step: Int,
    onReplay: () -> Unit,
    onNext: () -> Unit
) {
    val accent = MaterialTheme.colorScheme.primary
    val secondary = MaterialTheme.colorScheme.tertiary
    val track = MaterialTheme.colorScheme.outlineVariant
    val popup = MaterialTheme.colorScheme.surface
    val popupLine = MaterialTheme.colorScheme.onSurfaceVariant

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Canvas(
            Modifier.fillMaxWidth().height(92.dp)
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.30f), RoundedCornerShape(12.dp))
        ) {
            val y = size.height * 0.55f
            drawLine(track, Offset(size.width * 0.08f, y), Offset(size.width * 0.92f, y), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.12f, y - 15f), Offset(size.width * 0.30f, y + 8f), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.30f, y + 8f), Offset(size.width * 0.48f, y - 12f), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.48f, y - 12f), Offset(size.width * 0.67f, y + 5f), 2.dp.toPx())
            drawLine(track, Offset(size.width * 0.67f, y + 5f), Offset(size.width * 0.88f, y - 8f), 2.dp.toPx())

            val startX = size.width * 0.20f
            val finalX = size.width * 0.68f
            val cursorX = when (step.coerceIn(0, 3)) {
                0 -> startX
                1 -> startX + (finalX - startX) * 0.48f
                else -> finalX
            }
            if (step >= 1) {
                drawRect(
                    secondary.copy(alpha = 0.22f),
                    topLeft = Offset(startX, 8f),
                    size = androidx.compose.ui.geometry.Size((cursorX - startX).coerceAtLeast(2f), size.height - 16f)
                )
                drawLine(secondary, Offset(startX, 8f), Offset(startX, size.height - 8f), 2.dp.toPx())
                drawLine(secondary, Offset(cursorX, 8f), Offset(cursorX, size.height - 8f), 2.dp.toPx())
            }
            drawCircle(accent, 6.dp.toPx(), Offset(cursorX, y))

            if (step >= 3) {
                val left = size.width * 0.66f
                val top = 7f
                val width = size.width * 0.30f
                val height = size.height * 0.68f
                drawRect(
                    popup,
                    topLeft = Offset(left, top),
                    size = androidx.compose.ui.geometry.Size(width, height)
                )
                repeat(3) { index ->
                    val lineY = top + 16f + index * 16f
                    drawLine(
                        popupLine,
                        Offset(left + 10f, lineY),
                        Offset(left + width - 10f, lineY),
                        1.5.dp.toPx()
                    )
                }
            }
        }

        Text(
            when (step.coerceIn(0, 3)) {
                0 -> "1 · Active la sélection et pose le doigt / la souris au début de la période."
                1 -> "2 · Glisse horizontalement : le rectangle suit exactement l'intervalle choisi."
                2 -> "3 · Relâche : la période reste surlignée."
                else -> "4 · La popup propose Entraîner, Exclure, Nouveau zoom ou Annuler."
            },
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            TextButton(onClick = onReplay) { Text("↻ Rejouer") }
            TextButton(onClick = onNext, enabled = step < 3) { Text("Étape suivante") }
        }
    }
}

@Composable
private fun ChartCard(
'''
text = replace_once(text, marker, helper, 'help demo composable')

MAIN.write_text(text)
print('v0.19.1 contextual help + micro-demo patch applied')
