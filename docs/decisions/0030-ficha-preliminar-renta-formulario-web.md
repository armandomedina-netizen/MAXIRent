# 0030. Ficha preliminar de renta como formulario web con enlace de firma por ejecutivo

Fecha: 2026-11-10

## Contexto

El área de Validaciones usa la "Ficha preliminar para renta vehicular" como PDF que el
cliente descarga, llena y regresa. Se quiere que el cliente la conteste directamente en
una página, sin descargar nada, con el diseño y los colores del PDF y el logotipo del manual
de marca.

Reglas de negocio pedidas:

- Cada documento firmado debe quedar guardado para el ejecutivo que lo envió.
- El archivo cambia de nombre cuando el cliente lo firma, para usarlo como histórico.
- La ficha debe poder compartirse con el cliente para que la firme.

Quien la llena es un cliente externo: no tiene cuenta de monday ni de Google.

## Decisión

- **Formulario** en una página HTML estática (`automations/ficha-preliminar-renta/index.html`).
  Sólo se abre con un enlace personal `...#t=<token>`; sin él no muestra la ficha. El token va
  en el fragmento para que no llegue a los registros del hosting.
- **Enlace único por cliente.** Un ejecutivo autorizado (hoja `Ejecutivos`) genera el enlace
  desde un panel. El enlace tiene folio `FP-AAAAMMDD-NNN`, sirve una sola vez, vence a los 7
  días y se puede cancelar.
- **Un solo documento que cambia de estado.** Al generar el enlace se crea un Google
  Doc `... - PENDIENTE DE FIRMA - Cliente` en la carpeta `Pendientes` del Drive del ejecutivo. Al firmar
  se completa con los datos y la firma, se renombra a `... - FIRMADA - Razón social - fecha`,
  pasa a `Firmadas` y se guarda su PDF ahí y en `Historial`. El ejecutivo recibe un correo.
- **Receptor en Google Apps Script** vinculado a una hoja de Google Sheets: `Enlaces` (control),
  `Fichas` (respuestas, una columna por campo más el JSON) y `Ejecutivos` (altas). Dos
  despliegues del mismo código: uno público para el cliente y otro restringido a la
  organización para el panel, que identifica al ejecutivo por su correo.
- **Directo al Drive del ejecutivo.** Cada ejecutivo conecta desde el panel una carpeta propia,
  compartida como Editor con la cuenta del servicio; el servicio verifica que la carpeta es del
  ejecutivo (propietario) y que puede escribir. Como el cliente firma contra un despliegue que
  corre como la cuenta del servicio, no puede actuar como el ejecutivo; por eso se escribe en
  una carpeta que el ejecutivo le concede. Si no la conectó o la deja de compartir, el servicio
  usa una carpeta compartida con él en solo lectura en lugar de fallar.
- **Los datos se guardan antes que el documento.** Si el documento falla, la ficha ya está en
  la hoja y se rehace con `regenerarDocumento`.

## Por qué no monday ni otro servicio

- **WorkForm de monday:** es público y guardaría directo en un board, pero no reproduce el
  diseño del PDF, no tiene firma dibujada, no genera enlaces de un solo uso por ejecutivo ni
  produce un documento firmado con histórico. Además, crearlo exige una escritura en monday
  que sólo puede hacerse en el workspace `Desarrollo de Software` y con autorización. Sigue
  siendo la alternativa si se prefiere que las fichas vivan en monday; el receptor es el punto
  donde se agregaría esa integración.
- **monday code:** serviría como backend, pero requiere una app en el Developer Center y
  `MONDAY_TOKEN`; es desproporcionado para este flujo.
- **Azure, AWS, Supabase y similares:** innecesarios. El equipo ya opera con Google Sheets,
  Drive y Apps Script (por ejemplo el Vigilante de Maxinet), sin costo ni servicios nuevos.

## Consecuencias

- La dirección del despliegue público queda visible en el código de la página. Es inherente a
  cualquier formulario público; lo protegen el token de un solo uso (64 caracteres hexadecimales),
  el campo trampa, el tiempo mínimo de llenado y las validaciones del receptor.
- Los ejecutivos ven sus archivos en su propio Drive y sus fichas en el panel; no necesitan
  acceso a la hoja de resultados. Los archivos creados en su carpeta pertenecen a la cuenta del
  servicio, que conserva el control del histórico; transferir la propiedad al ejecutivo
  (`setOwner`) se descartó por ahora porque depende de la configuración del dominio y le
  quitaría a la empresa ese control.
- Las fichas contienen datos de contacto de terceros: la hoja y las carpetas quedan con acceso
  restringido. Nada de eso se versiona en este repositorio público.
- El PDF y el documento se generan en el servidor a partir de los datos recibidos, con la
  plantilla de `Documento.gs`. Agregar un campo al formulario obliga a agregarlo también ahí
  para que aparezca en el documento (la hoja lo recibe sola).
- La parte de Google (Drive, Docs, correo, despliegues) sólo se probó con servicios simulados;
  `autoprueba()` la ejercita de punta a punta con datos de ejemplo.
- Pendiente de decidir con negocio: si el cliente recibe una copia del PDF firmado y quién
  administra la hoja `Ejecutivos`.
