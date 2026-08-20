"""
Columnas EXTENDIDAS del archivo plano de Siigo Pyme (S en adelante — 105
columnas), verificadas contra un archivo real completo de producción
(RAL ENERGY SAS, 704 filas). El modelo real de Siigo Pyme
("MODELO PARA LA IMPORTACIÓN DE MOVIMIENTO CONTABLE") tiene 123 columnas
en total: A-R son las que el usuario diligencia con cada factura nueva
(comprobante, cuenta, débito/crédito, valor, NIT, etc. — ya cubiertas
por el resto de este proyecto), pero S en adelante DEBEN dejarse con
los mismos valores por defecto que trae el propio archivo de Siigo —
si se dejan vacías, Siigo puede rechazar el archivo o comportarse mal
al importarlo (confirmado: son campos de ancho fijo con ceros o textos
en blanco de una longitud exacta, no cadenas vacías).

11 de esas 105 columnas SÍ traían valores reales variables en el
archivo de referencia (fechas de actualización, cruces con facturas
electrónicas, vencimientos) — para esas se usa el valor que aparece en
la inmensa mayoría de las filas reales (el "sin cruzar todavía", que es
lo correcto para una factura recién generada), nunca se inventa un
cruce o vencimiento que el sistema no conoce. Las columnas de fecha/hora
de actualización del documento (AL, AM) se resuelven aparte, con la
fecha y hora reales del momento en que se genera la exportación.
"""

# título de columna (normalizado tal como aparece en el Excel real de
# Siigo Pyme) -> (origen, valor_fijo) — mismo formato que ya usa
# PlantillaExportacion.columnas_json, source="fijo" ya es soportado.
DEFAULTS_SIIGO_PYME_EXTENDIDO: dict[str, tuple[str, object]] = {
    'NÚMERO DE CHEQUE': ('fijo', '0'),
    'COMPROBANTE ANULADO': ('fijo', 'N'),
    'CÓDIGO DEL MOTIVO DE DEVOLUCIÓN': ('fijo', '0'),
    'FORMA DE PAGO': ('fijo', '0'),
    'VALOR DEL CARGO 1 DE LA SECUENCIA': ('fijo', '0'),
    'VALOR DEL CARGO 2 DE LA SECUENCIA': ('fijo', '0'),
    'VALOR DEL DESCUENTO 1 DE LA SECUENCIA': ('fijo', '0'),
    'VALOR DEL DESCUENTO 2 DE LA SECUENCIA': ('fijo', '0'),
    'VALOR DEL DESCUENTO 3 DE LA SECUENCIA': ('fijo', '0'),
    'FACTURA ELECTRÓNICA A DEBITAR/ACREDITAR': ('fijo', '     '),
    'NÚMERO DE FACTURA ELECTRÓNICA A DEBITAR/ACREDITAR': ('fijo', '0'),
    'PREFIJO DE ORDER REFERENCE': ('fijo', '          '),
    'CONSECUTIVO DE ORDER REFERENCE': ('fijo', '                                        '),
    'PREFIJO ORDEN DE ENTREGA': ('fijo', '          '),
    'NÚMERO ORDEN DE ENTREGA': ('fijo', '                                        '),
    'AÑO FECHA DE ORDEN DE ENTREGA': ('fijo', '0'),
    'MES FECHA DE ORDEN DE ENTREGA': ('fijo', '0'),
    'DÍA FECHA DE ORDEN DE ENTREGA': ('fijo', '0'),
    'INGRESOS PARA TERCEROS': ('fijo', ' '),
    'FECHA ACTUALIZACIÓN DEL DOCUMENTO': ('fecha_generacion', None),
    'HORA DE ACTUALIZACIÓN DEL DOCUMENTO': ('hora_generacion', None),
    'PREFIJO ORDEN DE ENTREGA2': ('fijo', '          '),
    'NÚMERO ORDEN DE ENTREGA2': ('fijo', '                                        '),
    'AÑO FECHA DE ORDEN DE ENTREGA2': ('fijo', '0'),
    'MES FECHA DE ORDEN DE ENTREGA2': ('fijo', '0'),
    'DÍA FECHA DE ORDEN DE ENTREGA2': ('fijo', '0'),
    'PREFIJO ORDEN DE ENTREGA3': ('fijo', '          '),
    'NÚMERO ORDEN DE ENTREGA3': ('fijo', '                                        '),
    'AÑO FECHA DE ORDEN DE ENTREGA3': ('fijo', '0'),
    'MES FECHA DE ORDEN DE ENTREGA3': ('fijo', '0'),
    'DÍA FECHA DE ORDEN DE ENTREGA3': ('fijo', '0'),
    'PREFIJO ORDEN DE ENTREGA4': ('fijo', '          '),
    'NÚMERO ORDEN DE ENTREGA4': ('fijo', '                                        '),
    'AÑO FECHA DE ORDEN DE ENTREGA4': ('fijo', '0'),
    'MES FECHA DE ORDEN DE ENTREGA4': ('fijo', '0'),
    'DÍA FECHA DE ORDEN DE ENTREGA4': ('fijo', '0'),
    'PREFIJO ORDEN DE ENTREGA5': ('fijo', '          '),
    'NÚMERO ORDEN DE ENTREGA5': ('fijo', '                                        '),
    'AÑO FECHA DE ORDEN DE ENTREGA5': ('fijo', '0'),
    'MES FECHA DE ORDEN DE ENTREGA5': ('fijo', '0'),
    'DÍA FECHA DE ORDEN DE ENTREGA5': ('fijo', '0'),
    'PORCENTAJE ALIMENTOS ULTRAPROCESADOS': ('fijo', '0'),
    'VALOR ALIMENTOS ULTRAPROCESADOS': ('fijo', '0'),
    'VALOR BEBIDAS AZUCARADAS': ('fijo', '0'),
    'AÑO EXPEDICIÓN FACTURA': ('fijo', '    '),
    'MES EXPEDICIÓN FACTURA': ('fijo', '  '),
    'DÍA EXPEDICIÓN FACTURA': ('fijo', '  '),
    'RUTA DOCUMENTO': ('fijo', '                                                                                                    '),
    'PORCENTAJE DEL IVA DE LA SECUENCIA': ('fijo', '0'),
    'VALOR DE IVA DE LA SECUENCIA': ('fijo', '0'),
    'BASE DE RETENCIÓN': ('fijo', '                   '),
    'BASE PARA CUENTAS MARCADAS COMO RETEIVA': ('fijo', '0'),
    'SECUENCIA GRAVADA O EXCENTA': ('fijo', 'N'),
    'PORCENTAJE AIU': ('fijo', '           '),
    'BASE IVA AIU': ('fijo', '                '),
    'VALOR TOTAL IMPOCONSUMO DE LA SECUENCIA': ('fijo', '0'),
    'IVA COMO MAYOR VALOR DE LA COMPRA': ('fijo', ' '),
    'LÍNEA PRODUCTO': ('fijo', '   '),
    'GRUPO PRODUCTO': ('fijo', '    '),
    'CÓDIGO PRODUCTO': ('fijo', '      '),
    'CANTIDAD': ('fijo', '0'),
    'CANTIDAD DOS': ('fijo', '0'),
    'CÓDIGO DE LA BODEGA': ('fijo', '0'),
    'CÓDIGO DE LA UBICACIÓN': ('fijo', '0'),
    'CANTIDAD DE FACTOR DE CONVERSIÓN': ('fijo', '0'),
    'OPERADOR DE FACTOR DE CONVERSIÓN': ('fijo', '0'),
    'VALOR DEL FACTOR DE CONVERSIÓN': ('fijo', '0'),
    'GRUPO ACTIVOS': ('fijo', '    '),
    'CÓDIGO ACTIVO': ('fijo', '     '),
    'ADICIÓN O MEJORA': ('fijo', ' '),
    'VECES ADICIONALES A DEPRECIAR POR ADICIÓN O MEJORA': ('fijo', '0'),
    'VECES A DEPRECIAR NIIF': ('fijo', '0'),
    'NÚMERO DEL DOCUMENTO DEL PROVEEDOR': ('fijo', '0'),
    'PREFIJO DEL DOCUMENTO DEL PROVEEDOR': ('fijo', '          '),
    'AÑO DOCUMENTO DEL PROVEEDOR': ('fijo', '    '),
    'MES DOCUMENTO DEL PROVEEDOR': ('fijo', '  '),
    'DÍA DOCUMENTO DEL PROVEEDOR': ('fijo', '  '),
    'TIPO DOCUMENTO DE PEDIDO': ('fijo', ' '),
    'CÓDIGO COMPROBANTE DE PEDIDO': ('fijo', '0'),
    'NÚMERO DE COMPROBANTE PEDIDO': ('fijo', '0'),
    'SECUENCIA DE PEDIDO': ('fijo', '0'),
    'TIPO DE MONEDA ELABORACIÓN': ('fijo', '0'),
    'TIPO Y COMPROBANTE CRUCE': ('fijo', '     '),
    'NÚMERO DE DOCUMENTO CRUCE': ('fijo', '0'),
    'NÚMERO DE VENCIMIENTO': ('fijo', '0'),
    'AÑO VENCIMIENTO DE DOCUMENTO CRUCE': ('fijo', '    '),
    'MES VENCIMIENTO DE DOCUMENTO CRUCE': ('fijo', '  '),
    'DÍA VENCIMIENTO DE DOCUMENTO CRUCE': ('fijo', '  '),
    'NÚMERO DE CAJA ASOCIADA AL COMPROBANTE': ('fijo', '0'),
    'DESCRIPCIÓN DE COMENTARIOS': ('fijo', '                                                                                                                                                                                                                                    '),
    'DESCRIPCIÓN LARGA': ('fijo', '                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        '),
    'INCONTERM': ('fijo', '          '),
    'DESCRIPCIÓN EXPORTACIÓN': ('fijo', '                                                  '),
    'MEDIO DE TRANSPORTE': ('fijo', '                                                  '),
    'PAÍS DE ORIGEN': ('fijo', '0'),
    'CIUDAD DE ORIGEN': ('fijo', '0'),
    'PAIS DESTINO': ('fijo', '0'),
    'CIUDAD DESTINO': ('fijo', '0'),
    'PESO NETO': ('fijo', '0'),
    'PESO BRUTO': ('fijo', '0'),
    'UNIDAD DE MEDIDA NETO': ('fijo', '          '),
    'UNIDAD DE MEDIDA BRUTO': ('fijo', '          '),
    'CONCEPTO FACTURACION EN BLOQUE': ('fijo', '0'),
    'DATOS ESTABLEC. (L=LOCAL O=OFICINA)': ('fijo', ' '),
    'NÚMERO ESTABLECIMIENTO': ('fijo', '0'),
}

# Columnas del rango A:R (las que sí trae cada factura nueva) que
# también se pudieron reconocer con certeza contra el archivo real:
# CÓDIGO DEL VENDEDOR, SUBCENTRO DE COSTO y SUCURSAL fueron siempre el
# mismo valor en las 194 filas de referencia; SECUENCIA y CENTRO DE
# COSTO ya se pueden calcular con datos que el sistema sí rastrea
# (posición de la línea dentro del comprobante, y el centro de costo
# real asignado a esa línea). Deliberadamente NO se incluyen aquí
# "CÓDIGO COMPROBANTE", "CÓDIGO DE LA CIUDAD" ni "CÓDIGO DE LA ZONA" —
# variaron según el tercero en el archivo real y el sistema no tiene
# de dónde sacar ese dato con certeza; inventarlo sería un error
# contable/tributario silencioso.
DEFAULTS_SIIGO_PYME_A_R: dict[str, tuple[str, object]] = {
    'CÓDIGO DEL VENDEDOR': ('fijo', '1'),
    'SUBCENTRO DE COSTO': ('fijo', '0'),
    'SUCURSAL': ('fijo', '0'),
    'SECUENCIA': ('secuencia_linea', None),
    'CENTRO DE COSTO': ('centro_costo', None),
}
