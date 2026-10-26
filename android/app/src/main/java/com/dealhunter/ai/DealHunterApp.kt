package com.dealhunter.ai

import android.app.Application
import com.dealhunter.ai.data.Api
import com.dealhunter.ai.data.AppDb
import com.dealhunter.ai.data.Prefs
import com.dealhunter.ai.data.Repository
import com.dealhunter.ai.push.ensureChannel
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class DealHunterApp : Application() {
    lateinit var prefs: Prefs
    lateinit var api: Api
    lateinit var repo: Repository

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        api = Api(prefs)
        repo = Repository(this, prefs, api, AppDb.create(this))
        ensureChannel(this)
        repo.schedulePeriodicSync()
    }

    /** Push disponible sólo si la compilación incluye un google-services.json propio. */
    fun pushAvailable(): Boolean = try {
        FirebaseApp.getApps(this).isNotEmpty() || FirebaseApp.initializeApp(this) != null
    } catch (_: Throwable) {
        false
    }

    /** Pide el token FCM y lo registra en el servidor (si hay sesión y Firebase está configurado). */
    fun registerPushToken(onDone: (Boolean) -> Unit = {}) {
        if (!pushAvailable()) return onDone(false)
        try {
            FirebaseMessaging.getInstance().token.addOnSuccessListener { t ->
                prefs.pushToken = t
                if (!prefs.loggedIn) return@addOnSuccessListener onDone(false)
                CoroutineScope(Dispatchers.IO).launch {
                    val ok = runCatching { api.registerDevice(t) }.isSuccess
                    onDone(ok)
                }
            }.addOnFailureListener { onDone(false) }
        } catch (_: Throwable) {
            onDone(false)
        }
    }
}
