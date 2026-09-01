from pathlib import Path

LYON = Path("app/src/main/java/com/fabdata/app/LyonWeatherSync.kt")
MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")

# -----------------------------------------------------------------------------
# Lyon: merge two acquisition methods for the SAME observed station.
# Archive is authoritative when both sources expose the same timestamp;
# realtime only fills missing recent hours. No synthetic/interpolated samples.
# -----------------------------------------------------------------------------
text = LYON.read_text(encoding="utf-8")
original = text

if "private fun mergedObservedDay(" not in text:
    start = text.find("    fun syncToday(): LyonWeatherSyncResult {\n")
    end = text.find("\n    /**\n     * Complète Lyon", start)
    if start < 0 or end < 0:
        raise SystemExit("v0.8.7: Lyon syncToday block not found")
    replacement = '''    fun syncToday(): LyonWeatherSyncResult {
        val sensor = db.getOrCreateSensor(STABLE_KEY, DISPLAY_NAME)
        val date = ZonedDateTime.now(LYON_ZONE).toLocalDate()
        val points = mergedObservedDay(date)

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

    old_fetch = '''            val html = runCatching { downloadHtml(archiveUrl(date)) }.getOrElse { firstError ->
                if (date == LocalDate.now(LYON_ZONE)) downloadHtml() else throw firstError
            }
            downloaded++
            val points = parseArchiveDay(html, date)
'''
    new_fetch = '''            // Fusionne uniquement des observations réelles Lyon-Bron :
            // archive datée + temps réel pour aujourd'hui/hier. Aucun remplissage artificiel.
            val points = mergedObservedDay(date)
            downloaded++
'''
    if old_fetch not in text:
        raise SystemExit("v0.8.7: Lyon completion fetch block not found")
    text = text.replace(old_fetch, new_fetch, 1)

    anchor = '''    /**
     * Détecte les anomalies grossières avant de décider qu'une journée météo
'''
    helpers = '''    /**
     * Fusionne les méthodes d'acquisition sans mélanger des modèles météo :
     * - temps réel Lyon-Bron pour combler les dernières heures disponibles ;
     * - archive Lyon-Bron, prioritaire au même timestamp.
     * Si aucune observation réelle n'existe, aucun point n'est inventé.
     */
    private fun mergedObservedDay(date: LocalDate): LinkedHashMap<Long, WeatherPoint> {
        val now = ZonedDateTime.now(LYON_ZONE)
        val merged = linkedMapOf<Long, WeatherPoint>()

        // La page temps réel est utile pour aujourd'hui et parfois la veille.
        if (!date.isBefore(now.toLocalDate().minusDays(1))) {
            runCatching { downloadHtml() }.getOrNull()?.let { html ->
                parseRealtimeWindow(html, now).values
                    .filter { point ->
                        Instant.ofEpochMilli(point.timestamp).atZone(LYON_ZONE).toLocalDate() == date
                    }
                    .forEach { point -> merged[point.timestamp] = point }
            }
        }

        // L'archive est la référence finale quand elle possède le même horaire.
        runCatching { downloadHtml(archiveUrl(date)) }.getOrNull()?.let { html ->
            runCatching { parseArchiveDay(html, date) }.getOrNull()?.values?.forEach { point ->
                merged[point.timestamp] = point
            }
        }

        if (merged.isEmpty()) error("Aucune observation réelle Lyon-Bron exploitable pour $date")
        return merged
    }

    /** Parse la fenêtre roulante temps réel sans fabriquer les heures absentes. */
    private fun parseRealtimeWindow(
        html: String,
        now: ZonedDateTime
    ): LinkedHashMap<Long, WeatherPoint> {
        val points = linkedMapOf<Long, WeatherPoint>()
        rowRegex.findAll(html).forEach { match ->
            val text = Html.fromHtml(match.groupValues[1], Html.FROM_HTML_MODE_LEGACY)
                .toString()
                .replace('\\u00A0', ' ')
                .replace(Regex("\\\\s+"), " ")
                .trim()
            val hour = hourRegex.find(text)?.groupValues?.getOrNull(1)?.toIntOrNull()
                ?: return@forEach
            val temperature = temperatureRegex.find(text)?.groupValues?.getOrNull(1)
                ?.replace(',', '.')?.toDoubleOrNull()
                ?: return@forEach
            val humidity = humidityRegex.find(text)?.groupValues?.getOrNull(1)
                ?.replace(',', '.')?.toDoubleOrNull()
                ?: return@forEach
            if (temperature !in -100.0..150.0 || humidity !in 0.0..100.0) return@forEach

            val observationDate = if (hour > now.hour) now.toLocalDate().minusDays(1) else now.toLocalDate()
            val timestamp = observationDate.atTime(hour, 0)
                .atZone(LYON_ZONE)
                .toInstant()
                .toEpochMilli()
            points[timestamp] = WeatherPoint(timestamp, temperature, humidity)
        }
        return points
    }

'''
    if anchor not in text:
        raise SystemExit("v0.8.7: Lyon suspicious-day anchor not found")
    text = text.replace(anchor, helpers + anchor, 1)

text = text.replace("FabData/0.8.6\")", "FabData/0.8.7\")")

if text != original:
    LYON.write_text(text, encoding="utf-8")

# -----------------------------------------------------------------------------
# Charts/inspector: missing Lyon data stays missing.
# Detailed chart breaks the line after an hourly gap; inspector never carries a
# distant Lyon value forward/backward. Physical sensors keep their old behavior.
# -----------------------------------------------------------------------------
text = MAIN.read_text(encoding="utf-8")
original = text

if "LYON_DETAIL_GAP_MS" not in text:
    anchor = '''private data class ChartPrefs(\n'''
    insert = '''private const val LYON_DETAIL_GAP_MS = 90L * 60L * 1000L
private const val LYON_NEAREST_TOLERANCE_MS = 75L * 60L * 1000L

'''
    if anchor not in text:
        raise SystemExit("v0.8.7: ChartPrefs anchor not found")
    text = text.replace(anchor, insert + anchor, 1)

# Mini-preview: do not draw a giant bridge across a large missing interval.
old_preview = '''                                val path = Path()
                                points.forEachIndexed { index, point ->
                                    val x = ((point.timestamp - previewFrom).toDouble() / previewSpan.toDouble())
                                        .toFloat() * size.width
                                    val y = size.height - (((point.temperature - minTemp) / tempRange)
                                        .toFloat() * size.height)
                                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                                }
'''
new_preview = '''                                val path = Path()
                                var previous: SamplePoint? = null
                                // La prévisu est sous-échantillonnée ; son seuil de coupure
                                // s'adapte à sa largeur temporelle pour ne pas casser chaque bucket.
                                val previewGapLimit = maxOf(
                                    6L * 60L * 60L * 1000L,
                                    previewSpan / 150L
                                )
                                points.forEach { point ->
                                    val x = ((point.timestamp - previewFrom).toDouble() / previewSpan.toDouble())
                                        .toFloat() * size.width
                                    val y = size.height - (((point.temperature - minTemp) / tempRange)
                                        .toFloat() * size.height)
                                    val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                                        previous?.let { point.timestamp - it.timestamp > previewGapLimit } == true
                                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                                    previous = point
                                }
'''
if "val previewGapLimit = maxOf(" not in text:
    if old_preview not in text:
        raise SystemExit("v0.8.7: preview path block not found")
    text = text.replace(old_preview, new_preview, 1)

# Detailed temperature path: >90 min with no Lyon observation = visible gap.
old_temp = '''                val path = Path()
                points.forEachIndexed { index, p ->
                    val x = mapX(p.timestamp)
                    val y = mapTemp(p.temperature)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
'''
new_temp = '''                val path = Path()
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val x = mapX(p.timestamp)
                    val y = mapTemp(p.temperature)
                    val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                        previous?.let { p.timestamp - it.timestamp > LYON_DETAIL_GAP_MS } == true
                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                    previous = p
                }
'''
if "p.timestamp - it.timestamp > LYON_DETAIL_GAP_MS" not in text:
    if old_temp not in text:
        raise SystemExit("v0.8.7: detailed temperature path not found")
    text = text.replace(old_temp, new_temp, 1)

# Detailed humidity path uses the same no-bridge rule.
old_hum = '''                val path = Path()
                points.forEachIndexed { index, p ->
                    val x = mapX(p.timestamp)
                    val y = mapHum(p.humidity)
                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
'''
new_hum = '''                val path = Path()
                var previous: SamplePoint? = null
                points.forEach { p ->
                    val x = mapX(p.timestamp)
                    val y = mapHum(p.humidity)
                    val breakHere = sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
                        previous?.let { p.timestamp - it.timestamp > LYON_DETAIL_GAP_MS } == true
                    if (previous == null || breakHere) path.moveTo(x, y) else path.lineTo(x, y)
                    previous = p
                }
'''
# There are now two identical gap expressions after temperature replacement,
# so key idempotency on the old humidity block itself.
if old_hum in text:
    text = text.replace(old_hum, new_hum, 1)

# Sensor-aware nearest lookup for annotations/details.
text = text.replace(
    'sensor?.let { nearest(sampleMap[it.id].orEmpty(), note.timestamp) }',
    'sensor?.let { nearestForSensor(it, sampleMap[it.id].orEmpty(), note.timestamp) }'
)
text = text.replace(
    'sensor?.let { nearest(sampleMap[it.id].orEmpty(), annotation.timestamp) }',
    'sensor?.let { nearestForSensor(it, sampleMap[it.id].orEmpty(), annotation.timestamp) }'
)

# Inspector must show a dash for Lyon when there is no nearby real observation.
old_inspector_loop = '''            sensors.filter { showTemp[it.id] == true || showHumidity[it.id] == true }.forEach { sensor ->
                nearest(sampleMap[sensor.id].orEmpty(), timestamp)?.let { point ->
                    Row(Modifier.fillMaxWidth()) {
                        Text(sensor.room, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                        if (showTemp[sensor.id] == true) {
                            Text(String.format(Locale.FRANCE, "%.1f °C", point.temperature), Modifier.width(78.dp))
                        }
                        if (showHumidity[sensor.id] == true) {
                            Text(String.format(Locale.FRANCE, "%.1f %%", point.humidity), Modifier.width(72.dp))
                        }
                    }
                }
            }
'''
new_inspector_loop = '''            sensors.filter { showTemp[it.id] == true || showHumidity[it.id] == true }.forEach { sensor ->
                val point = nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), timestamp)
                Row(Modifier.fillMaxWidth()) {
                    Text(sensor.room, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                    if (showTemp[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f °C", it.temperature) } ?: "—",
                            Modifier.width(78.dp)
                        )
                    }
                    if (showHumidity[sensor.id] == true) {
                        Text(
                            point?.let { String.format(Locale.FRANCE, "%.1f %%", it.humidity) } ?: "—",
                            Modifier.width(72.dp)
                        )
                    }
                }
            }
'''
if "val point = nearestForSensor(sensor, sampleMap[sensor.id].orEmpty(), timestamp)" not in text:
    if old_inspector_loop not in text:
        raise SystemExit("v0.8.7: Inspector loop not found")
    text = text.replace(old_inspector_loop, new_inspector_loop, 1)

if "private fun nearestForSensor(" not in text:
    anchor = '''private fun nearest(points: List<SamplePoint>, timestamp: Long): SamplePoint? {\n'''
    helper = '''private fun nearestForSensor(
    sensor: Sensor,
    points: List<SamplePoint>,
    timestamp: Long
): SamplePoint? {
    val point = nearest(points, timestamp) ?: return null
    if (sensor.stableKey == LyonWeatherSync.STABLE_KEY &&
        abs(point.timestamp - timestamp) > LYON_NEAREST_TOLERANCE_MS
    ) return null
    return point
}

'''
    if anchor not in text:
        raise SystemExit("v0.8.7: nearest helper anchor not found")
    text = text.replace(anchor, helper + anchor, 1)

if text != original:
    MAIN.write_text(text, encoding="utf-8")

print("FabData v0.8.7 Lyon continuity/no-synthetic-gap patch applied")
