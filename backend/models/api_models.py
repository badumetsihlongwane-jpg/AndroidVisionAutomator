"""
Models for backend API
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional


@dataclass
class UserRequest:
    """Incoming request from Android device"""
    user_id: str
    command: str
    screen_state: Dict[str, Any]
    timestamp: float


@dataclass
class TaskExecutionLog:
    """Log entry for task execution"""
    task_id: str
    action_index: int
    action_type: str
    status: str  # SUCCESS, FAILED, ELEMENT_NOT_FOUND
    duration_ms: int
    error_message: Optional[str] = None
    screen_state_after: Optional[Dict[str, Any]] = None


@dataclass
class ApiResponse:
    """Standard API response"""
    success: bool
    data: Any
    error: Optional[str] = None
    timestamp: Optional[str] = None
