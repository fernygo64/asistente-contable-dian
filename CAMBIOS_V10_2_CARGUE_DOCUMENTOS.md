# V10.2 — Corrección del cargue de documentos

- Se conserva toda la lógica V10.1 de cargos, descuentos, propinas, total DIAN, notas crédito/débito y consecutivos internos sin memoria.
- Cuando un XML ya está disponible, el PDF asociado se relaciona como soporte sin ejecutar OCR durante el cargue.
- Si XML y Excel DIAN difieren, el PDF se consulta de forma perezosa usando únicamente texto embebido; el OCR no bloquea la carga.
- El OCR completo queda reservado para documentos PDF que realmente no tengan XML asociado.
- El botón de carga ahora muestra `Procesando…`, se deshabilita temporalmente y evita dobles envíos accidentales.
- No se modifican reglas contables, cuentas ni formatos de exportación.
