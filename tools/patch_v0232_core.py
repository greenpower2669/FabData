from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(p): return (ROOT / p).read_text(encoding='utf-8')
def write(p, s): (ROOT / p).write_text(s, encoding='utf-8')

def once(s, old, new, label):
    if new in s: return s
    n = s.count(old)
    if n != 1: raise RuntimeError(f'{label}: expected 1 occurrence, got {n}')
    return s.replace(old, new, 1)

p='app/build.gradle.kts'; s=read(p)
s=once(s,'versionCode = 58\n        versionName = "0.23.1"','versionCode = 59\n        versionName = "0.23.2"','version')
write(p,s)

p='app/src/main/java/com/fabdata/app/ForecastHorizonArchive.kt'; s=read(p)
s=s.replace('fixed lead H+1..H+24','fixed lead H+1..H+48')
s=once(s,'val FORECAST_HORIZON_HOURS: IntRange = 1..24','val FORECAST_HORIZON_HOURS: IntRange = 1..48','horizon range')
s=once(s,'from = from - 25L * HORIZON_HOUR_MS,','from = from - 49L * HORIZON_HOUR_MS,','horizon lookback')
write(p,s)

p='app/src/main/java/com/fabdata/app/ForecastAdaptive.kt'; s=read(p)
s=s.replace('Causal Fab adaptive forecast at four fixed horizons.','Causal Fab adaptive forecast at five fixed horizons.')
s=once(s,'val FORECAST_ADAPTIVE_HORIZONS: List<Int> = listOf(3, 6, 12, 24)','val FORECAST_ADAPTIVE_HORIZONS: List<Int> = listOf(3, 6, 12, 24, 48)','adaptive H48')
s=once(s,'now + 26L * ADAPTIVE_HOUR_MS,','now + 50L * ADAPTIVE_HOUR_MS,','adaptive materialize')
s=once(s,'.coerceIn(0.5, 30.0)','.coerceIn(0.5, 54.0)','adaptive tangent range')
write(p,s)

p='app/src/main/java/com/fabdata/app/ForecastAdaptiveUi.kt'; s=read(p)
s=once(s,'"H+3 · H+6 · H+12 · H+24 · apprentissage causal + tangente + détection de changement de régime. Les cadrans restent sur le H+24 historique actuel.",','"H+3 · H+6 · H+12 · H+24 · H+48 · apprentissage causal + tangente + détection de changement de régime. Les cadrans restent sur le H+24 historique actuel.",','adaptive UI')
write(p,s)

p='app/src/main/java/com/fabdata/app/LiveUpdateCoordinator.kt'; s=read(p)
s=s.replace("ensuite toutes les 5 minutes tant que l'utilisateur regarde l'app","ensuite toutes les 10 minutes tant que l'utilisateur regarde l'app")
s=once(s,'delay(300_000L)','delay(600_000L)','foreground cadence')
write(p,s)

p='app/src/main/java/com/fabdata/app/ForecastArchiveWorker.kt'; s=read(p)
s=once(s,'PeriodicWorkRequestBuilder<ForecastArchiveWorker>(1, TimeUnit.HOURS)','PeriodicWorkRequestBuilder<ForecastArchiveWorker>(15, TimeUnit.MINUTES)','worker cadence')
s=once(s,'ExistingPeriodicWorkPolicy.KEEP,','ExistingPeriodicWorkPolicy.UPDATE,','worker update')
write(p,s)

p='app/src/main/java/com/fabdata/app/UiPreferenceStore.kt'; s=read(p)
s=once(s,
'''    fun forecastArchiveExpanded(): Boolean = prefs.getBoolean("forecast_archive_expanded", false)
    fun saveForecastArchiveExpanded(value: Boolean) { prefs.edit().putBoolean("forecast_archive_expanded", value).apply() }

    fun bandChooserOpen(): Boolean = prefs.getBoolean("band_chooser_open", false)
''',
'''    fun forecastArchiveExpanded(): Boolean = prefs.getBoolean("forecast_archive_expanded", false)
    fun saveForecastArchiveExpanded(value: Boolean) { prefs.edit().putBoolean("forecast_archive_expanded", value).apply() }

    fun adaptiveForecastExpanded(): Boolean = prefs.getBoolean("adaptive_forecast_expanded", false)
    fun saveAdaptiveForecastExpanded(value: Boolean) { prefs.edit().putBoolean("adaptive_forecast_expanded", value).apply() }

    fun bandChooserOpen(): Boolean = prefs.getBoolean("band_chooser_open", false)
''','adaptive expanded pref')
write(p,s)

# v0.23.2 audit: H25-H48 must restore persisted visibility just like H1-H23.
p='app/src/main/java/com/fabdata/app/MainActivity.kt'; s=read(p)
s=s.replace(
    'FORECAST_HORIZON_HOURS.filter { it < 24 }.forEach { lead ->',
    'FORECAST_HORIZON_HOURS.filter { it != 24 }.forEach { lead ->'
)
write(p,s)
