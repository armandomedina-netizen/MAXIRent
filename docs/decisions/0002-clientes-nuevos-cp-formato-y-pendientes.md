# ADR 0002: Clientes Nuevos CP — se mantiene el formato de Nuvia; mejoras pendientes

- Estado: aceptada (temporal), con revisiones pendientes
- Fecha: 2026-09-30

## Contexto

La automatización `automations/maxinet-clientes-nuevos-cp` agrega filas a la pestaña "Reporte Generales Clientes Nuevo" del Tablero CP. Esa pestaña la mantenía Nuvia a mano, y su formato/estructura debe conservarse para no romper el archivo ni las fórmulas que dependen de él.

## Decisión

Se conserva el formato de Nuvia tal cual, incluso donde tiene defectos conocidos. Los ajustes de abajo se posponen hasta alinearlos con ella.

## Revisiones necesarias (pendientes)

1. **IDs con `$` dañados por formato de moneda.** Algunos ClientNo/BookingNo de Maxinet empiezan con `$` (ej. `$123456A`). Al pegarlos, Sheets los interpretó como moneda: se pierde el prefijo y las letras finales, y quedan como número con formato `#,##0.00"$"` (ej. `123,456.00$`). Hay 4 filas afectadas (6 celdas) en B y F. Se dejaron como las tenía Nuvia. Riesgo: pérdida de información y posibles colisiones de ID. Mejora propuesta: guardar esas columnas como texto y corregir los históricos con el valor de Maxinet.
2. **Script y IDs con `$`.** Para filas nuevas el script escribe los IDs que empiezan con `$` como texto (no como moneda). Es intencional para no perder datos, pero difiere del formato histórico. Confirmar con Nuvia.
3. **Clientes que entran tarde a Maxinet.** (Mitigado parcialmente: desde 2026-10-05 Clientes Nuevos consulta anteayer → hoy y corre 9:30 AM, para recoger lo que Maxinet importa a las 9:40.) El reporte omite clientes registrados con días de retraso (caso real: un cliente de fin de julio con DateImport del 4-ago que nunca se pegó). Mejora propuesta: ventana móvil de ~7 días (el control de repetidos evita duplicar) o auditoría semanal que avise de faltantes.
4. **Registro faltante histórico.** Un cliente de julio existe en Maxinet y no en el Sheet original; decidir con Nuvia si se agrega y dónde (al final o en su fecha).
5. **Orden de filas fuera de fecha.** Definir si los rezagados van al final o se insertan en su fecha.

## Salvaguardas ya implementadas

- Se omite cualquier fila cuyo ClientNo, BookingNo o llave Nombre + CreationDate + placa ya exista (esta última cubre los IDs dañados del punto 1).
- Al final de cada corrida se valida todo el Sheet: si hay ClientNo o BookingNo repetidos, la corrida falla.
- Nunca se usa `append_rows()`; la fila destino se calcula. Las columnas con fórmulas (A y R:V) no se tocan.

## Clientes Potenciales CP (pestaña "Reporte Clientes Potenciales CP")

Automatización en `automations/maxinet-clientes-potenciales-cp`. Pendientes para alinear con Nuvia:

6. **Cliente faltante histórico (enero).** Maxinet lista un cliente en el periodo 01/2026 que no está en el Sheet. No se agregó (el reporte diario solo consulta el mes en curso y, la primera semana del mes, el anterior). Confirmar si se omitió a propósito.
7. **Registros ya pegados no se actualizan.** Maxinet cambia el No. Rentas y la Fecha Última Renta de un cliente con el tiempo; el Sheet conserva el valor del momento en que se pegó, igual que el proceso manual.
8. **Fórmulas pre-arrastradas incompletas.** Las fórmulas de A y J:M llegan hasta la fila ~2511 con huecos después; el script copia las que falten en las filas que escribe, pero conviene revisar el resto del rango.
