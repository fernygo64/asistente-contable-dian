# Subir SIIGO V3 a GitHub / Render

1. Haz respaldo de la base PostgreSQL/Neon antes del despliegue.
2. Descarga y descomprime `GITHUB_1_APLICATIVO_SIIGO_V3_AUTO_HISTORIAL.zip`.
3. En la raíz del repositorio de GitHub usa **Add file → Upload files**.
4. Arrastra el contenido descomprimido: `backend/`, `frontend/`, `render.yaml` y los documentos `.md`.
5. Haz commit. Render ejecutará el despliegue y `entrypoint.sh` correrá `alembic upgrade head`.
6. Verifica en el log que Alembic llegue a `e5b7a6c41022`.
7. En una segunda tanda puedes subir `GITHUB_2_PRUEBAS_SIIGO_V3_AUTO_HISTORIAL.zip`.
8. Después del despliegue, vuelve a subir en **Historial → Auxiliar / Movimiento contable** el Movimiento Contable SIIGO que quieras usar como base técnica. No debes diligenciar ninguna tabla de parámetros por cuenta.
