# ADR 0012: El Tablero CP copia adopta el diseño nuevo de Nuvia y lee de nuestras copias

- Estado: aceptada, con autorizaciones y protecciones pendientes de Armando
- Fecha: 2026-10-21

## Contexto

Nuvia reorganizó el "CP - TABLERO" original: cambió la estructura de FLOTA CP y DETALLE, agregó una fila a UNIDADES CP y columnas diarias a UNIDADES CP y a las hojas de utilización, movió el bloque de DISPONIBLE CON RESERVA, ocultó cuatro hojas técnicas y dejó de leer la hoja RESUMEN del LP: la facturación proyectada del mes en curso se toma ahora de nuestro Tablero LP (`RESUMEN AFECTACIONES`), con el mes anterior congelado a mano.

El Tablero CP copia seguía con el diseño anterior, con 13 celdas en error en FLOTA CP, hojas capturadas a mano congeladas desde el 19 de octubre y varias fórmulas que todavía leían archivos de Nuvia (BASE LP en FLOTA CP, GRAFICAS y DISPONIBLE CON RESERVA; "h encuestas" en la Base CP copia).

La política vigente es que las copias sean independientes de los archivos de Nuvia (ADR 0010, 0005).

## Decisión

### 1. Copiar el diseño en sitio, no duplicar el archivo

La cuenta de servicio no puede duplicar libros enteros (cuota de Drive) y reemplazar pestañas cambiaría sus identificadores, con lo que se romperían los vínculos del MENU PRINCIPAL y las gráficas. Se copió cada pestaña **en sitio** con la API de Sheets (valores, fórmulas, formato de celda, notas, validaciones, anchos y alturas, filas y columnas ocultas, celdas combinadas, formato condicional, filtro y filas congeladas), sustituyendo las claves de archivo dentro de las fórmulas. Las pestañas conservan su identificador. El libro de Nuvia sólo se lee; nunca se escribe en él.

Se respaldaron antes ambos libros (valores y fórmulas de todas las pestañas) en `private/backups`, fuera del repositorio.

### 2. Fase de validación con la fuente original

Primero se copió el diseño dejando FLOTA CP, GRAFICAS y DISPONIBLE CON RESERVA leyendo todavía la BASE LP de Nuvia. Con la misma fuente, el Tablero copia coincide con el de Nuvia celda por celda (fórmulas y valores mostrados) en FLOTA CP, DETALLE, UNIDADES CP, las dos hojas de utilización, DISPONIBLE CON RESERVA, GRAFICAS, FACTURACIÓN CP, DIAS VENDIDOS, Clientes Frecuentes Activos y TASA DE ENTREGAS. FLOTA CP conserva los mismos 4 errores que el original (AN701, AN1248, AN1357 y AN1514). Eso valida la réplica del diseño antes de cambiar la fuente.

### 3. Repunte a nuestras copias

- `FLOTA CP!D1`, `GRAFICAS!O53`, `GRAFICAS!O70` y `DISPONIBLE CON RESERVA!A4/G4/M4`: BASE LP de Nuvia -> nuestra Base LP copia. FLOTA CP importa ahora 44 columnas (A:AR) y obtiene la fecha de ingreso con un XLOOKUP sobre su propia columna, en lugar de la tabla de placas pegada a mano.
- `FACTURACION LP & CP` (Base CP copia) alineada con el original: septiembre congelado en D11, octubre en D12 leyendo `RESUMEN AFECTACIONES` de nuestro Tablero LP, y E2 vacía (ya no importa de `CP - TABLERO`).
- `FACTURACIÓN CP!D82` queda vacía (tenía `=IMPORTRANGE("","")` suelto).
- `MaxiEmergencia!F1` (Base CP copia) pasa de un IMPORTRANGE del propio archivo original a una referencia local, `={'TABLA NUEVA CLIENTES'!A42:D55}`. Una referencia simple sin llaves devuelve `#VALUE!`; con llaves se expande igual que el import.
- Hojas ocultas como en el original: FLOTA CP, DETALLE, ENCUESTAS POR SUCURSAL y ENCUESTAS POR AREAS RESPONSABLES.

### 4. Carga única de las hojas de captura manual

Las hojas que Nuvia captura a mano no tienen fuente en Maxinet y estaban congeladas. Se cargaron una sola vez desde el original (precedente: ADR 0005):

- Tablero CP copia: UNIDADES CP, UTILIZACION TODOS LOS GRUPO, UTILIZACION POR GRUPO, MKT, Bitácora Entregas / Recolecciones CP, POR ASESOR, Clientes Frecuentes Activos, DIAS VENDIDOS y FACTURACIÓN CP.
- Base CP copia: CRE, POR ASESOR, NUEVA ENCUENTAS V1, SUCURSALES, TABLA NUEVA CLIENTES, NOMINA, gasolina, kardex, FACTURACION CP y FACTURACION LP & CP. Quedaron idénticas al original en fórmulas y constantes, salvo `MaxiEmergencia!F1`.

Esas hojas son una **instantánea del 2026-10-21**: seguirán desfasándose mientras Nuvia las capture en su archivo. Quedan como deuda de automatización (ver pendientes).

### 5. Fechas como texto en RESERVAS

Nuestra hoja `RESERVAS CP&LP` guarda las fechas como texto ISO (`2026-10-20`) y la de Nuvia como números de serie con formato de fecha. Se probó en el propio libro: la igualdad en `COUNTIFS`, la resta y las divisiones con fechas en texto funcionan; las comparaciones (`>=`, `<`) y la igualdad dentro de `SUMPRODUCT` no. Las fórmulas actuales de FLOTA CP y de las hojas que la leen sólo usan igualdad y resta (el Tablero LP ya opera igual con nuestra Base). Una fórmula nueva que compare fechas con `<` o `>` tendría que envolverlas con `DATEVALUE`.

## Pendiente

1. **Autorizar las conexiones nuevas, una vez cada una** (Google no lo permite por API): en el Tablero CP copia, una celda con `#REF!` de FLOTA CP (lee la Base LP copia) y otra de una hoja que lea la Base CP copia; en la Base CP copia, `FACTURACION LP & CP!D12` (lee el Tablero LP); y en la copia de Gestoría, `ÍNDICE SINIESTRALIDAD!C1`. Después se repite la comparación contra el original para confirmar que los números coinciden con la nueva fuente.
2. **Protecciones.** La cuenta de servicio no puede editar hojas o celdas protegidas sin ser editora: Reporte Prospectos CP y ENTREGA A DOMICILIO (hojas completas; no se pudieron actualizar y MKT y Bitácora dependen de ellas), TASA DE ENTREGAS, y las celdas ENCUESTAS 2026 V1!A1, KADEX EJECUTIVOS!A2 y PROYECCIÓN DE VENTA $$!A5. TASA DE ENTREGAS y KADEX EJECUTIVOS siguen leyendo "h encuestas" y deben apuntar a la Base copia una vez desbloqueadas.
3. **Siguen en archivos que no son nuestros:** el Tablero CP lee `PROYECCIÓN DE VENTA $$` y `RESERVAS SIN FACTURAR` de un archivo al que la cuenta de servicio no tiene acceso, y `Ticket Sac/Maxiemergencia` y `MaxiEmergencia` de otro (TICKETS TOTALES, `por Mes`); `MaxiEmergencia!A56` da `#REF!` también en el original.
4. **`DISPONIBLE+TALLER`** (oculta) da 640 errores en los dos libros porque lee la hoja `LISTA AUTOS`, que ya no existe. No se tocó.
5. **Fuente para las hojas de captura manual** (UNIDADES CP, UTILIZACION, MKT, Bitácora, Prospectos, ENTREGA A DOMICILIO, CRE, kardex y similares): identificar con Nuvia el reporte de Maxinet que las alimenta o acordar un refresco periódico.

## Cómo revertir

Los respaldos de valores y fórmulas están en `private/backups` (`tablero_cp_antes_diseno_*.json` y `base_cp_antes_diseno_*.json`, fuera del repositorio). Para volver a la BASE LP de Nuvia en una fórmula basta sustituir el ID de nuestra Base LP copia por el del archivo original (Buscar y reemplazar en fórmulas).
