"""
Aislamiento multiempresa (sección 32).

get_empresa_activa es una dependencia de FastAPI que TODO endpoint que
toque datos contables debe usar. Resuelve la empresa a partir de
empresa_id en la URL, verifica que existe y está activa, y falla con
404 si no — de forma que nunca es posible, ni por error de código,
consultar datos de una empresa sin pasar por este filtro explícito.

Nota sobre autenticación: esta etapa no implementa login/JWT todavía
(no estaba priorizado en la Etapa 1). El "usuario" que queda registrado
en auditoría se toma del header X-User como placeholder. Esto debe
reemplazarse por autenticación real (JWT + roles) en una etapa
posterior antes de cualquier uso con datos reales de producción.
"""
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Empresa


def get_empresa_activa(empresa_id: str, db: Session = Depends(get_db)) -> Empresa:
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail=f"Empresa {empresa_id} no existe.")
    if not empresa.activa:
        raise HTTPException(status_code=403, detail=f"Empresa {empresa_id} está inactiva.")
    return empresa


def usuario_actual(x_user: str = Header(default="usuario_sin_identificar")) -> str:
    return x_user
