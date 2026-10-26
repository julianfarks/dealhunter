# Estado de cada tienda

Regla del proyecto: **una tienda sólo se considera «integrada» cuando se probó una conexión real**. Ninguna de las
siguientes lo está todavía, porque en el entorno de desarrollo no hay credenciales ni acceso a esas APIs.

| Tienda | Fuente | Estado | Qué hace la app hoy |
|---|---|---|---|
| Mercado Libre | API oficial `api.mercadolibre.com` (exige access token) | **Implementado, sin verificar contra la API real** | Con `MELI_ACCESS_TOKEN` (o client id/secret + refresh token) consulta precio, moneda, disponibilidad, imagen y descuento anunciado. Sin credenciales: «Requiere una fuente de datos compatible». |
| eBay | Browse API oficial (client credentials) | **Implementado, sin verificar contra la API real** | Con `EBAY_CLIENT_ID/SECRET` consulta el artículo. Sin credenciales: estado de fuente requerida. |
| Tiendas independientes | JSON-LD / Open Graph públicos de la página | **Implementado y probado con respuestas simuladas** | Respeta `robots.txt`, protección SSRF por redirección. Si la página no publica precio: «Precio no disponible». |
| Amazon | Product Advertising API requeriría cuenta de Afiliados aprobada | **Pendiente** | El producto se guarda (ASIN extraído del enlace) con estado «Requiere una fuente de datos compatible». No se hace scraping. |
| AliExpress | API de afiliados/dropshipping requiere aprobación | **Pendiente** | Igual que Amazon. |
| Temu | Sin API pública de precios | **Pendiente** | Igual que Amazon. |

Para comprobar un conector con tus credenciales: `python -m app.admin check <url-del-producto>` (hace una consulta
real y muestra el resultado o el error exacto).

## Cómo añadir una tienda

1. Crea una clase que herede de `Connector` en `backend/app/connectors/` (`configured()`, `fetch()`, opcional `search()`).
2. Regístrala en `registry.py`.
3. Añade el patrón de URL en `urlutil.py` (identificador del producto y de la variante).
4. Añade pruebas con respuestas **simuladas y etiquetadas**. No marques la tienda como integrada hasta probarla en real.
