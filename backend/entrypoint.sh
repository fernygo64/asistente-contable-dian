#!/bin/sh
# Se ejecuta cada vez que arranca el contenedor en el hosting.
# 1) Aplica las migraciones de Alembic contra la base de datos real
#    (así el esquema siempre queda al día sin pasos manuales).
# 2) Levanta el servidor en el puerto que el hosting indique con la
#    variable de entorno PORT (Render, Railway, etc. la asignan
#    automáticamente; localmente por defecto usa 8000).
set -e

echo "Aplicando migraciones de base de datos..."
alembic upgrade head

echo "Iniciando servidor en el puerto ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
