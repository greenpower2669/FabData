from pathlib import Path

p = Path("app/src/main/java/com/fabdata/app/ForecastCurve10mStore.kt")
s = p.read_text()
s = s.replace('const val MODEL_VERSION = "fab-local-causal-h24-v2"', 'const val MODEL_VERSION = "fab-local-causal-h24-terrain-v3"', 1)
s = s.replace('const val ORIGIN = "meteofrance-h24-cosine-10m"', 'const val ORIGIN = "meteofrance-h24-terrain-cosine-10m"', 1)
if 'fab-local-causal-h24-terrain-v3' not in s:
    raise SystemExit('forecast cache v3 marker missing')
p.write_text(s)
print('Forecast 10-minute cache moved to H24 terrain v3')
