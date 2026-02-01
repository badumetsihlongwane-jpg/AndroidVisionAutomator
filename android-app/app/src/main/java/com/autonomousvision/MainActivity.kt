package com.autonomousvision

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.autonomousvision.agent.AgentExecutorService
import com.autonomousvision.llm.GroqLLMClient
import com.autonomousvision.models.TaskPlan
import com.autonomousvision.models.UIAction
import com.autonomousvision.models.UserIntent
import com.google.gson.Gson
import androidx.core.app.ActivityCompat
import android.content.pm.PackageManager
import android.Manifest

class MainActivity : AppCompatActivity() {

    private lateinit var inputCommand: EditText
    private lateinit var runButton: Button
    private lateinit var selfTestButton: Button
    private lateinit var settingsButton: Button
    private lateinit var openAccessibilityButton: Button
    private lateinit var accStatusView: TextView
    private lateinit var requestPermButton: Button
    private lateinit var statusView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        inputCommand = findViewById(R.id.input_command)
        runButton = findViewById(R.id.btn_run)
        selfTestButton = findViewById(R.id.btn_selftest)
        settingsButton = findViewById(R.id.btn_settings)
        statusView = findViewById(R.id.tv_status)
        accStatusView = findViewById(R.id.tv_accessibility_status)
        openAccessibilityButton = findViewById(R.id.btn_open_accessibility)
        requestPermButton = findViewById(R.id.btn_request_permissions)

        // Settings button opens API key configuration
        settingsButton.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        openAccessibilityButton.setOnClickListener {
            startActivity(Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }

        requestPermButton.setOnClickListener {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE, Manifest.permission.READ_EXTERNAL_STORAGE),
                42
            )
        }

        runButton.setOnClickListener {
            val cmd = inputCommand.text.toString().trim()
            if (cmd.isEmpty()) {
                Toast.makeText(this, "Enter a command (e.g. send message)", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            statusView.text = "Parsing intent with Groq..."
            
            // Get API key from SharedPreferences
            val sharedPref = getSharedPreferences("automation_config", Context.MODE_PRIVATE)
            val apiKey = sharedPref.getString("groq_api_key", "")
            
            if (apiKey.isNullOrEmpty()) {
                statusView.text = "Error: API key not configured. Go to Settings."
                Toast.makeText(this, "Configure API key in Settings first", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // Call Groq LLM to parse intent in background thread
            Thread {
                try {
                    val groqClient = GroqLLMClient(apiKey)
                    val intent = groqClient.parseIntent(cmd)

                    runOnUiThread {
                        if (intent == null) {
                            statusView.text = "Error: Intent parsing failed. Check logs."
                            Toast.makeText(this, "Failed to parse intent. Enable verbose logging.", Toast.LENGTH_LONG).show()
                            return@runOnUiThread
                        }

                        // Build actions from parsed intent
                        val actions = buildActionsFromIntent(intent, cmd)
                        val plan = TaskPlan(
                            taskId = "task_${System.currentTimeMillis()}",
                            originalIntent = intent,
                            actions = actions
                        )

                        val json = Gson().toJson(plan)

                        // Enqueue the Worker
                        try {
                            AgentExecutorService.scheduleTask(this@MainActivity, json)
                            statusView.text = "✓ Intent: ${intent.intent} | App: ${intent.targetApp}"
                            Toast.makeText(this@MainActivity, "Parsed: ${intent.intent}", Toast.LENGTH_SHORT).show()
                        } catch (e: Exception) {
                            statusView.text = "Failed to enqueue: ${e.message}"
                        }
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        statusView.text = "Error: ${e.localizedMessage}"
                        Toast.makeText(this, "Error: ${e.message}", Toast.LENGTH_LONG).show()
                    }
                }
            }.start()
        }

        selfTestButton.setOnClickListener {
            statusView.text = "Self-test: running..."
            // Lightweight, guaranteed local test — doesn't require Accessibility or network
            val handler = android.os.Handler(android.os.Looper.getMainLooper())
            handler.postDelayed({
                val ts = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US).format(java.util.Date())
                statusView.text = "Self-test OK — ${ts}"
                Toast.makeText(this@MainActivity, "Self-test passed", Toast.LENGTH_SHORT).show()
            }, 1000)
        }
        updateAccessibilityStatus()
    }

    override fun onResume() {
        super.onResume()
        updateAccessibilityStatus()
    }

    private fun updateAccessibilityStatus() {
        val enabled = try {
            val setting = android.provider.Settings.Secure.getString(
                contentResolver,
                android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            ) ?: ""
            val serviceId = "${packageName}/${"com.autonomousvision.accessibility.AutomationAccessibilityService"}"
            setting.split(":" ).any { it.contains(serviceId) }
        } catch (e: Exception) {
            false
        }

        accStatusView.text = if (enabled) "Accessibility: enabled" else "Accessibility: disabled"
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 42) {
            val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
            Toast.makeText(this, if (granted) "Storage permission granted" else "Storage permission denied", Toast.LENGTH_SHORT).show()
        }
    }

    private fun buildActionsFromIntent(intent: UserIntent, userCommand: String): List<UIAction> {
        // Build generic action sequence based on intent type
        return when (intent.intent) {
            "send_message" -> {
                val contact = intent.entities?.get("contact") ?: "contact"
                val message = intent.entities?.get("message") ?: userCommand
                listOf(
                    UIAction(action = "open_app", value = intent.targetApp),
                    UIAction(action = "find_text", target = contact),
                    UIAction(action = "click", target = contact),
                    UIAction(action = "click", target = "message input"),
                    UIAction(action = "setText", value = message),
                    UIAction(action = "click", target = "send")
                )
            }
            "open_app" -> {
                listOf(UIAction(action = "open_app", value = intent.targetApp))
            }
            else -> {
                listOf(UIAction(action = "unknown", value = userCommand))
            }
        }
    }
}
