package com.fabdata.app

import android.content.Context
import android.net.Uri
import java.io.OutputStreamWriter
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Export de données : measured uniquement par défaut. La sauvegarde complète reste séparée. */
class FabDataSourceExporter(private val context: Context, private val db: FabDataDb) {
    data class Result(val rows: Int, val reconstructed: Int, val forecast: Int)

    fun export(uri: Uri, includeReconstructed: Boolean = false, includeForecast: Boolean = false): Result {
        PointSourceStore.ensure(db.readableDatabase)
        val output = context.contentResolver.openOutputStream(uri, "wt")
            ?: error("Impossible de créer le fichier d'export")
        val formatter = DateTimeFormatter.ofPattern("yyyy/MM/dd HH:mm:ss", Locale.ROOT)
        var count = 0
        var reconstructed = 0
        var forecast = 0
        OutputStreamWriter(output, Charsets.UTF_8).buffered().use { writer ->
            writer.write("Capteur_ID,Capteur,Piece,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,source,confidence,Reference_Station_ID,Reference_Ville,Calibration_Debut_ms,Calibration_Fin_ms,Model_Version\n")
            db.readableDatabase.rawQuery(
                """
                SELECT s.stable_key, s.name, s.room, p.timestamp, p.temperature, p.humidity,
                       ps.source, ps.confidence, ps.reference_station_id, ps.reference_city,
                       ps.calibration_from, ps.calibration_to, ps.model_version
                FROM samples p
                JOIN sensors s ON s.id=p.sensor_id
                LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
                WHERE (ps.source IS NULL OR ps.source='measured')
                   OR (?=1 AND ps.source='reconstructed')
                   OR (?=1 AND ps.source='forecast')
                ORDER BY p.timestamp, s.id
                """.trimIndent(),
                arrayOf(if (includeReconstructed) "1" else "0", if (includeForecast) "1" else "0")
            ).use { c ->
                while (c.moveToNext()) {
                    val source = PointSource.fromDb(if (c.isNull(6)) null else c.getString(6))
                    if (source == PointSource.RECONSTRUCTED) reconstructed++
                    if (source == PointSource.FORECAST) forecast++
                    val ts = c.getLong(3)
                    val row = listOf(
                        c.getString(0), c.getString(1), c.getString(2),
                        Instant.ofEpochMilli(ts).atZone(ZoneId.systemDefault()).format(formatter),
                        c.getDouble(4).toString(), c.getDouble(5).toString(), source.dbValue,
                        if (c.isNull(7)) "" else c.getDouble(7).toString(),
                        if (c.isNull(8)) "" else c.getString(8),
                        if (c.isNull(9)) "" else c.getString(9),
                        if (c.isNull(10)) "" else c.getLong(10).toString(),
                        if (c.isNull(11)) "" else c.getLong(11).toString(),
                        if (c.isNull(12)) "" else c.getString(12)
                    ).joinToString(",") { csvEscape(it) }
                    writer.write(row)
                    writer.write("\n")
                    count++
                }
            }
        }
        return Result(count, reconstructed, forecast)
    }

    private fun csvEscape(value: String): String {
        if (value.none { it == ',' || it == '"' || it == '\n' || it == '\r' }) return value
        return "\"${value.replace("\"", "\"\"")}\""
    }
}
