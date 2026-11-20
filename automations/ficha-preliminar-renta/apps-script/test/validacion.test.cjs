/* Reglas de validación del formulario (index.html), extraídas entre las marcas @validacion.
   Uso: node apps-script/test/validacion.test.cjs  (sólo Node, sin dependencias). */
const fs=require('fs'),path=require('path'),assert=require('assert');
const html=fs.readFileSync(path.join(__dirname,'..','..','index.html'),'utf8');
const m=html.match(/\/\* @validacion-inicio \*\/([\s\S]*?)\/\* @validacion-fin \*\//);
assert(m,'no se encontraron las marcas @validacion en index.html');
const V=new Function(m[1]+'\nreturn {digits,tel10,fmtTel,telErr,textoErr,mailErr,repetidos};')();

// teléfonos: formatos que sí deben aceptarse y dar 10 dígitos
[['81 1234 5678','8112345678'],['(81) 1234-5678','8112345678'],['+52 81 1234 5678','8112345678'],['52 81 1234 5678','8112345678'],
 ['+52 1 81 1234 5678','8112345678'],['0052 81 1234 5678','8112345678'],['01 81 1234 5678','8112345678'],['044 81 1234 5678','8112345678'],
 ['045 81 1234 5678','8112345678'],['5512345678','5512345678'],['449 123 4567','4491234567']].forEach(([e,d])=>{
  assert.strictEqual(V.tel10(e),d,'tel10 '+e);assert.strictEqual(V.telErr(e),'','debe aceptar '+e)});
// teléfonos que deben rechazarse (los de las capturas de prueba y otros de relleno)
[['52810000000',/Falta un dígito o la lada/],['810000000',/Falta un dígito o la lada/],['5281000000',/52 es el código/],['8100000000',/relleno/],['0000000000',/lada|relleno/],
 ['1234567890',/lada|relleno/],['9999999999',/relleno/],['11 1234 5678',/empezar con/],['81 1234',/10 d/],['81 1234 5678 ext 12',/Sobran/]].forEach(([e,re])=>{
  const r=V.telErr(e);assert(r&&re.test(r),'debe rechazar '+e+' -> '+r)});
assert.strictEqual(V.fmtTel('+52 81 1234 5678'),'81 1234 5678');

// textos: sin puntos ni relleno
['.','..','...','-','--','  . ','1','12','a','x','xxx','aaaa','N/A','n.a.','Ninguno','NO APLICA','Sin datos','???','123'].forEach(t=>assert(V.textoErr(t),'debe rechazar «'+t+'»'));
['Transportes del Norte SA de CV','Juan Pérez','Ñandú Hnos.','Monterrey, N.L.','Jo','Dirección de Compras'].forEach(t=>assert.strictEqual(V.textoErr(t),'','debe aceptar «'+t+'»'));

// correos
['a@b','x@y.com','.a@b.com','a..b@b.com','juan@example.com','na@empresa.com','juan@ejemplo.com','juan perez@mail.com','juan@'].forEach(t=>assert(V.mailErr(t),'debe rechazar '+t));
['juan.perez@empresa.com.mx','ana_1@dominio.mx','Contacto@Empresa.COM'].forEach(t=>assert.strictEqual(V.mailErr(t),'','debe aceptar '+t));

// repetidos entre personas
const P=[{id:'principal',etq:'Contacto principal',nombre:'c_principal_nombre',externo:false,tels:['c_principal_tel'],mail:'c_principal_mail'},
 {id:'legal',etq:'Representante legal',nombre:'c_legal_nombre',externo:false,tels:['c_legal_tel','c_legal_movil'],mail:'c_legal_mail'},
 {id:'pagos',etq:'Contacto de pagos',nombre:'c_pagos_nombre',externo:false,tels:['c_pagos_tel'],mail:'c_pagos_mail'},
 {id:'r1',etq:'Proveedor referencia 1',nombre:'r1_contacto',externo:true,tels:['r1_tel'],mail:'r1_mail'}];
const base=()=>({c_principal_nombre:'Ana Ruiz',c_principal_tel:'81 1111 2222',c_principal_mail:'ana@empresa.mx',
 c_legal_nombre:'Luis Soto',c_legal_tel:'81 3333 4444',c_legal_movil:'81 5555 6666',c_legal_mail:'luis@empresa.mx',
 c_pagos_nombre:'Eva Paz',c_pagos_tel:'81 7777 8888',c_pagos_mail:'eva@empresa.mx',r1_contacto:'Omar Gil',r1_tel:'55 1234 9876',r1_mail:'omar@prov.mx'});
assert.deepStrictEqual(V.repetidos(P,base()),{},'datos distintos: sin avisos');
// mismo teléfono en dos personas distintas (aun escrito distinto o con +52)
let v=base();v.c_pagos_tel='+52 (81) 1111-2222';let r=V.repetidos(P,v);assert(r.c_pagos_tel&&/Contacto principal/.test(r.c_pagos_tel),'teléfono repetido');
// mismo correo (mayúsculas)
v=base();v.c_legal_mail='ANA@empresa.mx';r=V.repetidos(P,v);assert(r.c_legal_mail,'correo repetido');
// la misma persona en dos roles (mismo nombre) sí puede repetir
v=base();v.c_pagos_nombre='ana  RUIZ';v.c_pagos_tel='81 1111 2222';v.c_pagos_mail='ana@empresa.mx';assert.deepStrictEqual(V.repetidos(P,v),{},'misma persona');
// un proveedor no puede usar datos de la empresa, aunque se llame igual
v=base();v.r1_contacto='Ana Ruiz';v.r1_mail='ana@empresa.mx';r=V.repetidos(P,v);assert(r.r1_mail&&/externos/.test(r.r1_mail),'proveedor repite correo de la empresa');
// el teléfono y el móvil de una misma persona pueden coincidir
v=base();v.c_legal_movil='81 3333 4444';assert.deepStrictEqual(V.repetidos(P,v),{},'misma persona, dos teléfonos iguales');
console.log('VALIDACION DEL FORMULARIO OK');
