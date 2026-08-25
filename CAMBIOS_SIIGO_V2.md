# Asistente Contable DIAN — SIIGO Pyme V2

Base utilizada: `asistente-contable-dian-desplegable(1).zip` (última entrega indicada por el usuario).

## Qué se corrigió

1. **Tipo, código y consecutivo SIIGO separados**
   - Tipo y código se configuran por empresa y clase documental.
   - El código deja de depender del valor fijo `1` como única posibilidad.

2. **Consecutivos SIIGO persistentes**
   - Se guardan por empresa + tipo + código.
   - La vista previa no consume números.
   - La generación definitiva reserva los números dentro de la transacción.
   - En PostgreSQL se usa bloqueo transaccional para evitar que dos exportaciones concurrentes reciban el mismo consecutivo.
   - Una reexportación conserva el número ya asignado.
   - No se permite reducir manualmente un consecutivo existente porque podría producir duplicados.

3. **Exportación independiente por sistema contable**
   - Se agregó una relación `ExportacionFactura`.
   - Una factura exportada a SIIGO puede seguir pendiente para World Office y viceversa.
   - El estado visual legacy se conserva por compatibilidad, pero ya no es la fuente de verdad para determinar pendientes por destino.

4. **Parametrización técnica SIIGO por cuenta**
   - Tabla separada de `CuentaContable`.
   - Permite indicar si la cuenta maneja tercero y configurar NIT técnico, vendedor, ciudad, zona, centro, subcentro y sucursal.
   - Una cuenta configurada sin tercero puede exportar, por ejemplo, `NIT = 0`, sin alterar el tercero de las demás líneas.

5. **Descripción SIIGO de salida**
   - Puede construirse uniformemente desde la factura al exportar.
   - No obliga a modificar ni regenerar el texto histórico guardado en los movimientos anteriores.

6. **Modelo General SIIGO 123 columnas**
   - Se mantienen literalmente los encabezados de la plantilla.
   - Las plantillas completas SIIGO se reprocesan con las reglas actuales.
   - El bloque S:DS utiliza los defaults técnicos ya verificados (0, N, espacios, fecha/hora, etc.) y no la regla incorrecta “vacío = 0”.

7. **Versionado/reprocesamiento de plantillas SIIGO**
   - Las plantillas históricas quedan en versión 1.
   - Se puede crear una versión SIIGO v2 reprocesada conservando la plantilla original y sus encabezados.

8. **World Office**
   - Se conserva su formato/exportador actual.
   - Las reglas SIIGO de 10 dígitos, S:DS, parametrización de cuenta y consecutivos no se aplican a World Office.
   - El único cambio compartido es el historial de exportación por destino.

## Base de datos

Nueva migración Alembic:

`d4c9e8a77101_siigo_persistencia_exportacion_por_destino.py`

Crea de forma aditiva:

- `configuraciones_comprobante_siigo`
- `consecutivos_siigo`
- `parametrizaciones_cuenta_siigo`
- `exportaciones_facturas`

Y agrega versionado a `plantillas_exportacion`.

La migración fue probada tanto desde una instalación nueva como desde una base que ya tenía empresa, plantilla, factura y exportación histórica.

## Pruebas

Resultado final de la suite:

**255 pruebas aprobadas.**

Prueba adicional con el lote real de referencia del usuario:

- 10 documentos
- 26 movimientos
- 123 columnas
- 123 encabezados idénticos al modelo de referencia
- S:DS: 0 celdas genuinamente vacías
- Débitos: $7.243.535,36
- Créditos: $7.243.535,36
- Diferencia: $0,00
- consecutivos de prueba: 81 a 90
- la vista previa no consumió el consecutivo 81
- cuenta Caja configurada sin tercero: NIT de salida 0

## Archivos principales modificados

- `backend/app/models/models.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/schemas.py`
- `backend/app/services/export_service.py`
- `backend/app/services/siigo_pyme_extendido.py`
- `backend/app/services/siigo_config_service.py` (nuevo)
- `backend/app/api/exportacion.py`
- `backend/app/api/empresas.py`
- `backend/app/api/siigo_config.py` (nuevo)
- `backend/app/main.py`
- `backend/alembic/versions/d4c9e8a77101_siigo_persistencia_exportacion_por_destino.py` (nuevo)
- `frontend/index.html`
- `backend - copia/tests/test_siigo_persistencia_v2.py` (nuevo)
- `backend - copia/tests/test_siigo_modelo_general_v2.py` (nuevo)

`partida_doble_service.py` NO fue modificado.
