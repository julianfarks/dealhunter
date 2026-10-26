package com.dealhunter.ai.push

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.dealhunter.ai.DealHunterApp
import com.dealhunter.ai.MainActivity
import com.dealhunter.ai.R
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

const val CHANNEL_ALERTS = "alerts"

fun ensureChannel(ctx: Context) {
    if (Build.VERSION.SDK_INT >= 26) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ALERTS, ctx.getString(R.string.channel_alerts), NotificationManager.IMPORTANCE_HIGH)
                .apply { description = ctx.getString(R.string.channel_alerts_desc) }
        )
    }
}

/** Recibe los push (FCM) enviados por el backend y los muestra. Sin google-services.json esta clase queda inactiva. */
class PushService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        val app = applicationContext as DealHunterApp
        app.prefs.pushToken = token
        CoroutineScope(Dispatchers.IO).launch { runCatching { if (app.prefs.loggedIn) app.api.registerDevice(token) } }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        ensureChannel(this)
        val title = message.notification?.title ?: message.data["title"] ?: "DealHunter AI"
        val body = message.notification?.body ?: message.data["body"] ?: return
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            message.data["tracked_id"]?.let { putExtra("tracked_id", it) }
        }
        val pi = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(this, CHANNEL_ALERTS)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title).setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true).setContentIntent(pi).build()
        try {
            getSystemService(NotificationManager::class.java).notify((message.messageId ?: body).hashCode(), n)
        } catch (_: SecurityException) {
        }
    }
}
