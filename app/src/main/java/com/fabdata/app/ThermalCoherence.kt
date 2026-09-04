package com.fabdata.app

import java.security.MessageDigest

/** Empreinte minimale attachée aux points calculés. */
data class ThermalDependencyFingerprint(
    val profileHash: String,
    val dependencyHash: String
)

data class ThermalCurveCoherence(
    val sensorId: Long,
    val source: PointSource,
    val bounds: LongRange,
    val expected: ThermalDependencyFingerprint,
    val totalPoints: Int,
    val stalePoints: Int,
    val unknownPoints: Int
) {
    val current: Boolean get() = stalePoints == 0
}

/**
 * v0.16 : cohérence des courbes calculées.
 *
 * Le journal est volontairement minuscule : les colonnes profile_hash et dependency_hash
 * vivent dans point_sources, à côté de source/model_version/updated_at déjà existants.
 * Une ancienne sauvegarde sans empreinte reste lisible ; elle est simplement "inconnue"
 * lors d'une rationalisation manuelle et sera alors recalculée par sécurité.
 */
class ThermalCoherenceStore(private val db: FabDataDb) {
    init {
        PointSourceStore.ensure(db.writableDatabase)
        WeatherReferenceStore.ensure(db.writableDatabase)
    }

    fun profileHash(raw: ThermalBuildingProfile): String {
        val p = raw.normalized()
        return hashStrings(
            "profile-v1",
            java.lang.Double.doubleToRawLongBits(p.surfaceM2).toString(),
            p.floor.toString(),
            p.insulation.uppercase(),
            p.inertia.name,
            p.exposure.name,
            p.initialMassOverrideC?.let { java.lang.Double.doubleToRawLongBits(it).toString() } ?: "auto"
        )
    }

    fun dependencyFingerprint(
        reference: WeatherReference,
        profile: ThermalBuildingProfile,
        sensorId: Long,
        source: PointSource,
        forecastMode: ForecastHorizonMode? = null
    ): ThermalDependencyFingerprint {
        require(source != PointSource.MEASURED) { "Une mesure réelle n'a pas d'empreinte calculée" }
        val pHash = profileHash(profile)
        val measured = measuredHash(sensorId)
        val weather = weatherHash(reference.key, includeForecast = source == PointSource.FORECAST)
        val mode = if (source == PointSource.FORECAST) (forecastMode ?: ForecastHorizonMode.AUTO).name else "history"
        val dependency = hashStrings(
            "thermal-dependency-v1",
            source.dbValue,
            PointSourceStore.MODEL_VERSION,
            reference.key,
            reference.stationId,
            pHash,
            measured,
            weather,
            mode
        )
        return ThermalDependencyFingerprint(pHash, dependency)
    }

    fun inspect(
        reference: WeatherReference,
        profile: ThermalBuildingProfile,
        sensorId: Long,
        source: PointSource,
        forecastMode: ForecastHorizonMode? = null
    ): ThermalCurveCoherence? {
        require(source != PointSource.MEASURED)
        val expected = dependencyFingerprint(reference, profile, sensorId, source, forecastMode)
        return db.readableDatabase.rawQuery(
            """
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp),
                   SUM(CASE WHEN COALESCE(dependency_hash,'')<>? OR COALESCE(profile_hash,'')<>? THEN 1 ELSE 0 END),
                   SUM(CASE WHEN dependency_hash IS NULL OR profile_hash IS NULL THEN 1 ELSE 0 END)
            FROM point_sources
            WHERE sensor_id=? AND source=?
            """.trimIndent(),
            arrayOf(expected.dependencyHash, expected.profileHash, sensorId.toString(), source.dbValue)
        ).use { c ->
            if (!c.moveToFirst() || c.getInt(0) <= 0 || c.isNull(1) || c.isNull(2)) return null
            ThermalCurveCoherence(
                sensorId = sensorId,
                source = source,
                bounds = c.getLong(1)..c.getLong(2),
                expected = expected,
                totalPoints = c.getInt(0),
                stalePoints = if (c.isNull(3)) 0 else c.getInt(3),
                unknownPoints = if (c.isNull(4)) 0 else c.getInt(4)
            )
        }
    }

    fun calculatedSensorIds(): List<Long> {
        val out = mutableListOf<Long>()
        db.readableDatabase.rawQuery(
            """
            SELECT DISTINCT ps.sensor_id
            FROM point_sources ps
            JOIN sensors s ON s.id=ps.sensor_id
            WHERE ps.source IN ('reconstructed','forecast')
              AND ps.sensor_id>=0
              AND s.stable_key NOT LIKE 'meteo-%'
              AND s.stable_key NOT LIKE 'http-get-%'
            ORDER BY ps.sensor_id
            """.trimIndent(), null
        ).use { c -> while (c.moveToNext()) out += c.getLong(0) }
        return out
    }

    fun firstMeasuredTimestamp(sensorId: Long): Long? {
        return db.readableDatabase.rawQuery(
            """
            SELECT MIN(p.timestamp)
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source='measured')
            """.trimIndent(), arrayOf(sensorId.toString())
        ).use { c ->
            if (!c.moveToFirst() || c.isNull(0)) null else c.getLong(0)
        }
    }

    fun hasStampedCalculatedPoints(): Boolean {
        return db.readableDatabase.rawQuery(
            "SELECT 1 FROM point_sources WHERE source IN ('reconstructed','forecast') AND dependency_hash IS NOT NULL LIMIT 1",
            null
        ).use { it.moveToFirst() }
    }

    private fun measuredHash(sensorId: Long): String {
        val digest = MessageDigest.getInstance("SHA-256")
        put(digest, "measured-v1")
        db.readableDatabase.rawQuery(
            """
            SELECT p.timestamp, p.temperature, p.humidity
            FROM samples p
            LEFT JOIN point_sources ps ON ps.sensor_id=p.sensor_id AND ps.timestamp=p.timestamp
            WHERE p.sensor_id=? AND (ps.source IS NULL OR ps.source='measured')
            ORDER BY p.timestamp
            """.trimIndent(), arrayOf(sensorId.toString())
        ).use { c ->
            while (c.moveToNext()) {
                put(digest, c.getLong(0).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(1)).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(2)).toString())
            }
        }
        return hex(digest.digest())
    }

    private fun weatherHash(referenceKey: String, includeForecast: Boolean): String {
        val digest = MessageDigest.getInstance("SHA-256")
        put(digest, if (includeForecast) "weather-all-v1" else "weather-history-v1")
        val sql = if (includeForecast) {
            """
            SELECT timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
            WHERE reference_key=?
            ORDER BY timestamp
            """.trimIndent()
        } else {
            """
            SELECT timestamp, temperature, humidity, source, confidence
            FROM weather_reference_samples
            WHERE reference_key=? AND source<>'forecast'
            ORDER BY timestamp
            """.trimIndent()
        }
        db.readableDatabase.rawQuery(sql, arrayOf(referenceKey)).use { c ->
            while (c.moveToNext()) {
                put(digest, c.getLong(0).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(1)).toString())
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(2)).toString())
                put(digest, c.getString(3))
                put(digest, java.lang.Double.doubleToRawLongBits(c.getDouble(4)).toString())
            }
        }
        return hex(digest.digest())
    }

    private fun hashStrings(vararg values: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        values.forEach { put(digest, it) }
        return hex(digest.digest())
    }

    private fun put(digest: MessageDigest, value: String) {
        digest.update(value.toByteArray(Charsets.UTF_8))
        digest.update(0)
    }

    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }
}
