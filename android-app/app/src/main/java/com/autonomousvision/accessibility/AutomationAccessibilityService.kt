package com.autonomousvision.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.autonomousvision.models.ActionResult
import com.autonomousvision.models.ScreenState
import com.autonomousvision.models.UIAction
import kotlinx.coroutines.*
import timber.log.Timber

/**
 * Core Accessibility Service - this is the "hands" of the automation system
 * Executes UI actions and provides screen feedback
 */
class AutomationAccessibilityService : AccessibilityService() {
    
    private val screenAnalyzer = ScreenAnalyzer()
    private var lastScreenState: ScreenState? = null

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return
        
        Timber.d("Accessibility Event: ${event.eventType} from ${event.packageName}")
        
        // Update screen state on major events
        if (event.eventType in listOf(
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED
        )) {
            lastScreenState = screenAnalyzer.captureScreenState(this)
        }
    }

    override fun onInterrupt() {
        Timber.d("Accessibility Service interrupted")
    }

    /**
     * Execute a UI Action - main entry point for action executor
     */
    suspend fun executeAction(action: UIAction): ActionResult = withContext(Dispatchers.Main) {
        return@withContext try {
            val result = when (action.action) {
                "click" -> handleClick(action)
                "setText" -> handleSetText(action)
                "scroll" -> handleScroll(action)
                "back" -> handleBack()
                "home" -> handleHome()
                "open_app" -> handleOpenApp(action)
                "find_text" -> handleFindText(action)
                "wait" -> handleWait(action)
                else -> ActionResult(
                    action = action,
                    status = "FAILED",
                    errorMessage = "Unknown action: ${action.action}"
                )
            }
            
            // Capture screen state after action
            delay(500)  // Wait for UI to settle
            val screenState = screenAnalyzer.captureScreenState(this@AutomationAccessibilityService)
            lastScreenState = screenState
            
            result.copy(screenStateAfter = screenState)
        } catch (e: Exception) {
            Timber.e(e, "Error executing action: ${action.action}")
            ActionResult(
                action = action,
                status = "FAILED",
                errorMessage = e.message ?: "Unknown error"
            )
        }
    }

    private suspend fun handleClick(action: UIAction): ActionResult {
        val nodeInfo = findAccessibilityNode(
            text = action.target,
            className = action.className
        )
        
        return if (nodeInfo != null) {
            if (performClick(nodeInfo)) {
                ActionResult(action = action, status = "SUCCESS")
            } else {
                ActionResult(
                    action = action,
                    status = "FAILED",
                    errorMessage = "Click gesture failed"
                )
            }
        } else {
            ActionResult(
                action = action,
                status = "ELEMENT_NOT_FOUND",
                errorMessage = "Could not find element: ${action.target}"
            )
        }
    }

    private suspend fun handleSetText(action: UIAction): ActionResult {
        val nodeInfo = findAccessibilityNode(
            text = action.target,
            className = action.className
        )
        
        return if (nodeInfo != null && nodeInfo.isEditable) {
            // Clear existing text
            val bundle = android.os.Bundle()
            bundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                action.value.orEmpty()
            )
            
            if (nodeInfo.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle)) {
                ActionResult(action = action, status = "SUCCESS")
            } else {
                // Fallback: focus + clipboard paste
                try {
                    nodeInfo.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
                    val clipboard = getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                    val clip = android.content.ClipData.newPlainText("automation", action.value.orEmpty())
                    clipboard.setPrimaryClip(clip)
                    if (nodeInfo.performAction(AccessibilityNodeInfo.ACTION_PASTE)) {
                        ActionResult(action = action, status = "SUCCESS")
                    } else {
                        ActionResult(
                            action = action,
                            status = "FAILED",
                            errorMessage = "setText failed (and paste fallback failed)"
                        )
                    }
                } catch (e: Exception) {
                    Timber.w(e, "setText fallback failed")
                    ActionResult(
                        action = action,
                        status = "FAILED",
                        errorMessage = "setText failed: ${e.message}"
                    )
                }
            }
        } else {
            ActionResult(
                action = action,
                status = "ELEMENT_NOT_FOUND",
                errorMessage = "Editable element not found: ${action.target}"
            )
        }
    }

    private suspend fun handleScroll(action: UIAction): ActionResult {
        val direction = action.value ?: "down"  // up, down, left, right
        val nodeInfo = rootInActiveWindow ?: return ActionResult(
            action = action,
            status = "FAILED",
            errorMessage = "No active window"
        )
        
        val scrollAction = when (direction) {
            "up" -> AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
            "down" -> AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
            else -> AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
        }
        
        return if (nodeInfo.performAction(scrollAction)) {
            ActionResult(action = action, status = "SUCCESS")
        } else {
            ActionResult(
                action = action,
                status = "FAILED",
                errorMessage = "Scroll failed"
            )
        }
    }

    private suspend fun handleBack(): ActionResult {
        return if (performGlobalAction(GLOBAL_ACTION_BACK)) {
            ActionResult(
                action = UIAction(action = "back"),
                status = "SUCCESS"
            )
        } else {
            ActionResult(
                action = UIAction(action = "back"),
                status = "FAILED",
                errorMessage = "Back action failed"
            )
        }
    }

    private suspend fun handleHome(): ActionResult {
        return if (performGlobalAction(GLOBAL_ACTION_HOME)) {
            ActionResult(
                action = UIAction(action = "home"),
                status = "SUCCESS"
            )
        } else {
            ActionResult(
                action = UIAction(action = "home"),
                status = "FAILED",
                errorMessage = "Home action failed"
            )
        }
    }

    private suspend fun handleOpenApp(action: UIAction): ActionResult {
        val packageName = action.value ?: return ActionResult(
            action = action,
            status = "FAILED",
            errorMessage = "No package name provided"
        )
        
        return try {
            val intent = packageManager.getLaunchIntentForPackage(packageName)
            if (intent != null) {
                intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                try {
                    startActivity(intent)
                } catch (e: Exception) {
                    // Some device policies or contexts prevent starting activity from service; try fallback via shell
                    Timber.w(e, "startActivity failed from AccessibilityService, attempting fallback")
                    try {
                        val pm = packageManager
                        val launch = pm.getLaunchIntentForPackage(packageName)
                        if (launch != null) {
                            launch.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                            startActivity(launch)
                        }
                    } catch (ex: Exception) {
                        Timber.e(ex, "Fallback launch also failed")
                        return ActionResult(action = action, status = "FAILED", errorMessage = ex.message)
                    }
                }
                delay(2000)  // Wait for app to open
                ActionResult(action = action, status = "SUCCESS")
            } else {
                ActionResult(
                    action = action,
                    status = "FAILED",
                    errorMessage = "App not found: $packageName"
                )
            }
        } catch (e: Exception) {
            ActionResult(
                action = action,
                status = "FAILED",
                errorMessage = e.message
            )
        }
    }

    private suspend fun handleFindText(action: UIAction): ActionResult {
        val node = findAccessibilityNode(text = action.target)
        return if (node != null) {
            ActionResult(action = action, status = "SUCCESS")
        } else {
            ActionResult(
                action = action,
                status = "ELEMENT_NOT_FOUND",
                errorMessage = "Text not found: ${action.target}"
            )
        }
    }

    private suspend fun handleWait(action: UIAction): ActionResult {
        val duration = action.value?.toLongOrNull() ?: 1000
        delay(duration)
        return ActionResult(action = action, status = "SUCCESS")
    }

    /**
     * Find accessibility node by text or other properties
     */
    private fun findAccessibilityNode(
        text: String? = null,
        className: String? = null
    ): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        
        fun traverse(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
            try {
                // Check if this node matches
                if (text != null && node.text?.contains(text, ignoreCase = true) == true) {
                    return node
                }
                if (text != null && node.contentDescription?.toString()?.contains(text, ignoreCase = true) == true) {
                    return node
                }
                if (className != null && node.className?.endsWith(className) == true) {
                    return node
                }

                // Traverse children
                for (i in 0 until node.childCount) {
                    val child = node.getChild(i) ?: continue
                    val result = traverse(child)
                    if (result != null) return result
                }
            } catch (e: Exception) {
                Timber.w(e, "Error traversing node")
            }

            return null
        }
        
        return traverse(root)
    }

    /**
     * Perform click using accessibility or gestures
     */
    private suspend fun performClick(nodeInfo: AccessibilityNodeInfo): Boolean {
        try {
            // Try accessibility click first
            if (nodeInfo.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                return true
            }

            // Try clicking parent as a fallback
            val parent = nodeInfo.parent
            if (parent != null) {
                try {
                    if (parent.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                        return true
                    }
                } catch (e: Exception) {
                    Timber.w(e, "Parent click fallback failed")
                }
            }

            // Fallback to gesture
            val bounds = android.graphics.Rect()
            nodeInfo.getBoundsInScreen(bounds)

            if (bounds.width() > 0 && bounds.height() > 0) {
                val x = bounds.centerX().toFloat()
                val y = bounds.centerY().toFloat()
                return performGestureClick(x, y)
            }
        } catch (e: Exception) {
            Timber.e(e, "performClick failed")
        }

        return false
    }

    private suspend fun performGestureClick(x: Float, y: Float): Boolean {
        return withContext(Dispatchers.Main) {
            val path = Path()
            path.moveTo(x, y)
            val gesture = GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, 100))
                .build()
            
            dispatchGesture(gesture, object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) {
                    Timber.d("Gesture completed")
                }
                
                override fun onCancelled(gestureDescription: GestureDescription?) {
                    Timber.d("Gesture cancelled")
                }
            }, null)
            
            true
        }
    }

    /**
     * Get current screen state
     */
    fun getCurrentScreenState(): ScreenState? {
        return lastScreenState ?: screenAnalyzer.captureScreenState(this)
    }

    companion object {
        private var instance: AutomationAccessibilityService? = null
        
        fun getInstance(): AutomationAccessibilityService? = instance
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        Timber.plant(Timber.DebugTree())
    }
}
