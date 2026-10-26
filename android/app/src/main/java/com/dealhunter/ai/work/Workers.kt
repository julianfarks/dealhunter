package com.dealhunter.ai.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.dealhunter.ai.DealHunterApp

/** Envía al servidor los enlaces guardados en el teléfono. Se reintenta con espera creciente si no hay red. */
class ProcessLinkWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val repo = (applicationContext as DealHunterApp).repo
        return try {
            val retry = repo.pushPending()
            runCatching { repo.pull() }
            if (retry) Result.retry() else Result.success()
        } catch (e: Exception) {
            if (runAttemptCount < 8) Result.retry() else Result.failure()
        }
    }
}

/** Sincronización periódica de precios y estados (la vigilancia de precios en sí ocurre en el servidor). */
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val repo = (applicationContext as DealHunterApp).repo
        return try {
            repo.syncAll()
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }
}
