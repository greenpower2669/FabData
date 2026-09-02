package com.fabdata.app

import android.content.ContentValues
import java.time.LocalDate
import java.time.ZoneId
import kotlin.math.cos
import kotlin.math.PI

/**
 * Historique Lyon reconstruit embarqué pour juillet + août 2026.
 *
 * Les extrema journaliers proviennent de la base préparée pour FabData ; les valeurs
 * horaires intermédiaires sont reconstruites par interpolation cosinus afin d'obtenir
 * une courbe douce. Ces points servent uniquement de filet de sécurité historique.
 *
 * Chaque heure reconstruite est marquée PROVISOIRE : une observation réelle ou un
 * import Lyon pourra la remplacer, et le bouton « Compléter » ne la considère jamais
 * comme une observation météo définitive.
 */
object LyonEmbeddedHistory {
    private val LYON_ZONE: ZoneId = ZoneId.of("Europe/Paris")
    private const val MARKER_TABLE = "lyon_reconstructed_seed"

    private data class Day(
        val year: Int,
        val month: Int,
        val day: Int,
        val highF: Double,
        val lowF: Double,
        val rhMin: Double,
        val rhMax: Double
    )

    private val days = listOf(
        Day(2026,7,1,86.0,68.0,32.0,69.0), Day(2026,7,2,86.0,62.6,27.0,64.0),
        Day(2026,7,3,86.0,69.8,27.0,69.0), Day(2026,7,4,89.6,64.4,11.0,49.0),
        Day(2026,7,5,93.2,60.8,22.0,59.0), Day(2026,7,6,93.2,69.8,16.0,57.0),
        Day(2026,7,7,98.6,60.8,11.0,68.0), Day(2026,7,8,96.8,64.4,16.0,60.0),
        Day(2026,7,9,95.0,71.6,20.0,60.0), Day(2026,7,10,100.4,68.0,20.0,64.0),
        Day(2026,7,11,95.0,73.4,22.0,73.0), Day(2026,7,12,100.4,66.2,15.0,68.0),
        Day(2026,7,13,98.6,75.2,20.0,54.0), Day(2026,7,14,100.4,73.4,19.0,65.0),
        Day(2026,7,15,87.8,73.4,46.0,83.0), Day(2026,7,16,93.2,66.2,34.0,100.0),
        Day(2026,7,17,87.8,66.2,41.0,94.0), Day(2026,7,18,89.6,66.2,33.0,88.0),
        Day(2026,7,19,87.8,68.0,29.0,78.0), Day(2026,7,20,84.2,62.6,25.0,59.0),
        Day(2026,7,21,82.4,62.6,23.0,52.0), Day(2026,7,22,86.0,62.6,19.0,55.0),
        Day(2026,7,23,84.2,62.6,23.0,68.0), Day(2026,7,24,89.6,60.8,15.0,59.0),
        Day(2026,7,25,91.4,66.2,24.0,94.0), Day(2026,7,26,82.4,64.4,44.0,94.0),
        Day(2026,7,27,84.2,66.2,37.0,83.0), Day(2026,7,28,95.0,60.8,23.0,77.0),
        Day(2026,7,29,100.4,68.0,20.0,78.0), Day(2026,7,30,93.2,69.8,30.0,69.0),
        Day(2026,7,31,91.4,71.6,34.0,83.0), Day(2026,8,1,89.6,68.0,38.0,88.0),
        Day(2026,8,2,98.6,66.2,24.0,83.0), Day(2026,8,3,100.4,75.2,20.0,79.0),
        Day(2026,8,4,98.6,71.6,27.0,69.0), Day(2026,8,5,93.2,69.8,34.0,83.0),
        Day(2026,8,6,91.4,73.4,28.0,53.0), Day(2026,8,7,87.8,68.0,22.0,53.0),
        Day(2026,8,8,95.0,60.8,18.0,55.0), Day(2026,8,9,98.6,68.0,22.0,83.0),
        Day(2026,8,10,95.0,68.0,28.0,88.0), Day(2026,8,11,95.0,69.8,28.0,73.0),
        Day(2026,8,12,98.6,68.0,22.0,73.0), Day(2026,8,13,104.0,69.8,19.0,69.0),
        Day(2026,8,14,100.4,73.4,21.0,69.0), Day(2026,8,15,100.4,73.4,17.0,61.0),
        Day(2026,8,16,93.2,77.0,28.0,51.0), Day(2026,8,17,87.8,68.0,43.0,94.0),
        Day(2026,8,18,91.4,66.2,26.0,94.0), Day(2026,8,19,98.6,66.2,21.0,78.0),
        Day(2026,8,20,86.0,62.6,40.0,94.0), Day(2026,8,21,75.2,62.6,54.0,94.0),
        Day(2026,8,22,78.8,60.8,28.0,88.0), Day(2026,8,23,84.2,55.4,25.0,82.0),
        Day(2026,8,24,91.4,60.8,26.0,94.0), Day(2026,8,25,86.0,60.8,40.0,100.0),
        Day(2026,8,26,87.8,64.4,43.0,94.0), Day(2026,8,27,93.2,73.4,39.0,61.0),
        Day(2026,8,28,82.4,66.2,30.0,94.0), Day(2026,8,29,84.2,57.2,35.0,88.0),
        Day(2026,8,30,87.8,68.0,35.0,78.0), Day(2026,8,31,82.4,68.0,30.0,88.0)
    )

    private fun ensureMarkerTable(db: FabDataDb) {
        db.writableDatabase.execSQL(
            "CREATE TABLE IF NOT EXISTS $MARKER_TABLE (timestamp INTEGER PRIMARY KEY)"
        )
    }

    /**
     * Ajoute seulement les timestamps absents. Retourne le nombre de points réellement créés.
     */
    fun seed(db: FabDataDb): Int {
        ensureMarkerTable(db)
        val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
        var added = 0
        db.inTransaction {
            days.forEachIndexed { index, day ->
                val previous = days.getOrNull(index - 1)
                val next = days.getOrNull(index + 1)
                for (hour in 0..23) {
                    val (temperature, humidity) = hourlyValue(day, previous, next, hour)
                    val timestamp = LocalDate.of(day.year, day.month, day.day)
                        .atTime(hour, 0)
                        .atZone(LYON_ZONE)
                        .toInstant()
                        .toEpochMilli()
                    if (db.insertSample(sensor.id, timestamp, temperature, humidity)) {
                        markProvisional(db, timestamp)
                        added++
                    }
                }
            }
        }
        return added
    }

    fun markProvisional(db: FabDataDb, timestamp: Long) {
        ensureMarkerTable(db)
        val values = ContentValues().apply { put("timestamp", timestamp) }
        db.writableDatabase.insertWithOnConflict(
            MARKER_TABLE,
            null,
            values,
            android.database.sqlite.SQLiteDatabase.CONFLICT_IGNORE
        )
        val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
        PointSourceStore.setProvenance(
            db, sensor.id, timestamp,
            PointProvenance(
                source = PointSource.RECONSTRUCTED,
                confidence = 0.72,
                referenceKey = WeatherReferenceCatalog.DEFAULT_KEY,
                referenceStationId = "69029001",
                referenceCity = "Lyon",
                modelVersion = "lyon-embedded-2026-07-08"
            )
        )
    }

    fun markObserved(db: FabDataDb, timestamp: Long) {
        ensureMarkerTable(db)
        db.writableDatabase.delete(MARKER_TABLE, "timestamp=?", arrayOf(timestamp.toString()))
        val sensor = db.getOrCreateSensor(LyonWeatherSync.STABLE_KEY, LyonWeatherSync.DISPLAY_NAME)
        PointSourceStore.markMeasured(db, sensor.id, timestamp)
    }

    fun isProvisional(db: FabDataDb, timestamp: Long): Boolean {
        ensureMarkerTable(db)
        db.readableDatabase.rawQuery(
            "SELECT 1 FROM $MARKER_TABLE WHERE timestamp=? LIMIT 1",
            arrayOf(timestamp.toString())
        ).use { c -> return c.moveToFirst() }
    }

    fun hasProvisional(db: FabDataDb, from: Long, to: Long): Boolean {
        ensureMarkerTable(db)
        db.readableDatabase.rawQuery(
            "SELECT 1 FROM $MARKER_TABLE WHERE timestamp BETWEEN ? AND ? LIMIT 1",
            arrayOf(from.toString(), to.toString())
        ).use { c -> return c.moveToFirst() }
    }

    private fun hourlyValue(day: Day, previous: Day?, next: Day?, hour: Int): Pair<Double, Double> {
        val high = fToC(day.highF)
        val low = fToC(day.lowF)

        return when {
            hour < 6 -> {
                if (previous != null) {
                    val t = (hour + 9).toDouble() / 15.0
                    ease(fToC(previous.highF), low, t) to ease(previous.rhMin, day.rhMax, t)
                } else {
                    val startTemp = low + 0.35 * (high - low)
                    val startHum = day.rhMax - 0.35 * (day.rhMax - day.rhMin)
                    ease(startTemp, low, hour / 6.0) to ease(startHum, day.rhMax, hour / 6.0)
                }
            }
            hour <= 15 -> {
                val t = (hour - 6).toDouble() / 9.0
                ease(low, high, t) to ease(day.rhMax, day.rhMin, t)
            }
            else -> {
                val targetLow = fToC(next?.lowF ?: day.lowF)
                val targetRh = next?.rhMax ?: day.rhMax
                val t = (hour - 15).toDouble() / 15.0
                ease(high, targetLow, t) to ease(day.rhMin, targetRh, t)
            }
        }.let { (temperature, humidity) ->
            round1(temperature) to round1(humidity.coerceIn(0.0, 100.0))
        }
    }

    private fun fToC(fahrenheit: Double): Double = (fahrenheit - 32.0) * 5.0 / 9.0

    /** Interpolation cosinus : tangente nulle aux extrema, donc pas de cassure visuelle. */
    private fun ease(a: Double, b: Double, tRaw: Double): Double {
        val t = tRaw.coerceIn(0.0, 1.0)
        val u = (1.0 - cos(PI * t)) / 2.0
        return a + (b - a) * u
    }

    private fun round1(value: Double): Double = kotlin.math.round(value * 10.0) / 10.0
}
