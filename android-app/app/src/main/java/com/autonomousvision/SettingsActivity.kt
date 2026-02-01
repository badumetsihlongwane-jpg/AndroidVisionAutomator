package com.autonomousvision

import android.content.Context
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class SettingsActivity : AppCompatActivity() {

    private lateinit var apiKeyInput: EditText
    private lateinit var saveButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        apiKeyInput = findViewById(R.id.input_api_key)
        saveButton = findViewById(R.id.btn_save_api_key)

        // Load existing API key (if any)
        val sharedPref = getSharedPreferences("automation_config", Context.MODE_PRIVATE)
        val existingKey = sharedPref.getString("groq_api_key", "")
        if (!existingKey.isNullOrEmpty()) {
            apiKeyInput.setText(existingKey.take(10) + "***")  // Show masked
        }

        saveButton.setOnClickListener {
            val apiKey = apiKeyInput.text.toString().trim()
            if (apiKey.isEmpty() || apiKey.endsWith("***")) {
                Toast.makeText(this, "Enter a valid API key", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // Save API key to SharedPreferences
            sharedPref.edit().apply {
                putString("groq_api_key", apiKey)
                putLong("api_key_saved_time", System.currentTimeMillis())
                apply()
            }

            Toast.makeText(this, "API key saved", Toast.LENGTH_SHORT).show()
            finish()
        }
    }
}
