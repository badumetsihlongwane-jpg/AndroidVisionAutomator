package com.autonomousvision.accessibility

import android.accessibilityservice.AccessibilityService
import android.app.ActivityManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.accessibility.AccessibilityNodeInfo
import com.autonomousvision.models.ScreenState
import timber.log.Timber

/**
 * Captures and analyzes screen state for feedback to the planner
 */
class ScreenAnalyzer {
    
    fun captureScreenState(service: AccessibilityService): ScreenState {
        val rootNode = service.rootInActiveWindow
        val activityManager = service.getSystemService(ActivityManager::class.java)
        
        val currentApp = getCurrentApp(activityManager)
        val visibleTexts = extractVisibleTexts(rootNode)
        val focusedElement = getFocusedElement(rootNode)
        val uiTree = serializeNodeTree(rootNode)
        
        return ScreenState(
            currentApp = currentApp,
            visibleTexts = visibleTexts,
            focusedElement = focusedElement,
            uiTree = uiTree,
            timestamp = System.currentTimeMillis()
        )
    }
    
    private fun getCurrentApp(activityManager: ActivityManager?): String {
        try {
            val tasks = activityManager?.getRunningTasks(1)
            if (!tasks.isNullOrEmpty()) {
                return tasks[0].topActivity?.packageName ?: "unknown"
            }
        } catch (e: Exception) {
            Timber.e(e, "Error getting current app")
        }
        return "unknown"
    }
    
    private fun extractVisibleTexts(root: AccessibilityNodeInfo?): List<String> {
        val texts = mutableListOf<String>()
        
        fun traverse(node: AccessibilityNodeInfo?) {
            if (node == null) return
            
            node.text?.takeIf { it.isNotEmpty() }?.let {
                texts.add(it.toString())
            }
            
            for (i in 0 until (node.childCount ?: 0)) {
                traverse(node.getChild(i))
            }
        }
        
        traverse(root)
        return texts.distinct()
    }
    
    private fun getFocusedElement(root: AccessibilityNodeInfo?): String? {
        var focused = root
        var depth = 0
        
        while (focused != null && depth < 20) {
            if (focused.isFocused) {
                return focused.text?.toString() ?: focused.contentDescription?.toString()
            }
            focused = focused.parent
            depth++
        }
        
        return null
    }
    
    private fun serializeNodeTree(root: AccessibilityNodeInfo?, depth: Int = 0): String {
        if (root == null) return ""
        
        val indent = "  ".repeat(depth)
        val text = root.text?.toString() ?: ""
        val desc = root.contentDescription?.toString() ?: ""
        val className = root.className?.toString()?.substringAfterLast(".") ?: ""
        
        val sb = StringBuilder()
        sb.append("$indent<$className")
        if (text.isNotEmpty()) sb.append(" text=\"$text\"")
        if (desc.isNotEmpty()) sb.append(" desc=\"$desc\"")
        
        if (root.childCount == 0) {
            sb.append(" />\n")
        } else {
            sb.append(">\n")
            for (i in 0 until root.childCount) {
                val child = root.getChild(i)
                if (child != null) {
                    sb.append(serializeNodeTree(child, depth + 1))
                }
            }
            sb.append("$indent</$className>\n")
        }
        
        return sb.toString()
    }
}
