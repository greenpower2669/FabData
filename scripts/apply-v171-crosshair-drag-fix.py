from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app/src/main/java/com/fabdata/app/MainActivity.kt"
s = p.read_text()

def once(old: str, new: str, label: str) -> None:
    global s
    if old not in s:
        if new in s:
            return
        raise SystemExit(f"missing anchor: {label}")
    if s.count(old) != 1:
        raise SystemExit(f"anchor not unique: {label}")
    s = s.replace(old, new, 1)

once(
    "import androidx.compose.runtime.rememberCoroutineScope\n",
    "import androidx.compose.runtime.rememberCoroutineScope\nimport androidx.compose.runtime.rememberUpdatedState\n",
    "rememberUpdatedState import"
)

once(
    "    var sightTemperature by remember(resetKey, from, to) { mutableStateOf<Double?>(null) }\n\n",
    "    var sightTemperature by remember(resetKey, from, to) { mutableStateOf<Double?>(null) }\n    val currentSelectedTimestamp by rememberUpdatedState(selectedTimestamp)\n\n",
    "updated selected timestamp state"
)

once(
    ".pointerInput(from, to, resetKey, selectedTimestamp, sightTemperature) {",
    ".pointerInput(from, to, resetKey) {",
    "stable pointerInput keys"
)

once(
    "                    val selectedX = selectedTimestamp\n                        ?.takeIf { it in window }",
    "                    val selectedX = currentSelectedTimestamp\n                        ?.takeIf { it in window }",
    "live selected timestamp in drag"
)

p.write_text(s)
print("FabData v0.17.1 crosshair drag stabilization applied")
