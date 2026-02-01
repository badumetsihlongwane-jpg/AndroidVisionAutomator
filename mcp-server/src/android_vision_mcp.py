#!/usr/bin/env python3
"""
MCP Server for Android Vision Automator
Provides:
1. Intent Parser (LLM)
2. Task Planner (LLM)
3. Verification Loop Manager
4. Communication with Android agent
"""

import json
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
import asyncio

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("AndroidVisionMCP")


@dataclass
class UserIntent:
    """Parsed user intent (from LLM)"""
    intent: str
    target_app: Optional[str] = None
    entities: Optional[Dict[str, str]] = None


@dataclass
class UIAction:
    """Concrete UI action (from task planner)"""
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    className: Optional[str] = None
    index: Optional[int] = None


@dataclass
class TaskPlan:
    """Complete task plan with actions"""
    task_id: str
    original_intent: UserIntent
    actions: List[UIAction]


class IntentParser:
    """
    Layer 2️⃣: Intent Understanding using LLM
    Converts natural language to structured intent
    """
    
    def __init__(self, llm_client):
        self.llm = llm_client
    
    async def parse_user_input(self, user_input: str) -> UserIntent:
        """
        Convert user text/voice to structured intent
        """
        prompt = f"""Parse this user command into a structured intent:

Command: "{user_input}"

Return JSON with:
- intent: what action (send_message, open_app, search, etc)
- target_app: which app if applicable
- entities: extracted data (contact names, messages, search terms, etc)

Example:
{{"intent": "send_message", "target_app": "WhatsApp", "entities": {{"contact": "Mom", "message": "I'm late"}}}}

Return ONLY valid JSON."""

        response = await self.llm.complete(prompt)
        
        try:
            intent_data = json.loads(response)
            return UserIntent(
                intent=intent_data.get("intent"),
                target_app=intent_data.get("target_app"),
                entities=intent_data.get("entities")
            )
        except json.JSONDecodeError:
            logger.error(f"Failed to parse intent: {response}")
            raise ValueError(f"Invalid intent format: {response}")


class TaskPlanner:
    """
    Layer 3️⃣: Task Planner using LLM
    Converts intent + app state into action sequence
    """
    
    def __init__(self, llm_client):
        self.llm = llm_client
    
    async def plan_task(
        self,
        intent: UserIntent,
        current_screen_state: Dict[str, Any]
    ) -> TaskPlan:
        """
        Create concrete action plan from intent and current screen
        """
        
        prompt = f"""Given the user intent and current screen state, create a sequence of UI actions.

User Intent:
{json.dumps(asdict(intent), indent=2)}

Current Screen:
- App: {current_screen_state.get('current_app')}
- Visible text: {current_screen_state.get('visible_texts')}
- Focused element: {current_screen_state.get('focused_element')}

Available actions:
- click: click on element by text
- setText: set text in input field
- scroll: scroll screen (up/down)
- open_app: launch application by package
- find_text: verify text exists
- back: go back
- home: go to home

Return JSON array of actions:
[
  {{"action": "open_app", "value": "com.whatsapp"}},
  {{"action": "find_text", "target": "Mom"}},
  {{"action": "click", "target": "Mom"}},
  {{"action": "setText", "value": "I'm late"}}
]

Requirements:
- Be specific with text targets
- Use scroll if element not found
- Verify each major step
- Maximum 20 actions per task"""

        response = await self.llm.complete(prompt)
        
        try:
            actions_data = json.loads(response)
            actions = [
                UIAction(
                    action=a["action"],
                    target=a.get("target"),
                    value=a.get("value"),
                    className=a.get("className"),
                    index=a.get("index")
                )
                for a in actions_data
            ]
            
            return TaskPlan(
                task_id=f"task_{id(intent)}",
                original_intent=intent,
                actions=actions
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse task plan: {response}")
            raise ValueError(f"Invalid task plan format: {response}")


class VerificationLoop:
    """
    Layer 6️⃣: Verification & Replanning
    Checks if expected UI state appears after each action
    """
    
    def __init__(self, llm_client, task_planner):
        self.llm = llm_client
        self.planner = task_planner
    
    async def verify_action_result(
        self,
        action: UIAction,
        expected_outcome: str,
        actual_screen_state: Dict[str, Any]
    ) -> bool:
        """
        Check if action produced expected result
        """
        verification_prompt = f"""Did this action achieve its goal?

Action: {action.action}
Target: {action.target or action.value}
Expected: {expected_outcome}

Actual Screen:
- App: {actual_screen_state.get('current_app')}
- Visible: {actual_screen_state.get('visible_texts')}

Answer YES or NO."""

        response = await self.llm.complete(verification_prompt)
        return "YES" in response.upper()
    
    async def replan_after_failure(
        self,
        original_plan: TaskPlan,
        failed_action_index: int,
        failure_reason: str,
        current_screen_state: Dict[str, Any]
    ) -> Optional[TaskPlan]:
        """
        Create alternative plan after action failure
        """
        failed_action = original_plan.actions[failed_action_index]
        
        replan_prompt = f"""The action failed. Create an alternative plan.

Failed action: {failed_action.action} ({failed_action.target or failed_action.value})
Reason: {failure_reason}

Current Screen:
- App: {current_screen_state.get('current_app')}
- Visible: {current_screen_state.get('visible_texts')}

Original goal: {original_plan.original_intent.intent}

Alternative approach to achieve the goal:
- Try scrolling first?
- Navigate differently?
- Use different UI path?

Return new action sequence."""

        try:
            new_plan = await self.planner.plan_task(
                original_plan.original_intent,
                current_screen_state
            )
            return new_plan
        except Exception as e:
            logger.error(f"Replan failed: {e}")
            return None


class AndroidVisionMCP:
    """
    Main MCP Server orchestrating all layers
    """
    
    def __init__(self, llm_client):
        self.llm = llm_client
        self.intent_parser = IntentParser(llm_client)
        self.task_planner = TaskPlanner(llm_client)
        self.verifier = VerificationLoop(llm_client, self.task_planner)
    
    async def process_user_command(
        self,
        user_input: str,
        current_screen_state: Dict[str, Any]
    ) -> TaskPlan:
        """
        Full pipeline: text → intent → plan
        """
        logger.info(f"Processing: {user_input}")
        
        # Step 1: Parse intent
        intent = await self.intent_parser.parse_user_input(user_input)
        logger.debug(f"Parsed intent: {intent}")
        
        # Step 2: Plan task
        plan = await self.task_planner.plan_task(intent, current_screen_state)
        logger.debug(f"Created plan with {len(plan.actions)} actions")
        
        return plan
    
    async def handle_action_result(
        self,
        task_plan: TaskPlan,
        action_index: int,
        action_result: Dict[str, Any],
        current_screen_state: Dict[str, Any]
    ) -> Optional[TaskPlan]:
        """
        Process action result and replan if needed
        """
        action = task_plan.actions[action_index]
        status = action_result.get("status")
        
        if status == "SUCCESS":
            logger.debug(f"Action {action_index} succeeded")
            return task_plan
        
        if status == "ELEMENT_NOT_FOUND":
            logger.warning(f"Action {action_index} failed: element not found")
            
            # Try replanning
            new_plan = await self.verifier.replan_after_failure(
                task_plan,
                action_index,
                "Element not found",
                current_screen_state
            )
            
            return new_plan
        
        return None


async def main():
    """Example usage"""
    from mcp_llm_client import MockLLMClient
    
    llm = MockLLMClient()  # Replace with real Claude client
    mcp = AndroidVisionMCP(llm)
    
    # Example flow
    screen_state = {
        "current_app": "com.android.launcher",
        "visible_texts": ["WhatsApp", "Messages", "Settings"],
        "focused_element": None
    }
    
    task_plan = await mcp.process_user_command(
        "Send a message to Mom saying I'll be late",
        screen_state
    )
    
    print(f"Task plan: {len(task_plan.actions)} actions")
    for i, action in enumerate(task_plan.actions):
        print(f"  {i+1}. {action.action} {action.target or action.value}")


if __name__ == "__main__":
    asyncio.run(main())
