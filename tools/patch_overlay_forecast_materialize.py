from pathlib import Path
p=Path('app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt')
s=p.read_text()
marker='ForecastSelectableCurveStore(db).materializeLocalSnapshots('
if marker not in s:
    old='        val reference = WeatherReferencePrefs(appContext).selectedReference()\n        val nowHour = hourBucket(now)\n'
    new='        val reference = WeatherReferencePrefs(appContext).selectedReference()\n        runCatching {\n            ForecastSelectableCurveStore(db).materializeLocalSnapshots(reference.key, now - 48L * HOUR_MS, now + 24L * HOUR_MS, now)\n        }\n        val nowHour = hourBucket(now)\n'
    if old not in s: raise SystemExit('overlay marker missing')
    s=s.replace(old,new,1)
p.write_text(s)

# v0.21.6: after the already-validated overlay patch, migrate the past verification
# source from stitched Historical Forecast to a fair fixed-lead H+24 Météo-France archive.
exec(Path('tools/patch_forecast_fixed_lead_h24.py').read_text(), {'__name__': '__main__'})
