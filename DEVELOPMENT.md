## Development Guide for AndroidVisionAutomator

### Project Setup

1. **Clone repository**
```bash
git clone https://github.com/badumetsihlongwane-jpg/AndroidVisionAutomator
cd AndroidVisionAutomator
```

2. **Install dependencies**
```bash
chmod +x setup.sh
./setup.sh
```

3. **Configure API key**
```bash
export ANTHROPIC_API_KEY=sk-your-anthropic-key
```

### Architecture Overview

The project has 7 layers:

```
User Input (Voice/Text)
    ↓
Intent Parser (LLM - Claude)
    ↓
Task Planner (LLM - Claude)
    ↓
Action Executor (Android Accessibility Service)
    ↓
Screen Feedback (UI Tree Analysis)
    ↓
Verification & Replanning Loop
    ↓
Safety & Permissions Manager
```

### Key Components

#### Android Layer (`android-app/`)

- **AutomationAccessibilityService.kt**
  - Core service that executes UI actions
  - Handles click, setText, scroll, app launching
  - Captures screen state after each action

- **ScreenAnalyzer.kt**
  - Extracts visible text and UI hierarchy
  - Creates screen state JSON for LLM
  - Supports optional OCR with ML Kit

- **AgentExecutorService.kt**
  - Orchestrates task execution
  - Handles action verification
  - Implements retry/replan logic

- **SafetyManager.kt**
  - Enforces action whitelist
  - Blocks dangerous operations
  - Requires confirmation for sensitive actions

#### Backend Layer (`backend/`)

- **claude_llm_client.py**
  - Connects to Anthropic Claude API
  - Implements intent parsing
  - Generates action plans
  - Handles replanning on failure

- **app.py**
  - Flask REST API server
  - Endpoints for intent → plan → replan
  - Task tracking and logging

#### MCP Server (`mcp-server/`)

- **android_vision_mcp.py**
  - Main orchestrator combining all layers
  - Implements Model Context Protocol
  - Provides async/await interface

### Development Workflow

#### Adding New Actions

1. Define action in `UIAction` model (`models/Intent.kt`)
2. Implement in `AutomationAccessibilityService.handleXxx()`
3. Add to LLM prompt in `claude_llm_client.py`
4. Test with example command

Example - Adding a new action:
```kotlin
// In AutomationAccessibilityService.kt
private suspend fun handleCustomAction(action: UIAction): ActionResult {
    // Implementation
    return ActionResult(action = action, status = "SUCCESS")
}
```

#### Adding New Safety Rules

1. Edit `SafetyPolicy.kt` to add rule
2. Implement check in `SafetyManager.checkPermission()`
3. Test with safety tests

```kotlin
// In SafetyPolicy.kt
val newRestrictedAction = setOf(
    "restricted_action_1",
    "restricted_action_2"
)
```

#### Testing

```bash
# Android unit tests
cd android-app
./gradlew test

# Python backend tests
pytest backend/tests/

# Integration test
python examples.py
```

#### Debugging

**Android:**
- Enable Accessibility service logging
- Check logcat: `adb logcat -s "AndroidVisionAutomator"`
- Use Android Studio debugger

**Backend:**
- Check API responses: `curl localhost:5000/api/health`
- Enable debug logging in `claude_llm_client.py`
- Test LLM calls independently

### Common Tasks

#### Update Whitelist

Edit `config.json`:
```json
{
  "safety_policy": {
    "allowed_apps": [
      "com.new.app.package",
      "com.another.app"
    ]
  }
}
```

#### Change LLM Model

Edit `config.json`:
```json
{
  "llm": {
    "model": "claude-3-opus-20240229"
  }
}
```

#### Add Custom Action

1. Update `UIAction.action` enum
2. Implement executor in `AutomationAccessibilityService`
3. Update LLM prompt
4. Add safety rule if needed

#### Implement New Verification Strategy

Edit `VerificationLoop.verify_action_result()` to add custom verification logic.

### Performance Optimization

- **Screen capture:** Currently captures full tree. Can optimize to diff-based.
- **Action execution:** Batch actions when possible to reduce latency.
- **LLM calls:** Cache common intents to reduce API calls.
- **UI tree traversal:** Use indexed search instead of linear traversal.

### Troubleshooting

**"Accessibility Service not running"**
- Ensure service is enabled in Settings → Accessibility
- Check permissions are granted

**"Element not found" loops**
- Add scroll actions to task plan
- Increase element matching tolerance
- Check if element is actually on screen

**LLM timeouts**
- Check internet connection
- Verify API key is valid
- Increase timeout in config

**Safety policy blocked action**
- Add app to whitelist if safe
- Change action permission level
- Review safety policy requirements

### Contributing

1. Fork repository
2. Create feature branch: `git checkout -b feature/your-feature`
3. Make changes with tests
4. Submit pull request with description

### Resources

- [Android Accessibility API](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
- [Claude API Documentation](https://docs.anthropic.com)
- [Model Context Protocol Spec](https://modelcontextprotocol.io)

### Testing Checklist

- [ ] Intent parsing works with various command formats
- [ ] Task planning generates correct action sequences
- [ ] Action execution succeeds on target UI elements
- [ ] Verification detects success/failure correctly
- [ ] Replan works when action fails
- [ ] Safety rules block dangerous actions
- [ ] Sensitive actions require confirmation
- [ ] UI recovery works from edge cases
