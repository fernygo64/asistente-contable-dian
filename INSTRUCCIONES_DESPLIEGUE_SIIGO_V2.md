# Despliegue — SIIGO Pyme V2

## Antes de subir

1. Hacer respaldo de la base PostgreSQL/Neon actual.
2. Conservar las variables de entorno que ya utiliza el proyecto.
3. Subir esta versión completa a GitHub manteniendo la misma estructura del ZIP.

## Migración

La nueva migración es aditiva. El flujo normal del proyecto debe ejecutar:

```bash
alembic upgrade head
```

El `head` esperado es:

`d4c9e8a77101`

No borrar la base, no crear una base nueva y no eliminar plantillas históricas.

## Primera configuración SIIGO

Por cada empresa que use SIIGO Pyme:

1. Revisar Tipo + Código por clase documental.
2. Indicar el último consecutivo realmente usado en SIIGO antes de generar el primer lote nuevo.
3. Revisar “Parametrización SIIGO por cuenta”.
4. Marcar correctamente cuentas que NO manejan tercero y sus valores técnicos.
5. Si la plantilla SIIGO es antigua, usar “Actualizar SIIGO” para crear la versión reprocesada v2. La plantilla histórica no se elimina.

## Prueba recomendada antes de producción masiva

Generar un lote pequeño y validar:

- tipo/código;
- consecutivos;
- 123 columnas;
- S:DS;
- NIT por cuenta;
- descripción;
- débito = crédito;
- carga efectiva en SIIGO Pyme.

La suite automatizada y la comparación estructural no sustituyen la validación final dentro de la instalación real de SIIGO de cada empresa, especialmente para códigos propios como ciudad, vendedor, centros de costo o sucursal.
