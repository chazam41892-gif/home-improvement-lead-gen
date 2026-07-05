package com.leadgenpro.android.api

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object ApiClient {

    private const val PREF_NAME = "leadgen_prefs"
    private const val KEY_SERVER_URL = "server_url"
    private const val DEFAULT_URL = "http://10.0.2.2:8080"

    private var retrofit: Retrofit? = null
    private var currentBaseUrl: String = DEFAULT_URL

    private val okHttpClient: OkHttpClient by lazy {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BODY
        }
        OkHttpClient.Builder()
            .addInterceptor(logging)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    fun getApiService(context: Context): ApiService {
        val baseUrl = getBaseUrl(context)
        if (retrofit == null || baseUrl != currentBaseUrl) {
            currentBaseUrl = baseUrl
            retrofit = Retrofit.Builder()
                .baseUrl(baseUrl)
                .client(okHttpClient)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
        }
        return retrofit!!.create(ApiService::class.java)
    }

    fun getBaseUrl(context: Context): String {
        val prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        var url = prefs.getString(KEY_SERVER_URL, DEFAULT_URL) ?: DEFAULT_URL
        if (!url.endsWith("/")) {
            url = "$url/"
        }
        return url
    }

    fun updateBaseUrl(context: Context, url: String) {
        val cleanUrl = if (!url.endsWith("/")) "$url/" else url
        val prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_SERVER_URL, cleanUrl).apply()
        currentBaseUrl = cleanUrl
        retrofit = null
    }

    fun resetBaseUrl(context: Context) {
        val prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        prefs.edit().remove(KEY_SERVER_URL).apply()
        currentBaseUrl = DEFAULT_URL
        retrofit = null
    }
}
