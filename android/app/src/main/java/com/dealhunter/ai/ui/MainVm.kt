package com.dealhunter.ai.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.dealhunter.ai.DealHunterApp
import com.dealhunter.ai.data.AddResult
import com.dealhunter.ai.data.ApiException
import com.dealhunter.ai.data.CartEntity
import com.dealhunter.ai.data.CompareResponse
import com.dealhunter.ai.data.HistoryResponse
import com.dealhunter.ai.data.NotificationDto
import com.dealhunter.ai.data.OfferDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class Session(val loggedIn: Boolean, val email: String?, val tier: String, val baseUrl: String, val theme: String, val currency: String)

class MainVm(app: Application) : AndroidViewModel(app) {
    private val a = app as DealHunterApp
    val repo = a.repo
    val prefs = a.prefs
    val api = a.api

    val cart: StateFlow<List<CartEntity>> = repo.cart.stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())
    val pending: StateFlow<Int> = repo.pendingCount.stateIn(viewModelScope, SharingStarted.Eagerly, 0)

    private val _session = MutableStateFlow(readSession())
    val session: StateFlow<Session> = _session

    private val _message = MutableStateFlow<String?>(null)
    val message: StateFlow<String?> = _message
    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    val offers = MutableStateFlow<List<OfferDto>?>(null)
    val notifications = MutableStateFlow<List<NotificationDto>?>(null)
    val history = MutableStateFlow<HistoryResponse?>(null)
    val compare = MutableStateFlow<CompareResponse?>(null)
    val pushStatus = MutableStateFlow(if (a.pushAvailable()) "Firebase configurado" else "Notificaciones push no configuradas en esta compilación")

    private fun readSession() = Session(prefs.loggedIn, prefs.email, prefs.tier, prefs.baseUrl, prefs.theme, prefs.currency)
    fun refreshSession() { _session.value = readSession() }
    fun consumeMessage() { _message.value = null }
    fun say(m: String) { _message.value = m }

    private fun err(e: Throwable): String = if (e is ApiException) e.message else "Algo salió mal: ${e.message ?: "error desconocido"}"

    private fun launch(block: suspend () -> Unit) {
        viewModelScope.launch {
            _busy.value = true
            try { block() } catch (e: Throwable) { _message.value = err(e) } finally { _busy.value = false }
        }
    }

    fun setBaseUrl(url: String) { prefs.baseUrl = url; refreshSession() }
    fun setTheme(t: String) { prefs.theme = t; refreshSession() }

    fun auth(register: Boolean, email: String, password: String, onOk: () -> Unit) = launch {
        val r = if (register) api.register(email.trim(), password) else api.login(email.trim(), password)
        prefs.accessToken = r.accessToken; prefs.refreshToken = r.refreshToken
        prefs.email = r.user.email; prefs.tier = r.user.tier
        refreshSession()
        runCatching { api.preferences() }.onSuccess { prefs.currency = it.currency; refreshSession() }
        repo.enqueueSync()
        runCatching { repo.syncAll() }
        a.registerPushToken()
        onOk()
    }

    fun logout() = launch {
        prefs.clearSession(); repo.clearLocal(); offers.value = null; notifications.value = null; refreshSession()
    }

    fun addLink(raw: String, onDone: (Long?) -> Unit = {}) = launch {
        when (val r = repo.addLink(raw)) {
            is AddResult.Added -> {
                _message.value = if (prefs.loggedIn) "Añadido a tu carrito" else "Guardado en tu teléfono. Inicia sesión para que se vigile su precio."
                onDone(r.localId)
            }
            is AddResult.Duplicate -> { _message.value = "Este producto ya estaba en tu carrito"; onDone(r.localId) }
            is AddResult.Invalid -> { _message.value = r.reason; onDone(null) }
        }
        if (prefs.loggedIn) runCatching { repo.pushPending(); repo.pull() }
    }

    fun sync() = launch {
        if (!prefs.loggedIn) { _message.value = "Inicia sesión para sincronizar."; return@launch }
        repo.syncAll()
    }

    fun refreshOne(localId: Long) = launch { repo.refreshOne(localId); _message.value = "Consulta enviada. El precio se actualizará en unos segundos." }
    fun reload(localId: Long) = launch { repo.reload(localId) }
    fun remove(localId: Long) = launch { repo.remove(localId) }
    fun retry(localId: Long) = launch { repo.retryFailed(localId) }

    fun patch(localId: Long, remoteId: Long, json: String) = launch {
        repo.updateFromServer(localId, api.patchTracked(remoteId, json))
    }

    fun setTarget(localId: Long, remoteId: Long, price: String?, currency: String) = launch {
        val body = if (price == null) """{"target_price":null}""" else """{"target_price":"$price","target_currency":"$currency"}"""
        repo.updateFromServer(localId, api.patchTracked(remoteId, body))
        _message.value = if (price == null) "Precio objetivo eliminado" else "Precio objetivo guardado"
    }

    fun addAlert(localId: Long, remoteId: Long, kind: String, threshold: String?) = launch {
        api.addAlert(remoteId, kind, threshold, if (threshold != null) prefs.currency.takeIf { kind != "pct_drop" } else null)
        repo.reload(localId)
        _message.value = "Alerta creada"
    }

    fun toggleAlert(localId: Long, remoteId: Long, alertId: Long, active: Boolean) = launch {
        api.setAlertActive(remoteId, alertId, active); repo.reload(localId)
    }

    fun deleteAlert(localId: Long, remoteId: Long, alertId: Long) = launch {
        api.deleteAlert(remoteId, alertId); repo.reload(localId)
    }

    fun loadHistory(remoteId: Long, range: String) = launch {
        history.value = api.history(remoteId, range)
    }

    fun loadCompare(remoteId: Long) = launch { compare.value = api.compare(remoteId) }
    fun clearDetail() { history.value = null; compare.value = null }

    fun loadOffers() = launch { offers.value = api.offers().offers }
    fun loadNotifications() = launch { notifications.value = api.notifications().notifications }
    fun readAll() = launch { api.markAllRead(); notifications.value = api.notifications().notifications }
    fun readOne(id: Long) = launch { api.markRead(id) }

    fun savePrefs(json: String, currency: String?) = launch {
        val p = api.putPreferences(json)
        prefs.currency = currency ?: p.currency
        refreshSession()
        _message.value = "Preferencias guardadas"
        runCatching { repo.pull(full = true) }
    }

    fun ai(text: String, trackedRemoteId: Long?, onResult: (String) -> Unit) = launch {
        val r = api.aiCommand(text, trackedRemoteId)
        onResult(r.message.ifBlank { "Listo." })
        runCatching { repo.pull(full = true) }
    }

    fun export(onJson: (String) -> Unit) = launch { onJson(api.exportAccount()) }

    fun deleteAccount(password: String) = launch {
        api.deleteAccount(password)
        prefs.clearSession(); repo.clearLocal(); refreshSession()
        _message.value = "Tu cuenta y tus datos fueron eliminados."
    }
}
