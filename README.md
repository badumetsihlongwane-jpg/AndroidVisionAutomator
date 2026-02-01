# AndroidVisionAutomator: Quick Start

An autonomous Android agent that transforms voice/text commands into automated UI actions using AI and Accessibility Services (no ADB, no root required).

## 🎯 What It Does

```
You say:        "Send a message to Mom"
                    ↓
Agent thinks:   Intent: send_message, Target: Mom, Message: ""
                    ↓
Agent plans:    open_app → find_chat("Mom") → click → type → send
                    ↓
Agent does:     [Automated UI actions execute on your phone]
                    ↓
Result:         Message sent! ✅
```

## ⚡ Quick Start (5 minutes)

### Prerequisites
- Android 7.0+ (API 24+)
- Python 3.8+
- Anthropic API key ([get one here](https://console.anthropic.com))

### 1. Clone & Setup

```bash
git clone https://github.com/badumetsihlongwane-jpg/AndroidVisionAutomator
cd AndroidVisionAutomator

# Set up API key
export ANTHROPIC_API_KEY=sk-your-key-here

# Install Python dependencies
pip install anthropic
```

### 2. Build Android App

```bash
cd android-app
./gradlew build
./gradlew installDebug  # Installs on connected device/emulator
```

### 3. Enable Accessibility Service

On your Android phone:
1. Settings → Accessibility → Vision
2. Enable "AndroidVisionAutomator"
3. Grant all requested permissions

### 4. Test It Out

Say one of these commands to your phone:

```
"Send a message to Mom saying I'll be late"
"Open YouTube and search for cats"
"Turn on WiFi"
"Find my last screenshot"
"Open WhatsApp and message Dad"
```

## 🏗️ Architecture

**7-Layer System:**

| Layer | Component | Brain |
|-------|-----------|--------|
| 1 | Voice/Text Input | Your voice 🗣️ |
| 2 | Intent Parser | Claude LLM 🧠 |
| 3 | Task Planner | Claude LLM 📋 |
| 4 | Action Executor | Android Accessibility Service 🤖 |
| 5 | Screen Feedback | UI Tree + OCR 📱 |
| 6 | Verification Loop | Claude LLM + Error Recovery 🔄 |
| 7 | Safety Guardian | Whitelist + Permission Checker 🔒 |

[Full architecture docs](docs/ARCHITECTURE.md)

## 📂 Project Structure

```
├── android-app/              # Android app source
│   ├── accessibility/        # Accessibility Service ("hands")
│   ├── models/              # Data structures
│   ├── agent/               # Orchestration logic
│   └── safety/              # Permission & safety checks
│
├── backend/                 # Cloud LLM integration
│   ├── services/
│   │   └── claude_llm_client.py  # Claude API wrapper
│   └── models/
│
├── mcp-server/              # MCP server
│   └── android_vision_mcp.py
│
├── config.json              # Safety policies & settings
├── examples.py              # Usage examples
└── docs/                    # Documentation
```

## 🔐 Safety Features

✅ **App Whitelist** - Only approved apps can be automated

✅ **Sensitive Action Confirmation** - Messages/calls need user approval

✅ **Dangerous Action Blocking** - Can't delete files, install apps, etc.

✅ **Rate Limiting** - Max 50 actions per task, max 3 retries

✅ **Timeout Protection** - Tasks timeout after 5 minutes

✅ **Kill Switch** - Stop any task instantly

## 💡 Example Commands

### Messaging
```
"Send a message to mom saying I'm running late"
"Text Dad that I'll be home at 5"
"WhatsApp the team about the meeting"
```

### Navigation
```
"Open Google Maps and navigate to the nearest coffee shop"
"Search for Italian restaurants nearby"
```

### Media
```
"Play some relaxing music on Spotify"
"Open YouTube and search for funny cat videos"
```

### System
```
"Turn on airplane mode"
"Enable WiFi and connect to my network"
"Show me my notifications"
```

## 🛠️ Development

### File Organization

**Android (Kotlin):**
- [AutomationAccessibilityService.kt](android-app/app/src/main/java/com/autonomousvision/accessibility/AutomationAccessibilityService.kt) - Core UI executor
- [ScreenAnalyzer.kt](android-app/app/src/main/java/com/autonomousvision/accessibility/ScreenAnalyzer.kt) - Screen state capture
- [SafetyManager.kt](android-app/app/src/main/java/com/autonomousvision/safety/SafetyManager.kt) - Permission enforcement
- [AgentExecutorService.kt](android-app/app/src/main/java/com/autonomousvision/agent/AgentExecutorService.kt) - Task orchestration

**Backend (Python):**
- [claude_llm_client.py](backend/services/claude_llm_client.py) - Claude API integration
- [android_vision_mcp.py](mcp-server/src/android_vision_mcp.py) - Main orchestrator
- [examples.py](examples.py) - Usage patterns

### Configuration

Edit [config.json](config.json) to customize:

```json
{
  "safety_policy": {
    "allowed_apps": ["com.whatsapp", "com.google.android.apps.messaging"],
    "max_actions_per_task": 50,
    "max_retry_count": 3
  },
  "llm": {
    "model": "claude-3-5-sonnet-20241022"
  }
}
```

## 🚀 How It Works

### Real Example: "Send message to Mom"

```
1. 🎤 VOICE INPUT
   Your voice → "Send a message to Mom"

2. 🧠 INTENT PARSING (Claude)
   Intent: send_message
   Target: WhatsApp
   Recipient: Mom

3. 📋 TASK PLANNING (Claude)
   Step 1: open_app(com.whatsapp)
   Step 2: find_text("Mom")
   Step 3: click("Mom")
   Step 4: click("message input")
   Step 5: type("I'm running late")
   Step 6: click("send")

4. 🤖 ACTION EXECUTION (Accessibility Service)
   [Each step executes and reports back]

5. ✅ VERIFICATION
   Did "I'm running late" appear in send box?
   YES → Continue
   NO → Ask Claude for alternative path

6. ✅ RESULT
   Message sent! 🎉
```

## 📊 Status

| Component | Status | Notes |
|-----------|--------|-------|
| Intent Parser | ✅ Complete | Using Claude |
| Task Planner | ✅ Complete | LLM-based |
| Action Executor | ✅ Complete | All core actions |
| Verification Loop | ✅ Complete | With replanning |
| Safety Layer | ✅ Complete | Whitelist + policies |
| Voice Input | ⚠️ Partial | Text input working, voice TBD |
| OCR Fallback | ⏳ Planned | For edge cases |
| Multi-task | ⏳ Planned | Queue management |

## ❓ FAQ

**Q: Does this require root access?**
A: No! Uses Accessibility Services only, just like accessibility apps.

**Q: Do I need ADB?**
A: No! Just install the APK normally.

**Q: Can it open any app?**
A: Only apps in the whitelist (for safety). Modify config.json to add more.

**Q: Is my data private?**
A: Command text is sent to Claude for processing. No sensitive data stored locally.

**Q: Can I run multiple tasks at once?**
A: Not yet - currently supports one task at a time.

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md)

## 📞 Support

- 📖 Read the [full architecture docs](docs/ARCHITECTURE.md)
- 🐛 Found a bug? Open an issue
- 💡 Have an idea? Start a discussion

## 📄 License

MIT License - Use freely, modify, distribute.

## 🙏 Acknowledgments

- Built with [Claude 3.5 Sonnet](https://www.anthropic.com)
- Android [Accessibility Services](https://developer.android.com/guide/topics/ui/accessibility/service)
- [Model Context Protocol](https://modelcontextprotocol.io)

---

**Made with ❤️ by the Autonomous Vision team**

👉 **[View Full Documentation](docs/ARCHITECTURE.md)**
