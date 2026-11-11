# Guía paso a paso: poner en marcha la Ficha preliminar de renta

Esta guía lleva de cero a un formulario funcionando. Cada código lleva un nombre; el mismo nombre aparece en la primera línea de cada archivo, en el editor de Apps Script y en la carpeta `apps-script/` (o en la carpeta de descarga `ficha-preliminar-apps-script`).

**Quién hace qué:** todo lo de Google lo hace la persona que será dueña de los archivos (de preferencia una cuenta de la empresa, no personal). Lo de GitHub lo hace quien administra el repositorio.

## Los códigos y sus nombres

| # | Nombre del archivo en Apps Script | Tipo | Qué hace |
| --- | --- | --- | --- |
| 1 | `1-Recepcion` | Script | Recibe la firma del cliente, valida y avisa al ejecutivo. |
| 2 | `2-Enlaces` | Script | Da de alta ejecutivos y crea, consulta y cancela enlaces de firma. |
| 3 | `3-Documento` | Script | Crea las carpetas, el documento pendiente y el firmado (con su PDF). |
| 4 | `4-Instalacion` | Script | Instalación (`configurar`), prueba (`autoprueba`) y reparación (`regenerarDocumento`). |
| 5 | `5-Logotipo` | Script | Logotipo MAXIRent para el documento. No se modifica. |
| 6 | `Panel` | HTML | Pantalla del ejecutivo. **Debe llamarse exactamente `Panel`.** |
| 7 | `appsscript.json` | Manifiesto | Zona horaria y permisos del servicio. |

El formulario del cliente (`index.html` y `logo.png`) no va en Apps Script: se publica en GitHub Pages (Parte 8).

---

## Parte 1. Crear la hoja de Google

1. Entre a Google Drive con la cuenta dueña del servicio.
2. Nuevo > Hoja de cálculo de Google. Nómbrela **Fichas preliminares de renta**.
3. Menú **Extensiones > Apps Script**. Se abre el editor en otra pestaña.
4. Arriba a la izquierda, donde dice "Proyecto sin título", escriba **Ficha preliminar de renta**.

## Parte 2. Pegar cada código

El editor trae un archivo llamado `Código.gs` con una función `myFunction`. Se reutiliza como el primer código.

**Cómo crear un archivo nuevo:** junto a "Archivos" pulse el **+** y elija *Secuencia de comandos* (Script) o *HTML*. Escriba el nombre **sin** la extensión; el editor agrega `.gs` o `.html`.
**Cómo cambiar un nombre:** pase el cursor sobre el archivo, pulse **⋮** > Cambiar nombre.
**Cómo pegar:** abra el archivo, seleccione todo (Cmd/Ctrl + A), borre y pegue el contenido nuevo. Guarde con Cmd/Ctrl + S.

### Código 1 · `1-Recepcion`
1. Cambie el nombre de `Código.gs` a `1-Recepcion`.
2. Borre todo y pegue el contenido de `1-Recepcion.gs`.
3. Guarde.

### Código 2 · `2-Enlaces`
1. **+** > Secuencia de comandos > nombre `2-Enlaces`.
2. Si el archivo trae contenido de ejemplo, bórrelo; pegue `2-Enlaces.gs`.
3. Guarde.

### Código 3 · `3-Documento`
1. **+** > Secuencia de comandos > nombre `3-Documento`.
2. Pegue `3-Documento.gs` y guarde.

### Código 4 · `4-Instalacion`
1. **+** > Secuencia de comandos > nombre `4-Instalacion`.
2. Pegue `4-Instalacion.gs` y guarde.

### Código 5 · `5-Logotipo`
1. **+** > Secuencia de comandos > nombre `5-Logotipo`.
2. Pegue `5-Logotipo.gs` (es una sola línea muy larga; es normal) y guarde.

### Código 6 · `Panel`
1. **+** > HTML > nombre exactamente `Panel`.
2. Borre el contenido de ejemplo y pegue `Panel.html`. Guarde.

### Código 7 · `appsscript.json`
1. Engrane **Configuración del proyecto** (columna izquierda).
2. Active **Mostrar el archivo de manifiesto "appsscript.json" en el editor**.
3. Vuelva a **Editor**, abra `appsscript.json`, borre todo y pegue el contenido de `appsscript.json`. Guarde.

**Cómo saber que quedó bien:** en la columna de archivos deben verse `1-Recepcion`, `2-Enlaces`, `3-Documento`, `4-Instalacion`, `5-Logotipo`, `Panel` y `appsscript.json`. Si guarda y aparece un subrayado rojo o un mensaje de error de sintaxis, falta una parte del código o se pegó en el archivo equivocado.

## Parte 3. Propiedad con la dirección del formulario

1. Engrane **Configuración del proyecto**.
2. Baje a **Propiedades de la secuencia de comandos** > **Agregar propiedad de la secuencia de comandos**.
3. Propiedad: `URL_FORMULARIO`. Valor: `https://armandomedina-netizen.github.io/MAXIRent/` (debe terminar en `/`). Guarde.

Propiedades opcionales con el mismo procedimiento:

| Propiedad | Para qué | Ejemplo |
| --- | --- | --- |
| `NOTIFICAR_A` | Recibir copia del aviso de cada firma. | `validaciones@su-dominio.com` |
| `DIAS_VIGENCIA` | Días de vida de cada enlace (1 a 90; por omisión 7). | `10` |

## Parte 4. Instalar: ejecutar `configurar()`

1. En el editor, abra el archivo `4-Instalacion`.
2. En el selector de funciones (arriba, junto a Ejecutar) elija **configurar** y pulse **Ejecutar**.
3. Google pide permisos: **Revisar permisos** > elija su cuenta > si aparece "Google no ha verificado esta app", pulse **Configuración avanzada** > **Ir a Ficha preliminar de renta (no seguro)** > **Permitir**. Es normal: es su propio código.
4. En el *Registro de ejecución* debe aparecer algo como: `Listo. Carpeta raíz en Drive: https://drive.google.com/...`.

**Resultado:** en la hoja aparecen las pestañas `Ejecutivos`, `Enlaces` y `Fichas`; en su Drive, la carpeta raíz del servicio; y en `Ejecutivos` hay una fila con su correo.

## Parte 5. Probar de punta a punta: `autoprueba()`

1. En `4-Instalacion` elija la función **autoprueba** y pulse **Ejecutar**.
2. Revise el Registro de ejecución. Debe mostrar, en orden:
   - `Enlace creado: FP-AAAAMMDD-001 ...`
   - `Resultado: {"ok":true,"folio":"FP-...","documento":true}`
   - `Segundo intento con el mismo enlace (debe rechazarse): ...`
   - `Documento firmado: <enlace>` y `PDF firmado: <enlace>`.
3. En Drive abra la carpeta raíz > `Ejecutivos` > su carpeta > `Firmadas`. Debe haber un documento `FP-... - FIRMADA - Cliente de ejemplo SA de CV - AAAA-MM-DD` y su PDF. En `Historial` está otra copia del PDF.
4. Revise que le haya llegado el correo de aviso de firma.
5. **Limpieza:** borre de las pestañas `Enlaces` y `Fichas` las filas de la prueba y los archivos de prueba en Drive.

Si algo falla, copie el mensaje de error del registro y envíelo a quien mantiene el código; esta es la parte que depende de Google y es donde puede haber ajustes.

## Parte 6. Los dos despliegues

El mismo código se publica dos veces, con permisos distintos. Para cada uno: **Implementar > Nueva implementación**, engrane > **Aplicación web**.

| Despliegue | Descripción | Ejecutar como | Quién tiene acceso | Para qué |
| --- | --- | --- | --- | --- |
| **Clientes** | `Clientes` | Yo | Cualquier persona | Lo usa el formulario del cliente. |
| **Ejecutivos** | `Ejecutivos` | Yo | Cualquier usuario de la organización | Es el panel que usan los ejecutivos. |

1. Cree primero **Clientes**. Al terminar, copie la **URL de la aplicación web** (termina en `/exec`) y guárdela: es la dirección que va en `FICHA_ENDPOINT` (Parte 8).
2. Cree **Ejecutivos** con el mismo procedimiento y copie también su URL `/exec`. Es la que se comparte con los ejecutivos.
3. Abra la URL de **Ejecutivos** con su cuenta: debe mostrar su nombre y correo. Si dice "Sin acceso", su correo no está en `Ejecutivos` con `SI`.

## Parte 7. Alta de ejecutivos y conexión de su carpeta

**En la hoja `Ejecutivos`** (quien administra el servicio), agregue una fila por persona:

| Correo | Nombre | Activo | Carpeta (ID) |
| --- | --- | --- | --- |
| correo de la organización | nombre completo | `SI` | *(la llena el panel)* |

**Cada ejecutivo, una sola vez, en su panel:**
1. En su Drive, crear una carpeta, por ejemplo **Fichas MAXIRent**.
2. Compartirla como **Editor** con la cuenta que el panel indica en "Mi carpeta en Drive".
3. Pegar el enlace de la carpeta en el panel y pulsar **Conectar**.

Dentro se crean `Pendientes` y `Firmadas`. Mientras no la conecte, sus fichas se guardan en una carpeta compartida con él en sólo lectura; el servicio no se detiene.

## Parte 8. Publicar el formulario en GitHub Pages

*Requiere que el PR de la ficha esté integrado a `main` (lo autoriza quien administra el repositorio).*

1. En GitHub: **Settings > Pages > Source: GitHub Actions** (una sola vez).
2. **Settings > Secrets and variables > Actions > pestaña Variables > New repository variable**:
   - Nombre: `FICHA_ENDPOINT`
   - Valor: la URL `/exec` del despliegue **Clientes** (Parte 6). Debe verse como `https://script.google.com/macros/s/<ID>/exec`.
3. **Actions > "Ficha preliminar - publicar formulario" > Run workflow.** Debe terminar en verde y mostrar `https://armandomedina-netizen.github.io/MAXIRent/`.

## Parte 9. Prueba con un cliente de ejemplo

1. Abra el panel (URL del despliegue **Ejecutivos**), escriba un cliente de prueba y pulse **Generar enlace**.
2. Abra el enlace en un celular. Debe verse la ficha con el nombre precargado y el mensaje "Ficha FP-... preparada por ...".
3. Llene, firme con el dedo y pulse **Guardar y descargar**. Debe ocurrir:
   - Se descarga un PDF con la ficha (revisar la carpeta de Descargas).
   - Aparece la pantalla "Ficha recibida" con el folio.
   - El documento `FIRMADA` llega a la carpeta del ejecutivo y le llega el correo de aviso.
   - Abrir el mismo enlace otra vez muestra "Esta ficha ya fue firmada".

## Parte 10. Cambios posteriores

- **Cambió un código:** pegue el nuevo contenido en el archivo correspondiente y luego **Implementar > Administrar implementaciones > (lápiz) > Versión: Nueva versión > Implementar**, en **los dos** despliegues. Las URL no cambian.
- **Cambió `index.html`:** se publica solo al integrarse a `main`.
- **Dar de baja a un ejecutivo:** poner `NO` en `Activo`.
- **Una ficha firmada no generó documento:** ejecute `regenerarDocumento('FP-AAAAMMDD-NNN')` desde `4-Instalacion`; los datos ya están en la hoja `Fichas`.

## Parte 11. Si algo no funciona

| Qué se ve | Causa probable | Qué hacer |
| --- | --- | --- |
| "Falta configurar la dirección del formulario (propiedad URL_FORMULARIO)" | No existe la propiedad. | Parte 3. |
| "Su correo no está autorizado para generar fichas" | El correo no está en `Ejecutivos` o `Activo` es `NO`. | Agregarlo con `SI`. |
| El panel dice "Sin acceso" | El despliegue **Ejecutivos** no es "Cualquier usuario de la organización" o se abrió con otra cuenta. | Revisar Parte 6. |
| El formulario dice "Modo de prueba" | `FICHA_ENDPOINT` vacío o el workflow no se ejecutó. | Parte 8, pasos 2 y 3. |
| "No puedo abrir esa carpeta" al conectar | La carpeta no está compartida como Editor con la cuenta del servicio. | Compartirla y reintentar. |
| "La carpeta debe ser suya" | La carpeta pertenece a otra persona. | Crearla desde la cuenta del ejecutivo. |
| "Este enlace no es válido" / "ya fue firmada" / "venció" | Enlace usado, vencido o cancelado. | Generar uno nuevo en el panel. |
| Cambié el código y no se nota | Los despliegues siguen en la versión vieja. | Parte 10, primera viñeta. |
