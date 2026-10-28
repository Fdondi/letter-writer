package io.github.fdondi.letterwriter.core

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.content.ContextCompat
import io.github.fdondi.letterwriter.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * Model calls take minutes. Without a foreground service Android freezes the app soon after the
 * user switches away and may kill it, which drops the drafts in progress. While any task runs,
 * [KeepAliveService] keeps the process in the foreground with a notification.
 */
object KeepAlive {
    private const val TAG = "KeepAlive"
    private val _tasks = MutableStateFlow<Map<String, String>>(emptyMap())
    val tasks: StateFlow<Map<String, String>> = _tasks.asStateFlow()

    private var watching: CoroutineScope? = null

    /** Mirrors [running] (task key to label) and starts the service whenever work begins. */
    fun watch(context: Context, running: StateFlow<Map<String, String>>) {
        val app = context.applicationContext
        watching?.cancel()
        watching = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate).also { scope ->
            scope.launch { running.collect { _tasks.value = it } }
            scope.launch {
                running.map { it.isNotEmpty() }.distinctUntilChanged().collect { busy -> if (busy) start(app) }
            }
        }
    }

    private fun start(context: Context) {
        try {
            ContextCompat.startForegroundService(context, Intent(context, KeepAliveService::class.java))
        } catch (e: Exception) {
            // Not allowed from the background (Android 12+). The work still runs; it just isn't protected.
            Log.w(TAG, "Could not start the keep-alive service", e)
        }
    }
}

class KeepAliveService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var observing = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Every startForegroundService() must be answered with startForeground(), even if the work already ended.
        if (!enterForeground(KeepAlive.tasks.value)) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (!observing) {
            observing = true
            scope.launch {
                KeepAlive.tasks.collect { tasks ->
                    if (tasks.isEmpty()) {
                        stopForeground(STOP_FOREGROUND_REMOVE)
                        stopSelf()
                    } else {
                        getSystemService(NotificationManager::class.java)?.notify(NOTIFICATION_ID, notification(tasks))
                    }
                }
            }
        }
        return START_NOT_STICKY
    }

    /** Android 15+ ends long `dataSync` services; stop instead of being killed. */
    override fun onTimeout(startId: Int, fgsType: Int) {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun enterForeground(tasks: Map<String, String>): Boolean =
        try {
            val n = notification(tasks)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIFICATION_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            } else {
                startForeground(NOTIFICATION_ID, n)
            }
            true
        } catch (e: Exception) {
            Log.w("KeepAlive", "startForeground failed", e)
            false
        }

    private fun notification(tasks: Map<String, String>): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm != null && nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL_ID, "Letters in progress", NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val text = tasks.values.distinct().joinToString(" · ").ifEmpty { "Finishing" }
        return Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("Letter Writer is working")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "work_in_progress"
        private const val NOTIFICATION_ID = 41
    }
}
