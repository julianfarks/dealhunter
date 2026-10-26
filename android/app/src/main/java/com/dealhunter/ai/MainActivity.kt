package com.dealhunter.ai

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LocalOffer
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.material3.MaterialTheme
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.dealhunter.ai.ui.AddLinkDialog
import com.dealhunter.ai.ui.AiDialog
import com.dealhunter.ai.ui.AuthScreen
import com.dealhunter.ai.ui.CartScreen
import com.dealhunter.ai.ui.DealHunterTheme
import com.dealhunter.ai.ui.DetailScreen
import com.dealhunter.ai.ui.HomeScreen
import com.dealhunter.ai.ui.MainVm
import com.dealhunter.ai.ui.NotificationsScreen
import com.dealhunter.ai.ui.OffersScreen
import com.dealhunter.ai.ui.SettingsScreen

class MainActivity : ComponentActivity() {
    private val vm: MainVm by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Si alguien abre la app con un enlace pegado desde otra app de forma directa.
        val shared = if (intent?.action == Intent.ACTION_SEND) intent.getStringExtra(Intent.EXTRA_TEXT) else null
        if (shared != null) vm.addLink(shared)
        setContent {
            val session by vm.session.collectAsState()
            DealHunterTheme(session.theme) {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { AppRoot(vm) }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        if (vm.prefs.loggedIn) vm.sync()
    }
}

private data class Tab(val route: String, val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

@Composable
private fun AppRoot(vm: MainVm) {
    val nav = rememberNavController()
    val session by vm.session.collectAsState()
    val message by vm.message.collectAsState()
    val snack = remember { SnackbarHostState() }
    var showAdd by remember { mutableStateOf(false) }
    var showAi by remember { mutableStateOf(false) }
    var skippedAuth by remember { mutableStateOf(vm.prefs.skippedAuth) }
    val tabs = listOf(
        Tab("home", "Inicio", Icons.Filled.Home), Tab("cart", "Carrito", Icons.Filled.ShoppingCart),
        Tab("offers", "Ofertas", Icons.Filled.LocalOffer), Tab("notifs", "Alertas", Icons.Filled.Notifications),
        Tab("settings", "Ajustes", Icons.Filled.Settings),
    )
    LaunchedEffect(message) { message?.let { snack.showSnackbar(it); vm.consumeMessage() } }
    val needAuth = !session.loggedIn && !skippedAuth
    val back by nav.currentBackStackEntryAsState()
    val route = back?.destination?.route

    if (needAuth) {
        AuthScreen(vm) { vm.prefs.skippedAuth = true; skippedAuth = true; vm.refreshSession() }
        return
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snack) },
        bottomBar = {
            if (route != null && !route.startsWith("detail")) NavigationBar {
                tabs.forEach { t ->
                    NavigationBarItem(
                        selected = route == t.route, label = { Text(t.label) }, icon = { Icon(t.icon, t.label) },
                        onClick = { nav.navigate(t.route) { popUpTo(nav.graph.findStartDestination().id) { saveState = true }; launchSingleTop = true; restoreState = true } },
                    )
                }
            }
        },
    ) { pad ->
        NavHost(nav, startDestination = "home", modifier = Modifier.padding(pad)) {
            composable("home") { HomeScreen(vm, { nav.navigate("cart") }, { nav.navigate("detail/$it") }, { showAdd = true }, { showAi = true }) }
            composable("cart") { CartScreen(vm, { nav.navigate("detail/$it") }, { showAdd = true }) }
            composable("offers") { OffersScreen(vm) { nav.navigate("detail/$it") } }
            composable("notifs") { NotificationsScreen(vm) { nav.navigate("detail/$it") } }
            composable("settings") { SettingsScreen(vm) { vm.prefs.skippedAuth = false; skippedAuth = false } }
            composable("detail/{id}", arguments = listOf(navArgument("id") { type = NavType.LongType })) { entry ->
                DetailScreen(vm, entry.arguments?.getLong("id") ?: 0L) { nav.popBackStack() }
            }
        }
    }
    if (showAdd) AddLinkDialog(vm) { id -> showAdd = false; if (id != null) nav.navigate("detail/$id") }
    if (showAi) AiDialog(vm, null) { showAi = false }
}
