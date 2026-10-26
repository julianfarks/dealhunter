package com.dealhunter.ai.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dealhunter.ai.DealHunterApp

@Composable
fun OffersScreen(vm: MainVm, openDetail: (Long) -> Unit) {
    val offers by vm.offers.collectAsState()
    val items by vm.cart.collectAsState()
    val session by vm.session.collectAsState()
    LaunchedEffect(session.loggedIn) { if (session.loggedIn) vm.loadOffers() }
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Text("Ofertas", fontSize = 24.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 12.dp))
        Text(
            "Sólo se muestran promociones anunciadas por la tienda, cambios calculados con tu historial y cupones. Cada una indica su origen.",
            fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(vertical = 6.dp),
        )
        val list = offers
        when {
            !session.loggedIn -> Text("Inicia sesión para ver las ofertas de tus productos.")
            list == null -> Text("Cargando…")
            list.isEmpty() -> Text("Por ahora no hay ofertas reales detectadas en tus productos. Te avisaremos cuando aparezcan.")
            else -> LazyColumn(contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 16.dp)) {
                items(list) { o ->
                    SurfaceCard(Modifier.padding(vertical = 5.dp).clickableCard {
                        items.firstOrNull { it.remoteId == o.trackedId }?.let { openDetail(it.localId) }
                    }) {
                        Text(o.title, fontWeight = FontWeight.SemiBold, maxLines = 2)
                        Text(o.storeName, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.height(4.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Chip(o.originLabel.ifBlank { o.origin }, if (o.origin == "store") Good else Blue)
                            if (o.type == "coupon") Chip(if (o.verified) "Cupón verificado" else "Cupón sin verificar", if (o.verified) Good else Warn)
                            pct(o.discountPct)?.let { Chip(it.removePrefix("+") + " menos", Good) }
                        }
                        o.description?.let { Text(it, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp)) }
                        if (o.currentPrice != null) Text("${money(o.previousPrice, o.currency)} → ${money(o.currentPrice, o.currency)}", fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 2.dp))
                        o.code?.let { Text("Código: $it", fontSize = 13.sp, fontWeight = FontWeight.Bold) }
                        o.verificationNote?.let { Text(it, fontSize = 12.sp, color = if (o.verified) Good else Warn) }
                        o.referenceNote?.let { Text(it, fontSize = 12.sp, color = Warn) }
                        o.conditions?.let { Text("Condiciones: $it", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        o.expiresAt?.let { Text("Vence: ${dateTime(it)}", fontSize = 12.sp) }
                    }
                }
            }
        }
    }
}

@Composable
fun NotificationsScreen(vm: MainVm, openDetail: (Long) -> Unit) {
    val list by vm.notifications.collectAsState()
    val items by vm.cart.collectAsState()
    val session by vm.session.collectAsState()
    LaunchedEffect(session.loggedIn) { if (session.loggedIn) vm.loadNotifications() }
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(Modifier.padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Alertas", fontSize = 24.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = { vm.readAll() }, enabled = list?.any { !it.read } == true) { Text("Marcar leídas") }
        }
        val l = list
        when {
            !session.loggedIn -> Text("Inicia sesión para recibir y ver alertas.")
            l == null -> Text("Cargando…")
            l.isEmpty() -> Text("Aún no hay alertas. Crea una en el detalle de un producto.")
            else -> LazyColumn(contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 16.dp)) {
                items(l, key = { it.id }) { n ->
                    SurfaceCard(Modifier.padding(vertical = 5.dp).clickableCard {
                        vm.readOne(n.id)
                        items.firstOrNull { it.remoteId == n.trackedId }?.let { openDetail(it.localId) }
                    }) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(n.title, fontWeight = if (n.read) FontWeight.Normal else FontWeight.Bold, modifier = Modifier.weight(1f))
                            if (!n.read) Chip("Nueva")
                        }
                        Text(n.body, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))
                        Text(dateTime(n.createdAt) + deliveryNote(n.deliveryStatus), fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                    }
                }
            }
        }
    }
}

private fun deliveryNote(status: String) = when (status) {
    "sent" -> " · push enviada"
    "deferred" -> " · push en espera (horas de silencio o límite diario)"
    "no_devices" -> " · sin dispositivo registrado para push"
    "not_configured" -> " · push no configurada en el servidor"
    "failed" -> " · falló el envío push"
    else -> ""
}

@Composable
fun SettingsScreen(vm: MainVm, onLogin: () -> Unit) {
    val s by vm.session.collectAsState()
    val push by vm.pushStatus.collectAsState()
    val ctx = LocalContext.current
    val app = ctx.applicationContext as DealHunterApp
    var server by remember(s.baseUrl) { mutableStateOf(s.baseUrl) }
    var qs by remember { mutableStateOf("") }
    var qe by remember { mutableStateOf("") }
    var currency by remember(s.currency) { mutableStateOf(s.currency) }
    var confirmDelete by remember { mutableStateOf(false) }
    var exportJson by remember { mutableStateOf<String?>(null) }
    val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri: Uri? ->
        val data = exportJson
        if (uri != null && data != null) {
            ctx.contentResolver.openOutputStream(uri)?.use { it.write(data.toByteArray()) }
            vm.say("Datos exportados")
        }
        exportJson = null
    }
    val notifPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Ajustes", fontSize = 24.sp, fontWeight = FontWeight.Bold)

        SurfaceCard {
            Text("Cuenta", fontWeight = FontWeight.SemiBold)
            if (s.loggedIn) {
                Text("${s.email} · plan ${if (s.tier == "premium") "Premium" else "Gratis"}", fontSize = 13.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
                    OutlinedButton(onClick = { vm.logout() }) { Text("Cerrar sesión") }
                }
            } else {
                Text("Sin sesión: tus productos sólo están en este teléfono.", fontSize = 13.sp)
                Button(onClick = onLogin, modifier = Modifier.padding(top = 8.dp)) { Text("Iniciar sesión o crear cuenta") }
            }
        }

        SurfaceCard {
            Text("Servidor", fontWeight = FontWeight.SemiBold)
            OutlinedTextField(server, { server = it }, singleLine = true, modifier = Modifier.fillMaxWidth(), label = { Text("Dirección del backend") })
            TextButton(onClick = { vm.setBaseUrl(server); vm.say("Servidor actualizado") }) { Text("Guardar dirección") }
        }

        SurfaceCard {
            Text("Apariencia y moneda", fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(vertical = 6.dp)) {
                for ((k, l) in listOf("dark" to "Oscuro", "light" to "Claro", "system" to "Sistema")) {
                    FilterChip(selected = s.theme == k, onClick = { vm.setTheme(k) }, label = { Text(l) })
                }
            }
            OutlinedTextField(currency, { currency = it.uppercase().take(3) }, singleLine = true, label = { Text("Moneda de visualización (COP por defecto)") })
            Text("Las conversiones muestran siempre la tasa y su fecha. Si no hay tasa disponible, verás el importe original.", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(
                onClick = { if (s.loggedIn) vm.savePrefs("""{"currency":"$currency"}""", currency) else { vm.prefs.currency = currency; vm.refreshSession() } },
                enabled = currency.length == 3,
            ) { Text("Guardar moneda") }
        }

        SurfaceCard {
            Text("Notificaciones", fontWeight = FontWeight.SemiBold)
            Text(push, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(vertical = 6.dp)) {
                OutlinedButton(onClick = {
                    if (android.os.Build.VERSION.SDK_INT >= 33) notifPerm.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                    app.registerPushToken { ok -> vm.say(if (ok) "Este teléfono quedó registrado para recibir avisos." else "No se pudo registrar el teléfono: revisa tu sesión y que la compilación tenga Firebase.") }
                }) { Text("Activar avisos push") }
            }
            Text("Horas de silencio (formato 24 h, p. ej. 22:00 a 07:00)", fontSize = 12.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(qs, { qs = it.take(5) }, label = { Text("Desde") }, singleLine = true, modifier = Modifier.weight(1f))
                OutlinedTextField(qe, { qe = it.take(5) }, label = { Text("Hasta") }, singleLine = true, modifier = Modifier.weight(1f))
            }
            Row {
                TextButton(onClick = { vm.savePrefs("""{"quiet_start":"$qs","quiet_end":"$qe"}""", null) }, enabled = s.loggedIn && qs.length == 5 && qe.length == 5) { Text("Guardar horas") }
                TextButton(onClick = { vm.savePrefs("""{"clear_quiet_hours":true}""", null) }, enabled = s.loggedIn) { Text("Quitar") }
            }
        }

        SurfaceCard {
            Text("Privacidad y datos", fontWeight = FontWeight.SemiBold)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 6.dp)) {
                OutlinedButton(onClick = { vm.export { exportJson = it; saver.launch("dealhunter-datos.json") } }, enabled = s.loggedIn) { Text("Exportar mis datos") }
                OutlinedButton(onClick = {
                    ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(s.baseUrl.trimEnd('/') + "/api/v1/privacy")))
                }, enabled = s.baseUrl.isNotBlank()) { Text("Política de privacidad") }
            }
            TextButton(onClick = { confirmDelete = true }, enabled = s.loggedIn) { Text("Eliminar mi cuenta y mis datos", color = Bad) }
        }

        SurfaceCard {
            Text("Acerca de", fontWeight = FontWeight.SemiBold)
            Text(
                "DealHunter AI nunca inventa precios, cupones ni historiales: sólo muestra datos obtenidos de fuentes reales. " +
                    "Si una tienda no tiene una fuente de datos compatible, el producto queda guardado y se indica claramente.",
                fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    if (confirmDelete) {
        var pass by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("Eliminar cuenta") },
            text = {
                Column {
                    Text("Se borrarán tu cuenta, tu carrito, historial y alertas. No se puede deshacer. Escribe tu contraseña para confirmar.", fontSize = 13.sp)
                    OutlinedTextField(pass, { pass = it }, visualTransformation = PasswordVisualTransformation(), singleLine = true)
                }
            },
            confirmButton = { Button(onClick = { vm.deleteAccount(pass); confirmDelete = false }, enabled = pass.isNotBlank()) { Text("Eliminar todo") } },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Cancelar") } },
        )
    }
}
