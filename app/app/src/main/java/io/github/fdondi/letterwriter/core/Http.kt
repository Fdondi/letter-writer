package io.github.fdondi.letterwriter.core

import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.JsonElement
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class HttpStatusException(
    val service: String,
    val status: Int,
    val body: String,
) : IOException("$service HTTP $status: ${body.take(2000)}")

object Http {
    private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

    /** LLM drafts can take minutes; keep the read timeout generous. */
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.MINUTES)
        .writeTimeout(2, TimeUnit.MINUTES)
        .callTimeout(15, TimeUnit.MINUTES)
        .build()

    suspend fun postJson(
        service: String,
        url: String,
        body: JsonElement,
        headers: Map<String, String> = emptyMap(),
    ): JsonElement {
        val request = Request.Builder()
            .url(url)
            .post(Json.codec.encodeToString(JsonElement.serializer(), body).toRequestBody(JSON_MEDIA))
            .apply { headers.forEach { (k, v) -> header(k, v) } }
            .build()
        return Json.parse(execute(service, request))
    }

    suspend fun getJson(service: String, url: String, headers: Map<String, String> = emptyMap()): JsonElement {
        val request = Request.Builder()
            .url(url)
            .get()
            .apply { headers.forEach { (k, v) -> header(k, v) } }
            .build()
        return Json.parse(execute(service, request))
    }

    suspend fun getText(service: String, url: String, headers: Map<String, String> = emptyMap()): String {
        val request = Request.Builder()
            .url(url)
            .get()
            .apply { headers.forEach { (k, v) -> header(k, v) } }
            .build()
        return execute(service, request)
    }

    suspend fun execute(service: String, request: Request): String =
        suspendCancellableCoroutine { cont ->
            val call = client.newCall(request)
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(
                object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        cont.resumeWithException(IOException("$service request failed: ${e.message}", e))
                    }

                    override fun onResponse(call: Call, response: Response) {
                        response.use {
                            val text = it.body.string()
                            if (it.isSuccessful) {
                                cont.resume(text)
                            } else {
                                cont.resumeWithException(HttpStatusException(service, it.code, text))
                            }
                        }
                    }
                },
            )
        }
}
