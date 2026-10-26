package com.dealhunter.ai.data

import android.content.Context
import android.content.SharedPreferences
import com.dealhunter.ai.BuildConfig

/** Ajustes locales: servidor, sesión y apariencia. Los tokens viven sólo en el almacenamiento privado de la app. */
class Prefs(context: Context) {
    private val sp: SharedPreferences = context.getSharedPreferences("dealhunter", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = sp.getString("base_url", null) ?: BuildConfig.DEFAULT_API_URL
        set(v) = sp.edit().putString("base_url", v.trim().trimEnd('/')).apply()
    var accessToken: String?
        get() = sp.getString("access", null)
        set(v) = sp.edit().putString("access", v).apply()
    var refreshToken: String?
        get() = sp.getString("refresh", null)
        set(v) = sp.edit().putString("refresh", v).apply()
    var email: String?
        get() = sp.getString("email", null)
        set(v) = sp.edit().putString("email", v).apply()
    var tier: String
        get() = sp.getString("tier", "free") ?: "free"
        set(v) = sp.edit().putString("tier", v).apply()
    var theme: String // dark | light | system
        get() = sp.getString("theme", "dark") ?: "dark"
        set(v) = sp.edit().putString("theme", v).apply()
    var currency: String
        get() = sp.getString("currency", "COP") ?: "COP"
        set(v) = sp.edit().putString("currency", v).apply()
    var lastSync: String?
        get() = sp.getString("last_sync", null)
        set(v) = sp.edit().putString("last_sync", v).apply()
    var pushToken: String?
        get() = sp.getString("push_token", null)
        set(v) = sp.edit().putString("push_token", v).apply()

    val loggedIn: Boolean get() = !refreshToken.isNullOrBlank()

    fun clearSession() {
        sp.edit().remove("access").remove("refresh").remove("email").remove("last_sync").putString("tier", "free").apply()
    }
}
