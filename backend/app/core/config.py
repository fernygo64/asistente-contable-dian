"""
Configuración central de la aplicación.

Por defecto usa SQLite en un archivo local (para ejecución local sin
infraestructura adicional). DATABASE_URL puede sobreescribirse con una
cadena de conexión a PostgreSQL (ej: postgresql+psycopg2://user:pass@host/db)
sin cambiar una sola línea del resto del código: todo el acceso a datos
pasa por SQLAlchemy.

Nota de despliegue: Render, Heroku y otros hostings entregan la URL de
Postgres con el prefijo "postgres://", que SQLAlchemy 2.x ya no acepta
(exige "postgresql://"). Se normaliza aquí automáticamente para que el
despliegue no falle por esto.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _normalizar_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = _normalizar_database_url(os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'asistente_contable.db'}",
))

# Carpeta donde se guardan los archivos originales (XML/PDF/ZIP/Excel),
# siempre particionada por empresa: storage/<empresa_id>/...
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# Autenticación real. En producción queda activa por defecto. Las pruebas
# heredadas pueden ejecutar con AUTH_REQUIRED=0 para aislar lógica contable.
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "1").strip().lower() not in {"0", "false", "no", "off"}
AUTH_TOKEN_HOURS = int(os.environ.get("AUTH_TOKEN_HOURS", "12"))
