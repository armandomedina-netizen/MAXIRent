# ADR 0010: El Tablero copia lee de la Base copia

- Estado: aceptada, con tres hojas y una autorización pendientes
- Fecha: 2026-10-19

## Contexto

El Tablero copia ("Copia Automatizada de CP - TABLERO") importaba por IMPORTRANGE los archivos originales de Nuvia ("h encuestas", "BASE LP", "CP - TABLERO"), de modo que no dependía de nuestras automatizaciones. La Base copia ya recibe los datos directo de Maxinet (ENTREGAS, Clientes Nuevos, Clientes Potenciales, Clientes Frecuentes Activos 35 y ENCUESTAS), por lo que el Tablero debe leerla a ella.

## Decisión

Con búsqueda y reemplazo dentro de fórmulas (reversible) en el Tablero copia:

- IMPORTRANGE de "h encuestas" -> Base copia, en 12 fórmulas de 8 hojas: CLIENTES NUEVOS & POTENCIAL, ENCUESTAS POR AREAS RESPONSABLES, ENCUESTAS POR SUCURSAL, ENTREGAS POR SUCURSAL, INDICADOR DE GASOLINA, NOMINA, POR ASESOR y Ticket Sac/Maxiemergencia.
- IMPORTRANGE de GRAFICAS al "CP - TABLERO" original -> el propio Tablero copia.

## Lo que queda pendiente

1. **Autorizar la conexión una vez.** Google exige autorizar el IMPORTRANGE entre dos archivos nuevos desde la hoja, con una cuenta que tenga acceso a ambos: abrir el Tablero copia, seleccionar una celda con `#REF!` (por ejemplo en CLIENTES NUEVOS & POTENCIAL) y pulsar "Permitir acceso". Una sola autorización sirve para todas las fórmulas que leen de la Base copia. No se puede hacer por API.
2. **Tres hojas con celdas protegidas** a las que la cuenta de servicio no tiene acceso de edición: ENCUESTAS 2026 V1 (A1), KADEX EJECUTIVOS (A2) y TASA DE ENTREGAS (hoja completa). Siguen leyendo "h encuestas". Se cambian con Ctrl+H (Buscar y reemplazar, todas las hojas, buscar también en fórmulas) o agregando a la cuenta de servicio como editora de esas protecciones.
3. **Siguen apuntando a archivos de Nuvia:** BASE LP (FLOTA CP, DISPONIBLE CON RESERVA, GRAFICAS), el archivo MaxiEmergencia 2026 (Ticket Sac/Maxiemergencia) y el archivo al que la cuenta de servicio no tiene acceso (PROYECCIÓN DE VENTA $$ y RESERVAS SIN FACTURAR, con `#REF!`).
4. Las hojas de la Base que todavía no se automatizan (CRE, kardex, FACTURACION CP, NUEVA ENCUENTAS V1, SUCURSALES, TABLA NUEVA CLIENTES, NOMINA, gasolina, POR ASESOR, MaxiEmergencia) alimentan al Tablero con la información que tengan; las que dependen de las automatizadas se recalculan solas.

## Cómo revertir

En el Tablero copia, Buscar y reemplazar (todas las hojas, incluyendo fórmulas): sustituir el ID de la Base copia por el del archivo original "h encuestas", y el ID del Tablero copia por el del "CP - TABLERO" original en GRAFICAS. Los IDs de los archivos se obtienen de sus direcciones (`/d/<ID>/`).
