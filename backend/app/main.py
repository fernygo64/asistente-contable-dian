from contextlib import asynccontextmanager
from pathlib import Path
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import empresas, config_empresa, historial, auditoria, documentos, exportacion, puc, siigo_config, auth

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


_api_docs = os.environ.get("ENABLE_API_DOCS", "0").strip().lower() in {"1", "true", "yes"}

app = FastAPI(
    title="Asistente Contable DIAN — API",
    description="Backend multiempresa: historial contable explicable, "
                "reglas, plan de cuentas, importación de históricos y auditoría.",
    version="0.2.0-multiusuario",
    lifespan=_lifespan,
    docs_url="/docs" if _api_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _api_docs else None,
)

# CORS abierto: este proyecto corre local, sin desplegar (ver README).
# Antes de exponerlo en una red compartida o desplegarlo, restringe
# allow_origins a los dominios reales.
_cors_env = os.environ.get("CORS_ORIGINS", "").strip()
_cors_origins = [x.strip() for x in _cors_env.split(",") if x.strip()] if _cors_env else [
    "http://127.0.0.1:8000", "http://localhost:8000",
]
app.add_middleware(
    CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.include_router(auth.router)
app.include_router(empresas.router)
app.include_router(auth.usuarios_router)
app.include_router(config_empresa.router)
app.include_router(historial.router)
app.include_router(documentos.router)
app.include_router(exportacion.router)
app.include_router(siigo_config.router)
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
