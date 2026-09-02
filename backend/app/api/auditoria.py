from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa
from app.models.models import Empresa, Auditoria

router = APIRouter(prefix="/empresas/{empresa_id}/auditoria", tags=["auditoria"])


@router.get("")
def listar_auditoria(empresa_id: str, db: Session = Depends(get_db),
                      empresa: Empresa = Depends(get_empresa_activa), limit: int = 100):
    filas = (
        db.query(Auditoria)
        .filter(Auditoria.empresa_id == empresa_id)
        .order_by(Auditoria.creado_en.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": f.id, "entidad": f.entidad, "entidad_id": f.entidad_id,
            "accion": f.accion, "detalle": f.detalle_json, "usuario": f.usuario,
            "creado_en": f.creado_en,
        }
        for f in filas
    ]
