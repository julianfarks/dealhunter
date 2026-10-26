# Despliegue

1. Un servidor con Docker y un dominio con HTTPS (ponlo detrás de un proxy como Caddy o Nginx; la app admite `http://`
   sólo para pruebas).
2. `cp backend/.env.example backend/.env` y completa al menos `SECRET_KEY` y las credenciales de las tiendas que uses.
3. `docker compose up -d --build`. El contenedor `api` ejecuta `alembic upgrade head` al arrancar; el contenedor
   `worker` (`python -m app.worker`) hace las consultas de precios y envía las notificaciones aunque ningún teléfono
   esté conectado.
4. Haz premium a un usuario: `docker compose exec api python -m app.admin set-tier correo@ejemplo.com premium`.
5. Comprueba una tienda: `docker compose exec api python -m app.admin check <url>`.
6. Copia de seguridad: `pg_dump` del volumen `dbdata`.

Salud: `GET /api/v1/health`. Política de privacidad: `GET /api/v1/privacy`.

## Cómo funciona la vigilancia

- Un trabajo por publicación (no por usuario): varios usuarios que siguen el mismo producto comparten una consulta.
- Cola con bloqueo (`FOR UPDATE SKIP LOCKED` en PostgreSQL), límite de peticiones por tienda y reintentos con espera creciente.
- Intervalos adaptativos: más seguido cuando el precio está cerca de tu objetivo o cambió mucho.
- Sólo se guarda una observación cuando el precio cambia (o pasan 24 h), así el historial es real y compacto.
