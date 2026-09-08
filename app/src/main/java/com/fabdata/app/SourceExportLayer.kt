package com.fabdata.app

import android.content.Context
import android.net.Uri
import java.io.OutputStreamWriter
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Export de données : measured uniquement par défaut.
 *
 * Il utilise l'enveloppe CSV FabData v2 afin qu'un fichier multi-sondes reste
 * directement réimportable par le bouton Import sans perdre l'identité des sondes.
 * La sauvegarde complète (capteurs + événements + toutes les données) reste séparée.
 */
class FabDataSourceExporter(private val context: Context, private val db: FabDataDb) {
    data class Result(val rows: Int, val reconstructed: Int, val forecast: Int)

    fun export(
        uri: Uri,
        includeReconstructed: Boolean = false,
        includeForecast: Boolean = false,
        sensorId: Long? = null
    ): Result {
        PointSourceStore.ensure(db.readableDatabase)
        val output = context.contentResolver.openOutputStream(uri, "wt")
            ?: error("Impossible de créer le fichier d'export")
        val formatter = DateTimeFormatter.ofPattern("uuuu/MM/dd HH:mm:ss", Locale.ROOT)
        var count = 0
        var reconstructed = 0
        var forecast = 0

        OutputStreamWriter(output, Charsets.UTF_8).buffered().use { writer ->
            // Extension compatible du CSV FabData v3. Les colonnes supplémentaires
            // gardent l'identité/provenance et la date du calcul pour éviter qu'un ancien
            // export ne remplace une reconstruction plus récente au réimport.
            writer.write(
                FabDataBackup.HEADER +
                    ",Reference_Key,Sigma_C,Analog_Count,Profile_Hash,Dependency_Hash,Source_UpdatedAt_ms"
            )
            writer.write("\n")

            val sensorClause = if (sensorId == null) "" else " AND p.sensor_id=?"
            val args = mutableListOf(
                if (includeReconstructed) "1" else "0",
                if (includeForecast) "1" else "0"
            ).apply { if (sensorId != null) add(sensorId.toString()) }.toTypedArray()

            db.readableDatabase.rawQuery(
                """
                SELECT s.stable_key, s.name, s.room, s.color_index,
                       p.timestamp, p.temperature, p.humidity,
                       ps.source, ps.confidence, ps.reference_station_id, ps.reference_city,
                       ps.calibration_from, ps.calibration_to, ps.model_version,
                       ps.reference_key, ps.sigma_c, ps.analog_count, ps.profile_hash,
                       ps.dependency_hash, ps.updated_at
                FROM samples p
                JOIN sensors s ON s.id=p.sensor_id
                LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
                WHERE (
                    (ps.source IS NULL OR ps.source='measured')
                    OR (?=1 AND ps.source='reconstructed')
                    OR (?=1 AND ps.source='forecast')
                )$sensorClause
                ORDER BY p.timestamp, s.id
                """.trimIndent(),
                args
            ).use { c ->
                while (c.moveToNext()) {
                    val source = PointSource.fromDb(if (c.isNull(7)) null else c.getString(7))
                    if (source == PointSource.RECONSTRUCTED) reconstructed++
                    if (source == PointSource.FORECAST) forecast++
                    val ts = c.getLong(4)
                    val row = listOf(
                        "SAMPLE",
                        FabDataBackup.FORMAT_VERSION,
                        c.getString(0),
                        c.getString(1),
                        c.getString(2),
                        c.getInt(3).toString(),
                        ts.toString(),
                        Instant.ofEpochMilli(ts).atZone(ZoneId.systemDefault()).format(formatter),
                        c.getDouble(5).toString(),
                        c.getDouble(6).toString(),
                        "", "", "", "",
                        source.dbValue,
                        if (c.isNull(8)) "" else c.getDouble(8).toString(),
                        if (c.isNull(9)) "" else c.getString(9),
                        if (c.isNull(10)) "" else c.getString(10),
                        if (c.isNull(11)) "" else c.getLong(11).toString(),
                        if (c.isNull(12)) "" else c.getLong(12).toString(),
                        if (c.isNull(13)) "" else c.getString(13),
                        if (c.isNull(14)) "" else c.getString(14),
                        if (c.isNull(15)) "" else c.getDouble(15).toString(),
                        if (c.isNull(16)) "" else c.getInt(16).toString(),
                        if (c.isNull(17)) "" else c.getString(17),
                        if (c.isNull(18)) "" else c.getString(18),
                        if (c.isNull(19)) "" else c.getLong(19).toString()
                    ).joinToString(",") { csvEscape(it) }
                    writer.write(row)
                    writer.write("\n")
                    count++
                }
            }
        }
        return Result(count, reconstructed, forecast)
    }

    /** Exporte une seule courbe, réelle + reconstruite, sous l'identité de la sonde d'origine. */
    fun exportSensorHistory(uri: Uri, sensorId: Long): Result =
        export(uri, includeReconstructed = true, includeForecast = false, sensorId = sensorId)

    private fun csvEscape(value: String): String {
        if (value.none { it == ',' || it == '"' || it == '\n' || it == '\r' }) return value
        return "\"${value.replace("\"", "\"\"")}\""
    }
}
