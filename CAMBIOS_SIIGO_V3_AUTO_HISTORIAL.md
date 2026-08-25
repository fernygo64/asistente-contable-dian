# SIIGO V3 — aprendizaje técnico automático desde Historial

## Cambio solicitado
Se retiró de la interfaz el módulo manual **“Parametrización SIIGO por cuenta”**.

La información técnica de SIIGO ya no se diligencia cuenta por cuenta. Al importar un **Auxiliar / Movimiento Contable de SIIGO Pyme**, el aplicativo inspecciona automáticamente cada fila y conserva la evidencia histórica necesaria para exportar movimientos nuevos.

## Qué aprende automáticamente
Por cada fila histórica SIIGO se conservan, cuando existen:

- cuenta contable;
- NIT observado;
- tipo de comprobante;
- código de comprobante;
- número de documento;
- código de vendedor;
- código de ciudad;
- código de zona;
- centro de costo;
- subcentro de costo;
- sucursal;
- fecha del documento.

Las cuentas que el usuario excluye del aprendizaje de **clasificación contable** (caja, bancos, IVA, proveedores, retenciones) se siguen excluyendo de la sugerencia de gasto/ingreso, pero **sus filas sí se conservan para el aprendizaje técnico SIIGO**.

Ejemplo: una fila histórica de `1105050000` con NIT `0` permite aprender que esa cuenta debe exportarse sin tercero, sin convertir Caja en una cuenta sugerida de gasto.

## Prioridad de búsqueda al exportar
Para cada movimiento nuevo, el exportador busca evidencia en este orden:

1. cuenta + NIT + tipo/código de comprobante;
2. cuenta + NIT;
3. cuenta + tipo/código;
4. NIT + tipo/código;
5. cuenta;
6. NIT;
7. defaults técnicos ya conocidos del formato.

Dentro del nivel más específico se usa el valor histórico más frecuente; en empates prevalece la observación más reciente.

## Manejo de tercero
El sistema no copia el NIT de un proveedor viejo. Aprende el comportamiento de la **cuenta**:

- si históricamente la cuenta usa terceros, coloca el NIT del documento actual;
- si históricamente la cuenta sale con `0`, coloca el valor técnico observado (normalmente `0`).

Los `tercero_nit_override` explícitos de movimientos como nómina conservan prioridad.

## Compatibilidad
- World Office no fue modificado.
- La tabla manual creada en V2 no se elimina de la base de datos para evitar una migración destructiva, pero ya no aparece en la interfaz y el historial automático tiene prioridad.
- Si una empresa ya había guardado parámetros manuales en V2, solo funcionan como respaldo silencioso cuando no existe evidencia histórica.
- Se conserva el manejo de Tipo/Código/Consecutivo SIIGO por tipo documental.

## Migración
Nueva revisión Alembic:

`e5b7a6c41022_historial_tecnico_siigo_automatico.py`

Crea la tabla `historial_tecnico_siigo`. Es una migración aditiva; no borra información existente.

## Importante para históricos ya cargados antes de V3
Las importaciones anteriores guardaban la cuenta, NIT, fecha, concepto, etc., pero **no almacenaban vendedor/ciudad/zona/centro/subcentro/sucursal**. Por eso esos campos no pueden reconstruirse retroactivamente solo desde la base de datos.

Después de desplegar V3, para aprovechar el aprendizaje técnico automático con históricos antiguos, basta con volver a subir el archivo de **Movimiento Contable SIIGO**. Desde ese momento sus filas técnicas quedan aprendidas automáticamente.

## Pruebas
- Suite completa: **257/257** pruebas aprobadas.
- Prueba específica de cuenta + NIT + tipo/código: aprobada.
- Prueba de cuenta excluida de clasificación pero conservada para aprendizaje técnico: aprobada.
- Frontend: confirma que la parametrización manual ya no está visible.
- `para_cargar.xlsx` real: 26/26 filas técnicas detectadas; `1105050000` se infiere con NIT 0 y `5195250000` con NIT real y ciudad 1.
- Migración desde instalación nueva hasta `e5b7a6c41022`: aprobada.
- Migración desde la versión V2 (`d4c9e8a77101`) conservando una empresa preexistente: aprobada.
