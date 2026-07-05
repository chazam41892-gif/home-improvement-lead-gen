package com.leadgenpro.android.api

import com.google.gson.annotations.SerializedName

data class LeadResponse(
    val leads: List<Lead> = emptyList(),
    val total: Int = 0
)

data class Lead(
    val id: String = "",
    val title: String = "",
    val url: String = "",
    val industry: String = "",
    val location: String = "",
    val source: String = "",
    val snippet: String = "",
    val score: Double = 0.0,
    val score_breakdown: ScoreBreakdown? = null,
    val email: String? = null,
    val phone: String? = null,
    val notes: String? = null,
    val created_at: String? = null
)

data class ScoreBreakdown(
    val relevance: Double = 0.0,
    val intent: Double = 0.0,
    val fit: Double = 0.0,
    val urgency: Double = 0.0,
    val budget: Double = 0.0
)

data class SearchRequest(
    val query: String,
    val result_count: Int = 25,
    val min_score: Double = 0.0,
    val provider: String = "exa"
)

data class SearchResponse(
    val results: List<Lead> = emptyList(),
    val query: String = "",
    val total_found: Int = 0
)

data class MultiSearchRequest(
    val queries: List<String>,
    val result_count: Int = 25,
    val min_score: Double = 0.0
)

data class MultiSearchResponse(
    val results: List<Lead> = emptyList(),
    val merge_stats: MergeStats? = null,
    val total_found: Int = 0
)

data class MergeStats(
    @SerializedName("from_exa") val fromExa: Int = 0,
    @SerializedName("from_perplexity") val fromPerplexity: Int = 0,
    @SerializedName("merged_deduplicated") val mergedDeduplicated: Int = 0
)

data class StatsResponse(
    val scheduler: SchedulerStats? = null,
    val capture: CaptureStats? = null,
    val nurture: NurtureStats? = null,
    val crm: CrmStats? = null,
    val business_config: BusinessConfig? = null,
    val total_leads: Int = 0,
    val avg_score: Double = 0.0,
    val searches_run: Int = 0
)

data class SchedulerStats(
    val total_schedules: Int = 0,
    val enabled: Int = 0,
    val total_runs: Int = 0,
    val leads_found: Int = 0
)

data class CaptureStats(
    val total_submissions: Int = 0,
    val today: Int = 0,
    val converted: Int = 0
)

data class NurtureStats(
    val total_sequences: Int = 0,
    val active: Int = 0,
    val completed: Int = 0,
    val upcoming_appointments: Int = 0
)

data class CrmStats(
    val total_contacts: Int = 0,
    val active_deals: Int = 0,
    val won: Int = 0,
    val lost: Int = 0,
    val total_value: Double = 0.0
)

data class BusinessConfig(
    val avg_job_size: Double = 0.0,
    val gross_margin: Double = 0.0,
    val lead_cost_ceiling: Double = 0.0,
    val monthly_ad_budget: Double = 0.0,
    val target_roas: Double = 0.0,
    val business_name: String = "",
    val business_phone: String = "",
    val business_email: String = "",
    val profit_per_job: Double = 0.0,
    val cac: Double = 0.0,
    val max_cpc: Double = 0.0,
    val break_even_leads: Int = 0
)

data class LandingPage(
    val id: String = "",
    val url: String = "",
    val business_name: String = "",
    val headline: String = "",
    val cta: String = "",
    val page_size: String = "",
    val page_id: String = "",
    val created_at: String = ""
)

data class LandingPageListResponse(
    val pages: List<LandingPage> = emptyList(),
    val total: Int = 0
)

data class ScheduleResponse(
    val schedules: List<Schedule> = emptyList()
)

data class Schedule(
    val id: String = "",
    val name: String = "",
    val query: String = "",
    val provider: String = "",
    val interval: String = "",
    val result_count: Int = 25,
    val enabled: Boolean = false,
    val runs: Int = 0,
    val last_run: String? = null,
    val results_count: Int = 0,
    val results: List<Lead>? = null,
    val created_at: String? = null
)

data class AdCopyRequest(
    val industry: String,
    val location: String,
    val platform: String = "Google",
    val usp: String = "",
    val count: Int = 3
)

data class AdCopyResponse(
    val copies: List<AdCopy> = emptyList()
)

data class AdCopy(
    val headline: String = "",
    val description: String = "",
    val cta: String = ""
)

data class KeywordResponse(
    val keywords: Keywords? = null
)

data class Keywords(
    val broad: List<String> = emptyList(),
    val phrase: List<String> = emptyList(),
    @SerializedName("exact") val exactMatch: List<String> = emptyList(),
    val negative: List<String> = emptyList()
)

data class PixelRequest(
    val type: String = "Google Ads",
    @SerializedName("tracking_id") val trackingId: String = ""
)

data class PixelResponse(
    val html: String = "",
    val type: String = "",
    @SerializedName("tracking_id") val trackingId: String = ""
)

data class BusinessConfigResponse(
    val config: BusinessConfig? = null
)

data class NurtureSequence(
    val id: String = "",
    val lead_name: String = "",
    val lead_industry: String = "",
    val steps: List<NurtureStep> = emptyList(),
    val current_step: Int = 0,
    val completed: Boolean = false,
    val created_at: String = ""
)

data class NurtureStep(
    val type: String = "",
    val content: String = "",
    val sent: Boolean = false,
    val scheduled_at: String? = null
)

data class Appointment(
    val id: String = "",
    val lead_name: String = "",
    val date: String = "",
    val time: String = "",
    val notes: String = ""
)

data class OkResponse(
    val ok: Boolean = false
)

data class TradeResponse(
    val trades: List<TradeConfig> = emptyList()
)

data class TradeConfig(
    val name: String = "",
    val best_platform: String = "",
    val avg_job_value: Double = 0.0,
    val conversion_rate: Double = 0.0,
    val platforms: List<String> = emptyList(),
    val description: String = "",
    val icon: String = "",
    val id: String = ""
)

data class TradeDiscoveryRequest(
    val trade: String,
    val location: String,
    val platforms: List<String>? = null,
    @SerializedName("max_results") val maxResults: Int = 10
)

data class TradeLeadResponse(
    @SerializedName("business_name") val businessName: String = "",
    val phone: String = "",
    val email: String = "",
    val website: String = "",
    val source: String = "",
    val score: Double = 0.0,
    val status: String = ""
)

data class TradeConvertRequest(
    val trade: String,
    @SerializedName("business_name") val businessName: String,
    val phone: String = "",
    val email: String = "",
    val plan: String = "starter"
)

data class TradeConvertResponse(
    val ok: Boolean = false,
    val lead: TradeLeadResponse? = null,
    val account: TradeAccount? = null,
    val payment: TradePayment? = null,
    val subscription: TradeSubscription? = null
)

data class TradeAccount(
    @SerializedName("account_id") val accountId: String = "",
    @SerializedName("business_name") val businessName: String = "",
    val status: String = ""
)

data class TradePayment(
    val amount: Double = 0.0,
    val currency: String = "USD",
    val status: String = ""
)

data class TradeSubscription(
    @SerializedName("subscription_id") val subscriptionId: String = "",
    val plan: String = "",
    val status: String = "",
    @SerializedName("renews_at") val renewsAt: String = ""
)

data class RevenueResponse(
    val stats: RevenueStats = RevenueStats()
)

data class RevenueStats(
    @SerializedName("total_accounts") val totalAccounts: Int = 0,
    @SerializedName("active_accounts") val activeAccounts: Int = 0,
    @SerializedName("total_revenue") val totalRevenue: Double = 0.0,
    @SerializedName("monthly_recurring_revenue") val monthlyRecurringRevenue: Double = 0.0,
    @SerializedName("average_revenue_per_account") val averageRevenuePerAccount: Double = 0.0
)

// ─── Key Vault Models ───
data class VaultResponse(
    val services: Map<String, VaultService> = emptyMap()
)

data class VaultService(
    val doc: String = "",
    val url: String = "",
    @SerializedName("env_var") val envVar: String = "",
    val configured: Boolean = false,
    val keys: List<VaultKey> = emptyList()
)

data class VaultKey(
    val label: String = "",
    val source: String = "",
    val masked: String = ""
)

data class VaultSetResponse(
    val ok: Boolean = false,
    val service: String = "",
    val label: String = ""
)

// ─── Enrichment Models ───
data class EnrichProvidersResponse(
    val providers: List<EnrichProvider> = emptyList(),
    val available: Boolean = false
)

data class EnrichProvider(
    val name: String = "",
    val available: Boolean = false
)

data class EnrichRequest(
    @SerializedName("business_name") val businessName: String,
    val trade: String,
    val location: String = "",
    val website: String? = null,
    val phone: String? = null
)

data class EnrichResponse(
    @SerializedName("business_name") val businessName: String = "",
    val trade: String = "",
    @SerializedName("contact_name") val contactName: String? = null,
    val title: String? = null,
    val phone: String? = null,
    val email: String? = null,
    val address: String? = null,
    val city: String? = null,
    val state: String? = null,
    val zip: String? = null,
    val website: String? = null,
    @SerializedName("employee_count") val employeeCount: Int? = null,
    val revenue: String? = null,
    @SerializedName("year_founded") val yearFounded: Int? = null,
    val sources: List<String> = emptyList(),
    val confidence: Double = 0.0,
    val error: String? = null
)

data class BatchEnrichRequest(
    val leads: List<EnrichRequest> = emptyList()
)

data class BatchEnrichResponse(
    val total: Int = 0,
    val results: List<EnrichResponse> = emptyList()
)

data class EnrichFromLeadResponse(
    @SerializedName("lead_id") val leadId: String = "",
    @SerializedName("business_name") val businessName: String = "",
    val trade: String = "",
    @SerializedName("contact_name") val contactName: String? = null,
    val title: String? = null,
    val phone: String? = null,
    val email: String? = null,
    val address: String? = null,
    val city: String? = null,
    val state: String? = null,
    val zip: String? = null,
    val website: String? = null,
    @SerializedName("employee_count") val employeeCount: Int? = null,
    val revenue: String? = null,
    @SerializedName("year_founded") val yearFounded: Int? = null,
    val sources: List<String> = emptyList(),
    val confidence: Double = 0.0,
    val error: String? = null
)
