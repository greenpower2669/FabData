from pathlib import Path

ENGINE = Path('app/src/main/java/com/fabdata/app/ThermalEngine.kt')
text = ENGINE.read_text(encoding='utf-8')
old = '''                val tout = outsideAt(outMap, extTs) ?: run { completed = false; break }
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
'''
new = '''                val tout = outsideAt(outMap, extTs)
                if (tout == null) {
                    completed = false
                    break
                }
                val avg6 = outsideAverage(outMap, extTs, 6) ?: tout
'''
if new not in text:
    if old not in text:
        raise SystemExit('v0.10.1 compile hardening anchor missing')
    text = text.replace(old, new, 1)
    ENGINE.write_text(text, encoding='utf-8')
print('FabData v0.10.1 forward compile hardening applied')
