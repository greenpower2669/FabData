#!/usr/bin/env python3
from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = path.read_text(encoding="utf-8")
old = '''                item { Spacer(Modifier.height(72.dp)) }
            }

            if (thermalBusy) {
                ThermalBusyOverlay('''
new = '''                item { Spacer(Modifier.height(72.dp)) }
            }
            }

            if (thermalBusy) {
                ThermalBusyOverlay('''
if new in text:
    print("Overlay scope brace: déjà appliqué")
elif old in text:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Overlay scope brace: OK")
else:
    raise SystemExit("Overlay scope brace: bloc introuvable")
