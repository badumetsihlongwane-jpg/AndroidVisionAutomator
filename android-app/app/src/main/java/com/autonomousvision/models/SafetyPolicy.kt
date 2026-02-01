package com.autonomousvision.models

import com.google.gson.annotations.SerializedName

/**
 * Safety Policy: Controls what actions are allowed
 */
data class SafetyPolicy(
    @SerializedName("allowed_apps")
    val allowedApps: Set<String> = setOf(
        "com.whatsapp",
        "com.google.android.apps.messaging",
        "com.google.android.apps.maps",
        "com.google.android.youtube",
        "com.google.android.googlequicksearchbox"
    ),
    
    @SerializedName("dangerous_actions")
    val dangerousActions: Set<String> = setOf(
        "delete_file",
        "uninstall_app",
        "change_settings",
        "send_payment"
    ),
    
    @SerializedName("sensitive_actions_require_confirmation")
    val sensitiveActions: Set<String> = setOf(
        "send_message",
        "make_call",
        "send_email"
    ),
    
    @SerializedName("max_retry_count")
    val maxRetryCount: Int = 3,
    
    @SerializedName("max_actions_per_task")
    val maxActionsPerTask: Int = 50,
    
    @SerializedName("enabled")
    val enabled: Boolean = true
)

/**
 * Action Permission: Check if action is allowed
 */
enum class ActionPermissionLevel {
    ALLOWED,           // Execute immediately
    REQUIRES_CONFIRMATION,  // Ask user first
    DANGEROUS,         // Block or ask user explicitly
    BLOCKED            // Never execute
}

data class PermissionRequest(
    @SerializedName("action")
    val action: UIAction,
    
    @SerializedName("level")
    val level: ActionPermissionLevel,
    
    @SerializedName("reason")
    val reason: String,
    
    @SerializedName("user_approval_needed")
    val userApprovalNeeded: Boolean = level != ActionPermissionLevel.ALLOWED
)
