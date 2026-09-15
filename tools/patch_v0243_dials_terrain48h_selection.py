from pathlib import Path


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Production version.
gradle = Path("app/build.gradle.kts")
replace_once(
    gradle,
    'versionCode = 69\n        versionName = "0.24.2"',
    'versionCode = 70\n        versionName = "0.24.3"'
)

# Local-only 48 h terrain reconstruction. This must NEVER make a provider/network request.
weather = Path("app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt")
replace_once(
    weather,
    """    fun ensureLocalCache(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {""",
    """    /**
     * Rebuild the recent terrain window strictly from data already present on the device.
     *
     * This is deliberately separate from refreshRecent/refreshSelected: opening FabData,
     * refreshing the UI or changing a viewport must never consume another provider forecast
     * capture. MEASURED keeps absolute priority; reconstruction only fills what local material
     * can support. The returned forecast count is therefore always zero.
     */
    fun reconstructRecentLocalOnly(
        reference: WeatherReference,
        anchorTimestamp: Long = System.currentTimeMillis(),
        hours: Int = 48
    ): WeatherReferenceSyncResult {
        val safeHours = hours.coerceIn(1, 168)
        val now = System.currentTimeMillis()
        val to = minOf(anchorTimestamp, now).coerceAtLeast(0L)
        val from = (to - safeHours.toLong() * hourMs).coerceAtLeast(0L)
        store.rememberReference(reference)

        if (reference.key == WeatherReferenceCatalog.DEFAULT_KEY) {
            // Lyon has a complete local reconstruction engine. Feed it first, then overlay
            // every real observation. WeatherReferenceStore.upsert protects that priority too.
            val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
            lyonLab.reconstruct(from, to).points.forEach { p ->
                store.upsert(
                    reference.key,
                    WeatherReferencePoint(
                        p.timestamp, p.temperature, p.humidity,
                        PointSource.RECONSTRUCTED, 0.72
                    )
                )
            }
            db.querySamples(sensor.id, from, to, maxPoints = 30_000).forEach { p ->
                val source = PointSourceStore.sourceFor(db, sensor.id, p.timestamp)
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, source))
            }
            lyonLab.queryOfficial(LyonSeriesKind.HOURLY, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
            }
            lyonLab.queryOfficial(LyonSeriesKind.SIX_MIN, from, to).forEach { p ->
                store.upsert(reference.key, WeatherReferencePoint(p.timestamp, p.temperature, p.humidity, PointSource.MEASURED))
            }
        } else {
            // Dynamic stations cannot invent unavailable observations. We only interpolate
            // short holes bounded by real local observations; existing reconstructed points
            // remain available and are never allowed to outrank MEASURED.
            reconstructShortGaps(reference.key, from, to)
        }

        store.reconcileMeasuredDominance(reference.key, from, to)
        val actual = store.query(reference.key, from, to)
            .filter { it.source != PointSource.FORECAST }
        return WeatherReferenceSyncResult(
            measured = actual.count { it.source == PointSource.MEASURED },
            reconstructed = actual.count { it.source == PointSource.RECONSTRUCTED },
            forecast = 0,
            label = reference.label
        )
    }

    fun ensureLocalCache(reference: WeatherReference, from: Long, to: Long): WeatherReferenceSyncResult {"""
)

# On startup and real data refreshes, refresh the recent 48 h terrain locally before reading bounds.
main = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
replace_once(
    main,
    """            val selectedWeatherReference = WeatherReferencePrefs(context).selectedReference()
            val weatherBounds = weatherReferenceStore.historyBounds(selectedWeatherReference.key)""",
    """            val selectedWeatherReference = WeatherReferencePrefs(context).selectedReference()
            if (priorityRank >= UiReloadPriority.DATA.rank) {
                FabOperationRegistry.update(reloadOperation, "Terrain récent · reconstruction locale 48 h…")
                FabOperationRegistry.ensureNotCancelled(reloadOperation)
                val terrainAnchor = userPhysicalBounds?.last ?: System.currentTimeMillis()
                runCatching {
                    weatherReferenceManager.reconstructRecentLocalOnly(
                        selectedWeatherReference,
                        anchorTimestamp = terrainAnchor,
                        hours = 48
                    )
                }
            }
            val weatherBounds = weatherReferenceStore.historyBounds(selectedWeatherReference.key)"""
)

# Move the range-selection switch directly above band 3: it controls band 3 and nothing else.
replace_once(
    main,
    """                }

                HorizontalDivider()
                Text(
                    "Sélection / exploration · LOD 6 h · météo colorée + sondes · 1/2 du bandeau 2",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )""",
    """                }

                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Start,
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
                }
                if (rangeSelectionMode) {
                    Text(
                        "↔ Mode sélection : glisse sur le bandeau 3. Désactive pour retrouver zoom, pincement et déplacement.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }

                HorizontalDivider()
                Text(
                    "Sélection / exploration · LOD 6 h · météo colorée + sondes · 1/2 du bandeau 2",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )"""
)

# Below the detail graph, keep help/alerts only; selection now belongs to band 3.
replace_once(
    main,
    """                Row(
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
                    ) { Text("! Alertes / astuce") }
                }
                if (rangeSelectionMode) {
                    Text(
                        "↔ Une seule zone à la fois : glisse, valide l'action, puis refais une sélection pour en ajouter une autre.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }""",
    """                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
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
                    ) { Text("! Alertes / astuce") }
                }"""
)

# Restore the three scientific dials as a translucent cockpit layer behind the pretty dashboard.
overlay = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")
replace_once(
    overlay,
    """        ForecastDashboardPainter.draw(
            canvas = canvas,
            width = width.toFloat(),
            height = height.toFloat(),
            snapshot = dashboardState,
            night = night,
            density = resources.displayMetrics.density,
            scaledDensity = resources.displayMetrics.scaledDensity
        )
        drawResizeHandle(canvas, night)
    }

    private fun drawCompact(""",
    """        // Keep the beautiful curve dashboard in the foreground, but never throw away
        // the scientific cockpit: PASSÉ / PRÉSENT / FUTUR remain visible as ghost instruments.
        drawBackgroundDials(canvas, night, current)
        ForecastDashboardPainter.draw(
            canvas = canvas,
            width = width.toFloat(),
            height = height.toFloat(),
            snapshot = dashboardState,
            night = night,
            density = resources.displayMetrics.density,
            scaledDensity = resources.displayMetrics.scaledDensity
        )
        drawResizeHandle(canvas, night)
    }

    private fun drawBackgroundDials(canvas: Canvas, night: Boolean, current: DialState?) {
        val dials = current?.samples ?: listOf(
            emptyDial("PASSÉ"), emptyDial("PRÉSENT"), emptyDial("FUTUR")
        )
        val slotWidth = width / 3f
        val cy = height * 0.47f
        val radius = min(slotWidth * 0.42f, height * 0.23f)
        val alphas = intArrayOf(28, 38, 50)
        dials.take(3).forEachIndexed { index, sample ->
            val cx = slotWidth * (index + 0.5f)
            val alpha = alphas[index.coerceIn(0, 2)]

            paint.style = Paint.Style.FILL
            paint.color = withAlpha(comparisonFill(sample, night), (alpha * 0.72f).toInt())
            canvas.drawCircle(cx, cy, radius, paint)

            paint.style = Paint.Style.STROKE
            paint.strokeWidth = dp(1.5f)
            paint.color = withAlpha(officialBorder(sample, night), alpha)
            canvas.drawCircle(cx, cy, radius, paint)

            val outer = RectF(
                cx - radius * 0.82f, cy - radius * 0.82f,
                cx + radius * 0.82f, cy + radius * 0.82f
            )
            paint.strokeWidth = dp(0.8f)
            paint.color = withAlpha(if (night) Color.WHITE else Color.DKGRAY, (alpha * 0.75f).toInt())
            canvas.drawArc(outer, 135f, 270f, false, paint)
            for (i in 0..8) {
                val angle = valueAngle(-2.0 + i * 0.5, -2.0, 2.0)
                val p1 = polar(cx, cy, radius * 0.72f, angle)
                val p2 = polar(cx, cy, radius * 0.81f, angle)
                canvas.drawLine(p1.first, p1.second, p2.first, p2.second, paint)
            }

            drawNeedle(canvas, sample.officialSlope, cx, cy, radius * 0.72f, OFFICIAL_RED, alpha)
            drawNeedle(canvas, sample.localSlope, cx, cy, radius * 0.67f, LOCAL_YELLOW, alpha)
            drawNeedle(canvas, sample.actualSlope, cx, cy, radius * 0.61f, REAL_GREEN, alpha)
        }
    }

    private fun drawCompact("""
)

replace_once(
    overlay,
    """append(if (compact) "Mode compact. Double-tape pour ouvrir la vue météo. " else "Mode complet : météo douze heures, inertie et Fab adaptative. Double-tape le cadre pour réduire. ")""",
    """append(if (compact) "Mode compact. Double-tape pour ouvrir la vue météo. " else "Mode complet : cadrans passé présent futur en arrière-plan, météo douze heures, inertie et Fab adaptative. Double-tape le cadre pour réduire. ")"""
)

print("v0.24.3 patch applied")
