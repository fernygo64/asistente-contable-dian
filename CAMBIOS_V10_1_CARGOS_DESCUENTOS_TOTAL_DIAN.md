# Asistente Contable DIAN — V10.1

Corrección de conciliación entre componentes del documento electrónico y Total DIAN.

## Cambios
- Lee los `AllowanceCharge` globales del XML UBL y conserva tipo, concepto, valor, base y porcentaje.
- `ChargeIndicator=true` se trata como cargo/recargo; `false` como descuento.
- Los cargos y descuentos se muestran al usuario con su concepto real cuando el XML lo informa.
- El Total DIAN/`PayableAmount` continúa siendo el valor final de control.
- La cuenta principal de gasto/ingreso absorbe el cargo, descuento o ajuste necesario; IVA/INC permanecen separados en sus cuentas cuando correspondan.
- La diferencia matemática se usa como validación. Si los componentes declarados no explican el total final, el documento queda para revisión en vez de adivinar el concepto.
- Antes de exportar se valida no solo Débito = Crédito: ambos lados también deben reproducir el Total DIAN. Una partida antigua balanceada pero distinta del Total DIAN queda bloqueada y debe regenerarse.

## Regresiones verificadas
- Factura con INC y cargo global: el cargo se incorpora y la partida termina exactamente en el Total DIAN.
- Una partida anterior que omite el cargo es bloqueada antes de exportar.
- Los documentos de la prueba de aceptación anterior continúan generando sus mismos totales finales.
- No se incorporaron datos de empresas de prueba como ejemplos ni reglas del aplicativo.
- No requiere migración de base de datos.
