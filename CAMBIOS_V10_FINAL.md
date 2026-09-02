# Asistente Contable DIAN — V10 Final

Versión de cierre operativo construida sobre V9.1, conservando la base funcional existente.

Cambios principales:
- Consecutivo interno SIIGO definido por cada exportación, sin memoria entre archivos.
- Clasificación reforzada de factura, nota crédito, nota débito y dirección recibida/emitida desde XML y Excel DIAN.
- XML: evita duplicar impuestos repetidos entre encabezado y líneas.
- Conciliación de total final entre XML, Excel DIAN y PDF, con avisos ante diferencias.
- Descuentos, recargos y redondeos ajustan la línea principal para respetar el total final DIAN, sin inventar cuentas.
- Valores fiscales DIAN bloqueados contra edición manual; clasificación/cuentas/contrapartida siguen siendo corregibles.
- Exportaciones se anulan conservando trazabilidad en vez de borrarse físicamente.
- Se mantienen separados el orden interno de documentos y la DESCRIPCIÓN DE LA SECUENCIA.

No contiene datos, nombres ni reglas hardcodeadas de empresas usadas durante las pruebas de aceptación.
