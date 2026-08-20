from pathlib import Path

DATA = Path("app/src/main/java/com/fabdata/app/DataLayer.kt")
LYON = Path("app/src/main/java/com/fabdata/app/LyonWeatherSync.kt")
MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")

# ---------------- DataLayer: physical thermometer period + existing timestamps
text = DATA.read_text(encoding="utf-8")
original = text
anchor = '''    fun globalTimeBounds(): LongRange? {
'''
insert = '''    /**
     * Période de référence des thermomètres réellement acquis/importés.
     * Les stations météo et sondes HTTP distantes ne doivent pas allonger
     * artificiellement cette fenêtre.
     */
    fun physicalSensorBounds(): LongRange? {
        readableDatabase.rawQuery(
            """
            SELECT MIN(p.timestamp), MAX(p.timestamp)
            FROM samples p
            JOIN sensors s ON s.id = p.sensor_id
            WHERE s.stable_key NOT LIKE 'meteo-%'
              AND s.stable_key NOT LIKE 'http-get-%'
            """.trimIndent(), null
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0) || c.isNull(1)) return null
            return c.getLong(0)..c.getLong(1)
        }
    }

    fun existingSampleTimestamps(sensorId: Long, from: Long, to: Long): Set<Long> {
        val out = linkedSetOf<Long>()
        readableDatabase.rawQuery(
            "SELECT timestamp FROM samples WHERE sensor_id = ? AND timestamp BETWEEN ? AND ?",
            arrayOf(sensorId.toString(), from.toString(), to.toString())
        ).use { c ->
            while (c.moveToNext()) out += c.getLong(0)
        }
        return out
    }

'''
if "fun physicalSensorBounds()" not in text:
    if anchor not in text:
        raise SystemExit("v0.8.3: DataLayer globalTimeBounds anchor not found")
    text = text.replace(anchor, insert + anchor, 1)
if text != original:
    DATA.write_text(text, encoding="utf-8")

# ---------------- LyonWeatherSync: historical completion on physical period
text = LYON.read_text(encoding="utf-8")
original = text

if "data class LyonWeatherCompleteResult" not in text:
    result_anchor = ''')

/**
 * Importe les observations horaires réellement affichées pour la station
'''
    result_insert = ''')

data class LyonWeatherCompleteResult(
    val fromDate: LocalDate,
    val toDate: LocalDate,
    val daysRequested: Int,
    val daysDownloaded: Int,
    val daysAlreadyComplete: Int,
    val added: Int,
    val duplicates: Int
)

/**
 * Importe les observations horaires réellement affichées pour la station
'''
    if result_anchor not in text:
        raise SystemExit("v0.8.3: Lyon result anchor not found")
    text = text.replace(result_anchor, result_insert, 1)

if "private val MONTH_SLUGS" not in text:
    companion_anchor = '''        private val LYON_ZONE: ZoneId = ZoneId.of("Europe/Paris")
'''
    companion_insert = companion_anchor + '''        private val MONTH_SLUGS = arrayOf(
            "janvier", "fevrier", "mars", "avril", "mai", "juin",
            "juillet", "aout", "septembre", "octobre", "novembre", "decembre"
        )
'''
    if companion_anchor not in text:
        raise SystemExit("v0.8.3: Lyon companion anchor not found")
    text = text.replace(companion_anchor, companion_insert, 1)

if "fun completePhysicalPeriod()" not in text:
    download_anchor = '''    private fun downloadHtml(): String {
'''
    methods = '''    /**
     * Complète Lyon sur exactement la période couverte par les thermomètres
     * physiques/importés. Les valeurs déjà présentes ne sont jamais écrasées.
     */
    fun completePhysicalPeriod(): LyonWeatherCompleteResult {
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
        var duplicates = 0

        while (!date.isAfter(toDate)) {
            requested++
            val start = date.atStartOfDay(LYON_ZONE).toInstant().toEpochMilli()
            val end = date.plusDays(1).atStartOfDay(LYON_ZONE).toInstant().toEpochMilli() - 1
            val existing = db.existingSampleTimestamps(sensor.id, start, end)
            val expected = (0..23).map { hour ->
                date.atTime(hour, 0).atZone(LYON_ZONE).toInstant().toEpochMilli()
            }.toSet()

            if (expected.all { it in existing }) {
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
                    } else {
                        duplicates++
                    }
                }
            }

            // Reste poli avec la source si plusieurs jours sont nécessaires.
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
            duplicates = duplicates
        )
    }

    private fun archiveUrl(date: LocalDate): String {
        val month = MONTH_SLUGS[date.monthValue - 1]
        return "https://www.infoclimat.fr/observations-meteo/archives/${date.dayOfMonth}/$month/${date.year}/lyon-bron/07480.html"
    }

    private fun parseArchiveDay(html: String, date: LocalDate): LinkedHashMap<Long, WeatherPoint> {
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

            val timestamp = date.atTime(hour, 0)
                .atZone(LYON_ZONE)
                .toInstant()
                .toEpochMilli()
            points[timestamp] = WeatherPoint(timestamp, temperature, humidity)
        }
        if (points.isEmpty()) error("Aucune archive Lyon-Bron exploitable pour $date")
        return points
    }

    private fun downloadHtml(url: String = SOURCE_URL): String {
'''
    if download_anchor not in text:
        raise SystemExit("v0.8.3: Lyon download anchor not found")
    text = text.replace(download_anchor, methods, 1)
    text = text.replace('val connection = (URL(SOURCE_URL).openConnection() as HttpURLConnection).apply {',
                        'val connection = (URL(url).openConnection() as HttpURLConnection).apply {', 1)

if "import java.time.Instant" not in text:
    text = text.replace("import java.time.LocalDate\n", "import java.time.Instant\nimport java.time.LocalDate\n", 1)

if text != original:
    LYON.write_text(text, encoding="utf-8")

# ---------------- MainActivity: 《 Compléter 》 button on Lyon station
text = MAIN.read_text(encoding="utf-8")
original = text

call_anchor = '''                        onSyncLyon = {
                            scope.launch {
                                busy = true
                                val result = withContext(Dispatchers.IO) { runCatching { lyonWeather.syncToday() } }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = { "Lyon : ${it.added} nouvelle(s) mesure(s)" },
                                        onFailure = { "Lyon : ${it.message ?: "source indisponible"}" }
                                    )
                                )
                            }
                        },
'''
complete_call = call_anchor + '''                        onCompleteLyon = {
                            scope.launch {
                                busy = true
                                val result = withContext(Dispatchers.IO) {
                                    runCatching { lyonWeather.completePhysicalPeriod() }
                                }
                                busy = false
                                reloadToken++
                                snackbar.showSnackbar(
                                    result.fold(
                                        onSuccess = {
                                            "Lyon complété : ${it.added} mesure(s) · ${it.daysDownloaded} jour(s) téléchargé(s) · ${it.daysAlreadyComplete} déjà complet(s)"
                                        },
                                        onFailure = { "Compléter Lyon : ${it.message ?: "archives indisponibles"}" }
                                    )
                                )
                            }
                        },
'''
if "onCompleteLyon = {" not in text:
    if call_anchor not in text:
        raise SystemExit("v0.8.3: MainActivity onSyncLyon anchor not found")
    text = text.replace(call_anchor, complete_call, 1)

sig_anchor = '''    onSyncLyon: () -> Unit,
    onAddRemote: () -> Unit,
'''
sig_insert = '''    onSyncLyon: () -> Unit,
    onCompleteLyon: () -> Unit,
    onAddRemote: () -> Unit,
'''
if "onCompleteLyon: () -> Unit" not in text:
    if sig_anchor not in text:
        raise SystemExit("v0.8.3: SensorSourcesCard signature anchor not found")
    text = text.replace(sig_anchor, sig_insert, 1)

old_desc = '''                "Lyon est préconfigurée par défaut. Une sonde HTTP ajoutée une fois reste ensuite automatique.",
'''
new_desc = '''                "Lyon est préconfigurée par défaut. 《 Compléter 》 aligne ses archives sur la période réelle des thermomètres connectés.",
'''
if old_desc in text:
    text = text.replace(old_desc, new_desc, 1)

button_anchor = '''                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
'''
button_insert = '''                TextButton(onClick = onCompleteLyon) { Text("《 Compléter 》") }
                OutlinedButton(onClick = onSyncLyon) { Text("Actualiser") }
'''
if 'Text("《 Compléter 》")' not in text:
    if button_anchor not in text:
        raise SystemExit("v0.8.3: Lyon button anchor not found")
    text = text.replace(button_anchor, button_insert, 1)

if text != original:
    MAIN.write_text(text, encoding="utf-8")

print("v0.8.3: weather completion patch applied")
