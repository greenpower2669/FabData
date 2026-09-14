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
 * WorkManager is best-effort (Android minimum 15 min), but it shares the exact same
 * SQLite canonical-slot claim as the foreground scheduler. It can therefore fill a
 * missing :00/:10/:20... slot when Android wakes it, but can never duplicate a slot
 * already claimed by the foreground app.
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

            ForecastMemoryStore.ensure(db.writableDatabase)
            val now = System.currentTimeMillis()
            val slot = ForecastMemoryStore.tryClaimCaptureSlot(
                db.writableDatabase,
                reference.key,
                now,
                "worker arrière-plan"
            ) ?: return@runCatching

            val count = manager.refreshForecast(reference, canonicalSlotClaimed = true)
            val captured = ForecastMemoryStore.hasCaptureSlot(db.writableDatabase, reference.key, slot)
            ForecastMemoryStore.finishCaptureSlot(
                db.writableDatabase,
                reference.key,
                slot,
                captured,
                "worker · $count point(s) fournisseur"
            )
        }.fold(
            onSuccess = { Result.success() },
            // The slot claim is intentionally once-only. Retrying inside the same slot
            // would violate the scientific capture cadence and can create provider spam.
            onFailure = { Result.success() }
        )
    }

    companion object {
        private const val UNIQUE_WORK = "fabdata-forecast-archive-canonical"

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<ForecastArchiveWorker>(15, TimeUnit.MINUTES)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()

            WorkManager.getInstance(context.applicationContext).enqueueUniquePeriodicWork(
                UNIQUE_WORK,
                ExistingPeriodicWorkPolicy.UPDATE,
                request
            )
        }
    }
}
