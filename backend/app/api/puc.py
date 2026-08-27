from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import PucCuenta
from app.services.excel_utils import _normalizar
from app.core.security import require_authenticated

router = APIRouter(prefix="/puc", tags=["puc"])


@router.get("/buscar")
def buscar_cuentas_puc(q: str = "", limite: int = 20, db: Session = Depends(get_db), _user=Depends(require_authenticated)):
    """
    Busca en el catálogo PUC base por código o por nombre (sección
    "Cuentas base de la empresa activa" — ayuda a elegir el código
    correcto en vez de escribirlo de memoria). Nunca es la única forma
    de asignar una cuenta: la empresa siempre puede escribir un código
    propio que no esté en este catálogo. La búsqueda ignora
    mayúsculas/minúsculas y tildes (el catálogo es pequeño, se filtra
    en memoria en vez de depender de LIKE de SQL, que no reconoce
    "retencion" como igual a "Retención").
    """
    todas = db.query(PucCuenta).order_by(PucCuenta.codigo).all()
    if q:
        q_norm = _normalizar(q)
        todas = [c for c in todas if q_norm in _normalizar(c.codigo) or q_norm in _normalizar(c.nombre)]
    resultado = todas[:limite]
    return [{"codigo": c.codigo, "nombre": c.nombre, "clase": c.clase, "naturaleza": c.naturaleza} for c in resultado]
