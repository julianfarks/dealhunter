package com.dealhunter.ai.data

import java.net.URI

/** Utilidades de enlaces SIN red: extraer el enlace de un texto compartido y una clave local para evitar duplicados. */
object Links {
    private val urlRegex = Regex("""https?://[^\s<>"']+""", RegexOption.IGNORE_CASE)
    private val tracking = setOf(
        "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_", "tag", "spm", "aff_fcid", "aff_fsk",
        "aff_platform", "aff_trace_key", "matt_tool", "matt_word", "mkcid", "mkrid", "campid", "customid",
        "pf_rd_p", "pf_rd_r", "psc", "pd_rd_i", "pd_rd_r", "pd_rd_w", "pd_rd_wg", "crid", "sprefix", "dib", "dib_tag",
    )

    /** Devuelve el primer enlace http(s) de un texto compartido, sin signos de puntuación finales. */
    fun extract(text: String?): String? {
        if (text.isNullOrBlank()) return null
        val m = urlRegex.find(text) ?: return null
        return m.value.trimEnd('.', ',', ')', ']', '}', ';', ':', '!', '?', '»', '"', '\'')
    }

    /** ¿Parece un enlace válido? (la validación completa y de seguridad la hace siempre el servidor). */
    fun isPlausible(url: String): Boolean = try {
        val u = URI(url)
        (u.scheme == "http" || u.scheme == "https") && !u.host.isNullOrBlank() && u.host.contains('.')
    } catch (_: Exception) {
        false
    }

    /** Clave local para detectar el mismo enlace aunque cambien parámetros publicitarios. */
    fun key(url: String): String {
        return try {
            val u = URI(url.trim())
            val host = u.host.lowercase().removePrefix("www.")
            val q = (u.rawQuery ?: "").split('&').filter { it.isNotBlank() }.filter { p ->
                val k = p.substringBefore('=').lowercase()
                !k.startsWith("utm_") && k !in tracking
            }.sorted().joinToString("&")
            val path = (u.rawPath ?: "").trimEnd('/')
            host + path + if (q.isNotEmpty()) "?$q" else ""
        } catch (_: Exception) {
            url.trim().lowercase()
        }
    }
}
