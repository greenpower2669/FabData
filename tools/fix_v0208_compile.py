from pathlib import Path

path = Path(__file__).resolve().parents[1] / "app/src/main/java/com/fabdata/app/MainActivity.kt"
text = path.read_text(encoding="utf-8")

old_draw = "                            MaterialTheme.colorScheme.scrim.copy(alpha = 0.07f),"
count = text.count(old_draw)
if count != 2:
    raise SystemExit(f"expected 2 navigator dim draw colors, got {count}")
text = text.replace(old_draw, "                            navigatorDim,")

anchor = """                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)\n\n                // Bandeau d'exploration DU bandeau d'exploration.\n"""
replacement = """                val surface = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.28f)\n                val navigatorDim = MaterialTheme.colorScheme.scrim.copy(alpha = 0.07f)\n\n                // Bandeau d'exploration DU bandeau d'exploration.\n"""
if text.count(anchor) != 1:
    raise SystemExit("navigator color anchor missing or duplicated")
text = text.replace(anchor, replacement, 1)

path.write_text(text, encoding="utf-8")
print("v0.20.8 compile fix applied")
