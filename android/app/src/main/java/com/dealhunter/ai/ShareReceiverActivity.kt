package com.dealhunter.ai

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.lifecycle.lifecycleScope
import androidx.activity.ComponentActivity
import com.dealhunter.ai.data.AddResult
import kotlinx.coroutines.launch

/**
 * Recibe enlaces desde el menú "Compartir" de otras apps (Amazon, AliExpress, Mercado Libre, navegador…).
 * Guarda el enlace en el teléfono al instante —no necesita que DealHunter esté abierta— y lo sincroniza después.
 */
class ShareReceiverActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = if (intent?.action == Intent.ACTION_SEND) intent.getStringExtra(Intent.EXTRA_TEXT) else null
        val repo = (application as DealHunterApp).repo
        lifecycleScope.launch {
            val msg = when (val r = repo.addLink(text.orEmpty())) {
                is AddResult.Added -> "Añadido a tu carrito de DealHunter"
                is AddResult.Duplicate -> "Este producto ya estaba en tu carrito"
                is AddResult.Invalid -> r.reason
            }
            Toast.makeText(this@ShareReceiverActivity, msg, Toast.LENGTH_LONG).show()
            setResult(Activity.RESULT_OK)
            finish()
            overridePendingTransition(0, 0)
        }
    }
}
