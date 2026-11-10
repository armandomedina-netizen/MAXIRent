/* Prueba del flujo completo del receptor contra servicios de Google simulados.
   Uso: node apps-script/test/flujo.test.cjs  (sólo Node, sin dependencias). */
const vm=require('vm'),fs=require('fs'),assert=require('assert');
const dir=require('path').join(__dirname,'..')+'/';
const code=['Code.gs','Enlaces.gs','Documento.gs','Setup.gs','Logo.gs'].map(f=>fs.readFileSync(dir+f,'utf8')).join('\n');

/* ---------- mocks ---------- */
const state={email:'',props:{},mails:[],calls:{},failDocs:false,nextId:1};
const log=(k)=>{state.calls[k]=(state.calls[k]||0)+1};
// Hojas
function mkSheet(name){const g=[];const sh={name,grid:g,
  getLastRow:()=>g.length,getLastColumn:()=>g.reduce((m,r)=>Math.max(m,(r||[]).length),0),setFrozenRows(){},
  getRange(r,c,nr=1,nc=1){const R={
    setValue(v){g[r-1]=g[r-1]||[];g[r-1][c-1]=v;return R},setNumberFormat(){return R},setNumberFormats(){return R},
    setFontWeight(){return R},setBackground(){return R},setFontColor(){return R},setWrap(){return R},
    setValues(v){v.forEach((row,i)=>{g[r-1+i]=g[r-1+i]||[];row.forEach((x,j)=>g[r-1+i][c-1+j]=x)});return R},
    getValues(){return Array.from({length:nr},(_,i)=>Array.from({length:nc},(_,j)=>((g[r-1+i]||[])[c-1+j])??''))}};return R}};return sh}
const sheets={};
// Drive
const files={},folders={};
function mkFolder(name,parent){const id='fld'+String(state.nextId++).padStart(30,'0');const f={id,name,parent,kids:[],files:[],viewers:[],ownerEmail:'owner@example.test',noAccess:false,getOwner:()=>({getEmail:()=>f.ownerEmail}),
  getId:()=>id,getUrl:()=>'https://drive/folders/'+id,
  getFoldersByName(n){const m=f.kids.filter(k=>k.name===n);let i=0;return{hasNext:()=>i<m.length,next:()=>m[i++]}},
  createFolder(n){return mkFolder(n,f)},addViewer(e){f.viewers.push(e)},
  createFile(b){return mkFile(b.name,f,b)}};folders[id]=f;if(parent)parent.kids.push(f);return f}
function mkFile(name,folder,blob){const id='fil'+String(state.nextId++).padStart(30,'0');const F={id,name,folder,blob,
  getId:()=>id,getUrl:()=>'https://drive/files/'+id,setName(n){F.name=n;return F},
  moveTo(t){F.folder.files=F.folder.files.filter(x=>x!==F);F.folder=t;t.files.push(F);return F},
  getAs(m){return mkBlob(F.name+'.pdf',m)},getBlob:()=>F.blob||mkBlob(F.name,'image/png')};folder&&folder.files.push(F);files[id]=F;return F}
function mkBlob(name,mime,bytes=[1,2,3]){const b={name,mime,getBytes:()=>bytes,setName(n){b.name=n;return b}};return b}
const rootDrive=mkFolder('<mi unidad>',null);
// Documentos
function mkChain(tag,extra={}){return new Proxy(extra,{get(t,k){if(k in t)return t[k];if(typeof k==='symbol'||k==='then')return undefined;
  return (...a)=>{log(tag+'.'+String(k));return proxy}}})}
let proxy;
function mkDoc(name){const id='doc'+(state.nextId++);
  const table=(cells)=>{const rows=cells.length;const t=mkChain('Table',{getNumRows:()=>rows,getRow:()=>({getNumCells:()=>cells[0].length}),
    getCell:(r,c)=>mkChain('Cell',{editAsText:()=>mkChain('Text'),getChild:()=>({asParagraph:()=>mkPar('')}),appendParagraph:()=>mkPar(''),setText(){return this}})});return t};
  const mkPar=(txt)=>mkChain('Par',{getText:()=>txt,getType:()=>'PARAGRAPH',asParagraph(){return this},editAsText:()=>mkChain('Text'),appendInlineImage:()=>mkChain('Img',{getWidth:()=>200,getHeight:()=>80}),removeFromParent(){},setText(){return this}});
  const body=mkChain('Body',{appendTable:(c)=>{log('Body.appendTable');return table(c)},appendParagraph:(t)=>{log('Body.appendParagraph');return mkPar(t)},
    getChild:()=>mkPar(''),getNumChildren:()=>5,editAsText:()=>mkChain('Text'),clear(){log('Body.clear');return body}});
  const d={id,name,body,getBody:()=>body,saveAndClose(){log('Doc.saveAndClose')},getId:()=>id};
  const f=mkFile(name,rootDrive,null);f.id=id;files[id]=f;f.getAs=(m)=>mkBlob(f.name+'.pdf',m);return d}
const ctx={console,JSON,Number,String,Array,Object,Date,Math,isFinite,parseInt,RegExp,Error,
 Session:{getScriptTimeZone:()=> 'America/Mexico_City',getEffectiveUser:()=>({getEmail:()=>'owner@example.test'}),getActiveUser:()=>({getEmail:()=>state.email})},
 LockService:{getScriptLock:()=>({waitLock(){},releaseLock(){}})},
 PropertiesService:{getScriptProperties:()=>({getProperty:k=>state.props[k]??null,setProperty:(k,v)=>{state.props[k]=v}})},
 Utilities:{getUuid:()=>require('crypto').randomUUID(),base64Decode:s=>Buffer.from(s,'base64'),base64Encode:b=>Buffer.from(b).toString('base64'),
  newBlob:(b,t,n)=>mkBlob(n,t,[...b]),
  formatDate:(d,tz,f)=>{const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:tz,hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).formatToParts(d).map(x=>[x.type,x.value]));
   return f.replace('yyyy',p.year).replace('MM',p.month).replace('dd',p.day).replace('HH',p.hour).replace('mm',p.minute).replace('ss',p.second).replace(/^d$/,String(+p.day)).replace(/^M$/,String(+p.month)).replace('yyyyMMdd',p.year+p.month+p.day)}},
 SpreadsheetApp:{getActiveSpreadsheet:()=>({getSheetByName:n=>sheets[n]||null,insertSheet:n=>sheets[n]=mkSheet(n),getUrl:()=>'https://sheet'})},
 DriveApp:{createFolder:n=>mkFolder(n,rootDrive),getFolderById:id=>{if(!folders[id]||folders[id].noAccess)throw new Error('no');return folders[id]},getFileById:id=>{if(!files[id])throw new Error('no file');return files[id]}},
 DocumentApp:{ElementType:{PARAGRAPH:'PARAGRAPH'},VerticalAlignment:{CENTER:'C'},
  create:n=>{if(state.failDocs)throw new Error('boom');log('Doc.create');return mkDoc(n)},openById:id=>{if(state.failDocs)throw new Error('boom');if(!files[id])throw new Error('no doc');return files[id].doc||(files[id].doc=Object.assign(mkDoc('x'),{id,getId:()=>id}))}},
 MailApp:{sendEmail:(to,s,b)=>state.mails.push({to,s,b})},
 HtmlService:{createHtmlOutputFromFile:n=>({html:n,setTitle(){return this}})},
 ContentService:{MimeType:{JSON:'json'},createTextOutput:s=>({s,setMimeType(){return this}})}};
proxy=mkChain('X');
// los documentos creados por create() deben reabrirse con openById
const origCreate=ctx.DocumentApp.create;ctx.DocumentApp.create=n=>{const d=origCreate(n);files[d.id].doc=d;return d};
vm.createContext(ctx);vm.runInContext(code,ctx);
const run=(s)=>vm.runInContext(s,ctx);

/* ---------- pruebas ---------- */
const png='data:image/png;base64,'+Buffer.from('png').toString('base64');
function campos(razon='ACME SA de CV'){const c=[];const add=(i,l,v)=>c.push([i,l,v]);
 add('s_nombre','Nombre completo o razón social',razon);add('s_giro','Giro','Transporte');add('s_ciudad','Ciudad','MTY');
 [['principal',['nombre','puesto','tel','mail']],['legal',['nombre','tel','movil','mail']],['supervisor',['nombre','tel','mail']],['cobranza',['nombre','tel','mail']],['pagos',['nombre','tel','mail']]].forEach(([r,fs])=>fs.forEach(f=>add('c_'+r+'_'+f,r+' – '+f,f==='tel'||f==='movil'?'8112345678':f==='mail'?'a@b.com':'Dato')));
 [1,2].forEach(n=>{add('r'+n+'_empresa','R'+n+' – Empresa','Prov '+n);add('r'+n+'_contacto','R'+n+' – Contacto','X');add('r'+n+'_tel','R'+n+' – Tel','8187654321');add('r'+n+'_fact','R'+n+' – Facturación',125000);add('r'+n+'_mail','R'+n+' – Correo','p@q.com')});
 add('f_firmante','Firmante','Ana Cliente');return c}
const payload=(token,over={})=>Object.assign({token,campos:campos(),firmante:'Ana Cliente',firma:png,fechaLlenado:'2026-11-10',tiempoMs:60000,web:''},over);
const post=(p)=>JSON.parse(ctx.doPost({postData:{contents:JSON.stringify(p)}}).s);
const get=(q)=>ctx.doGet({parameter:q});

// 1) instalación
state.email='owner@example.test';run('configurar()');
assert(sheets.Ejecutivos&&sheets.Enlaces&&sheets.Fichas,'hojas');
assert.strictEqual(sheets.Ejecutivos.grid[1][0],'owner@example.test');
// el dueño da de alta a Ana y a Beto (Beto inactivo)
sheets.Ejecutivos.grid.push(['ana@example.test','Ana Pérez','SI']);sheets.Ejecutivos.grid.push(['beto@example.test','Beto Ruiz','NO']);
state.props.URL_FORMULARIO='https://fichas.example.test/index.html';
// 2) ejecutivo autorizado crea enlace
state.email='ana@example.test';
const panel=run('panelInicial()');assert.strictEqual(panel.nombre,'Ana Pérez');
const e1=run("crearEnlace('  Acme   SA  ')");
console.log('enlace:',e1.folio,e1.url.slice(0,60)+'…');
assert(/^FP-\d{8}-001$/.test(e1.folio));assert(/#t=[a-f0-9]{64}$/.test(e1.url));
const token=e1.url.split('#t=')[1];
const pend=Object.values(files).find(f=>f.name.startsWith(e1.folio));
assert.strictEqual(pend.name,e1.folio+' - PENDIENTE DE FIRMA - Acme SA');
assert.strictEqual(pend.folder.name,'Pendientes');assert.strictEqual(pend.folder.parent.name,'Ana Pérez (ana@example.test)');
assert.deepStrictEqual(pend.folder.parent.viewers,['ana@example.test']);
// 3) consulta del cliente
let c=run(`consultarEnlace_('${token}')`);assert(c.ok&&c.ejecutivo==='Ana Pérez'&&c.cliente==='Acme SA');
assert.strictEqual(run("consultarEnlace_('x')").estado,'INVALIDO');
assert.strictEqual(run(`consultarEnlace_('${'a'.repeat(64)}')`).estado,'INVALIDO');
// 4) firma
let r=post(payload(token));console.log('firma:',r);assert.deepStrictEqual(r,{ok:true,folio:e1.folio,documento:true});
const firmado=files[pend.id];
assert.strictEqual(firmado.name,e1.folio+' - FIRMADA - ACME SA de CV - '+/\d{4}-\d{2}-\d{2}/.exec(firmado.name.slice(-10))[0]);
assert.strictEqual(firmado.folder.name,'Firmadas');assert.strictEqual(firmado.folder.parent.name,'Ana Pérez (ana@example.test)');
const pdfs=Object.values(files).filter(f=>f.name.endsWith('.pdf'));
assert.strictEqual(pdfs.length,2);assert(pdfs.map(p=>p.folder.name).sort().join()==='Firmadas,Historial');
const enl=sheets.Enlaces.grid;const hdr=enl[0];const fila=enl[1];
assert.strictEqual(fila[hdr.indexOf('Estado')],'FIRMADA');assert(fila[hdr.indexOf('PDF (enlace)')].includes('drive'));
const fh=sheets.Fichas.grid[0],ff=sheets.Fichas.grid[1];
assert.strictEqual(ff[fh.indexOf('Ejecutivo')],'ana@example.test');assert.strictEqual(JSON.parse(ff[fh.indexOf('Datos (JSON)')]).length,31);
assert(state.mails[0].to==='ana@example.test'&&state.mails[0].s.includes(e1.folio));
console.log('archivo final:',firmado.name);
// 5) el enlace no se reutiliza
r=post(payload(token));assert.strictEqual(r.ok,false);console.log('reuso:',r.mensaje);
assert.strictEqual(run(`consultarEnlace_('${token}')`).estado,'FIRMADA');
// 6) vencimiento
const e2=run("crearEnlace('Vence SA')");const t2=e2.url.split('#t=')[1];
const row2=enl.find(f=>f[0]===t2);row2[hdr.indexOf('Vence')]=new Date(Date.now()-1000).toISOString();
r=run(`consultarEnlace_('${t2}')`);assert.strictEqual(r.estado,'VENCIDA');
assert(Object.values(files).some(f=>f.name===e2.folio+' - VENCIDA - Vence SA'));
assert.strictEqual(post(payload(t2)).ok,false);
// 7) cancelar: sólo el dueño del enlace
const e3=run("crearEnlace('Cancela SA')");
state.email='beto@example.test';assert.throws(()=>run('panelInicial()'),/no está autorizado/);
state.email='owner@example.test';assert.throws(()=>run(`cancelarEnlace('${e3.folio}')`),/No encontré/);
state.email='ana@example.test';run(`cancelarEnlace('${e3.folio}')`);
assert(Object.values(files).some(f=>f.name===e3.folio+' - CANCELADA - Cancela SA'));
assert.strictEqual(post(payload(e3.url.split('#t=')[1])).ok,false);
const lista=run('fichasDe_("ana@example.test")');assert.strictEqual(lista.length,3);assert(!JSON.stringify(lista).match(/[a-f0-9]{64}/),'sin tokens en el panel');
// 8) reglas de validación
const e4=run("crearEnlace('Reglas SA')");const t4=e4.url.split('#t=')[1];
assert.strictEqual(post(payload(t4,{web:'x'})).ok,false);
assert.strictEqual(post(payload(t4,{tiempoMs:3000})).ok,false);
assert.strictEqual(post(payload('zzz')).ok,false);
assert.strictEqual(post(payload(t4,{firma:'data:image/jpeg;base64,AA'})).ok,false);
assert.strictEqual(post(payload(t4,{campos:campos().filter(c=>c[0]!=='s_nombre')})).ok,false);
assert.strictEqual(run(`consultarEnlace_('${t4}')`).ok,true,'los rechazos no queman el enlace');
// 9) falla del documento: los datos se conservan y se puede regenerar
state.failDocs=true;
const e5=(state.failDocs=false,run("crearEnlace('Falla SA')"));const t5=e5.url.split('#t=')[1];state.failDocs=true;
r=post(payload(t5,{campos:campos('FALLA SA')}));console.log('falla doc:',r);assert.deepStrictEqual(r,{ok:true,folio:e5.folio,documento:false});
assert.strictEqual(sheets.Fichas.grid.length,3);
state.failDocs=false;
// firma como archivo en Drive para regenerar
run(`regenerarDocumento('${e5.folio}')`);
assert(Object.values(files).some(f=>f.name.startsWith(e5.folio+' - FIRMADA - FALLA SA')),'regenerado');

// 11) carpeta propia en el Drive del ejecutivo
state.email='ana@example.test';
assert.strictEqual(run('panelInicial()').carpeta.conectada,false);
assert.strictEqual(run('panelInicial()').carpeta.dueno,'owner@example.test');
const suya=mkFolder('Fichas MAXIRent',rootDrive);suya.ownerEmail='ana@example.test';
const ajena=mkFolder('De Beto',rootDrive);ajena.ownerEmail='beto@example.test';
assert.throws(()=>run("conectarCarpeta('hola')"),/Pegue el enlace/);
assert.throws(()=>run(`conectarCarpeta('https://drive.google.com/drive/folders/${'x'.repeat(33)}')`),/No puedo abrir/);
assert.throws(()=>run(`conectarCarpeta('${ajena.id}')`),/debe ser suya/);
const sinPermiso=mkFolder('Sin edición',rootDrive);sinPermiso.ownerEmail='ana@example.test';sinPermiso.createFolder=()=>{throw new Error('sin permiso')};
assert.throws(()=>run(`conectarCarpeta('${sinPermiso.id}')`),/permiso de Editor/);
const est=run(`conectarCarpeta('https://drive.google.com/drive/folders/${suya.id}?usp=sharing')`);
assert(est.conectada&&est.url.includes(suya.id));
const ejRow=sheets.Ejecutivos.grid.find(f=>f[0]==='ana@example.test');assert.strictEqual(ejRow[3],suya.id);
assert.deepStrictEqual(suya.kids.map(k=>k.name).sort(),['Firmadas','Pendientes']);
const e6=run("crearEnlace('Directo SA')");const t6=e6.url.split('#t=')[1];
const pend6=Object.values(files).find(f=>f.name.startsWith(e6.folio));
assert.strictEqual(pend6.folder.parent,suya,'pendiente en su Drive');assert.strictEqual(pend6.folder.name,'Pendientes');
r=post(payload(t6,{campos:campos('DIRECTO SA')}));assert.strictEqual(r.ok,true);
assert.strictEqual(files[pend6.id].folder.parent,suya);assert.strictEqual(files[pend6.id].folder.name,'Firmadas');
assert(files[pend6.id].name.startsWith(e6.folder||e6.folio+' - FIRMADA - DIRECTO SA'));
const pdfs6=Object.values(files).filter(f=>f.name.startsWith(e6.folio)&&f.name.endsWith('.pdf'));
assert.deepStrictEqual(pdfs6.map(p=>p.folder.name+'@'+(p.folder.parent===suya?'suya':'otra')).sort(),['Firmadas@suya','Historial@otra'].sort());
// si deja de compartir la carpeta, el servicio no se detiene: usa la carpeta compartida y el panel avisa
suya.noAccess=true;
const e7=run("crearEnlace('Respaldo SA')");const pend7=Object.values(files).find(f=>f.name.startsWith(e7.folio));
assert.strictEqual(pend7.folder.parent.name,'Ana Pérez (ana@example.test)');
assert.strictEqual(run('panelInicial()').carpeta.perdida,true);
console.log('carpeta propia OK');

// 10) rutas
assert.strictEqual(JSON.parse(get({accion:'consultar',t:token}).s).estado,'FIRMADA');
assert.strictEqual(get({}).html,'Panel');
state.email='';assert.strictEqual(JSON.parse(get({}).s).ok,true);
console.log('TODAS LAS PRUEBAS DEL FLUJO OK');
