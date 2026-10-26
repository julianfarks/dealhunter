package com.dealhunter.ai.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

val AppJson = Json {
    ignoreUnknownKeys = true
    coerceInputValues = true
    explicitNulls = false
    encodeDefaults = false
}

@Serializable
data class UserDto(val id: Long = 0, val email: String = "", val tier: String = "free")

@Serializable
data class AuthResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String,
    val user: UserDto = UserDto(),
)

@Serializable
data class AlertDto(
    val id: Long,
    val kind: String,
    val threshold: String? = null,
    @SerialName("threshold_currency") val thresholdCurrency: String? = null,
    val active: Boolean = true,
    @SerialName("last_triggered_at") val lastTriggeredAt: String? = null,
)

@Serializable
data class ConvertedDto(
    val currency: String = "",
    val current: String? = null,
    val initial: String? = null,
    val target: String? = null,
    val rate: String? = null,
    @SerialName("as_of") val asOf: String? = null,
    val source: String? = null,
)

@Serializable
data class TrackedDto(
    val id: Long,
    val title: String = "Producto sin nombre",
    @SerialName("title_is_guess") val titleIsGuess: Boolean = false,
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("store_key") val storeKey: String = "",
    @SerialName("store_name") val storeName: String = "",
    val url: String = "",
    val state: String = "waiting_first_check",
    @SerialName("state_label") val stateLabel: String = "",
    @SerialName("state_detail") val stateDetail: String? = null,
    @SerialName("price_current") val priceCurrent: String? = null,
    @SerialName("price_initial") val priceInitial: String? = null,
    val currency: String? = null,
    @SerialName("target_price") val targetPrice: String? = null,
    @SerialName("target_currency") val targetCurrency: String? = null,
    @SerialName("change_from_initial_pct") val changeFromInitialPct: String? = null,
    @SerialName("verified_discount_pct") val verifiedDiscountPct: String? = null,
    @SerialName("has_promotion") val hasPromotion: Boolean = false,
    val available: Boolean? = null,
    @SerialName("last_checked_at") val lastCheckedAt: String? = null,
    val priority: Int = 0,
    val notes: String? = null,
    @SerialName("list_name") val listName: String? = null,
    val archived: Boolean = false,
    val purchased: Boolean = false,
    @SerialName("purchased_price") val purchasedPrice: String? = null,
    val paused: Boolean = false,
    val deleted: Boolean = false,
    val alerts: List<AlertDto> = emptyList(),
    val converted: ConvertedDto? = null,
    @SerialName("fx_error") val fxError: String? = null,
)

@Serializable
data class AddResponse(val item: TrackedDto, val duplicate: Boolean = false, val message: String = "")

@Serializable
data class ChangesResponse(val items: List<TrackedDto> = emptyList(), @SerialName("server_time") val serverTime: String? = null)

@Serializable
data class HistoryPoint(val at: String, val price: String, val currency: String? = null, val available: Boolean? = null)

@Serializable
data class HistoryStats(
    val current: String? = null,
    val min: String? = null,
    val max: String? = null,
    val average: String? = null,
    @SerialName("first_observed") val firstObserved: String? = null,
    @SerialName("first_observed_at") val firstObservedAt: String? = null,
    @SerialName("change_from_first_pct") val changeFromFirstPct: String? = null,
    @SerialName("observations_total") val observationsTotal: Int = 0,
)

@Serializable
data class PromoDto(
    val id: Long = 0,
    val kind: String = "",
    val origin: String = "",
    val description: String? = null,
    @SerialName("previous_price") val previousPrice: String? = null,
    @SerialName("current_price") val currentPrice: String? = null,
    @SerialName("discount_pct") val discountPct: String? = null,
    @SerialName("detected_at") val detectedAt: String? = null,
)

@Serializable
data class HistoryResponse(
    val range: String = "30d",
    @SerialName("available_ranges") val availableRanges: List<String> = emptyList(),
    val currency: String? = null,
    val points: List<HistoryPoint> = emptyList(),
    val stats: HistoryStats = HistoryStats(),
    val warnings: List<String> = emptyList(),
    val promotions: List<PromoDto> = emptyList(),
)

@Serializable
data class CompareBase(val store: String = "", val title: String? = null, val url: String = "", val price: String? = null, val currency: String? = null)

@Serializable
data class CompareOffer(
    @SerialName("store_name") val storeName: String = "",
    val title: String? = null,
    val url: String = "",
    val price: String? = null,
    val currency: String? = null,
    val shipping: String? = null,
    @SerialName("total_estimated") val totalEstimated: String? = null,
    val available: Boolean? = null,
    val match: String = "",
    val notes: String? = null,
    @SerialName("checked_at") val checkedAt: String? = null,
)

@Serializable
data class CompareResponse(
    val base: CompareBase = CompareBase(),
    val offers: List<CompareOffer> = emptyList(),
    val note: String? = null,
    val disclaimer: String = "",
)

@Serializable
data class NotificationDto(
    val id: Long,
    @SerialName("tracked_id") val trackedId: Long? = null,
    val kind: String = "",
    val title: String = "",
    val body: String = "",
    @SerialName("delivery_status") val deliveryStatus: String = "",
    @SerialName("created_at") val createdAt: String = "",
    val read: Boolean = false,
)

@Serializable
data class NotificationsResponse(val notifications: List<NotificationDto> = emptyList())

@Serializable
data class OfferDto(
    @SerialName("tracked_id") val trackedId: Long = 0,
    val title: String = "",
    @SerialName("store_name") val storeName: String = "",
    val type: String = "promotion",
    val kind: String = "",
    val origin: String = "",
    @SerialName("origin_label") val originLabel: String = "",
    val description: String? = null,
    @SerialName("previous_price") val previousPrice: String? = null,
    @SerialName("current_price") val currentPrice: String? = null,
    @SerialName("discount_pct") val discountPct: String? = null,
    val currency: String? = null,
    val code: String? = null,
    val verified: Boolean = false,
    @SerialName("verification_note") val verificationNote: String? = null,
    @SerialName("reference_note") val referenceNote: String? = null,
    val conditions: String? = null,
    @SerialName("expires_at") val expiresAt: String? = null,
    val url: String? = null,
)

@Serializable
data class OffersResponse(val offers: List<OfferDto> = emptyList())

@Serializable
data class PrefsDto(
    val currency: String = "COP",
    val theme: String = "dark",
    @SerialName("quiet_start") val quietStart: String? = null,
    @SerialName("quiet_end") val quietEnd: String? = null,
    @SerialName("max_notifications_per_day") val maxPerDay: Int = 20,
    @SerialName("daily_digest") val dailyDigest: Boolean = false,
    @SerialName("weekly_digest") val weeklyDigest: Boolean = false,
)

@Serializable
data class AiResult(
    val message: String = "",
    @SerialName("interpreted_as") val interpretedAs: kotlinx.serialization.json.JsonObject? = null,
)

@Serializable
data class ErrorDetail(val message: String = "", val retryable: Boolean = false)
