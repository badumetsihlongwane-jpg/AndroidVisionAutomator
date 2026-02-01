package com.autonomousvision.models

import com.google.gson.annotations.SerializedName

/**
 * Intent: What the user wants to do (extracted by LLM)
 */
data class UserIntent(
    @SerializedName("intent")
    val intent: String,  // e.g., "send_message", "open_app", "search_web"
    
    @SerializedName("app")
    val targetApp: String?,  // e.g., "WhatsApp", "Gmail"
    
    @SerializedName("entities")
    val entities: Map<String, String>?  // e.g., {"contact": "Mom", "message": "I'm late"}
)

/**
 * Action: Concrete UI action (from task planner)
 */
data class UIAction(
    @SerializedName("action")
    val action: String,  // "click", "setText", "scroll", "open_app", "find_text"
    
    @SerializedName("target")
    val target: String? = null,  // Text/contentDescription to find
    
    @SerializedName("value")
    val value: String? = null,  // Text to set, package name, etc.
    
    @SerializedName("className")
    val className: String? = null,  // Filter by view class
    
    @SerializedName("index")
    val index: Int? = null  // If multiple matches, which one?
)

/**
 * Task Plan: Sequence of actions to execute
 */
data class TaskPlan(
    @SerializedName("task_id")
    val taskId: String,
    
    @SerializedName("intent")
    val originalIntent: UserIntent,
    
    @SerializedName("actions")
    val actions: List<UIAction>,
    
    @SerializedName("timestamp")
    val timestamp: Long = System.currentTimeMillis()
)

/**
 * Action Result: Feedback from action executor
 */
data class ActionResult(
    @SerializedName("action")
    val action: UIAction,
    
    @SerializedName("status")
    val status: String,  // "SUCCESS", "FAILED", "ELEMENT_NOT_FOUND"
    
    @SerializedName("error_message")
    val errorMessage: String? = null,
    
    @SerializedName("screen_state_after")
    val screenStateAfter: ScreenState? = null
)

/**
 * Screen State: Current UI feedback
 */
data class ScreenState(
    @SerializedName("current_app")
    val currentApp: String,
    
    @SerializedName("current_activity")
    val currentActivity: String? = null,
    
    @SerializedName("visible_texts")
    val visibleTexts: List<String>,
    
    @SerializedName("focused_element")
    val focusedElement: String? = null,
    
    @SerializedName("ui_tree")
    val uiTree: String,  // Serialized AccessibilityNodeInfo tree
    
    @SerializedName("screenshot_base64")
    val screenshotBase64: String? = null,  // Optional OCR fallback
    
    @SerializedName("timestamp")
    val timestamp: Long = System.currentTimeMillis()
)

/**
 * Replan Request: When verification fails
 */
data class ReplanRequest(
    @SerializedName("task_id")
    val taskId: String,
    
    @SerializedName("last_action")
    val lastAction: UIAction,
    
    @SerializedName("expected_state")
    val expectedState: String,
    
    @SerializedName("actual_state")
    val actualState: ScreenState,
    
    @SerializedName("error_reason")
    val errorReason: String
)
