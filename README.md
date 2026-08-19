# FabData

FabData is an Android thermo-hygrometer dashboard designed for long-running local monitoring from CSV exports.

## v0.1

- Multi-file CSV import through Android's system file picker.
- Automatic sensor identification from export filenames.
- Incremental SQLite database: `(sensor, timestamp)` is unique, so overlapping re-imports only add missing dates.
- Temperature and humidity overlay across multiple rooms/sensors.
- Independent T° / humidity checkboxes per sensor.
- Dual Y axes: temperature on the left, relative humidity on the right.
- 1 h / 6 h / 12 h / 24 h / full-history ranges.
- Pinch-to-zoom, horizontal pan, reset zoom and tap inspection cursor.
- Per-room min / average / max and latest values.
- Configurable temperature and humidity warning thresholds.
- Persistent annotations attached to a timestamp and optionally to a sensor.
- Editable room name, sensor name and series color.
- Display decimation for long histories while statistics continue to use the complete SQLite range.
- No raw user CSV is committed to this public repository.

## Reference CSV schema

FabData currently recognizes the tested French thermo-hygrometer export schema:

```text
Temps,Température_Celsius,Humidité relative_Pourcentage
2026/08/19 11:14,26.1,42.7
```

It also accepts common English aliases, comma / semicolon / tab separators, quoted CSV cells, and several common date-time patterns.

## Build

The GitHub Actions workflow builds the debug APK on the development branch and publishes it both as a workflow artifact and under `artifacts/FabData-v0.1-debug.apk`.

Development branch: `agent/v0.1-thermo-dashboard`
