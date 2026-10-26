# Limitaciones reales (léelas)

- **Nada se ha probado contra tiendas reales.** Mercado Libre y eBay están implementados según su documentación
  oficial, pero no se ejecutaron con credenciales reales. Verifícalos con `python -m app.admin check <url>`.
- **Amazon, AliExpress y Temu no tienen fuente de datos.** Sus enlaces se guardan, pero el precio no se vigila hasta
  que exista una fuente permitida. No se hace scraping ni se evaden protecciones.
- **Tiendas independientes:** sólo funcionan si la página publica el precio como dato estructurado.
- **Push:** requiere tu proyecto de Firebase (`google-services.json` en la app y cuenta de servicio en el servidor). Sin
  eso, las alertas se guardan y se ven dentro de la app, y el estado de entrega lo indica.
- **El APK es de depuración**, no está firmado para Google Play.
- **Cupones:** sólo se muestran los que la tienda/usuario registró; se marcan «verificados» únicamente con fecha de
  verificación. No se buscan cupones en la web.
- **Comparación entre tiendas:** los totales son estimaciones; las coincidencias sin GTIN o marca+modelo son aproximadas.
- **Conversión de moneda:** usa una tasa pública (open.er-api.com) y siempre muestra tasa y fecha; si no hay tasa, se
  muestra el importe original.
- **IA:** el asistente sólo interpreta tu orden; ejecuta acciones deterministas sobre tus datos reales. Requiere
  `ANTHROPIC_API_KEY` (si no, usa un intérprete de reglas en español) y plan premium por defecto.
- **Pruebas de la app Android:** hay pruebas unitarias (enlaces y decodificación); no hay pruebas instrumentadas de UI.
- **Migraciones:** la migración inicial crea el esquema desde los modelos; las siguientes deben ser incrementales.
