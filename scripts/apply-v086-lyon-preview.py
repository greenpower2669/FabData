from pathlib import Path

DATA = Path("app/src/main/java/com/fabdata/app/DataLayer.kt")
LYON = Path("app/src/main/java/com/fabdata/app/LyonWeatherSync.kt")
MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")

# -----------------------------------------------------------------------------
# DataLayer: allow weather sources to correct an existing sample at same time.
# Physical/imported sensors continue to use insertSample() and are untouched.
# -----------------------------------------------------------------------------
text = DATA.read_text(encoding="utf-8")
original = text

if "fun updateSampleIfDifferent(" not in text:
    anchor = '''    fun inTransaction(block: () -> Unit) {\n'''
    insert = '''    /**
     * Corrige uniquement une mesure déjà présente au même timestamp.
     * Utilisé par les sources météo revalidées ; ne crée aucune nouvelle ligne.
     */
    fun updateSampleIfDifferent(
        sensorId: Long,
        timestamp: Long,
        temperature: Double,
        humidity: Double
    ): Boolean {
        val current = readableDatabase.rawQuery(
            "SELECT temperature, humidity FROM samples WHERE sensor_id = ? AND timestamp = ? LIMIT 1",
            arrayOf(sensorId.toString(), timestamp.toString())
        ).use { c ->
            if (!c.moveToFirst()) null else c.getDouble(0) to c.getDouble(1)
        } ?: return false

        if (kotlin.math.abs(current.first - temperature) < 0.001 &&
            kotlin.math.abs(current.second - humidity) < 0.001
        ) return false

        val values = ContentValues().apply {
            put("temperature", temperature)
            put("humidity", humidity)
        }
        return writableDatabase.update(
            "samples",
            values,
            "sensor_id = ? AND timestamp = ?",
            arrayOf(sensorId.toString(), timestamp.toString())
        ) > 0
    }

'''
    if anchor not in text:
        raise SystemExit("v0.8.6: DataLayer transaction anchor not found")
    text = text.replace(anchor, insert + anchor, 1)

if text != original:
    DATA.write_text(text, encoding="utf-8")

# -----------------------------------------------------------------------------
# Lyon weather: deterministic day parser + correction of stale/wrong duplicates.
# -----------------------------------------------------------------------------
text = LYON.read_text(encoding="utf-8")
original = text

if "import kotlin.math.abs" not in text:
    text = text.replace("import java.util.Locale\n", "import java.util.Locale\nimport kotlin.math.abs\n", 1)

text = text.replace(
'''data class LyonWeatherSyncResult(
    val parsed: Int,
    val added: Int,
    val duplicates: Int,
    val date: LocalDate
)''',
'''data class LyonWeatherSyncResult(
    val parsed: Int,
    val added: Int,
    val corrected: Int,
    val duplicates: Int,
    val date: LocalDate
)'''
)

text = text.replace(
'''    val daysAlreadyComplete: Int,
    val added: Int,
    val duplicates: Int
)''',
'''    val daysAlreadyComplete: Int,
    val added: Int,
    val corrected: Int,
    val duplicates: Int
)'''
)

if "Les doublons météo peuvent être corrigés" not in text:
    start = text.find("    fun syncToday(): LyonWeatherSyncResult {\n")
    end = text.find("\n    /**\n     * Complète Lyon", start)
    if start < 0 or end < 0:
        raise SystemExit("v0.8.6: Lyon syncToday block not found")
    replacement = '''    fun syncToday(): LyonWeatherSyncResult {
        // Crée la sonde même si la source distante est indisponible.
        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)
        val date = ZonedDateTime.now(LYON_ZONE).toLocalDate()

        // Préfère l'URL datée : on ne devine plus la date d'une ligne à partir
        // de l'heure courante. Le temps-réel reste un repli pour la journée en cours.
        val html = runCatching { downloadHtml(archiveUrl(date)) }
            .getOrElse { downloadHtml() }
        val points = parseArchiveDay(html, date)

        var added = 0
        var corrected = 0
        var duplicates = 0
        db.inTransaction {
            points.values.sortedBy { it.timestamp }.forEach { point ->
                if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) {
                    added++
                } else if (db.updateSampleIfDifferent(
                        sensor.id, point.timestamp, point.temperature, point.humidity
                    )
                ) {
                    // Les doublons météo peuvent être corrigés après revalidation.
                    corrected++
                } else {
                    duplicates++
                }
            }
        }

        return LyonWeatherSyncResult(points.size, added, corrected, duplicates, date)
    }
'''
    text = text[:start] + replacement + text[end:]

if "private fun isSuspiciousDay(" not in text:
    start = text.find("    fun completePhysicalPeriod(): LyonWeatherCompleteResult {\n")
    end = text.find("\n    private fun archiveUrl(date: LocalDate): String {", start)
    if start < 0 or end < 0:
        raise SystemExit("v0.8.6: Lyon completion block not found")
    replacement = '''    fun completePhysicalPeriod(): LyonWeatherCompleteResult {
        val bounds = db.physicalSensorBounds()
            ?: error("Aucune période de thermomètre connecté à compléter")
        val fromDate = Instant.ofEpochMilli(bounds.first).atZone(LYON_ZONE).toLocalDate()
        val toDate = Instant.ofEpochMilli(bounds.last).atZone(LYON_ZONE).toLocalDate()
        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)

        var date = fromDate
        var requested = 0
        var downloaded = 0
        var alreadyComplete = 0
        var added = 0
        var corrected = 0
        var duplicates = 0

        // Les 31 derniers jours de la période physique sont toujours revalidés
        // lors d'un « Compléter ». Au-delà, on ne retélécharge que les journées
        // incomplètes ou manifestement suspectes afin d'éviter des milliers de GET.
        val recentRepairCutoff = toDate.minusDays(31)

        while (!date.isAfter(toDate)) {
            requested++
            val start = date.atStartOfDay(LYON_ZONE).toInstant().toEpochMilli()
            val end = date.plusDays(1).atStartOfDay(LYON_ZONE).toInstant().toEpochMilli() - 1
            val existingPoints = db.querySamples(sensor.id, start, end, maxPoints = 72)
            val existingTimestamps = existingPoints.map { it.timestamp }.toSet()
            val expected = (0..23).map { hour ->
                date.atTime(hour, 0).atZone(LYON_ZONE).toInstant().toEpochMilli()
            }.toSet()
            val complete = expected.all { it in existingTimestamps }
            val suspicious = isSuspiciousDay(existingPoints)
            val revalidateRecent = !date.isBefore(recentRepairCutoff)

            if (complete && !suspicious && !revalidateRecent) {
                alreadyComplete++
                date = date.plusDays(1)
                continue
            }

            val html = runCatching { downloadHtml(archiveUrl(date)) }.getOrElse { firstError ->
                if (date == LocalDate.now(LYON_ZONE)) downloadHtml() else throw firstError
            }
            downloaded++
            val points = parseArchiveDay(html, date)

            db.inTransaction {
                points.values.sortedBy { it.timestamp }.forEach { point ->
                    if (db.insertSample(sensor.id, point.timestamp, point.temperature, point.humidity)) {
                        added++
                    } else if (db.updateSampleIfDifferent(
                            sensor.id, point.timestamp, point.temperature, point.humidity
                        )
                    ) {
                        corrected++
                    } else {
                        duplicates++
                    }
                }
            }

            if (date != toDate) Thread.sleep(80)
            date = date.plusDays(1)
        }

        return LyonWeatherCompleteResult(
            fromDate = fromDate,
            toDate = toDate,
            daysRequested = requested,
            daysDownloaded = downloaded,
            daysAlreadyComplete = alreadyComplete,
            added = added,
            corrected = corrected,
            duplicates = duplicates
        )
    }

    /**
     * Détecte les anomalies grossières avant de décider qu'une journée météo
     * existante est « complète ». Un saut > 8 °C en <= 2 h mérite revalidation.
     */
    private fun isSuspiciousDay(points: List<SamplePoint>): Boolean {
        if (points.any { it.temperature !in -35.0..50.0 || it.humidity !in 0.0..100.0 }) return true
        val sorted = points.sortedBy { it.timestamp }
        return sorted.zipWithNext().any { (a, b) ->
            val dt = b.timestamp - a.timestamp
            dt in 1..(2L * 60L * 60L * 1000L) && abs(b.temperature - a.temperature) > 8.0
        }
    }
'''
    text = text[:start] + replacement + text[end:]

text = text.replace("FabData/0.8\")", "FabData/0.8.6\")")

if text != original:
    LYON.write_text(text, encoding="utf-8")

# -----------------------------------------------------------------------------
# MainActivity: 6/12/24/36/48-month preview, drag/pinch, safe outside inspector.
# -----------------------------------------------------------------------------
text = MAIN.read_text(encoding="utf-8")
original = text

if "private enum class PreviewPreset" not in text:
    anchor = '''private data class ChartPrefs(\n'''
    insert = '''private enum class PreviewPreset(val label: String, val spanMs: Long) {
    M6("6 mois", 183L * 24L * 60L * 60L * 1000L),
    M12("12 mois", 366L * 24L * 60L * 60L * 1000L),
    M24("24 mois", 732L * 24L * 60L * 60L * 1000L),
    M36("36 mois", 1098L * 24L * 60L * 60L * 1000L),
    M48("48 mois", 1464L * 24L * 60L * 60L * 1000L)
}

'''
    if anchor not in text:
        raise SystemExit("v0.8.6: ChartPrefs anchor not found")
    text = text.replace(anchor, insert + anchor, 1)

# Lyon status messages now expose corrected measurements.
text = text.replace(
    '"Lyon : ${it.added} nouvelle(s) mesure(s) · ${it.duplicates} déjà présente(s)"',
    '"Lyon : ${it.added} ajoutée(s) · ${it.corrected} corrigée(s) · ${it.duplicates} inchangée(s)"'
)
text = text.replace(
    '"Lyon : ${it.added} nouvelle(s) mesure(s)"',
    '"Lyon : ${it.added} ajoutée(s) · ${it.corrected} corrigée(s)"'
)
text = text.replace(
    '"Lyon complété : ${it.added} mesure(s) · ${it.daysDownloaded} jour(s) téléchargé(s) · ${it.daysAlreadyComplete} déjà complet(s)"',
    '"Lyon : ${it.added} ajoutée(s) · ${it.corrected} corrigée(s) · ${it.daysDownloaded} jour(s) vérifié(s)"'
)

# Outside-main-window preview selection must not show unrelated nearest samples.
old_inspector = '''                selectedTimestamp?.let { ts ->
                    item {
                        InspectorCard(ts, sensors, sampleMap, showTemp, showHumidity)
                    }
                }
'''
new_inspector = '''                selectedTimestamp?.let { ts ->
                    item {
                        if (viewBounds?.let { ts in it } == true) {
                            InspectorCard(ts, sensors, sampleMap, showTemp, showHumidity)
                        } else {
                            Card(shape = RoundedCornerShape(18.dp)) {
                                Column(
                                    Modifier.fillMaxWidth().padding(14.dp),
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
                                    Text("Sélection prévisu · ${formatDateTime(ts)}", fontWeight = FontWeight.Bold)
                                    Text(
                                        "Hors de la fenêtre détaillée · double-tape sur le bandeau pour ouvrir cette période.",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
                    }
                }
'''
if "Sélection prévisu · ${formatDateTime(ts)}" not in text:
    if old_inspector not in text:
        raise SystemExit("v0.8.6: Inspector block not found")
    text = text.replace(old_inspector, new_inspector, 1)

# Replace the complete preview composable.
start = text.find("@Composable\nprivate fun HistoryOverviewCard(\n")
end = text.find("\n@Composable\nprivate fun ChartCard(\n", start)
if start < 0 or end < 0:
    raise SystemExit("v0.8.6: HistoryOverviewCard function not found")

new_overview = '''@Composable
private fun HistoryOverviewCard(
    sensors: List<Sensor>,
    sampleMap: Map<Long, List<SamplePoint>>,
    historyBounds: LongRange?,
    viewBounds: LongRange?,
    selectedTimestamp: Long?,
    onSelectTimestamp: (Long) -> Unit,
    onNavigate: (Long) -> Unit
) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp)
        ) {
            Text("Vue globale", fontWeight = FontWeight.Bold)
            Text(
                "Tap = sélectionner · double tap = ouvrir · glisse = déplacer la prévisu · pince = élargir/rétrécir",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            val bounds = historyBounds
            if (bounds == null) {
                Text("Historique global indisponible", style = MaterialTheme.typography.bodySmall)
            } else {
                var previewPreset by rememberSaveable { mutableStateOf(PreviewPreset.M6) }
                var previewZoom by rememberSaveable { mutableFloatStateOf(1f) }
                var previewCenter by remember(bounds.first, bounds.last) {
                    mutableStateOf(
                        viewBounds?.let { it.first + (it.last - it.first) / 2L }
                            ?: (bounds.first + (bounds.last - bounds.first) / 2L)
                    )
                }

                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    PreviewPreset.entries.forEach { item ->
                        Surface(
                            onClick = {
                                previewPreset = item
                                previewZoom = 1f
                                previewCenter = (selectedTimestamp
                                    ?: viewBounds?.let { it.first + (it.last - it.first) / 2L }
                                    ?: previewCenter).coerceIn(bounds.first, bounds.last)
                            },
                            color = if (item == previewPreset) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent,
                            shape = RoundedCornerShape(14.dp)
                        ) {
                            Text(
                                item.label,
                                Modifier.padding(horizontal = 10.dp, vertical = 7.dp),
                                fontWeight = if (item == previewPreset) FontWeight.Bold else FontWeight.Normal
                            )
                        }
                    }
                }

                val fullSpan = (bounds.last - bounds.first).coerceAtLeast(1L)
                val maxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)
                val mainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }
                    ?: (24L * 60L * 60L * 1000L)
                val minSpan = minOf(maxSpan, maxOf(24L * 60L * 60L * 1000L, mainSpan))
                val maxZoom = (maxSpan.toDouble() / minSpan.toDouble()).toFloat().coerceAtLeast(1f)
                val effectiveZoom = previewZoom.coerceIn(1f, maxZoom)
                val previewSpan = (maxSpan.toDouble() / effectiveZoom.toDouble()).toLong()
                    .coerceIn(minSpan, maxSpan)

                fun clampCenter(value: Long, span: Long): Long {
                    if (span >= fullSpan) return bounds.first + fullSpan / 2L
                    val half = span / 2L
                    return value.coerceIn(bounds.first + half, bounds.last - (span - half))
                }

                val effectiveCenter = clampCenter(previewCenter, previewSpan)
                val previewFrom = if (previewSpan >= fullSpan) bounds.first else effectiveCenter - previewSpan / 2L
                val previewTo = if (previewSpan >= fullSpan) bounds.last else previewFrom + previewSpan
                val previewWindow = previewFrom..previewTo
                val visiblePoints = sensors.flatMap { sensor ->
                    sampleMap[sensor.id].orEmpty().filter { it.timestamp in previewWindow }
                }
                val minTemp = visiblePoints.minOfOrNull { it.temperature } ?: 0.0
                val maxTemp = visiblePoints.maxOfOrNull { it.temperature } ?: 1.0
                val tempRange = (maxTemp - minTemp).takeIf { it > 0.01 } ?: 1.0
                val highlight = MaterialTheme.colorScheme.primary
                val selectionColor = MaterialTheme.colorScheme.tertiary
                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)

                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(92.dp)
                        .background(surface, RoundedCornerShape(12.dp))
                        .pointerInput(bounds, previewPreset) {
                            detectTransformGestures { centroid, pan, zoomChange, _ ->
                                val oldMaxSpan = minOf(previewPreset.spanMs, fullSpan).coerceAtLeast(1L)
                                val oldMainSpan = viewBounds?.let { (it.last - it.first).coerceAtLeast(1L) }
                                    ?: (24L * 60L * 60L * 1000L)
                                val oldMinSpan = minOf(
                                    oldMaxSpan,
                                    maxOf(24L * 60L * 60L * 1000L, oldMainSpan)
                                )
                                val oldMaxZoom = (oldMaxSpan.toDouble() / oldMinSpan.toDouble())
                                    .toFloat().coerceAtLeast(1f)
                                val oldZoom = previewZoom.coerceIn(1f, oldMaxZoom)
                                val oldSpan = (oldMaxSpan.toDouble() / oldZoom.toDouble()).toLong()
                                    .coerceIn(oldMinSpan, oldMaxSpan)
                                val oldCenter = clampCenter(previewCenter, oldSpan)
                                val oldFrom = if (oldSpan >= fullSpan) bounds.first else oldCenter - oldSpan / 2L
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val fraction = (centroid.x / width).coerceIn(0f, 1f)
                                val anchorTs = oldFrom + (oldSpan * fraction).toLong()

                                val newZoom = (oldZoom * zoomChange).coerceIn(1f, oldMaxZoom)
                                val newSpan = (oldMaxSpan.toDouble() / newZoom.toDouble()).toLong()
                                    .coerceIn(oldMinSpan, oldMaxSpan)
                                val zoomAnchoredCenter = anchorTs - (newSpan * fraction).toLong() + newSpan / 2L
                                val panShift = (-(pan.x / width) * newSpan.toDouble()).toLong()

                                previewZoom = newZoom
                                previewCenter = clampCenter(zoomAnchoredCenter + panShift, newSpan)
                            }
                        }
                        .pointerInput(previewFrom, previewTo) {
                            detectTapGestures(
                                onDoubleTap = { p ->
                                    val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                    val ts = previewFrom + (previewSpan * frac).toLong()
                                    onSelectTimestamp(ts)
                                    onNavigate(ts)
                                },
                                onTap = { p ->
                                    val frac = (p.x / size.width.toFloat().coerceAtLeast(1f)).coerceIn(0f, 1f)
                                    onSelectTimestamp(previewFrom + (previewSpan * frac).toLong())
                                }
                            )
                        }
                ) {
                    if (visiblePoints.isNotEmpty()) {
                        sensors.forEach { sensor ->
                            val points = sampleMap[sensor.id].orEmpty()
                                .filter { it.timestamp in previewWindow }
                                .sortedBy { it.timestamp }
                            if (points.size >= 2) {
                                val path = Path()
                                points.forEachIndexed { index, point ->
                                    val x = ((point.timestamp - previewFrom).toDouble() / previewSpan.toDouble())
                                        .toFloat() * size.width
                                    val y = size.height - (((point.temperature - minTemp) / tempRange)
                                        .toFloat() * size.height)
                                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                                }
                                drawPath(
                                    path,
                                    palette[sensor.colorIndex % palette.size].copy(alpha = 0.72f),
                                    style = Stroke(width = 1.5.dp.toPx())
                                )
                            }
                        }
                    }

                    // Fenêtre détaillée actuelle : fond grisé + deux limites.
                    viewBounds?.let { visible ->
                        val clippedStart = maxOf(visible.first, previewFrom)
                        val clippedEnd = minOf(visible.last, previewTo)
                        if (clippedEnd > clippedStart) {
                            val left = (((clippedStart - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            val right = (((clippedEnd - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                                .coerceIn(0f, size.width)
                            drawRect(
                                highlight.copy(alpha = 0.16f),
                                topLeft = Offset(left, 0f),
                                size = androidx.compose.ui.geometry.Size(right - left, size.height)
                            )
                            drawLine(highlight.copy(alpha = 0.85f), Offset(left, 0f), Offset(left, size.height), 2f)
                            drawLine(highlight.copy(alpha = 0.85f), Offset(right, 0f), Offset(right, size.height), 2f)
                        }
                    }

                    selectedTimestamp?.takeIf { it in previewWindow }?.let { selected ->
                        val x = (((selected - previewFrom).toDouble() / previewSpan.toDouble()).toFloat() * size.width)
                            .coerceIn(0f, size.width)
                        drawLine(
                            selectionColor.copy(alpha = 0.95f),
                            Offset(x, 0f),
                            Offset(x, size.height),
                            2.dp.toPx()
                        )
                        drawCircle(selectionColor, 4.dp.toPx(), Offset(x, size.height / 2f))
                    }
                }

                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDateTime(previewFrom), style = MaterialTheme.typography.labelSmall)
                    Text(
                        "max ${previewPreset.label}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(formatDateTime(previewTo), style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}
'''

text = text[:start] + new_overview + text[end:]

if text != original:
    MAIN.write_text(text, encoding="utf-8")

print("FabData v0.8.6 Lyon repair + preview navigator patch applied")
