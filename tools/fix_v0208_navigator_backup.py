from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/src/main/java/com/fabdata/app/MainActivity.kt"
BACKUP = ROOT / "app/src/main/java/com/fabdata/app/BackupLayer.kt"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{label}: start marker not found")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:a] + replacement + text[b:]


# -----------------------------------------------------------------------------
# MainActivity: true navigator-of-navigator + backup visible as one operation.
# -----------------------------------------------------------------------------
main = MAIN.read_text(encoding="utf-8")
if "Navigation globale · glisse la fenêtre" not in main:
    main = replace_once(
        main,
        '"Tap = viser · double tap = ouvrir · Sélection = choisir une période · pince/glisse = prévisu"',
        '"Bandeau fin = déplacer la fenêtre · bandeau principal = viser/sélectionner · pince = zoom de prévisu"',
        "history overview help text",
    )

    main = replace_once(
        main,
        """                val previewWindow = previewFrom..previewTo
                val visiblePoints = sensors.flatMap { sensor ->
                    sampleMap[sensor.id].orEmpty().filter { it.timestamp in previewWindow }
                }
""",
        """                val previewWindow = previewFrom..previewTo
                // v0.20.8 : le bandeau exploré ne recalcule que sa fenêtre courante.
                // Le bandeau supérieur reste volontairement grossier et global.
                val previewSensorPoints = remember(sampleMap, sensors, previewFrom, previewTo) {
                    sensors.associate { sensor ->
                        sensor.id to sampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in previewWindow }
                            .sortedBy { it.timestamp }
                    }
                }
                val visiblePoints = remember(previewSensorPoints) {
                    previewSensorPoints.values.flatten()
                }
""",
        "preview scoped points",
    )

    main = replace_once(
        main,
        """                            val points = sampleMap[sensor.id].orEmpty()
                                .filter { it.timestamp in previewWindow }
                                .sortedBy { it.timestamp }
""",
        """                            val points = previewSensorPoints[sensor.id].orEmpty()
""",
        "preview canvas scoped points",
    )

    navigator_block = r'''                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)

                // Bandeau d'exploration DU bandeau d'exploration.
                // Il représente tout l'historique avec des points déjà décimés par la couche overview.
                // La fenêtre colorée se comporte comme un vrai curseur : on la glisse au doigt/souris,
                // et seul ce morceau alimente ensuite le bandeau principal + ses MIN/MAX.
                val navigatorSensorPoints = remember(sampleMap, sensors, bounds.first, bounds.last) {
                    sensors.associate { sensor ->
                        sensor.id to sampleMap[sensor.id].orEmpty()
                            .filter { it.timestamp in bounds }
                            .sortedBy { it.timestamp }
                    }
                }
                val navigatorAllPoints = remember(navigatorSensorPoints) {
                    navigatorSensorPoints.values.flatten()
                }
                val navigatorMin = navigatorAllPoints.minOfOrNull { it.temperature } ?: 0.0
                val navigatorMax = navigatorAllPoints.maxOfOrNull { it.temperature } ?: 1.0
                val navigatorTempRange = (navigatorMax - navigatorMin).takeIf { it > 0.01 } ?: 1.0

                Text(
                    "Navigation globale · glisse la fenêtre",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Canvas(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(58.dp)
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.22f), RoundedCornerShape(12.dp))
                        .pointerInput(bounds.first, bounds.last, previewSpan) {
                            detectDragGestures { change, dragAmount ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val deltaTs = ((dragAmount.x / width) * fullSpan.toDouble()).toLong()
                                previewCenter = clampCenter(previewCenter + deltaTs, previewSpan)
                                change.consume()
                            }
                        }
                        .pointerInput(bounds.first, bounds.last, previewSpan) {
                            detectTapGestures(onTap = { p ->
                                val width = size.width.toFloat().coerceAtLeast(1f)
                                val fraction = (p.x / width).coerceIn(0f, 1f)
                                val target = bounds.first + (fullSpan * fraction).toLong()
                                previewCenter = clampCenter(target, previewSpan)
                            })
                        }
                ) {
                    if (navigatorAllPoints.isNotEmpty()) {
                        navigatorSensorPoints.forEach { (sensorId, points) ->
                            if (points.size >= 2) {
                                val sensor = sensors.firstOrNull { it.id == sensorId } ?: return@forEach
                                val path = Path()
                                points.forEachIndexed { index, point ->
                                    val x = (((point.timestamp - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                                        .coerceIn(0f, size.width)
                                    val y = size.height - (((point.temperature - navigatorMin) / navigatorTempRange)
                                        .toFloat() * size.height)
                                    if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                                }
                                drawPath(
                                    path,
                                    palette[sensor.colorIndex % palette.size].copy(alpha = 0.42f),
                                    style = Stroke(width = 1.dp.toPx())
                                )
                            }
                        }
                    }

                    val left = (((previewFrom - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(0f, size.width)
                    val right = (((previewTo - bounds.first).toDouble() / fullSpan.toDouble()).toFloat() * size.width)
                        .coerceIn(left, size.width)
                    if (left > 0f) {
                        drawRect(
                            MaterialTheme.colorScheme.scrim.copy(alpha = 0.07f),
                            topLeft = Offset(0f, 0f),
                            size = androidx.compose.ui.geometry.Size(left, size.height)
                        )
                    }
                    if (right < size.width) {
                        drawRect(
                            MaterialTheme.colorScheme.scrim.copy(alpha = 0.07f),
                            topLeft = Offset(right, 0f),
                            size = androidx.compose.ui.geometry.Size(size.width - right, size.height)
                        )
                    }
                    drawRect(
                        highlight.copy(alpha = 0.16f),
                        topLeft = Offset(left, 0f),
                        size = androidx.compose.ui.geometry.Size((right - left).coerceAtLeast(1f), size.height)
                    )
                    drawLine(highlight, Offset(left, 0f), Offset(left, size.height), 2.dp.toPx())
                    drawLine(highlight, Offset(right, 0f), Offset(right, size.height), 2.dp.toPx())
                    val handleX = (left + right) / 2f
                    drawLine(highlight.copy(alpha = 0.9f), Offset(handleX - 5.dp.toPx(), size.height / 2f), Offset(handleX + 5.dp.toPx(), size.height / 2f), 2.dp.toPx())
                    drawCircle(highlight, 3.5.dp.toPx(), Offset(handleX, size.height / 2f))
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDateTime(bounds.first), style = MaterialTheme.typography.labelSmall)
                    Text("historique complet", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(formatDateTime(bounds.last), style = MaterialTheme.typography.labelSmall)
                }

                if (minPoint != null && maxPoint != null) {
'''
    main = replace_once(
        main,
        """                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)

                if (minPoint != null && maxPoint != null) {
""",
        navigator_block,
        "insert navigator-of-navigator",
    )

    export_launcher = r'''    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        if (uri != null) {
            scope.launch {
                val opId = FabOperationRegistry.tryStart(
                    key = "backup-export",
                    title = "Sauvegarde FabData",
                    detail = "Écriture temporaire + contrôle d’intégrité…",
                    cancellable = false
                )
                if (opId == null) {
                    snackbar.showSnackbar("Une sauvegarde est déjà en cours")
                    return@launch
                }
                busy = true
                val result = withContext(Dispatchers.IO) { runCatching { backup.export(uri) } }
                busy = false
                snackbar.showSnackbar(
                    result.fold(
                        onSuccess = {
                            FabOperationRegistry.finish(
                                opId,
                                "Vérifiée · ${it.measurements} mesures · ${it.events} événement(s) · ${it.sensors} capteur(s)"
                            )
                            "Sauvegarde vérifiée : ${it.measurements} mesures · ${it.events} événement(s) · ${it.sensors} capteur(s)"
                        },
                        onFailure = {
                            FabOperationRegistry.fail(opId, "Échec : ${it.message ?: "erreur inconnue"}")
                            "Sauvegarde impossible : ${it.message ?: "erreur inconnue"}"
                        }
                    )
                )
            }
        }
    }'''
    main = replace_between(
        main,
        '    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->',
        "\n\n    val picker =",
        export_launcher,
        "backup launcher operation",
    )

MAIN.write_text(main, encoding="utf-8")


# -----------------------------------------------------------------------------
# BackupLayer: v4 integrity footer + build into cache before touching destination.
# v1/v2/v3 remain readable; only v4 requires the completion marker.
# -----------------------------------------------------------------------------
backup = BACKUP.read_text(encoding="utf-8")
if 'const val FORMAT_VERSION = "4"' not in backup:
    backup = replace_once(
        backup,
        "import java.io.BufferedReader\n",
        "import java.io.BufferedReader\nimport java.io.File\n",
        "backup File import",
    )
    backup = replace_once(
        backup,
        'const val FORMAT_VERSION = "3"',
        'const val FORMAT_VERSION = "4"',
        "backup version 4",
    )
    backup = replace_once(
        backup,
        'formatVersion !in setOf("1", "2", FORMAT_VERSION)',
        'formatVersion !in setOf("1", "2", "3", FORMAT_VERSION)',
        "backup compatible versions",
    )

    backup = replace_once(
        backup,
        """            val records = splitCsvRecords(reader.readText())
            val v3Support = FabDataBackupV3Support(context, db)
""",
        """            val records = splitCsvRecords(reader.readText())

            // v4 : un fichier n'est restaurable que s'il a été complètement finalisé.
            // Les anciennes sauvegardes v1/v2/v3 restent volontairement acceptées.
            fun recordType(line: String): String = splitCsv(line, ',').firstOrNull().orEmpty().trim().uppercase(Locale.ROOT)
            val metaLine = records.firstOrNull { recordType(it) == "META" }
            val metaFields = metaLine?.let { splitCsv(it, ',') }.orEmpty()
            val fileVersion = col(metaFields, "Format_Version").trim()
            if (fileVersion == FORMAT_VERSION) {
                val footerLine = records.lastOrNull { it.isNotBlank() }
                    ?: error("Sauvegarde v4 vide ou incomplète")
                if (recordType(footerLine) != "BACKUP_END") {
                    error("Sauvegarde v4 incomplète : marqueur de fin absent")
                }
                val footer = splitCsv(footerLine, ',')
                val note = col(footer, "Note")
                val expected = note.split(';').mapNotNull { token ->
                    val pair = token.split('=', limit = 2)
                    if (pair.size == 2) pair[0].trim() to pair[1].trim().toIntOrNull() else null
                }.toMap()
                val actualSensors = records.count { recordType(it) == "SENSOR" }
                val actualSamples = records.count { recordType(it) == "SAMPLE" }
                val actualEvents = records.count { recordType(it) == "EVENT" }
                if (expected["sensors"] != actualSensors ||
                    expected["measurements"] != actualSamples ||
                    expected["events"] != actualEvents
                ) {
                    error("Sauvegarde v4 incomplète : compteurs d’intégrité incohérents")
                }
            }

            val v3Support = FabDataBackupV3Support(context, db)
""",
        "backup import integrity validation",
    )

    backup = replace_once(
        backup,
        '                            "META" -> {\n                                // Réservé aux évolutions futures du format.\n                            }',
        '                            "META", "BACKUP_END" -> {\n                                // META décrit la sauvegarde ; BACKUP_END certifie une v4 complète.\n                            }',
        "backup footer recognized",
    )

    backup = replace_once(
        backup,
        """    fun export(uri: Uri): FabDataBackupExportResult {
        val output = context.contentResolver.openOutputStream(uri, "wt")
            ?: error("Impossible de créer le fichier de sauvegarde")

        var sensorCount = 0
""",
        """    fun export(uri: Uri): FabDataBackupExportResult {
        // Génération locale d'abord : jamais de demi-sauvegarde présentée comme valide.
        // Le document choisi n'est touché qu'après écriture + contrôle du footer.
        val tempFile = File.createTempFile("fabdata-backup-", ".csv", context.cacheDir)

        var sensorCount = 0
""",
        "backup temp file start",
    )

    backup = replace_once(
        backup,
        """        var measurementCount = 0
        var eventCount = 0

        OutputStreamWriter(output, Charsets.UTF_8).buffered().use { writer ->
""",
        """        var measurementCount = 0
        var eventCount = 0

        try {
            OutputStreamWriter(tempFile.outputStream(), Charsets.UTF_8).buffered().use { writer ->
""",
        "backup temp writer",
    )

    backup = replace_once(
        backup,
        """            // v3 state is appended after the ordinary human-readable records.
            FabDataBackupV3Support(context, db).writeExtraRows(writer)
        }

        return FabDataBackupExportResult(sensorCount, measurementCount, eventCount)
    }
""",
        """            // L'état thermique/météo complet reste append-only après les lignes lisibles.
            FabDataBackupV3Support(context, db).writeExtraRows(writer)

            // Le footer est la preuve qu'on a atteint la fin de TOUTES les tables.
            writeRow(
                writer,
                listOf(
                    "BACKUP_END", FORMAT_VERSION, "", "FabData", "", "", "", "", "", "",
                    "Sauvegarde complète et vérifiée",
                    "sensors=$sensorCount;measurements=$measurementCount;events=$eventCount",
                    "integrity",
                    System.currentTimeMillis().toString()
                )
            )
        }

            val lastRecord = tempFile.useLines(Charsets.UTF_8) { lines ->
                lines.filter { it.isNotBlank() }.lastOrNull()
            } ?: error("Sauvegarde vide après génération")
            val footer = splitCsv(lastRecord, ',')
            if (footer.firstOrNull()?.trim() != "BACKUP_END") {
                error("Sauvegarde incomplète : footer absent après génération")
            }
            val expectedNote = "sensors=$sensorCount;measurements=$measurementCount;events=$eventCount"
            if (footer.getOrNull(11).orEmpty() != expectedNote) {
                error("Sauvegarde incomplète : compteurs de fin incohérents")
            }

            val output = context.contentResolver.openOutputStream(uri, "wt")
                ?: error("Impossible de créer le fichier de sauvegarde")
            output.use { out ->
                tempFile.inputStream().use { input -> input.copyTo(out, 256 * 1024) }
                out.flush()
            }
            return FabDataBackupExportResult(sensorCount, measurementCount, eventCount)
        } finally {
            tempFile.delete()
        }
    }
""",
        "backup footer and final copy",
    )

BACKUP.write_text(backup, encoding="utf-8")

print("v0.20.8 navigator + backup integrity patch applied")
