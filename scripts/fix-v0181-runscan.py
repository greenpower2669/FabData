from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / "app/src/main/java/com/fabdata/app/StationDiscoveryUi.kt",
    ROOT / "scripts/apply-v0181-station-discovery-fix.py",
]

for path in paths:
    text = path.read_text(encoding="utf-8")

    replacements = {
        "runScan { memory.anchor() }": "runScan(anchorProvider = { memory.anchor() })",
        "runScan { discovery.gpsAnchor() }": "runScan(anchorProvider = { discovery.gpsAnchor() })",
        "runScan { discovery.geocode(query) }": "runScan(anchorProvider = { discovery.geocode(query) })",
        "runScan { discovery.reverse(lat, lon) }": "runScan(anchorProvider = { discovery.reverse(lat, lon) })",
        "runScan { anchor }": "runScan(anchorProvider = { anchor })",
        "runScan(openMapWhenReady = true) { discovery.reverse(lat, lon) }": "runScan(openMapWhenReady = true, anchorProvider = { discovery.reverse(lat, lon) })",
        "runScan(openMapWhenReady = true) { discovery.geocode(query) }": "runScan(openMapWhenReady = true, anchorProvider = { discovery.geocode(query) })",
        "runScan(openMapWhenReady = true) { savedSector.anchor() }": "runScan(openMapWhenReady = true, anchorProvider = { savedSector.anchor() })",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    old_multiline = '''else -> runScan(openMapWhenReady = true) {
                                    StationSearchAnchor(
                                        "Autour de ${currentReference.label}",
                                        currentReference.latitude,
                                        currentReference.longitude,
                                        currentReference.departmentId
                                    )
                                }'''
    new_multiline = '''else -> runScan(
                                    openMapWhenReady = true,
                                    anchorProvider = {
                                        StationSearchAnchor(
                                            "Autour de ${currentReference.label}",
                                            currentReference.latitude,
                                            currentReference.longitude,
                                            currentReference.departmentId
                                        )
                                    }
                                )'''
    text = text.replace(old_multiline, new_multiline)

    if path.name == "StationDiscoveryUi.kt":
        if "runScan {" in text or "runScan(openMapWhenReady = true) {" in text:
            raise SystemExit("A shorthand runScan call remains")
        if "runScan(anchorProvider = {" not in text:
            raise SystemExit("No explicit runScan anchorProvider calls found")

    path.write_text(text, encoding="utf-8")

print("v0.18.1 runScan callbacks made explicit")
