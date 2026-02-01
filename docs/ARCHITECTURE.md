# AndroidVisionAutomator: Autonomous Android MCP

**Goal (one sentence):** Build an AI-driven Android agent that converts voice/text → intent → UI actions, using Accessibility Services as hands and Claude LLM as the brain.

---

## 🧱 System Architecture

```
User (Voice/Text)
      ↓
[1] Input Layer (SpeechRecognizer / Text Input)
      ↓
[2] Intent Parser (Claude LLM)
      ↓
[3] Task Planner (Claude LLM) 
      ↓
[4] Action Executor (Accessibility Service)
      ↓
[5] Screen Feedback (UI Tree / OCR)
      ↓
[6] Verification & Replanning Loop
      ↓
[7] Safety & Permissions Layer
```

---

## 📁 Project Structure

```
AndroidVisionAutomator/
├── android-app/                          # Android application
│   ├── build.gradle.kts                  # Gradle build config
│   ├── app/src/main/
│   │   ├── AndroidManifest.xml           # Permissions & services
│   │   └── java/com/autonomousvision/
│   │       ├── models/
│   │       │   ├── Intent.kt             # Data models
│   │       │   └── SafetyPolicy.kt       # Safety rules
│   │       ├── accessibility/
│   │       │   ├── AutomationAccessibilityService.kt  # Core "muscles"
│   │       │   └── ScreenAnalyzer.kt     # Screen capture & parsing
│   │       ├── agent/
│   │       │   └── AgentExecutorService.kt  # Orchestrator
│   │       └── safety/
│   │           └── SafetyManager.kt      # Permission checker
│   │
├── backend/                              # Python backend (cloud)
│   ├── services/
│   │   └── claude_llm_client.py          # Claude API integration
│   ├── controllers/
│   ├── models/
│   └── utils/
│
├── mcp-server/                           # MCP server components
│   └── src/
│       └── android_vision_mcp.py         # Main orchestrator
│
├── config.json                           # Global configuration
├── examples.py                           # Usage examples
├── docs/
│   └── ARCHITECTURE.md                   # This file
└── README.md                             # Quick start guide
```

---

## 🔄 The 7 Layers Explained

### 1️⃣ Input Layer (Human → Text)

**Files:** `AutomationAccessibilityService.kt`

Converts human voice or text to a command string.

```kotlin
// Voice input
val recognizer = SpeechRecognizer.createSpeechRecognizer(context)
recognizer.startListening(intent)

// Text input
val userCommand = "Send a message to Mom"
```

**Output:** Normalized command string → Layer 2

---

### 2️⃣ Intent Understanding (LLM)

**Files:** `claude_llm_client.py`, `IntentParser`

Parses natural language into structured intent using Claude.

```python
# Input: "Send a message to Mom saying I'll be late"
# Output: 
{
  "intent": "send_message",
  "target_app": "WhatsApp",
  "entities": {
    "contact": "Mom",
    "message": "I'll be late"
  }
}
```

**Responsibilities:**
- Understand what user wants
- Extract intent type
- Identify target app
- Extract entities (names, numbers, text)
- App-agnostic (not tied to specific UI)

---

### 3️⃣ Task Planner (LLM)

**Files:** `TaskPlanner`, `claude_llm_client.py`

Converts intent + current screen state → sequence of concrete UI actions.

```python
# Input:
{
  "intent": "send_message",
  "target_app": "WhatsApp",
  "entities": {"contact": "Mom", "message": "I'll be late"},
  "current_screen": {
    "app": "com.android.launcher",
    "visible_texts": ["WhatsApp", "Messages", "Settings"]
  }
}

# Output:
[
  {"action": "open_app", "value": "com.whatsapp"},
  {"action": "find_text", "target": "Mom"},
  {"action": "click", "target": "Mom"},
  {"action": "setText", "value": "I'll be late"},
  {"action": "click", "target": "send"}
]
```

**Key Principle:** Planner does NOT click directly — it issues abstract commands. Execution layer finds specific UI elements.

---

### 4️⃣ Action Executor (Accessibility Service)

**Files:** `AutomationAccessibilityService.kt`

The "hands" — executes abstract actions on real Android UI.

```kotlin
// Supported actions:
- click(target: String)           // Find & click
- setText(value: String)          // Type text
- scroll(direction: String)       // up/down
- open_app(package: String)       // Launch app
- find_text(target: String)       // Verify exists
- back()                          // Android back
- home()                          // Home screen
- wait(duration: Long)            // Pause

// Each action reports back:
ActionResult {
  status: "SUCCESS" | "FAILED" | "ELEMENT_NOT_FOUND",
  errorMessage: "...",
  screenStateAfter: ScreenState
}
```

**Element Matching Strategy:**
1. Find node by text (case-insensitive)
2. Find by contentDescription
3. Find by className
4. If multiple matches, use index

---

### 5️⃣ Screen Understanding (Feedback Loop)

**Files:** `ScreenAnalyzer.kt`

Captures current UI state and converts to LLM-friendly format.

```kotlin
ScreenState {
  currentApp: "com.whatsapp",
  visibleTexts: ["Mom", "Type a message", "Send"],
  focusedElement: "message_input",
  uiTree: "XML tree of accessibility nodes",
  screenshotBase64: "optional for OCR"
}
```

**Used for:**
- Verifying action success
- Replanning when element not found
- Context for next action decision

---

### 6️⃣ Verification & Replanning

**Files:** `VerificationLoop`, `AgentExecutorService.kt`

The autonomy layer — detects failures and adapts.

```
For each action:
  1. Execute action
  2. Wait for screen update
  3. Verify expected state appeared
  
  If verification fails:
    - Extract why it failed
    - Send replan request to LLM
    - Get alternative action sequence
    - Resume from point of failure
    
  If after 3 retries still fails:
    - Mark task as failed
    - Report to user
```

**Example Failure Scenario:**
```
Original action: click("Mom")
Expected: Mom's chat opens
Actual: Chat list shown (Mom not visible)

Replan: scroll_down → find_text("Mom") → click("Mom")
```

---

### 7️⃣ Safety & Permissions Layer

**Files:** `SafetyManager.kt`, `SafetyPolicy.kt`

Prevents harm, maintains Play Store compliance.

```kotlin
Safety Rules:
├── Allowed Apps (whitelist)
│   ├── WhatsApp
│   ├── Google Maps
│   ├── YouTube
│   └── [configurable]
│
├── Dangerous Actions (blocked)
│   ├── delete_file
│   ├── uninstall_app
│   ├── change_settings
│   └── send_payment
│
├── Sensitive Actions (require confirmation)
│   ├── send_message
│   ├── make_call
│   └── send_email
│
└── Limits
    ├── max_actions_per_task: 50
    ├── max_retry_count: 3
    └── task_timeout: 5 minutes
```

**Permission Check:**
```kotlin
enum ActionPermissionLevel {
  ALLOWED,                    // Execute immediately
  REQUIRES_CONFIRMATION,      // Ask user first
  DANGEROUS,                  // Explicit user approval
  BLOCKED                     // Never execute
}
```

---

## 🚀 Execution Flow Example

**User says:** "Send a message to Mom saying I'll be late"

```
[1] INPUT LAYER
    Voice → "Send a message to Mom saying I'll be late"

[2] INTENT PARSER
    LLM extracts:
    {
      "intent": "send_message",
      "target_app": "WhatsApp",
      "entities": {"contact": "Mom", "message": "I'll be late"}
    }

[3] TASK PLANNER
    Current screen: Home screen with WhatsApp icon visible
    LLM creates plan:
    [
      {"action": "open_app", "value": "com.whatsapp"},
      {"action": "find_text", "target": "Mom"},
      {"action": "click", "target": "Mom"},
      {"action": "click", "target": "message input"},
      {"action": "setText", "value": "I'll be late"},
      {"action": "click", "target": "send"}
    ]

[4] ACTION EXECUTOR - Action 1
    execute: open_app(com.whatsapp)
    → WhatsApp opens
    ✅ SUCCESS

[5] SCREEN FEEDBACK
    Current app: com.whatsapp
    Visible: ["Chats", "My Status", "Calls", "Settings"]
    → No "Mom" visible

[6] VERIFICATION FAILS
    Expected: See "Mom" in chat list
    Actual: Mom not visible (probably need to scroll)
    
    Trigger replan:
    New plan: scroll_down → find "Mom" → click

[7] SAFETY CHECK
    All actions whitelisted?
    ✅ Yes (WhatsApp is allowed, send_message requires confirmation)
    User confirms via notification.

[4] ACTION EXECUTOR - Retry with new plan
    Continued execution with replanned actions...
    
[✅] TASK COMPLETE
    Message sent to Mom
```

---

## 🔐 Safety Guarantees

1. **Whitelist Only:** Only configured apps can be automated
2. **Dangerous Action Blocking:** Payment, deletion, uninstall blocked
3. **Sensitive Action Confirmation:** Messages, calls require user approval
4. **Rate Limiting:** Max actions/task and max retries prevent loops
5. **Timeout Protection:** Tasks killed after 5 minutes
6. **Kill Switch:** User can stop any task instantly
7. **Audit Logging:** All actions logged for review

---

## 📋 Configuration

See `config.json` for:
- Allowed apps whitelist
- Blocked/sensitive actions
- Max retries and timeouts
- Logging level
- LLM model and API settings

---

## 🛠️ Development

### Android Setup
```bash
cd android-app
./gradlew build
./gradlew installDebug
```

### Backend Setup
```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
python examples.py
```

### Testing
```bash
# Unit tests
./gradlew test

# Integration tests
python -m pytest backend/tests/
```

---

## ⚠️ Limitations & Future Work

**Current Limitations:**
- Single task at a time (no parallelization)
- Screen understanding relies on text (no image ML)
- No persistent learning (doesn't improve over time)
- Limited to UI automation (no system commands)

**Future Enhancements:**
- Vision model integration (Claude Vision)
- Multi-task execution
- Gesture recognition (long press, swipe)
- Custom action plugins
- Performance analytics
- Speech synthesis for feedback

---

## 📚 References

- [Android Accessibility Service API](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService)
- [Claude API Docs](https://docs.anthropic.com)
- [Model Context Protocol](https://modelcontextprotocol.io)

---

## 📄 License

MIT License - See LICENSE file

---

**Built with ❤️ using Claude 3.5 Sonnet**
