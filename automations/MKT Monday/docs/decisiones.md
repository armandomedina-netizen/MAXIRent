# Decisiones

1. **El conteo se recalcula desde el tablero de leads.** La API pública de monday no entrega los datos de las gráficas de un tablero de control (solo permite crearlos), así que no se puede leer el gráfico directamente. Se leen los leads y se cuenta por mes.
2. **Tipo de lead configurable.** El gráfico de origen no cuenta todos los leads del tablero, solo los de un tipo. Ese tipo se declara en la configuración (`tipos_incluidos`) y se validó contra los meses que ya estaban en la hoja. Si el equipo de ventas cambia el criterio del gráfico, se cambia la configuración sin tocar el código.
3. **Mes de creación en hora de Ciudad de México.** monday entrega la fecha en UTC; se convierte antes de asignarla al mes para que un lead creado la noche del último día no cuente en el mes siguiente.
4. **Solo el mes en curso.** Los meses anteriores son un registro histórico y no se reescriben; `--mes` existe para correcciones puntuales.
5. **La fila se identifica por la fecha de la columna de periodos**, no por una posición fija, de modo que insertar o mover filas en la hoja no rompe la automatización.
6. **Solo se escriben recibidos y calificados.** La columna de cierres y las fórmulas se dejan intactas; si una de las dos celdas tiene fórmula, el script se detiene.
7. **Configuración real fuera de git.** El repositorio es público: los IDs y nombres de monday van en `private/` (local) o en un secret (Actions), y los mensajes de error y el registro no los repiten.
8. **Registro sin cifras en Actions.** El registro de las corridas de GitHub es público; las cifras solo se imprimen en ejecuciones locales.
