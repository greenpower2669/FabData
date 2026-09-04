#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "app/src/main/java/com/fabdata/app/ThermalInertiaExperiment.kt"
text = path.read_text()
marker = "    private fun allHourly(sensorId: Long): List<SamplePoint> {"

# Reliquat historique v0.15 : deux copies identiques du helper ont pu être
# conservées dans le source généré. On garde la première (celle déjà corrigée)
# et on supprime uniquement les copies suivantes, fonction entière comprise.
def function_end(src: str, start: int) -> int:
    brace = src.find("{", start)
    if brace < 0:
        raise SystemExit("allHourly: accolade ouvrante introuvable")
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                while end < len(src) and src[end] in " \t":
                    end += 1
                if end < len(src) and src[end] == "\r":
                    end += 1
                if end < len(src) and src[end] == "\n":
                    end += 1
                return end
    raise SystemExit("allHourly: accolade fermante introuvable")

positions = []
pos = text.find(marker)
while pos >= 0:
    positions.append(pos)
    pos = text.find(marker, pos + len(marker))

while len(positions) > 1:
    start = positions[-1]
    end = function_end(text, start)
    # Retire aussi une ligne vide adjacente, sans toucher au helper suivant.
    while start > 0 and text[start - 1] == "\n" and start > 1 and text[start - 2] == "\n":
        start -= 1
        break
    text = text[:start] + text[end:]
    positions = []
    pos = text.find(marker)
    while pos >= 0:
        positions.append(pos)
        pos = text.find(marker, pos + len(marker))

# SamplePoint.confidence est nullable. Si une ancienne variante survit, elle est
# normalisée vers le comportement déjà validé en v0.15.
text = text.replace(
    "best.first().source, best.map { it.confidence }.average()",
    "best.first().source, best.mapNotNull { it.confidence }.averageOr(1.0)"
)

if text.count(marker) != 1:
    raise SystemExit(f"allHourly: {text.count(marker)} définition(s), attendu 1")
if "best.mapNotNull { it.confidence }.averageOr(1.0)" not in text:
    raise SystemExit("allHourly: moyenne de confiance sûre absente")

path.write_text(text)
print("FabData v0.16 inertial build normalization applied")
