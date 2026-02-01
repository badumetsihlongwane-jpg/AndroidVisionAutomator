package com.autonomousvision.safety

import com.autonomousvision.models.*
import timber.log.Timber

/**
 * Safety Manager - enforces security policies
 */
class SafetyManager(private val policy: SafetyPolicy = SafetyPolicy()) {
    
    /**
     * Check if an action is allowed
     */
    fun checkPermission(action: UIAction, targetApp: String? = null): PermissionRequest {
        // Check if target app is whitelisted
        if (targetApp != null && action.action == "open_app") {
            if (targetApp !in policy.allowedApps) {
                return PermissionRequest(
                    action = action,
                    level = ActionPermissionLevel.REQUIRES_CONFIRMATION,
                    reason = "Opening app outside whitelist: $targetApp"
                )
            }
        }
        
        // Check dangerous actions
        if (action.action in policy.dangerousActions) {
            Timber.w("Blocked dangerous action: ${action.action}")
            return PermissionRequest(
                action = action,
                level = ActionPermissionLevel.BLOCKED,
                reason = "Action blocked by safety policy: ${action.action}"
            )
        }
        
        // Check sensitive actions (require confirmation)
        if (action.action in policy.sensitiveActions) {
            return PermissionRequest(
                action = action,
                level = ActionPermissionLevel.REQUIRES_CONFIRMATION,
                reason = "Sensitive action requires user confirmation: ${action.action}"
            )
        }
        
        // All others are allowed
        return PermissionRequest(
            action = action,
            level = ActionPermissionLevel.ALLOWED,
            reason = "Action allowed",
            userApprovalNeeded = false
        )
    }
    
    /**
     * Validate task plan safety
     */
    fun validateTaskPlan(plan: TaskPlan): Boolean {
        if (plan.actions.size > policy.maxActionsPerTask) {
            Timber.w("Task exceeded max actions: ${plan.actions.size} > ${policy.maxActionsPerTask}")
            return false
        }
        
        for (action in plan.actions) {
            if (action.action in policy.dangerousActions) {
                Timber.w("Task contains dangerous action: ${action.action}")
                return false
            }
        }
        
        return true
    }
    
    /**
     * Get safety verdict for executing plan
     */
    fun getSafetyVerdictForPlan(plan: TaskPlan): SafetyVerdict {
        if (!policy.enabled) {
            return SafetyVerdict(allowed = true, requiresConfirmation = false)
        }
        
        if (!validateTaskPlan(plan)) {
            return SafetyVerdict(
                allowed = false,
                requiresConfirmation = false,
                reason = "Task plan violates safety policy"
            )
        }
        
        var needsConfirmation = false
        for (action in plan.actions) {
            val perm = checkPermission(action)
            when (perm.level) {
                ActionPermissionLevel.BLOCKED -> {
                    return SafetyVerdict(
                        allowed = false,
                        requiresConfirmation = false,
                        reason = perm.reason
                    )
                }
                ActionPermissionLevel.REQUIRES_CONFIRMATION -> {
                    needsConfirmation = true
                }
                else -> {}
            }
        }
        
        return SafetyVerdict(
            allowed = true,
            requiresConfirmation = needsConfirmation
        )
    }
}

data class SafetyVerdict(
    val allowed: Boolean,
    val requiresConfirmation: Boolean,
    val reason: String = "",
    val blockedActions: List<UIAction> = emptyList()
)
