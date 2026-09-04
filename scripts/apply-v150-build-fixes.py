#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str, label: str):
    p = ROOT / path
    text = p.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable dans {path}")
    p.write_text(text.replace(old, new, 1))

# SamplePoint.confidence est nullable : ne moyenner que les confiances présentes.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    'best.first().source, best.map { it.confidence }.average()',
    'best.first().source, best.mapNotNull { it.confidence }.averageOr(1.0)',
    "nullable confidence"
)

# Documentation désormais conforme au rôle v0.15 : paramètres appris sur MEASURED,
# puis état inertiel utilisé comme entrée du modèle couplé.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt",
    '''/**\n * Expérience observationnelle v0.14.\n *\n * - ne lit que les points intérieurs MEASURED ;\n * - peut lire la référence météo comme variable explicative ;\n * - ne persiste rien et n'appelle jamais PointSourceStore.upsert* ;\n * - n'est utilisée ni par reconstructHistory, ni par refreshForecasts.\n *\n * T_mass est un état latent lent. Plusieurs constantes de temps et couplages extérieurs\n * sont testés ; le choix est fait sur la capacité à expliquer dT_air/dt sur des périodes\n * non perturbées, avec un bonus de cohérence près des plateaux/tangentes.\n */''',
    '''/**\n * Estimateur inertiel couplé v0.15.\n *\n * - les paramètres sont appris uniquement sur les points intérieurs MEASURED ;\n * - les périodes perturbées/douteuses sont exclues par les masques mais restent visibles ;\n * - la météo sert de variable explicative lente ;\n * - l'estimateur ne persiste aucune donnée et ne modifie jamais les points MEASURED ;\n * - T_mass devient une entrée obligatoire du modèle d'historique et de prévision.\n *\n * T_mass est un état latent lent. Plusieurs constantes de temps et couplages extérieurs\n * sont testés sur les seules mesures propres, puis ces paramètres peuvent être propagés\n * sur l'historique sans réentraîner le modèle sur ses propres sorties.\n */''',
    "v015 inertia documentation"
)

# Le bouton ▶ doit persister exactement comme ◀ afin que MainActivity et la courbe
# inertielle utilisent toujours la même sonde du modèle.
replace_once(
    "app/src/main/java/com/fabdata/app/ThermalUi.kt",
    '''val next = (index + 1) % selectable.size\n                                    selectedSensorId = selectable[next].sensor.id\n                                }''',
    '''val next = (index + 1) % selectable.size\n                                    selectedSensorId = selectable[next].sensor.id\n                                    modelSensorPrefs.edit().putLong("selected_sensor_id", selectable[next].sensor.id).apply()\n                                }''',
    "right carousel persistence"
)

# Sanity checks.
for path, needle in [
    ("app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt", "mapNotNull { it.confidence }.averageOr(1.0)"),
    ("app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt", "Estimateur inertiel couplé v0.15"),
    ("app/src/main/java/com/fabdata/app/ThermalUi.kt", 'val next = (index + 1) % selectable.size'),
]:
    if needle not in (ROOT / path).read_text():
        raise SystemExit(f"Invariant absent: {needle}")

ui = (ROOT / "app/src/main/java/com/fabdata/app/ThermalUi.kt").read_text()
if ui.count('modelSensorPrefs.edit().putLong("selected_sensor_id"') < 3:
    raise SystemExit("La sonde modèle n'est pas persistée dans les deux sens du tourniquet")

print("FabData v0.15 build fixes applied")
