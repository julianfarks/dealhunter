package com.dealhunter.ai.ui

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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.ContentPaste
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.dealhunter.ai.data.Links
import com.dealhunter.ai.data.SyncState

@Composable
fun AuthScreen(vm: MainVm, onDone: () -> Unit) {
    val session by vm.session.collectAsState()
    val busy by vm.busy.collectAsState()
    var register by remember { mutableStateOf(false) }
    var email by remember { mutableStateOf("") }
    var pass by remember { mutableStateOf("") }
    var server by remember { mutableStateOf(session.baseUrl) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Spacer(Modifier.height(24.dp))
        Text("DealHunter AI", fontSize = 32.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
        Text("Cazador de ofertas: comparte un enlace y vigilamos su precio por ti, aunque la app esté cerrada.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(server, { server = it }, label = { Text("Dirección de tu servidor DealHunter") }, singleLine = true,
            placeholder = { Text("https://mi-servidor.com") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(email, { email = it }, label = { Text("Correo") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth())
        OutlinedTextField(pass, { pass = it }, label = { Text(if (register) "Contraseña (mínimo 8 caracteres)" else "Contraseña") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
        Button(
            onClick = { vm.setBaseUrl(server); vm.auth(register, email, pass, onDone) },
            enabled = !busy && email.isNotBlank() && pass.length >= 8 && server.isNotBlank(), modifier = Modifier.fillMaxWidth(),
        ) { if (busy) CircularProgressIndicator(Modifier.height(18.dp)) else Text(if (register) "Crear cuenta" else "Iniciar sesión") }
        TextButton(onClick = { register = !register }) { Text(if (register) "Ya tengo cuenta" else "Crear una cuenta nueva") }
        OutlinedButton(onClick = { vm.setBaseUrl(server); onDone() }, modifier = Modifier.fillMaxWidth()) { Text("Continuar sin cuenta (sólo en este teléfono)") }
        Text(
            "Sin cuenta puedes guardar enlaces en tu carrito, pero el precio sólo se vigila cuando tu cuenta está conectada al servidor.",
            fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
fun AddLinkDialog(vm: MainVm, onClose: (Long?) -> Unit) {
    var text by remember { mutableStateOf("") }
    val clip = LocalClipboardManager.current
    AlertDialog(
        onDismissRequest = { onClose(null) },
        title = { Text("Añadir producto") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Pega el enlace de Amazon, AliExpress, Mercado Libre, eBay, Temu u otra tienda. También puedes usar «Compartir» desde esas apps.", fontSize = 13.sp)
                OutlinedTextField(text, { text = it }, label = { Text("Enlace del producto") }, modifier = Modifier.fillMaxWidth())
                TextButton(onClick = { clip.getText()?.text?.let { text = it } }) {
                    Icon(Icons.Filled.ContentPaste, null); Spacer(Modifier.padding(4.dp)); Text("Pegar del portapapeles")
                }
            }
        },
        confirmButton = { Button(onClick = { vm.addLink(text) { id -> onClose(id) } }, enabled = text.isNotBlank()) { Text("Añadir") } },
        dismissButton = { TextButton(onClick = { onClose(null) }) { Text("Cancelar") } },
    )
}

@Composable
fun AiDialog(vm: MainVm, trackedRemoteId: Long?, onClose: () -> Unit) {
    var text by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf<String?>(null) }
    val busy by vm.busy.collectAsState()
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Asistente de ofertas") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Ejemplos: «avísame cuando baje de 200.000», «pausa este producto», «qué producto bajó más».", fontSize = 13.sp)
                OutlinedTextField(text, { text = it }, label = { Text("¿Qué quieres hacer?") }, modifier = Modifier.fillMaxWidth())
                answer?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
            }
        },
        confirmButton = {
            Button(onClick = { vm.ai(text, trackedRemoteId) { answer = it } }, enabled = text.isNotBlank() && !busy) { Text("Enviar") }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Cerrar") } },
    )
}

@Composable
fun HomeScreen(vm: MainVm, openCart: () -> Unit, openDetail: (Long) -> Unit, onAdd: () -> Unit, onAi: () -> Unit) {
    val items by vm.cart.collectAsState()
    val pending by vm.pending.collectAsState()
    val session by vm.session.collectAsState()
    val active = items.filter { !it.archived && !it.purchased }
    val dtos = active.mapNotNull { it.dto }
    val drops = active.filter { (dec(it.dto?.changeFromInitialPct)?.signum() ?: 0) < 0 }
        .sortedBy { dec(it.dto?.changeFromInitialPct) }.take(5)
    val needsAttention = dtos.count { it.state in setOf("temporarily_failed", "needs_source", "price_unavailable", "unavailable_in_store") }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 16.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Hola 👋", fontSize = 26.sp, fontWeight = FontWeight.Bold)
                    Text(if (session.loggedIn) session.email.orEmpty() else "Modo sin cuenta", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                IconButton(onClick = { vm.sync() }) { Icon(Icons.Filled.Refresh, "Sincronizar") }
                IconButton(onClick = onAi) { Icon(Icons.Filled.AutoAwesome, "Asistente") }
            }
            Spacer(Modifier.height(12.dp))
            SurfaceCard {
                Text("Tu carrito universal", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Chip("${active.size} productos")
                    if (pending > 0) Chip("$pending por enviar", Warn)
                    if (needsAttention > 0) Chip("$needsAttention requieren atención", Bad)
                    if (drops.isNotEmpty()) Chip("${drops.size} con baja", Good)
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onAdd) { Icon(Icons.Filled.Add, null); Spacer(Modifier.padding(3.dp)); Text("Añadir enlace") }
                    OutlinedButton(onClick = openCart) { Text("Ver carrito") }
                }
            }
            Spacer(Modifier.height(14.dp))
            Text("Mayores bajadas desde que los añadiste", fontWeight = FontWeight.SemiBold)
            if (drops.isEmpty()) {
                Text(
                    if (active.isEmpty()) "Comparte un enlace desde cualquier tienda y aparecerá aquí."
                    else "Todavía no hay bajadas registradas. Sólo mostramos cambios reales observados.",
                    fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp),
                )
            }
        }
        items(drops, key = { it.localId }) { CartRow(it) { openDetail(it.localId) } }
        item {
            Spacer(Modifier.height(10.dp))
            if (!session.loggedIn) {
                SurfaceCard { Text("Estás sin cuenta: los productos se guardan en el teléfono, pero el servidor no vigila sus precios. Inicia sesión en Ajustes.", fontSize = 13.sp) }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CartScreen(vm: MainVm, openDetail: (Long) -> Unit, onAdd: () -> Unit) {
    val items by vm.cart.collectAsState()
    var q by remember { mutableStateOf("") }
    var filter by remember { mutableStateOf("active") }
    val shown = items.filter { e ->
        val d = e.dto
        val matches = q.isBlank() || (d?.title ?: e.title ?: e.url).contains(q, true) || (d?.storeName ?: "").contains(q, true) || (d?.notes ?: "").contains(q, true)
        val inFilter = when (filter) {
            "active" -> !e.archived && !e.purchased
            "archived" -> e.archived
            "purchased" -> e.purchased
            "attention" -> !e.archived && !e.purchased && (e.syncState != SyncState.SYNCED || d?.state in setOf("temporarily_failed", "needs_source", "price_unavailable", "unavailable_in_store"))
            else -> true
        }
        matches && inFilter
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(16.dp, 12.dp, 16.dp, 0.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Mi carrito", fontSize = 24.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Button(onClick = onAdd) { Icon(Icons.Filled.Add, null); Text("Añadir") }
        }
        OutlinedTextField(q, { q = it }, label = { Text("Buscar por nombre, tienda o nota") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(16.dp, 8.dp))
        Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((k, label) in listOf("active" to "Activos", "attention" to "Atención", "purchased" to "Comprados", "archived" to "Archivados")) {
                FilterChip(selected = filter == k, onClick = { filter = k }, label = { Text(label) })
            }
        }
        if (shown.isEmpty()) {
            Text(
                if (items.isEmpty()) "Tu carrito está vacío. Comparte un enlace desde Amazon, AliExpress, Mercado Libre, eBay o Temu, o pégalo con «Añadir»."
                else "No hay productos con ese filtro.",
                modifier = Modifier.padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        LazyColumn(Modifier.fillMaxWidth().padding(horizontal = 16.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 8.dp)) {
            items(shown, key = { it.localId }) { CartRow(it) { openDetail(it.localId) } }
        }
    }
}
