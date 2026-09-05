from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


# Version only: the physical equations remain those validated in v0.19.5.
build = Path("app/build.gradle.kts")
text = build.read_text()
text = replace_once(text, 'versionCode = 41', 'versionCode = 42', 'versionCode')
text = replace_once(text, 'versionName = "0.19.5"', 'versionName = "0.19.6"', 'versionName')
build.write_text(text)

# Main graph: keep the building thermal mass as an internal model state.
# The visible reconstructed physical sensor is the surface/ground-equivalent output.
main = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = main.read_text()

text = replace_once(
    text,
    '''        if (!showTemp.containsKey(THERMAL_INERTIA_SENSOR_ID)) showTemp[THERMAL_INERTIA_SENSOR_ID] = true
        showHumidity[THERMAL_INERTIA_SENSOR_ID] = false
''',
    '''        // v0.19.6: la masse thermique du bâtiment reste un état caché du modèle.
        // La courbe reconstruite de la sonde représente la surface/sol équivalent ;
        // on ne superpose donc plus l'état profond sur le graphe principal.
        showTemp[THERMAL_INERTIA_SENSOR_ID] = false
        showHumidity[THERMAL_INERTIA_SENSOR_ID] = false
''',
    'hide internal mass state'
)

text = replace_once(
    text,
    '''    // Les deux pseudo-capteurs météo sont uniquement des vues de la référence sélectionnée.
    // Aucun doublon n'est persisté et les anciennes clés internes restent compatibles.
    val inertiaVisible = viewBounds?.let { b -> inertiaEstimate?.window(b.first, b.last).orEmpty() }.orEmpty()
    val inertiaOverview = globalBounds?.let { b -> inertiaEstimate?.window(b.first, b.last, 1200).orEmpty() }.orEmpty()
    val inertiaSensor = Sensor(
        id = THERMAL_INERTIA_SENSOR_ID,
        stableKey = THERMAL_INERTIA_STABLE_KEY,
        name = "Température inertielle estimée",
        room = "Température inertielle estimée",
        colorIndex = 4,
        latestTimestamp = inertiaEstimate?.points?.lastOrNull()?.timestamp
    )
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor + inertiaSensor
''',
    '''    // Les deux pseudo-capteurs météo sont uniquement des vues de la référence sélectionnée.
    // Aucun doublon n'est persisté et les anciennes clés internes restent compatibles.
    // v0.19.6 : ThermalInertiaEstimate reste consommé par le moteur thermique mais n'est
    // plus exposé comme pseudo-capteur. La masse bâtiment sera réservée à une future vue Topo.
    val physicalChartSensors = sensors.filterNot { it.stableKey == LyonWeatherSync.STABLE_KEY }
    val chartSensors = physicalChartSensors + weatherOfficialSensor + lyonReconstructedSensor
''',
    'remove internal inertia pseudo-sensor'
)

text = replace_once(
    text,
    '''    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +
        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaVisible)
''',
    '''    val chartSampleMap = sampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to weatherOfficialSamples) +
        (LYON_RECONSTRUCTED_SENSOR_ID to weatherReconstructedSamples)
''',
    'remove inertia detailed series'
)

text = replace_once(
    text,
    '''    val chartOverviewSampleMap = overviewSampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to overviewReference.filter { it.source == PointSource.MEASURED }.map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +
        (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference.filter { it.source == PointSource.RECONSTRUCTED }) +
        (THERMAL_INERTIA_SENSOR_ID to inertiaOverview)
''',
    '''    val chartOverviewSampleMap = overviewSampleMap.filterKeys { id -> physicalChartSensors.any { it.id == id } } +
        (WEATHER_OFFICIAL_SENSOR_ID to overviewReference.filter { it.source == PointSource.MEASURED }.map { it.copy(sensorId = WEATHER_OFFICIAL_SENSOR_ID) }) +
        (LYON_RECONSTRUCTED_SENSOR_ID to overviewReference.filter { it.source == PointSource.RECONSTRUCTED })
''',
    'remove inertia overview series'
)

main.write_text(text)

# Diagnostics: name the state for what it is and explain what remains visible.
ui = Path("app/src/main/java/com/fabdata/app/ThermalExperimentUi.kt")
text = ui.read_text()
text = replace_once(
    text,
    'Text("Température inertielle estimée · expérimental", fontWeight = FontWeight.Bold)',
    'Text("Modèle thermique interne · expérimental", fontWeight = FontWeight.Bold)',
    'internal model title'
)
text = replace_once(
    text,
    '''                "Apprise uniquement sur les points MEASURED propres. Clim, fenêtres probables et données douteuses restent visibles mais ne forment pas le modèle. Cette inertie accompagne désormais la météo pour prolonger l’historique.",
''',
    '''                "La courbe reconstruite visible représente la surface / le sol équivalent. La masse thermique du bâtiment reste un état caché appris uniquement sur les points MEASURED propres ; elle sert au calcul mais n’est plus tracée sur le graphe principal.",
''',
    'model explanation'
)
text = replace_once(
    text,
    'Text(String.format(Locale.FRANCE, "État inertiel actuel : %.1f °C", d.currentC), fontWeight = FontWeight.SemiBold)',
    'Text(String.format(Locale.FRANCE, "État thermique bâtiment (caché) : %.1f °C", d.currentC), fontWeight = FontWeight.SemiBold)',
    'hidden state label'
)
text = replace_once(
    text,
    '''                    "τ ≈ ${formatTau(d.tauHours)} · extérieur inertiel ${(d.outsideWeight * 100).toInt()} % · couplage air ↔ masse ${d.couplingLabel} · confiance ${d.confidenceLabel} ${(d.confidence * 100).toInt()} %",
''',
    '''                    "surface τ ≈ ${formatTau(d.surfaceTauHours)} · profondeur τ ≈ ${formatTau(d.deepTauHours)} · part profonde ${(d.deepShare * 100).toInt()} % · confiance ${d.confidenceLabel} ${(d.confidence * 100).toInt()} %",
''',
    'two-mass diagnostic label'
)
ui.write_text(text)

# Clarify the invariant directly next to the estimator implementation.
inertia = Path("app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt")
text = inertia.read_text()
text = replace_once(
    text,
    ''' * T_mass affichée est la moyenne énergétique de deux états latents : une couche
 * superficielle réactive (murs/mobilier/cloisons) et une masse profonde lente.
 * Un changement extérieur modifie donc immédiatement la dérivée de la couche de surface
 * sans faire sauter aucune température ; si le forçage persiste, il se transmet ensuite
 * à la masse profonde. Les paramètres sont appris uniquement sur les vraies mesures.
''',
    ''' * T_mass est la moyenne énergétique interne de deux états latents : une couche
 * superficielle réactive et une masse profonde lente du bâtiment. Depuis v0.19.6 cet
 * état n'est plus tracé sur le graphe principal : le moteur l'utilise comme référence
 * cachée pour reconstruire la température de surface / sol équivalente observable.
 * Un changement extérieur modifie immédiatement la dérivée de la couche de surface
 * sans faire sauter aucune température ; s'il persiste, il se transmet à la masse profonde.
''',
    'estimator semantic comment'
)
inertia.write_text(text)

print("v0.19.6 ground-visible / hidden-building-mass patch applied")
