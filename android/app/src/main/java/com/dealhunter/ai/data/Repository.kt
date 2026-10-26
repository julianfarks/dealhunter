package com.dealhunter.ai.data

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.dealhunter.ai.work.ProcessLinkWorker
import com.dealhunter.ai.work.SyncWorker
import kotlinx.coroutines.flow.Flow
import java.util.concurrent.TimeUnit

sealed class AddResult {
    data class Added(val localId: Long) : AddResult()
    data class Duplicate(val localId: Long) : AddResult()
    data class Invalid(val reason: String) : AddResult()
}

class Repository(private val ctx: Context, val prefs: Prefs, val api: Api, val db: AppDb) {
    private val dao = db.cart()

    val cart: Flow<List<CartEntity>> = dao.observeAll()
    val pendingCount: Flow<Int> = dao.pendingCount()
    fun observe(id: Long): Flow<CartEntity?> = dao.observe(id)

    /**
     * Guarda el enlace en el teléfono al instante (funciona sin red y sin sesión) y programa el envío al servidor.
     * Nada se pierde: si no hay conexión, WorkManager lo reintenta cuando vuelva.
     */
    suspend fun addLink(raw: String): AddResult {
        val url = Links.extract(raw) ?: raw.trim().takeIf { Links.isPlausible(it) }
            ?: return AddResult.Invalid("No encontré un enlace de producto en lo que compartiste.")
        if (!Links.isPlausible(url)) return AddResult.Invalid("El enlace no parece válido.")
        val key = Links.key(url)
        dao.byUrlKey(key)?.let { return AddResult.Duplicate(it.localId) }
        val id = dao.upsert(CartEntity(url = url, urlKey = key))
        enqueueSync()
        return AddResult.Added(id)
    }

    fun enqueueSync() {
        val c = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val req = OneTimeWorkRequestBuilder<ProcessLinkWorker>()
            .setConstraints(c).setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
        WorkManager.getInstance(ctx).enqueueUniqueWork("process-links", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
    }

    fun schedulePeriodicSync() {
        val c = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        val req = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES).setConstraints(c).build()
        WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("periodic-sync", ExistingPeriodicWorkPolicy.KEEP, req)
    }

    /** Envía al servidor los enlaces pendientes. Devuelve true si hay que reintentar más tarde. */
    suspend fun pushPending(): Boolean {
        if (!prefs.loggedIn) return false // sin sesión: quedan guardados y se envían al iniciar sesión
        var retry = false
        for (e in dao.pending()) {
            try {
                val r = api.addTracked(e.url)
                merge(e, r.item)
            } catch (ex: ApiException) {
                if (ex.retryable) {
                    dao.upsert(e.copy(attempts = e.attempts + 1, syncError = ex.message))
                    retry = true
                } else if (ex.code == 401) {
                    return false
                } else {
                    dao.upsert(e.copy(syncState = SyncState.FAILED, syncError = ex.message))
                }
            }
        }
        return retry
    }

    private suspend fun merge(local: CartEntity, dto: TrackedDto) {
        val existing = dao.byRemoteId(dto.id)
        if (existing != null && existing.localId != local.localId) dao.delete(local.localId) // ya estaba (otro dispositivo)
        val target = existing ?: local
        dao.upsert(toEntity(target, dto))
    }

    private fun toEntity(base: CartEntity, dto: TrackedDto) = base.copy(
        remoteId = dto.id, url = dto.url.ifBlank { base.url }, title = dto.title, storeName = dto.storeName,
        syncState = SyncState.SYNCED, syncError = null, archived = dto.archived, purchased = dto.purchased,
        json = AppJson.encodeToString(TrackedDto.serializer(), dto),
    )

    /** Descarga los cambios del servidor (incluye bajas hechas desde otros dispositivos). */
    suspend fun pull(full: Boolean = false) {
        if (!prefs.loggedIn) return
        val since = if (full) null else prefs.lastSync
        val r = api.changes(since, prefs.currency)
        for (dto in r.items) {
            val existing = dao.byRemoteId(dto.id)
            if (dto.deleted) {
                existing?.let { dao.delete(it.localId) }
                continue
            }
            val base = existing ?: dao.byUrlKey(Links.key(dto.url)) ?: CartEntity(url = dto.url, urlKey = Links.key(dto.url))
            dao.upsert(toEntity(base, dto).copy(urlKey = Links.key(dto.url)))
        }
        r.serverTime?.let { prefs.lastSync = it }
    }

    suspend fun syncAll() {
        pushPending()
        pull()
    }

    suspend fun refreshOne(localId: Long) {
        val e = dao.byLocalId(localId) ?: return
        val rid = e.remoteId ?: return
        runCatching { api.refreshTracked(rid) }
        val dto = api.getTracked(rid, prefs.currency)
        dao.upsert(toEntity(e, dto))
    }

    suspend fun updateFromServer(localId: Long, dto: TrackedDto) {
        val e = dao.byLocalId(localId) ?: return
        dao.upsert(toEntity(e, dto))
    }

    suspend fun reload(localId: Long) {
        val e = dao.byLocalId(localId) ?: return
        val rid = e.remoteId ?: return
        updateFromServer(localId, api.getTracked(rid, prefs.currency))
    }

    suspend fun remove(localId: Long) {
        val e = dao.byLocalId(localId) ?: return
        e.remoteId?.let { api.deleteTracked(it) }
        dao.delete(localId)
    }

    suspend fun retryFailed(localId: Long) {
        val e = dao.byLocalId(localId) ?: return
        dao.upsert(e.copy(syncState = SyncState.PENDING, syncError = null, attempts = 0))
        enqueueSync()
    }

    suspend fun clearLocal() = dao.clear()
}
