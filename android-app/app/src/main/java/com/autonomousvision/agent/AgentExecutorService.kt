package com.autonomousvision.agent

import android.content.Context
import android.content.Intent
import androidx.work.*
import com.autonomousvision.accessibility.AutomationAccessibilityService
import com.autonomousvision.models.*
import com.autonomousvision.safety.SafetyManager
import kotlinx.coroutines.*
import timber.log.Timber
import java.util.concurrent.TimeUnit

/**
 * Agent Executor Service - orchestrates the entire automation loop
 */
class AgentExecutorService(
    context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    private val safetyManager = SafetyManager()
    private var retryCount = 0

    override suspend fun doWork(): Result = withContext(Dispatchers.Default) {
        try {
            val taskPlanJson = inputData.getString("task_plan")
            if (taskPlanJson == null) {
                Timber.w("No task plan provided")
                return@withContext Result.retry()
            }

            // Parse task plan (in real implementation, use Gson)
            val taskPlan = parseTaskPlan(taskPlanJson)
            Timber.d("Executing task: ${taskPlan.taskId}")

            // Execute task with verification loop
            executeTaskWithVerification(taskPlan)

            Result.success()
        } catch (e: Exception) {
            Timber.e(e, "Task execution failed")
            if (retryCount < 3) {
                retryCount++
                Result.retry()
            } else {
                Result.failure()
            }
        }
    }

    private suspend fun executeTaskWithVerification(plan: TaskPlan) {
        // Safety check
        val verdict = safetyManager.getSafetyVerdictForPlan(plan)
        if (!verdict.allowed) {
            Timber.e("Task blocked by safety policy: ${verdict.reason}")
            return
        }

        if (verdict.requiresConfirmation) {
            Timber.d("Task requires user confirmation")
            // In real app, send notification for user approval
            return
        }

        val service = AutomationAccessibilityService.getInstance()
            ?: throw Exception("Accessibility Service not running")

        var successfulActions = 0
        var failedActions = 0

        for ((index, action) in plan.actions.withIndex()) {
            Timber.d("Executing action ${index + 1}/${plan.actions.size}: ${action.action}")

            try {
                val result = service.executeAction(action)

                when (result.status) {
                    "SUCCESS" -> {
                        successfulActions++
                        Timber.d("Action succeeded: ${action.action}")
                    }
                    "FAILED", "ELEMENT_NOT_FOUND" -> {
                        failedActions++
                        Timber.w("Action failed: ${result.errorMessage}")

                        // Try replanning
                        val shouldReplan = shouldReplanAfterFailure(action, result)
                        if (shouldReplan) {
                            val newPlan = replanTask(plan, index, result)
                            if (newPlan != null) {
                                Timber.d("Replanning after failure")
                                executeTaskWithVerification(newPlan)
                                return
                            }
                        }

                        // If replanning fails or not needed, continue or stop?
                        if (failedActions > 2) {
                            throw Exception("Too many failures")
                        }
                    }
                }

                delay(500)  // Brief pause between actions
            } catch (e: Exception) {
                Timber.e(e, "Error executing action: ${action.action}")
                throw e
            }
        }

        Timber.d("Task completed: $successfulActions succeeded, $failedActions failed")
    }

    private fun shouldReplanAfterFailure(
        action: UIAction,
        result: ActionResult
    ): Boolean {
        // Replan if element wasn't found (might need to scroll or navigate)
        return result.status == "ELEMENT_NOT_FOUND"
    }

    private suspend fun replanTask(
        originalPlan: TaskPlan,
        failedActionIndex: Int,
        failureResult: ActionResult
    ): TaskPlan? {
        // In real implementation, send replan request to cloud LLM
        // For now, just log it
        Timber.d("Replan request for action: ${originalPlan.actions[failedActionIndex].action}")

        val request = ReplanRequest(
            taskId = originalPlan.taskId,
            lastAction = originalPlan.actions[failedActionIndex],
            expectedState = "element should be found",
            actualState = failureResult.screenStateAfter
                ?: ScreenState(
                    currentApp = "unknown",
                    visibleTexts = emptyList(),
                    uiTree = ""
                ),
            errorReason = failureResult.errorMessage ?: "Unknown error"
        )

        // TODO: Send to cloud LLM for replanning
        return null
    }

    private fun parseTaskPlan(json: String): TaskPlan {
        // Simplified parsing - in real app use Gson
        return TaskPlan(
            taskId = "task_001",
            originalIntent = UserIntent("test", "test_app", null),
            actions = listOf(UIAction("click", "test"))
        )
    }

    companion object {
        private const val TAG = "AgentExecutor"

        fun scheduleTask(context: Context, taskPlanJson: String) {
            // If Accessibility Service is not enabled, attempt safe fallbacks.
            if (!isAccessibilityServiceEnabled(context)) {
                Timber.w("Accessibility Service not enabled - refusing to enqueue complex automation")
                // Try quick fallback: if plan requests only open_app, launch it directly.
                try {
                    val gson = com.google.gson.Gson()
                    val planMap = gson.fromJson(taskPlanJson, Map::class.java)
                    @Suppress("UNCHECKED_CAST")
                    val actions = planMap["actions"] as? List<Map<String, Any>>
                    val firstOpen = actions?.firstOrNull { it["action"] == "open_app" }
                    val packageName = firstOpen?.get("value") as? String
                    if (!packageName.isNullOrEmpty()) {
                        val launchIntent = context.packageManager.getLaunchIntentForPackage(packageName)
                        if (launchIntent != null) {
                            launchIntent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                            context.startActivity(launchIntent)
                            android.os.Handler(android.os.Looper.getMainLooper()).post {
                                android.widget.Toast.makeText(context, "Launched $packageName (accessibility disabled)", android.widget.Toast.LENGTH_LONG).show()
                            }
                            return
                        }
                    }
                } catch (e: Exception) {
                    Timber.e(e, "Fallback launch failed")
                }

                // Notify user to enable Accessibility
                android.os.Handler(android.os.Looper.getMainLooper()).post {
                    android.widget.Toast.makeText(context, "Enable Accessibility Service in Settings for full automation", android.widget.Toast.LENGTH_LONG).show()
                }
                return
            }

            val taskRequest = OneTimeWorkRequestBuilder<AgentExecutorService>()
                .setInputData(
                    workDataOf(
                        "task_plan" to taskPlanJson
                    )
                )
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    10,
                    TimeUnit.SECONDS
                )
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                TAG,
                ExistingWorkPolicy.KEEP,
                taskRequest
            )
        }

        private fun isAccessibilityServiceEnabled(context: Context): Boolean {
            return try {
                val enabled = android.provider.Settings.Secure.getString(
                    context.contentResolver,
                    android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
                ) ?: return false

                val serviceId = "${context.packageName}/${"com.autonomousvision.accessibility.AutomationAccessibilityService"}"
                enabled.split(":").any { it.contains(serviceId) }
            } catch (e: Exception) {
                Timber.e(e, "Failed to check accessibility setting")
                false
            }
        }
    }
}
