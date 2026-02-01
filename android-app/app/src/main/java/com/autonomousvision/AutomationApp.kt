package com.autonomousvision

import android.app.Application
import android.os.Environment
import android.content.Context
import timber.log.Timber
import java.io.File

class AutomationApp : Application() {
    override fun onCreate() {
        super.onCreate()
        
        // Plant Timber for debug logging + file logging
        Timber.plant(Timber.DebugTree())
        
        // Also log to OBB directory so user can access easily via file explorer
        try {
            val obbDir = File(Environment.getExternalStorageDirectory(), "Android/obb/${packageName}")
            if (!obbDir.exists()) obbDir.mkdirs()
            val logFile = File(obbDir, "automation_debug.log")
            Timber.plant(FileLoggingTree(logFile))
            Timber.d("Logging to: ${logFile.absolutePath}")
        } catch (e: Exception) {
            Timber.e(e, "Failed to create OBB log file, falling back to app external files")
            val logFile = File(getExternalFilesDir(null), "automation_debug.log")
            Timber.plant(FileLoggingTree(logFile))
        }
        
        Timber.d("=== AutomationApp started ===")
    }
}

/**
 * Custom Timber tree that logs to a file on device storage.
 */
class FileLoggingTree(private val logFile: File) : Timber.Tree() {
    override fun log(priority: Int, tag: String?, message: String, t: Throwable?) {
        try {
            logFile.appendText("${System.currentTimeMillis()} [$tag] $message\n")
            if (t != null) {
                logFile.appendText("${t.stackTraceToString()}\n")
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}
