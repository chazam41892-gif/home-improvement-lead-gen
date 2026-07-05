package com.leadgenpro.android.api

import retrofit2.Response
import retrofit2.http.*

interface ApiService {

    @POST("api/search/natural")
    suspend fun searchLeads(@Body request: SearchRequest): Response<SearchResponse>

    @POST("api/search/multi")
    suspend fun searchMulti(@Body request: MultiSearchRequest): Response<MultiSearchResponse>

    @GET("api/stats")
    suspend fun getStats(): Response<StatsResponse>

    @GET("api/leads")
    suspend fun getLeads(): Response<LeadResponse>

    @GET("api/leads/{id}")
    suspend fun getLead(@Path("id") id: String): Response<Lead>

    @POST("api/landing/generate")
    suspend fun createLandingPage(@Body body: Map<String, String>): Response<LandingPage>

    @GET("api/landing/list")
    suspend fun listLandingPages(): Response<LandingPageListResponse>

    @DELETE("api/landing/{id}")
    suspend fun deleteLandingPage(@Path("id") id: String): Response<OkResponse>

    @POST("api/schedules")
    suspend fun createSchedule(@Body body: Map<String, Any>): Response<Schedule>

    @GET("api/schedules")
    suspend fun listSchedules(): Response<ScheduleResponse>

    @PUT("api/schedules/{id}")
    suspend fun updateSchedule(
        @Path("id") id: String,
        @Body body: Map<String, Any>
    ): Response<Schedule>

    @DELETE("api/schedules/{id}")
    suspend fun deleteSchedule(@Path("id") id: String): Response<OkResponse>

    @POST("api/ads/generate-copy")
    suspend fun generateAdCopy(@Body request: AdCopyRequest): Response<AdCopyResponse>

    @POST("api/ads/generate-keywords")
    suspend fun generateKeywords(@Body body: Map<String, String>): Response<KeywordResponse>

    @POST("api/ads/generate-pixel")
    suspend fun generatePixel(@Body request: PixelRequest): Response<PixelResponse>

    @GET("api/business/config")
    suspend fun getBusinessConfig(): Response<BusinessConfigResponse>

    @PUT("api/business/config")
    suspend fun updateBusinessConfig(@Body config: BusinessConfig): Response<BusinessConfigResponse>

    @GET("api/business/metrics")
    suspend fun getBusinessMetrics(): Response<BusinessConfig>

    @POST("api/nurture/sequence")
    suspend fun createNurtureSequence(@Body body: Map<String, String>): Response<NurtureSequence>

    @GET("api/nurture/sequences")
    suspend fun listNurtureSequences(): Response<List<NurtureSequence>>

    @POST("api/nurture/schedule")
    suspend fun scheduleAppointment(@Body body: Map<String, String>): Response<Appointment>

    @POST("api/capture/lead")
    suspend fun captureLead(@Body body: Map<String, String>): Response<OkResponse>

    @GET("api/trades")
    suspend fun getTrades(): Response<TradeResponse>

    @GET("api/trades/{trade_id}")
    suspend fun getTrade(@Path("trade_id") tradeId: String): Response<TradeConfig>

    @POST("api/trades/discover")
    suspend fun discoverLeads(@Body request: TradeDiscoveryRequest): Response<List<TradeLeadResponse>>

    @POST("api/trades/convert")
    suspend fun convertLead(@Body request: TradeConvertRequest): Response<TradeConvertResponse>

    @GET("api/trades/revenue")
    suspend fun getRevenue(): Response<RevenueResponse>
}
