#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"{label}: déjà appliqué")
        return
    if old not in text:
        raise SystemExit(f"{label}: bloc introuvable")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: OK")


replace_once(
    "app/build.gradle.kts",
    '        versionCode = 27\n        versionName = "0.13.0"',
    '        versionCode = 28\n        versionName = "0.13.1"',
    "Version 0.13.1 / code 28",
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''        // Filet de sécurité historique public/modelisé. Ne peut jamais écraser measured.
        runCatching { fetchOpenMeteoHistory(reference, from, to) }
            .getOrDefault(emptyList())
            .forEach { store.upsert(reference.key, it) }
''',
    '''        // v0.13.1 : l'archive Open-Meteo est volontairement arrêtée avant sa zone
        // de fraîcheur incertaine, puis un pont "past_days" recolle les 14 derniers jours.
        // Une station dynamique garde ainsi une série continue sans toucher au moteur RC.
        runCatching { fetchOpenMeteoHistory(reference, from, to) }
            .getOrDefault(emptyList())
            .forEach { store.upsert(reference.key, it) }
        runCatching { fetchOpenMeteoRecentPast(reference, from, to) }
            .getOrDefault(emptyList())
            .forEach { store.upsert(reference.key, it) }
''',
    "Pont météo récent dans refreshSelected",
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''        val historyTo = minOf(to, System.currentTimeMillis() - hourMs)
''',
    '''        // L'archive n'est pas une source temps réel. Demander aujourd'hui peut faire
        // échouer toute la requête ; on laisse 10 jours de marge, couverts par past_days=14.
        val historyTo = minOf(to, System.currentTimeMillis() - 10L * 24L * hourMs)
''',
    "Borne sûre archive Open-Meteo",
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''    private fun httpGetAnonymous(url: String): String {
''',
    '''    /**
     * Pont récent pour les stations dynamiques : les derniers jours sont servis par
     * l'API forecast avec past_days, donc indépendamment du délai de l'archive.
     * Ces points restent RECONSTRUCTED et ne peuvent jamais écraser une observation.
     */
    private fun fetchOpenMeteoRecentPast(
        reference: WeatherReference,
        from: Long,
        to: Long
    ): List<WeatherReferencePoint> {
        val now = System.currentTimeMillis()
        val recentFrom = maxOf(from, now - 14L * 24L * hourMs)
        val recentTo = minOf(to, now - 20L * 60L * 1000L)
        if (recentTo <= recentFrom) return emptyList()

        val url = "https://api.open-meteo.com/v1/forecast" +
            "?latitude=${reference.latitude}&longitude=${reference.longitude}" +
            "&hourly=temperature_2m,relative_humidity_2m" +
            "&past_days=14&forecast_days=1&timezone=Europe%2FParis"
        val raw = httpGetAnonymous(url)
        val hourly = JSONObject(raw).getJSONObject("hourly")
        val times = hourly.getJSONArray("time")
        val temps = hourly.getJSONArray("temperature_2m")
        val hums = hourly.getJSONArray("relative_humidity_2m")
        val out = mutableListOf<WeatherReferencePoint>()
        for (i in 0 until minOf(times.length(), temps.length(), hums.length())) {
            val time = times.optString(i)
            val temp = temps.optDouble(i, Double.NaN)
            val hum = hums.optDouble(i, Double.NaN)
            if (!temp.isFinite() || !hum.isFinite()) continue
            val ts = runCatching {
                LocalDateTime.parse(time).atZone(zone).toInstant().toEpochMilli()
            }.getOrNull() ?: continue
            if (ts !in recentFrom..recentTo || temp !in -60.0..65.0 || hum !in 0.0..100.0) continue
            out += WeatherReferencePoint(ts, temp, hum, PointSource.RECONSTRUCTED, 0.72)
        }
        return out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
    }

    private fun httpGetAnonymous(url: String): String {
''',
    "Pont past_days Open-Meteo",
)

replace_once(
    "app/src/main/java/com/fabdata/app/WeatherReferenceLayer.kt",
    '''    private fun fetchOfficialHourly(reference: WeatherReference, from: Long, to: Long): List<WeatherReferencePoint> {
        val credential = credentials.get().takeIf { it.isNotBlank() } ?: error("Token Météo-France absent")
        val orderBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande-station/horaire"
        val fileBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande/fichier"
        val all = mutableListOf<WeatherReferencePoint>()
        var cursor = Instant.ofEpochMilli(from)
        val end = Instant.ofEpochMilli(to)
''',
    '''    private fun fetchOfficialHourly(reference: WeatherReference, from: Long, to: Long): List<WeatherReferencePoint> {
        val credential = credentials.get().takeIf { it.isNotBlank() } ?: error("Token Météo-France absent")
        val safeTo = minOf(to, System.currentTimeMillis() - 10L * 60L * 1000L)
        if (safeTo <= from) return emptyList()
        val orderBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande-station/horaire"
        val fileBase = "https://public-api.meteofrance.fr/public/DPClim/v1/commande/fichier"
        val all = mutableListOf<WeatherReferencePoint>()
        var cursor = Instant.ofEpochMilli(from)
        val end = Instant.ofEpochMilli(safeTo)
''',
    "Borne Météo-France au passé réel",
)

print("v0.13.1 history bridge patch complete")
