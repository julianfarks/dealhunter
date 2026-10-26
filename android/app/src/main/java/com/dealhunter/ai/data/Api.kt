package com.dealhunter.ai.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Error de la API con mensaje legible en español. `retryable` indica si tiene sentido reintentar más tarde. */
class ApiException(val code: Int, override val message: String, val retryable: Boolean) : Exception(message)

class Api(private val prefs: Prefs) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val refreshLock = Any()

    private fun url(path: String, query: Map<String, String?> = emptyMap()): okhttp3.HttpUrl {
        val base = prefs.baseUrl
        if (base.isBlank()) throw ApiException(0, "Configura primero la dirección de tu servidor DealHunter.", false)
        val full = "$base/api/v1$path"
        val b = full.toHttpUrlOrNull()?.newBuilder()
            ?: throw ApiException(0, "La dirección del servidor no es válida: $base", false)
        query.forEach { (k, v) -> if (v != null) b.addQueryParameter(k, v) }
        return b.build()
    }

    private fun execute(method: String, path: String, body: String?, query: Map<String, String?>, auth: Boolean, retried: Boolean = false): String {
        val rb = Request.Builder().url(url(path, query))
        if (auth) prefs.accessToken?.let { rb.header("Authorization", "Bearer $it") }
        val reqBody = body?.toRequestBody(jsonType)
        when (method) {
            "GET" -> rb.get()
            "DELETE" -> if (reqBody != null) rb.delete(reqBody) else rb.delete()
            else -> rb.method(method, reqBody ?: "".toRequestBody(jsonType))
        }
        try {
            client.newCall(rb.build()).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (resp.isSuccessful) return text
                if (resp.code == 401 && auth && !retried && refresh()) {
                    return execute(method, path, body, query, auth, retried = true)
                }
                throw toError(resp.code, text)
            }
        } catch (e: IOException) {
            throw ApiException(0, "Sin conexión con el servidor. Se reintentará automáticamente.", true)
        }
    }

    private fun toError(code: Int, text: String): ApiException {
        var msg: String? = null
        var retryable = code >= 500 || code == 429
        try {
            val obj = AppJson.parseToJsonElement(text) as? JsonObject
            val detail = obj?.get("detail")
            if (detail is JsonObject) {
                val d = AppJson.decodeFromJsonElement(ErrorDetail.serializer(), detail)
                msg = d.message
                retryable = d.retryable
            } else if (detail is kotlinx.serialization.json.JsonPrimitive && detail.isString) {
                msg = detail.content
            } else if (detail != null) {
                msg = "Datos no válidos. Revisa lo que escribiste."
            }
        } catch (_: Exception) {
        }
        if (msg.isNullOrBlank()) {
            msg = when (code) {
                401 -> "Tu sesión expiró. Inicia sesión de nuevo."
                402 -> "Alcanzaste el límite de tu plan."
                404 -> "No se encontró lo que buscabas."
                429 -> "Demasiadas solicitudes. Intenta de nuevo en un momento."
                else -> "El servidor respondió con un error ($code)."
            }
        }
        return ApiException(code, msg, retryable)
    }

    /** Renueva el token de acceso. Devuelve false si la sesión ya no es válida. */
    private fun refresh(): Boolean = synchronized(refreshLock) {
        val rt = prefs.refreshToken ?: return false
        return try {
            val text = execute("POST", "/auth/refresh", """{"refresh_token":"$rt"}""", emptyMap(), auth = false)
            val r = AppJson.decodeFromString<AuthResponse>(text)
            prefs.accessToken = r.accessToken
            prefs.refreshToken = r.refreshToken
            true
        } catch (e: ApiException) {
            if (e.code == 401) prefs.clearSession()
            false
        }
    }

    private suspend fun call(method: String, path: String, body: String? = null, query: Map<String, String?> = emptyMap(), auth: Boolean = true): String =
        withContext(Dispatchers.IO) { execute(method, path, body, query, auth) }

    private inline fun <reified T> enc(v: T): String = AppJson.encodeToString(v)

    // ---- autenticación
    suspend fun register(email: String, password: String): AuthResponse =
        AppJson.decodeFromString(call("POST", "/auth/register", """{"email":${q(email)},"password":${q(password)}}""", auth = false))

    suspend fun login(email: String, password: String): AuthResponse =
        AppJson.decodeFromString(call("POST", "/auth/login", """{"email":${q(email)},"password":${q(password)}}""", auth = false))

    suspend fun me(): UserDto = AppJson.decodeFromString(call("GET", "/auth/me"))

    // ---- carrito
    suspend fun addTracked(url: String, targetPrice: String? = null, currency: String? = null): AddResponse {
        val sb = StringBuilder("""{"url":${q(url)}""")
        if (targetPrice != null) sb.append(""","target_price":${q(targetPrice)}""")
        if (currency != null && targetPrice != null) sb.append(""","target_currency":${q(currency)}""")
        sb.append("}")
        return AppJson.decodeFromString(call("POST", "/tracked", sb.toString()))
    }

    suspend fun changes(since: String?, currency: String): ChangesResponse =
        AppJson.decodeFromString(call("GET", "/sync/changes", query = mapOf("since" to since, "currency" to currency)))

    suspend fun getTracked(id: Long, currency: String): TrackedDto =
        AppJson.decodeFromString(call("GET", "/tracked/$id", query = mapOf("currency" to currency)))

    suspend fun patchTracked(id: Long, json: String): TrackedDto =
        AppJson.decodeFromString(call("PATCH", "/tracked/$id", json))

    suspend fun bulk(ids: List<Long>, action: String): String =
        call("POST", "/tracked/bulk", """{"ids":[${ids.joinToString(",")}],"action":${q(action)}}""")

    suspend fun deleteTracked(id: Long) { call("DELETE", "/tracked/$id") }

    suspend fun refreshTracked(id: Long) { call("POST", "/tracked/$id/refresh") }

    suspend fun history(id: Long, range: String): HistoryResponse =
        AppJson.decodeFromString(call("GET", "/tracked/$id/history", query = mapOf("range" to range)))

    suspend fun compare(id: Long): CompareResponse = AppJson.decodeFromString(call("GET", "/tracked/$id/compare"))

    suspend fun addAlert(id: Long, kind: String, threshold: String?, thresholdCurrency: String?): AlertDto {
        val sb = StringBuilder("""{"kind":${q(kind)}""")
        if (threshold != null) sb.append(""","threshold":${q(threshold)}""")
        if (threshold != null && thresholdCurrency != null) sb.append(""","threshold_currency":${q(thresholdCurrency)}""")
        sb.append("}")
        return AppJson.decodeFromString(call("POST", "/tracked/$id/alerts", sb.toString()))
    }

    suspend fun setAlertActive(id: Long, alertId: Long, active: Boolean) {
        call("PATCH", "/tracked/$id/alerts/$alertId", """{"active":$active}""")
    }

    suspend fun deleteAlert(id: Long, alertId: Long) { call("DELETE", "/tracked/$id/alerts/$alertId") }

    // ---- ofertas, notificaciones, preferencias
    suspend fun offers(): OffersResponse = AppJson.decodeFromString(call("GET", "/offers"))
    suspend fun notifications(): NotificationsResponse = AppJson.decodeFromString(call("GET", "/notifications"))
    suspend fun markRead(id: Long) { call("POST", "/notifications/$id/read") }
    suspend fun markAllRead() { call("POST", "/notifications/read-all") }
    suspend fun preferences(): PrefsDto = AppJson.decodeFromString(call("GET", "/preferences"))
    suspend fun putPreferences(json: String): PrefsDto = AppJson.decodeFromString(call("PUT", "/preferences", json))
    suspend fun registerDevice(token: String) { call("POST", "/devices", """{"token":${q(token)},"platform":"android"}""") }
    suspend fun aiCommand(text: String, trackedId: Long?): AiResult {
        val tid = if (trackedId != null) ""","tracked_id":$trackedId""" else ""
        return AppJson.decodeFromString(call("POST", "/ai/command", """{"text":${q(text)}$tid}"""))
    }

    suspend fun exportAccount(): String = call("GET", "/account/export")
    suspend fun deleteAccount(password: String) { call("DELETE", "/account", """{"password":${q(password)}}""") }

    private fun q(s: String): String = AppJson.encodeToString(kotlinx.serialization.serializer<String>(), s)
}
