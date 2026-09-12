from pathlib import Path


def replace_once(path: str, old: str, new: str, marker: str) -> None:
    p = Path(path)
    s = p.read_text()
    if marker in s:
        return
    if old not in s:
        raise SystemExit(f"missing patch anchor {marker} in {path}")
    p.write_text(s.replace(old, new, 1))


past = Path("app/src/main/java/com/fabdata/app/ForecastPastArchive.kt")
s = past.read_text()

# This archive is for verification: use a fixed 24-hour lead from Météo-France model runs,
# not Historical Forecast, whose stitched first hours intentionally hug observations.
if 'open-meteo-previous-runs-h24-meteofrance' not in s:
    s = s.replace('import android.database.sqlite.SQLiteDatabase\n', 'import android.database.sqlite.SQLiteDatabase\nimport android.util.Log\n', 1)
    s = s.replace(
        'const val PROVIDER = "open-meteo-historical-forecast"',
        'const val PROVIDER = "open-meteo-previous-runs-h24-meteofrance"',
        1,
    )
    s = s.replace(
        '"CREATE INDEX IF NOT EXISTS idx_forecast_past_api_target ON $TABLE(reference_key, target_ts)"\n        )\n',
        '"CREATE INDEX IF NOT EXISTS idx_forecast_past_api_target ON $TABLE(reference_key, target_ts)"\n        )\n        // v0.21.6: the old stitched Historical Forecast series is not a fair forecast\n        // verification source. Remove it so a restored older backup cannot shadow H+24 data.\n        sql.delete(TABLE, "provider=?", arrayOf("open-meteo-historical-forecast"))\n',
        1,
    )
    s = s.replace(
        'WHERE reference_key=? AND target_ts BETWEEN ? AND ?\n            ORDER BY target_ts',
        'WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND provider=?\n            ORDER BY target_ts',
        1,
    )
    s = s.replace(
        'arrayOf(referenceKey, from.toString(), to.toString())\n        ).use { c ->',
        'arrayOf(referenceKey, from.toString(), to.toString(), PROVIDER)\n        ).use { c ->',
        1,
    )
    s = s.replace(
        'private val earliest = LocalDate.of(2022, 1, 1).atStartOfDay(zone).toInstant().toEpochMilli()',
        'private val earliest = LocalDate.of(2024, 1, 2).atStartOfDay(zone).toInstant().toEpochMilli()\n    private val fixedLeadMs = 24L * hourMs',
        1,
    )
    s = s.replace(
        'Completes missing past forecast anchors from Open-Meteo Historical Forecast API.\n     * The remote archive is stored separately and is used for display/backtest only.',
        'Completes missing past forecast anchors from Open-Meteo Previous Runs at a fixed H+24 lead.\n     * Météo-France seamless is used so the series represents an actual forecast made one day\n     * before valid time, not a stitched near-analysis. The remote archive is display/backtest only.',
        1,
    )
    s = s.replace(
        'if (hasDenseCoverage(reference.key, safeFrom, safeTo)) return 0\n\n        var added = 0',
        'if (hasDenseCoverage(reference.key, safeFrom, safeTo)) {\n            rebuildFabCausally(reference.key, safeFrom, safeTo)\n            return 0\n        }\n\n        var added = 0\n        var failures = 0',
        1,
    )
    s = s.replace(
        'val rows = runCatching {\n                fetchHistorical(reference, cursor, chunkEnd, safeFrom, safeTo)\n            }.getOrDefault(emptyList())',
        'val rows = runCatching {\n                fetchFixedLeadH24(reference, cursor, chunkEnd, safeFrom, safeTo)\n            }.getOrElse { error ->\n                failures++\n                Log.w("FabDataForecast", "Previous Runs H+24 failed for $cursor..$chunkEnd", error)\n                emptyList()\n            }',
        1,
    )
    s = s.replace(
        'rebuildFabCausally(reference.key, safeFrom, safeTo)\n        return added',
        'rebuildFabCausally(reference.key, safeFrom, safeTo)\n        if (failures > 0) {\n            Log.w("FabDataForecast", "H+24 archive completed with $failures failed chunk(s), $added point(s) added")\n        }\n        return added',
        1,
    )
    s = s.replace(
        'WHERE reference_key=? AND target_ts BETWEEN ? AND ?\n            """.trimIndent(),\n            arrayOf(referenceKey, from.toString(), to.toString())',
        'WHERE reference_key=? AND target_ts BETWEEN ? AND ? AND provider=?\n            """.trimIndent(),\n            arrayOf(referenceKey, from.toString(), to.toString(), ForecastPastArchiveStore.PROVIDER)',
        1,
    )

    start = s.index('    private fun fetchHistorical(')
    end = s.index('    /**\n     * Backtests the Fab local corrector', start)
    fixed_fetch = '''    private fun fetchFixedLeadH24(\n        reference: WeatherReference,\n        fromDate: LocalDate,\n        toDate: LocalDate,\n        clipFrom: Long,\n        clipTo: Long\n    ): List<ForecastPastArchivePoint> {\n        // Previous Runs keeps lead time fixed. _previous_day1 is the value forecast\n        // 24 hours before valid time. /v1/meteofrance defaults to Météo-France seamless.\n        val url = "https://previous-runs-api.open-meteo.com/v1/meteofrance" +\n            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +\n            "&start_date=$fromDate&end_date=$toDate" +\n            "&hourly=temperature_2m_previous_day1,relative_humidity_2m_previous_day1" +\n            "&timezone=Europe%2FParis"\n        val raw = httpGet(url)\n        val hourly = JSONObject(raw).getJSONObject("hourly")\n        val times = hourly.getJSONArray("time")\n        val temps = hourly.getJSONArray("temperature_2m_previous_day1")\n        val hums = hourly.getJSONArray("relative_humidity_2m_previous_day1")\n        val out = mutableListOf<ForecastPastArchivePoint>()\n        for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {\n            val local = runCatching { LocalDateTime.parse(times.getString(i)) }.getOrNull() ?: continue\n            val ts = local.atZone(zone).toInstant().toEpochMilli()\n            if (ts !in clipFrom..clipTo) continue\n            val t = temps.optDouble(i, Double.NaN)\n            val h = hums.optDouble(i, Double.NaN)\n            if (!t.isFinite() || !h.isFinite() || t !in -70.0..70.0 || h !in 0.0..100.0) continue\n            out += ForecastPastArchivePoint(\n                targetAt = ts,\n                weatherTemperature = t,\n                humidity = h,\n                fabTemperature = t,\n                weatherConfidence = 0.72,\n                fabConfidence = 0.40,\n                provider = ForecastPastArchiveStore.PROVIDER\n            )\n        }\n        return out.distinctBy { it.targetAt }.sortedBy { it.targetAt }\n    }\n\n'''
    s = s[:start] + fixed_fetch + s[end:]

    s = s.replace(
        'For target T, only measured residuals available at or before T-1h are used.',
        'For target T, only residuals whose verifying observation was already known by T-24h are used.',
        1,
    )
    s = s.replace(
        'val rows = ForecastPastArchiveStore.query(db, referenceKey, from - 25L * hourMs, to)',
        'val rows = ForecastPastArchiveStore.query(db, referenceKey, from - fixedLeadMs - 25L * hourMs, to)',
        1,
    )
    s = s.replace(
        'val measured = measuredByHour(referenceKey, from - 26L * hourMs, to)',
        'val measured = measuredByHour(referenceKey, from - fixedLeadMs - 26L * hourMs, to)',
        1,
    )
    s = s.replace(
        'val cutoff = row.targetAt - hourMs',
        'val cutoff = row.targetAt - fixedLeadMs',
        1,
    )
    s = s.replace(
        'val correction = (model.bias + model.slope + 0.5 * model.acceleration).coerceIn(-5.0, 5.0)',
        'val horizonHours = fixedLeadMs.toDouble() / hourMs.toDouble()\n            val correction = (model.bias + model.slope * horizonHours +\n                0.5 * model.acceleration * horizonHours * horizonHours).coerceIn(-5.0, 5.0)',
        1,
    )
    s = s.replace('error("Historical forecast HTTP $code")', 'error("Previous Runs H+24 HTTP $code")', 1)

past.write_text(s)

# Make the visible legend explicit about the fixed historical lead while keeping the future side active.
main = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
s = main.read_text()
s = s.replace(
    '// Historical forecast API is only a backfill. Once cached it is restored from\n                // FabData backup, so an app update does not need to download it again.',
    '// Fixed-lead H+24 Météo-France archive is only a backfill. Once cached it is\n                // restored from FabData backup, so an app update does not download it again.',
)
s = s.replace(
    '"Prévision météo reconstruite", "Archives de prévisions + futur actif · rendu 10 min"',
    '"Prévision météo reconstruite", "Passé Météo-France H+24 · futur actif · rendu 10 min"',
)
s = s.replace(
    '"Prévision Fab reconstruite", "Modèle local utilisateur · rendu 10 min"',
    '"Prévision Fab reconstruite", "Correction locale H+24 · rendu 10 min"',
)
main.write_text(s)

# Older v0.21.5 backups may contain the stitched Historical Forecast cache. It is deliberately
# ignored so the corrected build redownloads a fair fixed-lead archive once, then saves that.
backup = Path("app/src/main/java/com/fabdata/app/BackupV3Support.kt")
s = backup.read_text()
needle = '        val provider = o.optString("provider", ForecastPastArchiveStore.PROVIDER).ifBlank { ForecastPastArchiveStore.PROVIDER }\n'
if 'provider == "open-meteo-historical-forecast"' not in s:
    if needle not in s:
        raise SystemExit("missing backup provider restore anchor")
    s = s.replace(
        needle,
        needle + '        if (provider == "open-meteo-historical-forecast") return\n',
        1,
    )
backup.write_text(s)
