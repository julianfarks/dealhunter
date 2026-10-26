# DealHunter AI

App Android + backend para vigilar precios de productos de cualquier tienda: compartes un enlace desde la app de la
tienda (menú *Compartir*) y el servidor vigila el precio por ti, aunque tu teléfono esté apagado.

> **Estado honesto del proyecto** — léelo antes de usarlo: [`docs/limitaciones.md`](docs/limitaciones.md).
> En resumen: Mercado Libre y eBay están implementados con sus APIs oficiales **pero no se han probado contra
> las APIs reales** (hacen falta tus credenciales); Amazon, AliExpress y Temu **no tienen fuente de datos** y sus
> productos quedan guardados con el estado «Requiere una fuente de datos compatible». Nunca se inventan precios.

## Qué está verificado (y qué no)

- Backend: **143 pruebas pasan** en GitHub Actions (datos de tiendas simulados y etiquetados).
- Android: **compila** y pasa sus pruebas unitarias en GitHub Actions; el APK está en `releases/`.
- **No verificado:** uso real en un teléfono, conexión con las APIs reales de Mercado Libre/eBay, envío real de push (FCM).

## Qué incluye

| Carpeta | Contenido |
|---|---|
| `android/` | App Kotlin + Jetpack Compose (Room, WorkManager, OkHttp, FCM). Receptor de *Compartir*, carrito universal, detalle con gráfico de historial (7d/30d/90d/6m/1y), alertas, ofertas, comparación, ajustes, tema oscuro/claro. |
| `backend/` | API FastAPI + worker de precios + PostgreSQL/SQLite. Alertas sin duplicados, push FCM, horas de silencio, límites gratis/premium, exportación y borrado de cuenta. |
| `backend/app/connectors/` | Un conector por tienda (`mercadolibre`, `ebay`, `generic`, y los pendientes `amazon`, `aliexpress`, `temu`). |
| `backend/migrations/` | Migraciones Alembic. |
| `backend/tests/` | Pruebas (datos **simulados**, marcados `TEST_SIMULATED`). |
| `docs/` | Tiendas, despliegue, credenciales, API, privacidad y limitaciones. |
| `releases/` | APK de depuración compilado por GitHub Actions. |

## APK

El APK se compila **en GitHub Actions** (workflow *Android APK*) y se publica en
`releases/DealHunterAI-debug.apk` y en la sección *Releases*. Es un APK de **depuración** (firmado con la clave de
debug): sirve para instalar y probar, no para Google Play. Pasos de instalación en [`docs/instalacion.md`](docs/instalacion.md).

## Arranque rápido del backend

```bash
cp backend/.env.example backend/.env      # edita SECRET_KEY y las credenciales que tengas
docker compose up --build                 # API en :8000 + worker + PostgreSQL
```

Más detalles: [`docs/despliegue.md`](docs/despliegue.md) · credenciales: [`docs/credenciales.md`](docs/credenciales.md).

## Pruebas

```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
```

La CI ejecuta las pruebas del backend en cada *push* (`.github/workflows/backend.yml`) y las pruebas unitarias de
Android al compilar (`.github/workflows/android.yml`).
