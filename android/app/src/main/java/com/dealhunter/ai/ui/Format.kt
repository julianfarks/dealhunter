package com.dealhunter.ai.ui

import java.math.BigDecimal
import java.text.NumberFormat
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

fun dec(s: String?): BigDecimal? = s?.toBigDecimalOrNull()

/** "$229.900 COP": sin decimales cuando el importe es entero. Nunca inventa valores: null -> "—". */
fun money(amount: String?, currency: String?): String {
    val d = dec(amount) ?: return "—"
    val nf = NumberFormat.getNumberInstance(Locale("es", "CO"))
    val whole = d.stripTrailingZeros().scale() <= 0
    nf.maximumFractionDigits = if (whole) 0 else 2
    nf.minimumFractionDigits = if (whole) 0 else 2
    return "$" + nf.format(d) + (currency?.let { " $it" } ?: "")
}

fun pct(s: String?): String? {
    val d = dec(s) ?: return null
    val sign = if (d.signum() > 0) "+" else ""
    return sign + d.setScale(1, java.math.RoundingMode.HALF_UP).toPlainString() + "%"
}

private val dateFmt = DateTimeFormatter.ofPattern("d MMM yyyy, HH:mm", Locale("es", "CO"))
private val dayFmt = DateTimeFormatter.ofPattern("d MMM", Locale("es", "CO"))

fun parseInstant(iso: String?): Instant? = try {
    if (iso == null) null else Instant.parse(if (iso.endsWith("Z") || iso.contains("+")) iso else iso + "Z")
} catch (_: Exception) {
    null
}

fun dateTime(iso: String?): String =
    parseInstant(iso)?.atZone(ZoneId.systemDefault())?.format(dateFmt) ?: "—"

fun day(iso: String?): String =
    parseInstant(iso)?.atZone(ZoneId.systemDefault())?.format(dayFmt) ?: ""

val ALERT_LABELS = mapOf(
    "any_drop" to "Cualquier bajada de precio",
    "pct_drop" to "Bajada de un porcentaje",
    "target_price" to "Precio objetivo",
    "historic_low" to "Mínimo histórico observado",
    "promo" to "Promoción de la tienda",
    "coupon" to "Cupón verificado (premium)",
    "back_in_stock" to "Vuelve a estar disponible",
    "better_elsewhere" to "Mejor precio en otra tienda (premium)",
    "total_budget" to "Presupuesto total (premium)",
)

val RANGE_LABELS = mapOf("7d" to "7 días", "30d" to "30 días", "90d" to "90 días", "6m" to "6 meses", "1y" to "1 año")
