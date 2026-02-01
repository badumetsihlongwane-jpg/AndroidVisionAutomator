#!/usr/bin/env python3
"""
Claude LLM Integration for Android Vision Automator
Provides intent parsing and task planning via Anthropic API
"""

import anthropic
import json
import logging
from typing import Optional, Dict, Any
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("ClaudeLLM")


class ClaudeLLMClient:
    """
    Cloud LLM interface using Claude 3.5 Sonnet
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = "claude-3-5-sonnet-20241022"
    
    async def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        """
        Complete a prompt using Claude
        """
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            response = message.content[0].text
            logger.debug(f"Claude response: {response[:100]}...")
            return response
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise
    
    async def extract_intent(self, user_input: str) -> Dict[str, Any]:
        """
        Parse user command to intent
        """
        prompt = f"""You are an Android automation agent. Parse this user command into a structured intent.

User command: "{user_input}"

Respond with ONLY valid JSON in this format:
{{
  "intent": "one of: send_message, open_app, search, find_file, play_media, enable_feature, disable_feature, navigate_to, read_notification, make_call",
  "target_app": "app name if applicable, or null",
  "confidence": 0.0-1.0,
  "entities": {{
    "recipient": "contact name if applicable",
    "message": "message text if applicable",
    "search_query": "search term if applicable",
    "app_name": "target app if applicable"
  }}
}}"""
        
        response = await self.complete(prompt, max_tokens=512)
        
        try:
            # Extract JSON from response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        logger.error(f"Failed to parse intent from: {response}")
        return {
            "intent": "unknown",
            "target_app": None,
            "confidence": 0.0,
            "entities": {}
        }
    
    async def plan_actions(
        self,
        intent: Dict[str, Any],
        screen_state: Dict[str, Any]
    ) -> list:
        """
        Convert intent + screen state to action sequence
        """
        
        prompt = f"""You are planning a sequence of UI automation actions to achieve a goal.

User's intent:
- Action: {intent.get('intent')}
- Target app: {intent.get('target_app', 'N/A')}
- Details: {json.dumps(intent.get('entities', {}))}

Current screen state:
- Active app: {screen_state.get('current_app', 'unknown')}
- Visible elements: {screen_state.get('visible_texts', [])}
- Focused element: {screen_state.get('focused_element', 'N/A')}

Available actions:
- open_app: Launch an application (value: package name)
- click: Click an element (target: text or description)
- setText: Type text into a field (value: text to type)
- scroll: Scroll the screen (value: "up" or "down")
- find_text: Check if text is visible (target: text to find)
- wait: Pause briefly (value: milliseconds)
- back: Go back (Android back button)
- home: Go to home screen

Create a minimal action sequence to achieve the intent. Be specific with element names.
Respond with ONLY a JSON array, no explanation:

[
  {{"action": "action_name", "target": "element text or null", "value": "value or null"}},
  ...
]"""
        
        response = await self.complete(prompt, max_tokens=1024)
        
        try:
            # Extract JSON array
            json_start = response.find('[')
            json_end = response.rfind(']') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse actions from: {response}")
        
        return []
    
    async def verify_action_success(
        self,
        action: Dict[str, Any],
        expected_state: str,
        actual_screen_state: Dict[str, Any]
    ) -> bool:
        """
        Verify if action achieved expected result
        """
        
        prompt = f"""Did this UI automation action succeed?

Action: {action.get('action')} {action.get('target') or action.get('value') or ''}
Expected result: {expected_state}

Actual screen after action:
- App: {actual_screen_state.get('current_app')}
- Visible text: {actual_screen_state.get('visible_texts', [])}

Respond with only "YES" or "NO"."""
        
        response = await self.complete(prompt, max_tokens=10)
        return "YES" in response.upper()
    
    async def replan_for_failure(
        self,
        original_intent: Dict[str, Any],
        failed_action: Dict[str, Any],
        failure_reason: str,
        current_screen_state: Dict[str, Any]
    ) -> list:
        """
        Create alternative action sequence after failure
        """
        
        prompt = f"""An action failed during automation. Create an alternative plan.

Original intent: {original_intent.get('intent')}
Failed action: {failed_action.get('action')} {failed_action.get('target') or failed_action.get('value')}
Reason: {failure_reason}

Current screen:
- App: {current_screen_state.get('current_app')}
- Visible: {current_screen_state.get('visible_texts', [])}

Alternative approach? Return JSON action array:
[{{"action": "...", "target": "...", "value": "..."}}, ...]"""
        
        response = await self.complete(prompt, max_tokens=1024)
        
        try:
            json_start = response.find('[')
            json_end = response.rfind(']') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        return []


# Synchronous wrapper for Android integration
class SyncClaudeLLMClient(ClaudeLLMClient):
    """Synchronous version for easier Android integration"""
    
    def complete_sync(self, prompt: str, max_tokens: int = 1024) -> str:
        """Synchronous version of complete()"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return message.content[0].text
    
    def extract_intent_sync(self, user_input: str) -> Dict[str, Any]:
        """Synchronous intent extraction"""
        prompt = f"""Parse this Android automation command:
"{user_input}"

JSON format:
{{"intent": "...", "target_app": "...", "entities": {{...}}}}"""
        
        response = self.complete_sync(prompt, max_tokens=512)
        
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass
        
        return {"intent": "unknown", "target_app": None, "entities": {}}
    
    def plan_actions_sync(
        self,
        intent: Dict[str, Any],
        screen_state: Dict[str, Any]
    ) -> list:
        """Synchronous action planning"""
        prompt = f"""Plan UI actions for: {intent.get('intent')}
Current app: {screen_state.get('current_app')}
Visible: {screen_state.get('visible_texts', [])}

JSON array only."""
        
        response = self.complete_sync(prompt, max_tokens=1024)
        
        try:
            json_start = response.find('[')
            json_end = response.rfind(']') + 1
            if json_start >= 0:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass
        
        return []


if __name__ == "__main__":
    import asyncio
    
    async def test():
        client = ClaudeLLMClient()
        
        intent = await client.extract_intent("Send a message to Mom saying I'll be late")
        print(f"Intent: {json.dumps(intent, indent=2)}")
    
    asyncio.run(test())
