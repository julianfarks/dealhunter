# Credenciales que debes aportar tú

Ninguna se incluye en el repositorio. Se configuran en `backend/.env` (ver `.env.example`).

| Variable | Para qué | Dónde obtenerla |
|---|---|---|
| `SECRET_KEY` | Firma de sesiones (obligatoria, larga y aleatoria) | Genera una: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | PostgreSQL en producción | Tu proveedor / `docker-compose.yml` |
| `MELI_ACCESS_TOKEN` o `MELI_CLIENT_ID`+`MELI_CLIENT_SECRET`+`MELI_REFRESH_TOKEN` | Precios de Mercado Libre | developers.mercadolibre.com (crea una aplicación) |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | Precios de eBay | developer.ebay.com |
| `FCM_PROJECT_ID` + `FCM_SERVICE_ACCOUNT_FILE` | Enviar notificaciones push | Consola de Firebase → cuenta de servicio |
| `app/google-services.json` (Android) | Recibir push en la app | Consola de Firebase → app Android `com.dealhunter.ai`. Cópialo en `android/app/` y recompila. Sin él la app funciona, pero sin push. |
| `ANTHROPIC_API_KEY` | Asistente de IA (opcional) | console.anthropic.com. Vive sólo en el servidor, nunca en la app. |

La dirección del backend se escribe dentro de la app (pantalla de inicio o Ajustes), o se fija al compilar con
`-PDEALHUNTER_API_URL=https://tu-servidor`.
