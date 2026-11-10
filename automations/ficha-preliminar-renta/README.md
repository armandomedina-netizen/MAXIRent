# Ficha preliminar para renta vehicular (formulario digital con enlace de firma)

Versión web de la hoja "FICHA PRELIMINAR PARA RENTA VEHICULAR". Un ejecutivo genera un
enlace personal para su cliente; el cliente llena y firma en pantalla, sin descargar nada
ni tener cuenta de ningún servicio. El documento firmado queda guardado en la carpeta del
ejecutivo que lo envió, directo en su propio Drive, y cambia de nombre al firmarse, para usarlo como histórico.

Decisión técnica y alternativas: [ADR 0030](../../docs/decisions/0030-ficha-preliminar-renta-formulario-web.md).

## Cómo funciona

1. **El ejecutivo** abre el panel, escribe el cliente y pulsa "Generar enlace". Se crea el
   documento `FP-AAAAMMDD-NNN - PENDIENTE DE FIRMA - Cliente` en la carpeta `Pendientes` de su Drive.
2. **Comparte el enlace** (botón de WhatsApp o copiar). Sirve una sola vez y vence a los 7 días.
3. **El cliente** abre el enlace, ve la ficha preparada por su ejecutivo, la llena y firma.
4. **Al firmar**, el mismo documento se completa con los datos y la firma, se renombra a
   `FP-AAAAMMDD-NNN - FIRMADA - Razón social - AAAA-MM-DD`, pasa a la carpeta `Firmadas` del
   ejecutivo y se guarda su PDF ahí y en `Historial`. El ejecutivo recibe un correo.

### Reglas del receptor

| Regla | Detalle |
| --- | --- |
| Sólo ejecutivos autorizados | Quien genera enlaces debe estar en la hoja `Ejecutivos` con `Activo` distinto de `NO`. Se identifica por su correo de la organización. |
| Un enlace, una firma | El enlace se marca `FIRMADA` antes de generar nada; un segundo intento se rechaza. Estados: `PENDIENTE`, `FIRMADA`, `VENCIDA`, `CANCELADA`. |
| Vigencia | 7 días; se cambia con la propiedad `DIAS_VIGENCIA` (1 a 90). |
| El archivo llega a su Drive | Cada ejecutivo conecta una carpeta propia desde el panel (una vez). Dentro se crean `Pendientes` y `Firmadas`. Sin carpeta conectada, o si deja de compartirla, se usa `Ejecutivos/<Nombre (correo)>/` en la raíz del servicio, compartida con él en modo lectura; el servicio no se detiene. |
| Cambio de nombre | El mismo archivo pasa de `PENDIENTE DE FIRMA` a `FIRMADA` (o `VENCIDA`, `CANCELADA`) con folio, razón social y fecha. |
| Histórico | `Historial/` guarda el PDF de toda ficha firmada. `Fichas` (hoja) guarda cada respuesta en columnas y como JSON. |
| Sin pérdida de datos | Si falla la generación del documento, la ficha ya quedó en la hoja; se rehace con `regenerarDocumento('FP-...')`. |
| Antispam | Sin token válido no se acepta nada; además campo trampa, tiempo mínimo de llenado (10 s) y límites de tamaño. |

## Archivos

| Archivo | Para qué sirve |
| --- | --- |
| `index.html` | El formulario del cliente. Lee su enlace de `#t=...`, lo verifica y envía la firma. |
| `logo.png` | Logotipo para fondo azul tomado del manual de marca (pág. 15), con fondo transparente. Se publica junto a `index.html`. |
| `apps-script/Code.gs` | Rutas web, recepción de la firma y validaciones. |
| `apps-script/Enlaces.gs` | Ejecutivos, creación, consulta y cancelación de enlaces. |
| `apps-script/Documento.gs` | Carpetas de Drive, documento pendiente y firmado, renombrado y PDF. |
| `apps-script/Setup.gs` | `configurar()`, `autoprueba()` y `regenerarDocumento()`. |
| `apps-script/Panel.html` | Panel del ejecutivo. |
| `apps-script/Logo.gs` | Logotipo en base64 para el documento. Se regenera desde `logo.png`. |
| `apps-script/appsscript.json` | Manifiesto (zona horaria America/Mexico_City, V8). |
| `apps-script/test/flujo.test.cjs` | Prueba del flujo completo con Google simulado: `node apps-script/test/flujo.test.cjs`. |

Colores del formulario: valores RGB del PDF original (azul `#05394B`, naranja `#F47721`,
título `#EE8022`, claro `#F9A05E`, tarjetas `#F5FBFD`, campos `#E5F4FB`, aviso `#FBCEAF`,
rojo `#920000`). El logotipo es el del manual de marca.

## Puesta en marcha

**1. Hoja y receptor** (con la cuenta que será dueña de los archivos)

1. Crear una hoja de Google Sheets nueva ("Fichas preliminares de renta").
2. Extensiones > Apps Script. Crear los archivos de `apps-script/` con el mismo nombre
   (`.gs` como Script, `Panel.html` como HTML) y pegar su contenido. En Configuración del
   proyecto, activar "Mostrar el archivo de manifiesto" y pegar `appsscript.json`.
3. Ejecutar `configurar()` y aceptar los permisos. Crea las hojas `Ejecutivos`, `Enlaces`
   y `Fichas`, la carpeta raíz en Drive y da de alta a quien la ejecuta.
4. En la hoja `Ejecutivos`, agregar una fila por ejecutivo: correo de la organización,
   nombre y `SI` en `Activo`. La columna `Carpeta (ID)` la llena el panel.
5. Cada ejecutivo, una sola vez, en su panel: crea una carpeta en su Drive, la comparte como
   **Editor** con la cuenta que opera el servicio (el panel muestra cuál) y pega su enlace en
   "Mi carpeta en Drive". El servicio comprueba que la carpeta es suya y que puede escribir en ella.

**2. Dos despliegues del mismo código** (Implementar > Nueva implementación > Aplicación web)

| Despliegue | Ejecutar como | Quién tiene acceso | Para qué |
| --- | --- | --- | --- |
| Clientes | Yo | Cualquier persona | El formulario consulta y envía aquí. Esta dirección va en `ENDPOINT`. |
| Ejecutivos | Yo | Cualquier usuario de la organización | Panel donde se generan los enlaces. Se comparte esta dirección con los ejecutivos. |

**3. Conectar y publicar**

1. Pegar la dirección `/exec` del despliegue **Clientes** en `ENDPOINT` (inicio del `<script>` de `index.html`).
2. Publicar `index.html` y `logo.png` juntos en un hosting estático (GitHub Pages, Cloudflare Pages, Netlify, el sitio de la empresa).
3. En Configuración del proyecto > Propiedades del script, crear `URL_FORMULARIO` con la dirección pública de `index.html`.
   Opcional: `NOTIFICAR_A` (copia de cada firma a un correo) y `DIAS_VIGENCIA`.

**4. Probar de punta a punta**

Ejecutar `autoprueba()`: crea un enlace, simula la firma con datos de ejemplo, comprueba
que un segundo intento se rechaza y deja el documento firmado y su PDF en Drive. Revisar
`Firmadas` (en la carpeta del ejecutivo que ejecutó la prueba) y borrar después la ficha de prueba (filas de
`Enlaces` y `Fichas` y los archivos).

## Cambios posteriores

- **Agregar o renombrar un campo:** se edita `index.html`. La hoja crea la columna nueva con la etiqueta del formulario. Para que aparezca en el documento firmado hay que agregarlo también en `armarDocumentoFirmado_` (`Documento.gs`).
- **Cambiar el código del receptor:** Implementar > Administrar implementaciones > editar > Nueva versión, en **ambos** despliegues. Las direcciones no cambian.
- **Un ejecutivo cambia de carpeta:** conecta la nueva desde el panel; las fichas anteriores se quedan donde estaban.
- **Dar de baja a un ejecutivo:** poner `NO` en `Activo`. Sus enlaces pendientes siguen vigentes hasta que venzan o se cancelen.
- **Cambiar el logotipo:** reemplazar `logo.png` y regenerar `Logo.gs` con su base64.
- **Probar el formulario sin publicar:** `python3 -m http.server` dentro de esta carpeta y abrir `http://127.0.0.1:8000/index.html` (con `ENDPOINT` vacío funciona en modo de prueba).

## Privacidad

Las fichas viven en la hoja y en las carpetas de Drive de la cuenta que implementó el
receptor, más la copia que cada ejecutivo ve en su propia carpeta (los archivos creados ahí
siguen siendo de la cuenta del servicio, que conserva el control del histórico). Este repositorio es público: en él `ENDPOINT` se queda vacío. Las direcciones
`/exec` reales se pegan sólo en la copia que se publica; la hoja, las carpetas, los
documentos y las firmas nunca se versionan.
