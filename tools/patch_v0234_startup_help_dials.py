from pathlib import Path


def replace_once(path: str, old: str, new: str):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"pattern not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

# Version
replace_once(
    "app/build.gradle.kts",
    '        versionCode = 60\n        versionName = "0.23.3"',
    '        versionCode = 61\n        versionName = "0.23.4"',
)

# Dial monitoring defaults: new users start at H+1 / H+1. Existing saved choices stay untouched.
overlay = "app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt"
replace_once(
    overlay,
    'val weatherHorizon = dialPrefs.getInt(DIAL_WEATHER_HORIZON_KEY, 24).coerceIn(1, 48)',
    'val weatherHorizon = dialPrefs.getInt(DIAL_WEATHER_HORIZON_KEY, 1).coerceIn(1, 48)',
)
replace_once(
    overlay,
    'val requestedAdaptive = dialPrefs.getInt(DIAL_ADAPTIVE_HORIZON_KEY, 24)',
    'val requestedAdaptive = dialPrefs.getInt(DIAL_ADAPTIVE_HORIZON_KEY, 1)',
)
replace_once(
    overlay,
    'val adaptiveHorizon = requestedAdaptive.takeIf { it in FORECAST_ADAPTIVE_HORIZONS } ?: 24',
    'val adaptiveHorizon = requestedAdaptive.takeIf { it in FORECAST_ADAPTIVE_HORIZONS } ?: 1',
)

# Never draw Terrain for the FUTUR dial. Once that target rolls into PRESENT/PAST,
# the real terrain point becomes eligible automatically.
replace_once(
    overlay,
    '        val terrain = terrainAt(referenceKey, target)\n',
    '        val terrain = if (label == "FUTUR") null else terrainAt(referenceKey, target)\n',
)

# Activity registry: transient internal UI recompositions are not user jobs.
registry = "app/src/main/java/com/fabdata/app/FabOperationRegistry.kt"
replace_once(
    registry,
    '''    @Synchronized\n    fun clearFinished() {\n        operations.removeAll { !it.active }\n    }\n''',
    '''    @Synchronized\n    fun discard(id: Long?) {\n        if (id == null) return\n        operations.removeAll { it.id == id }\n    }\n\n    @Synchronized\n    fun clearFinished() {\n        operations.removeAll { !it.active }\n    }\n''',
)

main = "app/src/main/java/com/fabdata/app/MainActivity.kt"

# Coalesce the burst of state restoration/range clamping that happens at startup BEFORE
# registering an "Actualisation affichage" operation. Superseded effects die during the delay.
replace_once(
    main,
    '''    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {\n        reloadMutex.withLock {\n''',
    '''    LaunchedEffect(reloadToken, preset, windowCenterTimestamp, customViewSpanMs, wideOverviewRange, explorationOverviewRange) {\n        // Startup/preferences can settle through several Compose states in a few milliseconds.\n        // Debounce before registering work so Activity FabData shows one meaningful refresh,\n        // not a TERMINÉ/ANNULÉ/TERMINÉ burst.\n        delay(350L)\n        reloadMutex.withLock {\n''',
)

# Composition-driven cancellation is internal noise; a real user cancellation remains visible.
replace_once(
    main,
    '''        } catch (cancel: CancellationException) {\n            FabOperationRegistry.cancelled(reloadOperation, "Actualisation affichage annulée")\n            throw cancel\n''',
    '''        } catch (cancel: CancellationException) {\n            if (FabOperationRegistry.cancelRequested(reloadOperation)) {\n                FabOperationRegistry.cancelled(reloadOperation, "Actualisation affichage annulée")\n            } else {\n                FabOperationRegistry.discard(reloadOperation)\n            }\n            throw cancel\n''',
)

# Fast internal redraws (<750 ms) should not accumulate in the diagnostic Activity list.
replace_once(
    main,
    '''            if (reloadSucceeded) {\n                FabOperationRegistry.finish(\n                    reloadOperation,\n                    "Affichage prêt · ${System.currentTimeMillis() - reloadStarted} ms"\n                )\n            }\n''',
    '''            if (reloadSucceeded) {\n                val elapsed = System.currentTimeMillis() - reloadStarted\n                if (elapsed < 750L) {\n                    FabOperationRegistry.discard(reloadOperation)\n                } else {\n                    FabOperationRegistry.finish(reloadOperation, "Affichage prêt · $elapsed ms")\n                }\n            }\n''',
)

# Contextual help: make the long-press discovery explicit.
replace_once(
    main,
    '''                if (helpOpen) {\n                    Card(\n''',
    '''                if (helpOpen) {\n                    Text(\n                        "Cadrans flottants : appui long sur le cadran pour choisir séparément l’horizon météo et l’horizon Fab adaptatif. Double appui pour le mode compact/déplié.",\n                        style = MaterialTheme.typography.bodySmall,\n                        color = MaterialTheme.colorScheme.primary\n                    )\n                    Card(\n''',
)

# Settings help + privacy copy brought up to date with current network behaviour.
replace_once(
    main,
    '''                HorizontalDivider()\n                Text("Politique de confidentialité · FabData v0.8", fontWeight = FontWeight.Bold)\n''',
    '''                HorizontalDivider()\n                Text("Aide · cadrans flottants", fontWeight = FontWeight.Bold)\n                Text(\n                    "Appui long sur le cadran pour choisir la prévision météo et la prévision Fab adaptative à surveiller. " +\n                        "Double appui pour passer compact / déplié. Les choix, la position et la taille sont persistants et sauvegardés.",\n                    style = MaterialTheme.typography.bodySmall\n                )\n                HorizontalDivider()\n                Text("Politique de confidentialité · FabData v0.23.4", fontWeight = FontWeight.Bold)\n''',
)
replace_once(
    main,
    '''                    "Les mesures, noms de pièces et événements sont traités localement sur cet appareil. " +\n                        "FabData n'envoie aucune donnée utilisateur à un serveur, n'intègre ni publicité ni analytique " +\n                        "et ne crée aucun compte utilisateur. La sonde Lyon consulte uniquement une page publique " +\n                        "d'observations météo Lyon-Bron afin d'importer température et humidité.",\n''',
    '''                    "Les mesures intérieures, noms de pièces, événements, modèles et personnalisations restent traités localement sur cet appareil. " +\n                        "FabData n'intègre ni publicité ni analytique et ne crée aucun compte utilisateur. " +\n                        "Les fonctions météo contactent uniquement les fournisseurs nécessaires avec la station ou les coordonnées météo sélectionnées ; " +\n                        "les mesures intérieures ne leur sont pas envoyées.",\n''',
)

# Stale source comment: foreground cadence is 10 minutes now.
text = Path(main).read_text(encoding="utf-8")
text = text.replace(
    "// à l'ouverture, au retour au focus et ensuite toutes les 5 minutes au premier plan.",
    "// à l'ouverture, au retour au focus et ensuite sur les créneaux fixes de 10 minutes au premier plan.",
)
Path(main).write_text(text, encoding="utf-8")

print("v0.23.4 patch applied")
