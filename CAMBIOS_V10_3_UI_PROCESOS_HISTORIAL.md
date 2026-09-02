# Asistente Contable DIAN — V10.3

Base: V10.2 (cargue rápido).

## Cambios

1. Retroalimentación visual en procesos importantes
   - Los botones importantes muestran el proceso que están ejecutando: Guardando…, Importando…, Generando…, Validando…, Contabilizando…, Eliminando…, etc.
   - El botón queda temporalmente deshabilitado para evitar doble envío.
   - Se muestra además un indicador global discreto en la parte superior derecha mientras el proceso está en curso.
   - Se mantienen los mensajes de éxito/error que ya existían.
   - El flujo especial de Cargar y relacionar de V10.2 se conserva intacto.

2. Historial de exportaciones
   - El botón visible cambia de “Anular” a “Eliminar”.
   - Al eliminar, la exportación desaparece del historial operativo.
   - La fila original, sus relaciones y la evidencia técnica NO se destruyen.
   - La acción queda registrada en Auditoría como `exportacion_eliminada_historial`.
   - Las exportaciones antiguas marcadas como `[ANULADA]` también dejan de ocupar espacio en el historial operativo.

## No se modificó

- Procesamiento DIAN XML/PDF/Excel.
- Cargue rápido V10.2.
- Cargos, descuentos, propinas y Total DIAN.
- Partida doble.
- Clasificación Factura / Nota Crédito / Nota Débito.
- SIIGO / World Office.
- Consecutivos internos sin memoria.
- Cuentas, aprendizaje e historial contable.

## Verificaciones

- JavaScript: sintaxis OK.
- Backend Python: compilación OK.
- Migraciones Alembic desde base vacía: OK.
- `/salud`: 200.
- `/app/`: 200.
- Carga real de prueba 2 ZIP + Excel DIAN: 201, ~0,04 s en prueba local.
- Eliminar exportación: desaparece del historial visible y la evidencia permanece en base de datos.
- Auditoría de eliminación de exportación: OK.
