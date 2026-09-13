package com.fabdata.app

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * Lightweight scientific forecast capture.
 *
 * The user may display only a few hours, but the raw provider snapshot must still be
 * captured before it is replaced by a newer forecast. This worker therefore refreshes
 * only the selected weather reference forecast. It does NOT scan stations, retrain any
 * model, rebuild terrain history, run the adaptive model, or recalculate the thermal past.
 *
 * WorkManager is intentionally best-effort: Android may delay a run for battery reasons.
 * Foreground refresh remains the fast path whenever FabData is open.
 */
class ForecastArchiveWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        runCatching {
            val db = FabDataDb(applicationContext)
            val reference = WeatherReferencePrefs(applicationContext).selectedReference()
            val lyonLab = LyonLabStore(db)
            val credentials = MeteoFranceCredentialStore(applicationContext)
            val manager = WeatherReferenceManager(
                applicationContext,
                db,
                lyonLab,
                credentials
            )

            // Ensures the immutable raw snapshot table/trigger exists, then performs one
            // forecast-only refresh. The trigger archives every newly inserted forecast row.
            ForecastMemoryStore.ensure(db.writableDatabase)
            manager.refreshForecast(reference)
        }.fold(
            onSuccess = { Result.success() },
            onFailure = {
                if (runAttemptCount < 3) Result.retry() else Result.success()
            }
        )
    }

    companion object {
        private const val UNIQUE_WORK = "fabdata-forecast-archive-hourly"

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<ForecastArchiveWorker>(1, TimeUnit.HOURS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()

            WorkManager.getInstance(context.applicationContext).enqueueUniquePeriodicWork(
                UNIQUE_WORK,
                ExistingPeriodicWorkPolicy.KEEP,
                request
            )
        }
    }
}
