import json
from sqlalchemy.orm import Session

from app.models.models import Auditoria


def registrar(db: Session, empresa_id: str, entidad: str, entidad_id: str | None,
              accion: str, detalle: dict, usuario: str | None):
    ev = Auditoria(
        empresa_id=empresa_id,
        entidad=entidad,
        entidad_id=entidad_id,
        accion=accion,
        detalle_json=json.dumps(detalle, ensure_ascii=False, default=str),
        usuario=usuario,
    )
    db.add(ev)
    return ev
