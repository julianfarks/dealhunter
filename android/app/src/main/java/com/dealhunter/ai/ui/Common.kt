package com.dealhunter.ai.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dealhunter.ai.data.CartEntity
import com.dealhunter.ai.data.SyncState
import com.dealhunter.ai.data.TrackedDto
import coil.compose.AsyncImage
import androidx.compose.ui.layout.ContentScale

@Composable
fun SurfaceCard(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Card(
        modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.35f)),
    ) { Column(Modifier.padding(14.dp)) { content() } }
}

@Composable
fun Chip(text: String, color: Color = MaterialTheme.colorScheme.primary) {
    Box(Modifier.clip(RoundedCornerShape(50)).background(color.copy(alpha = 0.16f)).padding(horizontal = 10.dp, vertical = 4.dp)) {
        Text(text, color = color, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

fun stateColor(state: String): Color = when (state) {
    "active" -> Good
    "waiting_first_check", "paused" -> Blue
    "temporarily_failed", "price_unavailable" -> Warn
    "needs_source", "unavailable_in_store" -> Bad
    else -> Blue
}

/** Texto de estado del elemento del carrito. Distingue "guardado sólo en el teléfono" de lo ya sincronizado. */
fun statusOf(e: CartEntity): Pair<String, Color> {
    val d = e.dto
    return when {
        e.syncState == SyncState.PENDING -> "Guardado · pendiente de enviar" to Warn
        e.syncState == SyncState.FAILED -> "No se pudo añadir" to Bad
        d != null -> d.stateLabel.ifBlank { d.state } to stateColor(d.state)
        else -> "Sincronizado" to Good
    }
}

@Composable
fun ProductThumb(url: String?, size: Int = 64) {
    Box(Modifier.size(size.dp).clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceVariant)) {
        if (!url.isNullOrBlank()) AsyncImage(model = url, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.size(size.dp))
    }
}

@Composable
fun PriceLine(d: TrackedDto?) {
    val cur = d?.priceCurrent
    if (cur == null) {
        Text("Precio aún no disponible", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 14.sp)
        return
    }
    val conv = d.converted
    Column {
        Text(money(cur, d.currency), fontWeight = FontWeight.Bold, fontSize = 18.sp)
        if (conv?.current != null && conv.currency != d.currency) {
            Text(
                "≈ ${money(conv.current, conv.currency)} (tasa ${conv.rate ?: "?"} · ${dateTime(conv.asOf)})",
                fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
fun CartRow(e: CartEntity, onClick: () -> Unit) {
    val d = e.dto
    val (status, color) = statusOf(e)
    SurfaceCard(Modifier.padding(vertical = 5.dp).clickableCard(onClick)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ProductThumb(d?.imageUrl)
            Spacer(Modifier.size(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    d?.title ?: e.title ?: shortUrl(e.url), maxLines = 2, fontWeight = FontWeight.SemiBold,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
                Text(d?.storeName ?: "Tienda por identificar", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(4.dp))
                PriceLine(d)
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Chip(status, color)
                    val ch = pct(d?.changeFromInitialPct)
                    val c = dec(d?.changeFromInitialPct)
                    if (ch != null && c != null && c.signum() != 0) Chip(ch, if (c.signum() < 0) Good else Bad)
                }
            }
        }
    }
}

fun shortUrl(u: String): String = u.removePrefix("https://").removePrefix("http://").removePrefix("www.").take(60)

fun Modifier.clickableCard(onClick: () -> Unit): Modifier = this.then(Modifier.clickable(onClick = onClick))
