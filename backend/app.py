#!/usr/bin/env python3
"""
Backend REST API for AndroidVisionAutomator
Handles communication between Android app and cloud LLM
"""

from flask import Flask, request, jsonify
from services.claude_llm_client import SyncClaudeLLMClient
import json
import logging
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize LLM client
llm_client = SyncClaudeLLMClient()

# Simple in-memory task storage (replace with database in production)
tasks = {}


@app.route('/api/intent', methods=['POST'])
def parse_intent():
    """
    Parse user input to intent
    
    Request: {"input": "Send message to Mom"}
    Response: {"intent": "send_message", "target_app": "WhatsApp", "entities": {...}}
    """
    try:
        data = request.json
        user_input = data.get('input')
        
        if not user_input:
            return jsonify({"error": "No input provided"}), 400
        
        logger.info(f"Parsing intent: {user_input}")
        intent = llm_client.extract_intent_sync(user_input)
        
        return jsonify(intent), 200
    except Exception as e:
        logger.error(f"Error parsing intent: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/plan', methods=['POST'])
def plan_task():
    """
    Create action plan from intent and screen state
    
    Request: {
        "intent": {...},
        "screen_state": {
            "current_app": "com.android.launcher",
            "visible_texts": [...],
            "focused_element": "..."
        }
    }
    Response: [{"action": "...", "target": "...", "value": "..."}, ...]
    """
    try:
        data = request.json
        intent = data.get('intent')
        screen_state = data.get('screen_state')
        
        if not intent or not screen_state:
            return jsonify({"error": "Missing intent or screen_state"}), 400
        
        logger.info(f"Planning task for intent: {intent.get('intent')}")
        actions = llm_client.plan_actions_sync(intent, screen_state)
        
        # Save task
        task_id = f"task_{datetime.now().timestamp()}"
        tasks[task_id] = {
            "intent": intent,
            "actions": actions,
            "screen_state": screen_state,
            "created_at": datetime.now().isoformat()
        }
        
        return jsonify({
            "task_id": task_id,
            "actions": actions
        }), 200
    except Exception as e:
        logger.error(f"Error planning task: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/verify', methods=['POST'])
def verify_action():
    """
    Verify if an action succeeded
    
    Request: {
        "action": {...},
        "expected_state": "...",
        "actual_screen_state": {...}
    }
    Response: {"success": true/false}
    """
    try:
        data = request.json
        action = data.get('action')
        expected_state = data.get('expected_state')
        actual_screen = data.get('actual_screen_state')
        
        logger.info(f"Verifying action: {action.get('action')}")
        
        success = llm_client.verify_action_success(
            action,
            expected_state,
            actual_screen
        )
        
        return jsonify({"success": success}), 200
    except Exception as e:
        logger.error(f"Error verifying action: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/replan', methods=['POST'])
def replan_task():
    """
    Replan after action failure
    
    Request: {
        "original_intent": {...},
        "failed_action": {...},
        "failure_reason": "...",
        "current_screen_state": {...}
    }
    Response: [{"action": "...", ...}, ...]
    """
    try:
        data = request.json
        intent = data.get('original_intent')
        failed_action = data.get('failed_action')
        failure_reason = data.get('failure_reason')
        screen_state = data.get('current_screen_state')
        
        logger.warning(f"Replanning after failure: {failure_reason}")
        
        new_actions = llm_client.replan_for_failure(
            intent,
            failed_action,
            failure_reason,
            screen_state
        )
        
        return jsonify({"actions": new_actions}), 200
    except Exception as e:
        logger.error(f"Error replanning: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/task/<task_id>', methods=['GET'])
def get_task(task_id):
    """Get task details"""
    if task_id in tasks:
        return jsonify(tasks[task_id]), 200
    return jsonify({"error": "Task not found"}), 404


@app.route('/api/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200


if __name__ == '__main__':
    logger.info("Starting AndroidVisionAutomator Backend API")
    app.run(host='0.0.0.0', port=5000, debug=True)
