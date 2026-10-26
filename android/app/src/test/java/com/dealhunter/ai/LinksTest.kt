package com.dealhunter.ai

import com.dealhunter.ai.data.AppJson
import com.dealhunter.ai.data.Links
import com.dealhunter.ai.data.TrackedDto
import com.dealhunter.ai.data.HistoryResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LinksTest {
    @Test
    fun extraeElEnlaceDeUnTextoCompartido() {
        assertEquals(
            "https://a.co/d/xyz123",
            Links.extract("Mira esto en Amazon: https://a.co/d/xyz123). ¡Genial!"),
        )
        assertNull(Links.extract("sin enlace"))
        assertNull(Links.extract(null))
    }

    @Test
    fun laMismaPublicacionConParametrosPublicitariosTienLaMismaClave() {
        val a = Links.key("https://www.amazon.com/dp/B09XS7JWHH?tag=x&utm_source=y")
        val b = Links.key("https://amazon.com/dp/B09XS7JWHH/")
        assertEquals(a, b)
    }

    @Test
    fun lasVariantesNoSeConfunden() {
        assertNotEquals(
            Links.key("https://es.aliexpress.com/item/1005005123456789.html?sku_id=1"),
            Links.key("https://es.aliexpress.com/item/1005005123456789.html?sku_id=2"),
        )
    }

    @Test
    fun validaEnlacesPlausibles() {
        assertTrue(Links.isPlausible("https://tienda.com/producto"))
        assertFalse(Links.isPlausible("ftp://tienda.com/x"))
        assertFalse(Links.isPlausible("no es un enlace"))
        assertFalse(Links.isPlausible("https://localhost/x"))
    }

    @Test
    fun decodificaLaRespuestaDelServidorIgnorandoCamposNuevos() {
        val json = """{"id":7,"title":"Audífonos","state":"active","state_label":"Seguimiento automático activo",
            "price_current":"215000.00","currency":"COP","campo_futuro":123,"alerts":[{"id":1,"kind":"any_drop","active":true}]}"""
        val dto = AppJson.decodeFromString<TrackedDto>(json)
        assertEquals(7L, dto.id)
        assertEquals("215000.00", dto.priceCurrent)
        assertEquals(1, dto.alerts.size)
        assertNull(dto.priceInitial)
    }

    @Test
    fun decodificaElHistorialSinInventarDatos() {
        val h = AppJson.decodeFromString<HistoryResponse>("""{"range":"30d","points":[],"warnings":["Todavía no hay precios registrados para este producto."]}""")
        assertTrue(h.points.isEmpty())
        assertNull(h.stats.average)
    }
}
