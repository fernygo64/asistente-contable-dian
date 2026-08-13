from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import empresas, config_empresa, historial, auditoria, documentos, exportacion, puc

# El esquema de base de datos se gestiona con Alembic (carpeta alembic/),
# no con Base.metadata.create_all(). Antes de levantar el servidor por
# primera vez (o tras cambiar un modelo) corre:
#   alembic upgrade head
# Ver README.md para el flujo completo.


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from app.database import SessionLocal
    from app.services.puc_catalogo import sembrar_catalogo_puc
    db = SessionLocal()
    try:
        sembrar_catalogo_puc(db)
    except Exception:
        # Si la tabla puc_cuentas todavía no existe (ej. antes de correr
        # las migraciones, o en un entorno de pruebas con su propia base
        # de datos en memoria), no debe tumbar el arranque de la app —
        # simplemente no se siembra en este intento.
        db.rollback()
    finally:
        db.close()
    yield


app = FastAPI(
    title="Asistente Contable DIAN — API",
    description="Backend multiempresa: historial contable explicable, "
                "reglas, plan de cuentas, importación de históricos y auditoría.",
    version="0.1.0-etapa5",
    lifespan=_lifespan,
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
app.include_router(puc.router)


@app.get("/salud")
def salud():
    return {"status": "ok"}


class _NoCacheStaticFiles(StaticFiles):
    """
    El frontend es un solo archivo HTML que puede cambiar con cada
    despliegue. Sin esto, el navegador puede quedarse mostrando una
    versión vieja en caché (por ejemplo, con la dirección de la API
    equivocada) hasta que el usuario fuerce una recarga completa.
    """
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/app", _NoCacheStaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
