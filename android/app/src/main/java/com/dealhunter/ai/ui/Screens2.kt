package com.dealhunter.ai.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dealhunter.ai.data.SyncState

private val ALERT_CHOICES = listOf("any_drop", "pct_drop", "historic_low", "promo", "back_in_stock", "coupon", "better_elsewhere", "total_budget")

@Composable
fun DetailScreen(vm: MainVm, localId: Long, onBack: () -> Unit) {
    val entity by vm.repo.observe(localId).collectAsState(initial = null)
    val history by vm.history.collectAsState()
    val compare by vm.compare.collectAsState()
    val ctx = LocalContext.current
    val e = entity
    val d = e?.dto
    var range by remember { mutableStateOf("30d") }
    var showTarget by remember { mutableStateOf(false) }
    var showAlert by remember { mutableStateOf(false) }
    var showAi by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var editNotes by remember { mutableStateOf(false) }

    LaunchedEffect(e?.remoteId, range) {
        vm.clearDetail()
        e?.remoteId?.let { vm.loadHistory(it, range) }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Volver") }
            Text("Detalle", fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            if (e?.remoteId != null) IconButton(onClick = { showAi = true }) { Icon(Icons.Filled.AutoAwesome, "Asistente") }
            IconButton(onClick = { confirmDelete = true }) { Icon(Icons.Filled.Delete, "Eliminar") }
        }
        if (e == null) { Text("Este producto ya no está en tu carrito."); return@Column }

        SurfaceCard {
            Row {
                ProductThumb(d?.imageUrl, 84)
                Spacer(Modifier.padding(6.dp))
                Column(Modifier.weight(1f)) {
                    Text(d?.title ?: e.title ?: shortUrl(e.url), fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    if (d?.titleIsGuess == true) Text("Nombre deducido del enlace; se corregirá cuando la tienda lo confirme.", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(d?.storeName ?: "Tienda por identificar", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(8.dp))
            val (status, color) = statusOf(e)
            Chip(status, color)
            d?.stateDetail?.let { Text(it, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp)) }
            if (e.syncState != SyncState.SYNCED) {
                Text(e.syncError ?: "Guardado en tu teléfono; se enviará al servidor cuando haya conexión y sesión iniciada.", fontSize = 12.sp, color = Warn, modifier = Modifier.padding(top = 4.dp))
                if (e.syncState == SyncState.FAILED) TextButton(onClick = { vm.retry(localId) }) { Text("Reintentar") }
            }
        }

        if (d != null) {
            SurfaceCard {
                Text("Precio", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(4.dp))
                PriceLine(d)
                Spacer(Modifier.height(6.dp))
                Text("Precio al añadir: ${money(d.priceInitial, d.currency)}", fontSize = 13.sp)
                Text("Objetivo: ${if (d.targetPrice != null) money(d.targetPrice, d.targetCurrency) else "sin definir"}", fontSize = 13.sp)
                d.verifiedDiscountPct?.let { Text("Descuento anunciado por la tienda: ${pct(it)?.removePrefix("+")}", fontSize = 13.sp, color = Good) }
                Text("Última consulta: ${dateTime(d.lastCheckedAt)}", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                d.fxError?.let { Text(it, fontSize = 12.sp, color = Warn) }
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { showTarget = true }) { Text("Precio objetivo") }
                    OutlinedButton(onClick = { vm.refreshOne(localId) }) { Text("Actualizar") }
                }
            }

            SurfaceCard {
                Text("Historial de precios", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                val avail = history?.availableRanges?.ifEmpty { null } ?: listOf("7d", "30d", "90d", "6m", "1y")
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                    for (r in avail) FilterChip(selected = (history?.range ?: range) == r, onClick = { range = r }, label = { Text(RANGE_LABELS[r] ?: r, fontSize = 11.sp) })
                }
                val h = history
                if (h == null) Text("Cargando…", fontSize = 13.sp)
                else {
                    if (h.points.isEmpty()) Text("Todavía no hay precios registrados.", fontSize = 13.sp)
                    else {
                        PriceChart(h.points, h.currency)
                        Spacer(Modifier.height(6.dp))
                        Text("Mínimo ${money(h.stats.min, h.currency)} · Máximo ${money(h.stats.max, h.currency)}", fontSize = 12.sp)
                        Text("Promedio ${if (h.stats.average != null) money(h.stats.average, h.currency) else "no disponible aún"} · ${h.stats.observationsTotal} observaciones", fontSize = 12.sp)
                    }
                    h.warnings.forEach { Text("ℹ $it", fontSize = 12.sp, color = Warn, modifier = Modifier.padding(top = 4.dp)) }
                    h.promotions.forEach { p ->
                        Text("• ${if (p.origin == "store") "Anunciado por la tienda" else "Calculado con el historial"}: ${p.description ?: p.kind}", fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp))
                    }
                }
            }

            SurfaceCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Alertas", fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    TextButton(onClick = { showAlert = true }) { Text("Nueva alerta") }
                }
                if (d.alerts.isEmpty()) Text("Sin alertas. Crea una para que te avisemos.", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                d.alerts.forEach { a ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(ALERT_LABELS[a.kind] ?: a.kind, fontSize = 14.sp)
                            a.threshold?.let { Text(if (a.kind == "pct_drop") "$it %" else money(it, a.thresholdCurrency), fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                            a.lastTriggeredAt?.let { Text("Último aviso: ${dateTime(it)}", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        }
                        Switch(checked = a.active, onCheckedChange = { vm.toggleAlert(localId, d.id, a.id, it) })
                        IconButton(onClick = { vm.deleteAlert(localId, d.id, a.id) }) { Icon(Icons.Filled.Delete, "Quitar alerta") }
                    }
                }
            }

            SurfaceCard {
                Text("Comparar en otras tiendas", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(4.dp))
                val c = compare
                if (c == null) {
                    OutlinedButton(onClick = { vm.loadCompare(d.id) }) { Text("Buscar coincidencias") }
                } else {
                    if (c.offers.isEmpty()) Text("No hay otras tiendas con datos reales para este producto.", fontSize = 13.sp)
                    c.offers.forEach { o ->
                        Column(Modifier.padding(vertical = 4.dp)) {
                            Text("${o.storeName} · ${money(o.price, o.currency)}", fontWeight = FontWeight.Medium, fontSize = 14.sp)
                            Text(
                                (if (o.match == "exact") "Coincidencia exacta" else "Coincidencia aproximada") +
                                    (o.totalEstimated?.let { " · total estimado ${money(it, o.currency)}" } ?: "") +
                                    (o.notes?.let { " · $it" } ?: ""),
                                fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    c.note?.let { Text(it, fontSize = 12.sp, color = Warn) }
                    if (c.disclaimer.isNotBlank()) Text(c.disclaimer, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }

            SurfaceCard {
                Text("Gestionar", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.patch(localId, d.id, """{"paused":${!d.paused}}""") }) { Text(if (d.paused) "Reanudar" else "Pausar") }
                    OutlinedButton(onClick = { vm.patch(localId, d.id, """{"archived":${!d.archived}}""") }) { Text(if (d.archived) "Restaurar" else "Archivar") }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.patch(localId, d.id, """{"purchased":${!d.purchased}}""") }) { Text(if (d.purchased) "No comprado" else "Marcar comprado") }
                    OutlinedButton(onClick = { editNotes = true }) { Text("Notas") }
                }
                d.notes?.let { Text("Nota: $it", fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp)) }
            }
        }

        Button(onClick = { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(e.url))) }, modifier = Modifier.fillMaxWidth()) { Text("Abrir en la tienda") }
        Spacer(Modifier.height(24.dp))
    }

    if (showTarget && d != null) TargetDialog(d.targetPrice, d.targetCurrency ?: d.currency ?: "COP", onSave = { p -> vm.setTarget(localId, d.id, p, d.targetCurrency ?: d.currency ?: vm.prefs.currency); showTarget = false }) { showTarget = false }
    if (showAlert && d != null) NewAlertDialog(onSave = { k, t -> vm.addAlert(localId, d.id, k, t); showAlert = false }) { showAlert = false }
    if (showAi) AiDialog(vm, d?.id) { showAi = false }
    if (editNotes && d != null) NotesDialog(d.notes.orEmpty(), onSave = { n -> vm.patch(localId, d.id, """{"notes":${kotlinx.serialization.json.JsonPrimitive(n)}}"""); editNotes = false }) { editNotes = false }
    if (confirmDelete) AlertDialog(
        onDismissRequest = { confirmDelete = false },
        title = { Text("¿Eliminar del carrito?") },
        text = { Text("Se dejará de vigilar este producto y se borrará su seguimiento.") },
        confirmButton = { Button(onClick = { confirmDelete = false; vm.remove(localId); onBack() }) { Text("Eliminar") } },
        dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancelar") } },
    )
}

@Composable
private fun TargetDialog(current: String?, currency: String, onSave: (String?) -> Unit, onClose: () -> Unit) {
    var v by remember { mutableStateOf(current?.let { dec(it)?.stripTrailingZeros()?.toPlainString() } ?: "") }
    val valid = v.isBlank() || (dec(v)?.signum() ?: 0) > 0
    AlertDialog(
        onDismissRequest = onClose, title = { Text("Precio objetivo ($currency)") },
        text = { OutlinedTextField(v, { v = it.filter { c -> c.isDigit() || c == '.' } }, label = { Text("Te avisamos cuando llegue a este precio o menos") }, isError = !valid) },
        confirmButton = { Button(onClick = { onSave(v.ifBlank { null }) }, enabled = valid) { Text(if (v.isBlank()) "Quitar objetivo" else "Guardar") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Cancelar") } },
    )
}

@Composable
private fun NotesDialog(current: String, onSave: (String) -> Unit, onClose: () -> Unit) {
    var v by remember { mutableStateOf(current) }
    AlertDialog(
        onDismissRequest = onClose, title = { Text("Notas") },
        text = { OutlinedTextField(v, { v = it }, modifier = Modifier.fillMaxWidth()) },
        confirmButton = { Button(onClick = { onSave(v) }) { Text("Guardar") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Cancelar") } },
    )
}

@Composable
private fun NewAlertDialog(onSave: (String, String?) -> Unit, onClose: () -> Unit) {
    var kind by remember { mutableStateOf("any_drop") }
    var thr by remember { mutableStateOf("") }
    val needsThr = kind in setOf("pct_drop", "total_budget")
    AlertDialog(
        onDismissRequest = onClose, title = { Text("Nueva alerta") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                ALERT_CHOICES.forEach { k ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        androidx.compose.material3.RadioButton(selected = kind == k, onClick = { kind = k })
                        Text(ALERT_LABELS[k] ?: k, fontSize = 14.sp)
                    }
                }
                if (needsThr) OutlinedTextField(thr, { thr = it.filter { c -> c.isDigit() || c == '.' } }, label = { Text(if (kind == "pct_drop") "Porcentaje (1-99)" else "Presupuesto") })
            }
        },
        confirmButton = { Button(onClick = { onSave(kind, thr.ifBlank { null }) }, enabled = !needsThr || thr.isNotBlank()) { Text("Crear") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Cancelar") } },
    )
}
