# 0011 - Endurecimiento del repositorio: pruebas en cada PR, versiones fijas y límites en los workflows

Fecha: 2026-10-20

## Contexto

En octubre de 2026 el tablero LP se reestructuró varias veces (hojas renombradas, columnas movidas, hojas eliminadas) y tres incidentes salieron de la misma causa: código con nombres o letras de columna fijos, sin pruebas que lo cubrieran y con pasos auxiliares que podían detener el sync completo. Además, las dependencias no tenían versión, varios workflows no tenían tiempo máximo ni control de corridas simultáneas, ninguno limitaba los permisos del token (salvo uno) y el README no mencionaba las automatizaciones.

## Decisión

1. Pruebas automáticas en el repositorio para `maxinet-sync` (`automations/maxinet-sync/tests`, hojas simuladas, sin red ni credenciales) y un workflow `pruebas.yml` que las corre, junto con las de TableroSAC, en cada PR y en cada integración a `main`. Cubren lo que falló: la lista ON HIRE como fórmula matricial, los bloques pivote de `RESUMEN`, la extensión segura de `TABLAS`, los pasos auxiliares tolerantes, las pestañas por nombre, alias o gid, la lectura de `TARIFA DETALLE` con validación de encabezados y la tabla de ubicaciones.
2. Versiones fijas de las dependencias directas en los `requirements.txt` de las automatizaciones de Maxinet y Gestoría (las que instalaron las últimas corridas exitosas: `requests`, `pandas`, `gspread`, `google-auth`, `google-auth-oauthlib` y `python-dotenv`). TableroSAC conserva sus rangos.
3. Todos los workflows de sincronización declaran `permissions: contents: read`, un tiempo máximo (`timeout-minutes`) y un grupo de `concurrency` sin cancelar la corrida en curso.
4. Documentación: `docs/automatizaciones.md` (mapa de procesos, horarios, disparo externo, secrets y guía de operación) enlazada desde el README.

## Consecuencias

- Un cambio que rompa una protección falla en el PR, no en producción. Verificado quitando a propósito cada protección: la prueba correspondiente falla.
- Subir una dependencia es un cambio explícito (PR con pruebas y corrida desde la rama).
- Una corrida colgada se corta a los 10-25 minutos en vez de a las 6 horas, y dos corridas del mismo workflow no se pisan.
- Siguen fuera del repositorio, por llevar datos del equipo: el proyecto de Apps Script `Vigilante_Maxinet` y el script local de recuperación de días.
- Pendiente: disparo externo para los cinco workflows del Tablero CP, que hoy dependen solo del reloj de GitHub y llegan entre 2 y 5 horas tarde.
