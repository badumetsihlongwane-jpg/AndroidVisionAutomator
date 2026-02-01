#!/usr/bin/env python3
"""
Example usage and integration guide
"""

from backend.services.claude_llm_client import SyncClaudeLLMClient
import json

def example_voice_to_action():
    """
    Example: Voice input → Intent → Actions
    """
    
    # Initialize
    llm_client = SyncClaudeLLMClient()  # Uses ANTHROPIC_API_KEY env var
    
    # Step 1: User voice/text input
    user_command = "Send a message to Mom saying I'll be late"
    print(f"📱 User input: {user_command}")
    
    # Step 2: Parse intent (Layer 2️⃣)
    intent = llm_client.extract_intent_sync(user_command)
    print(f"\n🧠 Parsed intent: {json.dumps(intent, indent=2)}")
    
    # Step 3: Get current screen state (from Accessibility Service)
    current_screen = {
        "current_app": "com.android.launcher",
        "visible_texts": ["WhatsApp", "Messaging", "Settings", "Camera"],
        "focused_element": None
    }
    print(f"\n📺 Current screen: {current_screen['current_app']}")
    
    # Step 4: Plan actions (Layer 3️⃣)
    actions = llm_client.plan_actions_sync(intent, current_screen)
    print(f"\n📋 Action plan ({len(actions)} steps):")
    for i, action in enumerate(actions, 1):
        print(f"   {i}. {action.get('action')} {action.get('target') or action.get('value') or ''}")
    
    return actions


def example_with_verification():
    """
    Example: With verification and replanning
    """
    
    llm_client = SyncClaudeLLMClient()
    
    # Assume we got here from example_voice_to_action
    intent = {
        "intent": "send_message",
        "target_app": "com.whatsapp",
        "entities": {"contact": "Mom", "message": "I'll be late"}
    }
    
    actions = [
        {"action": "open_app", "value": "com.whatsapp"},
        {"action": "click", "target": "Mom"},
        {"action": "click", "target": "message input"},
        {"action": "setText", "value": "I'll be late"},
        {"action": "click", "target": "send"}
    ]
    
    print("🚀 Executing action sequence...")
    
    # After first action (open_app)
    print("\n✅ Action 1 succeeded: WhatsApp opened")
    
    # After second action (click Mom) - FAILURE
    screen_after_action = {
        "current_app": "com.whatsapp",
        "visible_texts": ["Chats", "Status", "Calls", "Settings"],
        "focused_element": None
    }
    
    print("\n❌ Action 2 failed: 'Mom' not found in chat list")
    print(f"   Visible: {screen_after_action['visible_texts']}")
    
    # Replan (Layer 6️⃣)
    print("\n🔄 Replanning...")
    new_actions = llm_client.replan_for_failure(
        intent,
        actions[1],
        "Contact 'Mom' not visible in chat list",
        screen_after_action
    )
    
    print(f"\n📋 New plan:")
    for i, action in enumerate(new_actions, 1):
        print(f"   {i}. {action.get('action')} {action.get('target') or action.get('value') or ''}")


def setup_android_integration():
    """
    Setup guide for Android app
    """
    print("""
🚀 ANDROID SETUP GUIDE
======================

1. Enable Accessibility Service:
   Settings → Accessibility → AndroidVisionAutomator
   
2. Grant Permissions:
   - RECORD_AUDIO (for voice input)
   - READ_EXTERNAL_STORAGE (optional)
   - INTERNET (for cloud LLM)

3. Configuration:
   - Set ANTHROPIC_API_KEY environment variable
   - Edit config.json for safety policies
   
4. Start Automation:
   - Open app and say: "Send a message to Mom"
   - Agent processes through all 7 layers
   - Tasks execute automatically

⚠️  Safety Features:
   - App whitelist (only trusted apps)
   - Dangerous action blocking
   - User confirmation for sensitive actions
   - Retry limit and task timeout
   - Kill switch available at all times
""")


if __name__ == "__main__":
    import os
    
    # Check if API key is set
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️  ANTHROPIC_API_KEY not set")
        print("   Export it: export ANTHROPIC_API_KEY=sk-...")
    else:
        print("✅ API key configured\n")
        
        # Run examples
        example_voice_to_action()
        print("\n" + "="*60 + "\n")
        example_with_verification()
        print("\n" + "="*60 + "\n")
        setup_android_integration()
