from pathlib import Path

p = Path(__file__).resolve().parents[1] / "app/src/main/java/com/fabdata/app/ForecastAdaptiveUi.kt"
text = p.read_text(encoding="utf-8")
lines = text.splitlines()
changed = False
for i, line in enumerate(lines):
    if line.strip().startswith("val short = raw."):
        indent = line[: len(line) - len(line.lstrip())]
        lines[i] = indent + 'val short = raw.lineSequence().firstOrNull().orEmpty().trim().take(220)'
        changed = True
        break
if not changed and "raw.lineSequence().firstOrNull().orEmpty().trim().take(220)" not in text:
    raise RuntimeError("adaptive error formatting anchor not found")
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Applied v0.23.1 compile hotfix")
