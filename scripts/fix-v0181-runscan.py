from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / "app/src/main/java/com/fabdata/app/StationDiscoveryUi.kt",
    ROOT / "scripts/apply-v0181-station-discovery-fix.py",
]

for path in paths:
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "fun runScan(anchorProvider: suspend () -> StationSearchAnchor, openMapWhenReady: Boolean = false) {",
        "fun runScan(openMapWhenReady: Boolean = false, anchorProvider: suspend () -> StationSearchAnchor) {",
    )
    text = text.replace(
        "runScan({ discovery.reverse(lat, lon) }, openMapWhenReady = true)",
        "runScan(openMapWhenReady = true) { discovery.reverse(lat, lon) }",
    )
    text = text.replace(
        "runScan({ discovery.geocode(query) }, openMapWhenReady = true)",
        "runScan(openMapWhenReady = true) { discovery.geocode(query) }",
    )
    text = text.replace(
        "runScan({ savedSector.anchor() }, openMapWhenReady = true)",
        "runScan(openMapWhenReady = true) { savedSector.anchor() }",
    )
    text = text.replace(
        "else -> runScan({\n",
        "else -> runScan(openMapWhenReady = true) {\n",
    )
    text = text.replace(
        "                                        currentReference.departmentId\n                                    )\n                                }, openMapWhenReady = true)",
        "                                        currentReference.departmentId\n                                    )\n                                }",
    )
    path.write_text(text, encoding="utf-8")

print("v0.18.1 runScan callback syntax fixed")
