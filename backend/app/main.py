from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import empresas, config_empresa, historial, auditoria, documentos, exportacion

# El esquema de base de datos se gestiona con Alembic (carpeta alembic/),
# no con Base.metadata.create_all(). Antes de levantar el servidor por
# primera vez (o tras cambiar un modelo) corre:
#   alembic upgrade head
# Ver README.md para el flujo completo.

app = FastAPI(
    title="Asistente Contable DIAN — API",
    description="Backend multiempresa: historial contable explicable, "
                "reglas, plan de cuentas, importación de históricos y auditoría.",
    version="0.1.0-etapa5",
)

# CORS abierto: este proyecto corre local, sin desplegar (ver README).
# Antes de exponerlo en una red compartida o desplegarlo, restringe
# allow_origins a los dominios reales.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(empresas.router)
app.include_router(config_empresa.router)
app.include_router(historial.router)
app.include_router(documentos.router)
app.include_router(exportacion.router)
app.include_router(auditoria.router)


@app.get("/salud")
def salud():
    return {"status": "ok"}


_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
