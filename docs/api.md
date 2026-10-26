# API (prefijo `/api/v1`)

Autenticación: `Authorization: Bearer <access_token>` (JWT de 60 min) + `POST /auth/refresh`.

| Método y ruta | Descripción |
|---|---|
| `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout-all`, `GET /auth/me` | Sesión |
| `POST /tracked` | Añadir un enlace (`url`, `target_price?`) → `{item, duplicate, message}` |
| `GET /tracked` | Carrito (filtros `q,store,state,list_name,archived,purchased,sort,currency`) |
| `GET/PATCH/DELETE /tracked/{id}` | Detalle, edición (objetivo, notas, lista, prioridad, pausa, archivado, comprado) y baja |
| `POST /tracked/bulk` | Acciones en grupo |
| `GET /tracked/{id}/history?range=7d\|30d\|90d\|6m\|1y` | Historial real + estadísticas + avisos de datos limitados |
| `POST /tracked/{id}/refresh` | Pedir una consulta inmediata (con enfriamiento) |
| `GET/POST/PATCH/DELETE /tracked/{id}/alerts` | Alertas |
| `GET /tracked/{id}/compare` | Comparación (exacta/aproximada, totales estimados) |
| `GET /offers`, `/notifications`, `/dashboard` | Ofertas con origen, notificaciones, resumen |
| `GET/PUT /preferences`, `POST/DELETE /devices` | Preferencias y tokens push |
| `POST /ai/command` | Asistente |
| `GET /sync/changes?since=` | Sincronización incremental (incluye bajas) |
| `GET /account/export`, `DELETE /account` | Exportación y borrado de cuenta |
| `GET /privacy`, `/health`, `/stores` | Información pública |

Errores: `{"detail": {"message": "...", "retryable": true|false}}` o `{"detail": "..."}`.
