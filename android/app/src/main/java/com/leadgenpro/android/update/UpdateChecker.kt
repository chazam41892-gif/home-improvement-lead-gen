package com.leadgenpro.android.update

import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

data class UpdateInfo(
    val latestVersion: String,
    val versionCode: Int,
    val downloadUrl: String,
    val releaseNotes: String,
    val required: Boolean
)

object UpdateChecker {
    private const val DEFAULT_UPDATE_URL = "https://your-domain.com/updates/android/latest.json"

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()

    fun checkForUpdate(
        currentVersionCode: Int,
        updateUrl: String = DEFAULT_UPDATE_URL,
        callback: (UpdateInfo?) -> Unit
    ) {
        GlobalScope.launch(Dispatchers.IO) {
            try {
                val request = Request.Builder().url(updateUrl).build()
                val response = client.newCall(request).execute()
                if (response.isSuccessful) {
                    val body = response.body?.string()
                    if (body != null) {
                        val updateInfo = gson.fromJson(body, UpdateInfo::class.java)
                        withContext(Dispatchers.Main) {
                            callback(if (updateInfo.versionCode > currentVersionCode) updateInfo else null)
                        }
                    } else {
                        withContext(Dispatchers.Main) { callback(null) }
                    }
                } else {
                    withContext(Dispatchers.Main) { callback(null) }
                }
            } catch (_: Exception) {
                withContext(Dispatchers.Main) { callback(null) }
            }
        }
    }
}
