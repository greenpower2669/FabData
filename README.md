# FabData

FabData is an Android thermo-hygrometer dashboard designed for long-running local monitoring from CSV exports.

## v0.2

- Multi-file CSV import through Android's system file picker.
- Automatic sensor identification from export filenames.
- Incremental SQLite database: `(sensor, timestamp)` is unique, so overlapping re-imports only add missing dates.
- Time tabs: **Heure / Jour / Semaine / Mois / Année**.
- Pinch zoom focused on the time axis, horizontal pan and reset by button or double tap on the graph background.
- Temperature and humidity overlays across multiple rooms/sensors.
- Independent T° / humidity checkboxes per sensor.
- Dual Y axes: temperature on the left, relative humidity on the right.
- Tap inspection cursor with nearest measurements for active series.
- Long press on the graph to create an event at the selected timestamp.
- Events are drawn directly on the graph as thick markers; sensor events use the sensor colour.
- Single tap on an event marker opens a compact preview.
- Double tap on an event marker opens a scrollable detailed sheet.
- Event details include title, note, date/time, room, sensor, optional type, and the closest temperature/humidity measurement.
- Events can be edited or deleted.
- Quick room labels: SDB, Chambre, Chambre principale and Salon; free-text room names remain supported.
- Per-room min / average / max and latest values.
- Configurable temperature and humidity warning thresholds.
- Editable room name, sensor name and series colour.
- Extrema-preserving display downsampling for long histories while statistics continue to use the complete SQLite range.
- SQLite v2 migration keeps existing v0.1 measurements and annotations.
- Dedicated FabData Android launcher icon.
- No raw user CSV is committed to this public repository.

## Reference CSV schema

FabData currently recognizes the tested French thermo-hygrometer export schema:

```text
Temps,Température_Celsius,Humidité relative_Pourcentage
2026/08/19 11:14,26.1,42.7
```

It also accepts common English aliases, comma / semicolon / tab separators, quoted CSV cells, and several common date-time patterns.

## Build

The GitHub Actions workflow builds the debug APK on the development branch and publishes it both as a workflow artifact and under:

`artifacts/FabData-v0.2-debug.apk`

Development branch: `agent/v0.2-interactive-annotations`
