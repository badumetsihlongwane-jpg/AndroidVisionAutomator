package com.autonomousvision.llm

import com.autonomousvision.models.UserIntent
import com.google.gson.Gson
import com.google.gson.JsonParser
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import timber.log.Timber

/**
 * Groq LLM client for intent parsing using the Groq API.
 * Free tier available at https://console.groq.com/
 */
class GroqLLMClient(private val apiKey: String) {

    private val httpClient = OkHttpClient()
    private val gson = Gson()

    /**
     * Parse user command into structured intent using Groq LLM.
     */
    fun parseIntent(userCommand: String): UserIntent? {
        return try {
            val prompt = """
                You are a task parser. Parse this user command and respond with ONLY a JSON object (no markdown, no code blocks).
                
                User command: "$userCommand"
                
                Respond with exactly this format:
                {"intent":"send_message","targetApp":"com.whatsapp","entities":{"contact":"Mom","message":"text"}}
                
                intent can be: send_message, open_app, call, search, or other
                targetApp: the Android package name (e.g., com.whatsapp, com.google.android.apps.messaging)
                entities: object with any relevant data
                
                RESPOND ONLY WITH JSON, NO MARKDOWN OR EXTRA TEXT.
            """.trimIndent()

            val requestBody = gson.toJson(mapOf(
                "model" to "llama-3.1-8b-instant",
                "messages" to listOf(
                    mapOf("role" to "user", "content" to prompt)
                ),
                "max_tokens" to 200,
                "temperature" to 0.3
            )).toRequestBody("application/json".toMediaType())

            val request = Request.Builder()
                .url("https://api.groq.com/openai/v1/chat/completions")
                .addHeader("Authorization", "Bearer $apiKey")
                .addHeader("Content-Type", "application/json")
                .post(requestBody)
                .build()

            val response = httpClient.newCall(request).execute()
            if (!response.isSuccessful) {
                val errorBody = response.body?.string() ?: "No error body"
                Timber.e("Groq API error: ${response.code} - $errorBody")
                return null
            }

            val responseBody = response.body?.string() ?: return null
            Timber.d("Groq response: $responseBody")

            val responseJson = gson.fromJson(responseBody, Map::class.java)

            @Suppress("UNCHECKED_CAST")
            val choices = responseJson["choices"] as? List<Map<String, Any>> ?: run {
                Timber.e("No choices in response: $responseJson")
                return null
            }
            
            val message = (choices.firstOrNull()?.get("message") as? Map<String, String>)?.get("content") ?: run {
                Timber.e("No message content in choices")
                return null
            }

            Timber.d("LLM message content: $message")

            // Parse the JSON response from LLM, handling markdown wrapping
            val cleanedMessage = message
                .replace("```json", "")
                .replace("```", "")
                .trim()

            val intentJson = try {
                JsonParser.parseString(cleanedMessage).asJsonObject
            } catch (e: Exception) {
                Timber.e("Failed to parse JSON: $cleanedMessage, error: ${e.message}")
                return null
            }

            @Suppress("UNCHECKED_CAST")
            val entities = (intentJson.getAsJsonObject("entities")?.asMap() as? Map<String, String>)?.toMutableMap() ?: mutableMapOf()

            val parsedIntent = UserIntent(
                intent = intentJson.get("intent")?.asString ?: "unknown",
                targetApp = intentJson.get("targetApp")?.asString ?: "unknown",
                entities = entities
            )

            Timber.d("Parsed intent: $parsedIntent")
            parsedIntent
        } catch (e: Exception) {
            Timber.e(e, "Error parsing intent with Groq: ${e.message}")
            null
        }
    }
}
