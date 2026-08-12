from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Empresa
from app.schemas.schemas import EmpresaCreate, EmpresaOut, EmpresaCuentasBase
from app.services.auditoria_service import registrar as auditoria_registrar
from app.core.security import usuario_actual, get_empresa_activa

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.post("", response_model=EmpresaOut, status_code=201)
def crear_empresa(payload: EmpresaCreate, db: Session = Depends(get_db),
                   usuario: str = Depends(usuario_actual)):
    existente = db.query(Empresa).filter(Empresa.nit == payload.nit).first()
    if existente:
        raise HTTPException(status_code=409, detail=f"Ya existe una empresa con NIT {payload.nit}.")
    empresa = Empresa(
        nit=payload.nit,
        nombre=payload.nombre,
        sistema_contable=payload.sistema_contable,
        responsable_iva=payload.responsable_iva,
        regimen_simple=payload.regimen_simple,
    )
    db.add(empresa)
    db.flush()
    auditoria_registrar(db, empresa.id, "Empresa", empresa.id, "creacion_empresa",
                         {"nit": empresa.nit, "nombre": empresa.nombre}, usuario)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("", response_model=list[EmpresaOut])
def listar_empresas(db: Session = Depends(get_db)):
    return db.query(Empresa).order_by(Empresa.nombre).all()


@router.get("/{empresa_id}", response_model=EmpresaOut)
def obtener_empresa(empresa_id: str, db: Session = Depends(get_db)):
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    return empresa


@router.patch("/{empresa_id}/cuentas-base", response_model=EmpresaOut)
def configurar_cuentas_base(empresa_id: str, payload: EmpresaCuentasBase, db: Session = Depends(get_db),
                             empresa: Empresa = Depends(get_empresa_activa),
                             usuario: str = Depends(usuario_actual)):
    """
    Configura las cuentas de proveedores/caja/banco/IVA/retenciones de la
    empresa (sección 38). Nunca se asumen por defecto: sin esto, la
    partida doble se niega a generarse si la factura las necesita
    (sección 37, "nunca inventar cuentas").
    """
    from app.services.historial_service import get_or_create_cuenta

    campo_a_columna = {
        "cuenta_proveedores": "cuenta_proveedores_id",
        "cuenta_caja": "cuenta_caja_id",
        "cuenta_banco": "cuenta_banco_id",
        "cuenta_iva_descontable": "cuenta_iva_descontable_id",
        "cuenta_retefuente": "cuenta_retefuente_id",
        "cuenta_reteica": "cuenta_reteica_id",
        "cuenta_reteiva": "cuenta_reteiva_id",
        "cuenta_inc": "cuenta_inc_id",
    }
    cambios = payload.model_dump(exclude_none=True)
    for campo, codigo in cambios.items():
        cuenta = get_or_create_cuenta(db, empresa_id, codigo)
        setattr(empresa, campo_a_columna[campo], cuenta.id)

    auditoria_registrar(db, empresa_id, "Empresa", empresa.id, "configurar_cuentas_base", cambios, usuario)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("/{empresa_id}/cuentas-base")
def obtener_cuentas_base(empresa_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa)):
    from app.models.models import CuentaContable

    def resolver(cuenta_id):
        if not cuenta_id:
            return None
        c = db.get(CuentaContable, cuenta_id)
        return {"codigo": c.codigo, "nombre": c.nombre} if c else None

    return {
        "cuenta_proveedores": resolver(empresa.cuenta_proveedores_id),
        "cuenta_caja": resolver(empresa.cuenta_caja_id),
        "cuenta_banco": resolver(empresa.cuenta_banco_id),
        "cuenta_iva_descontable": resolver(empresa.cuenta_iva_descontable_id),
        "cuenta_retefuente": resolver(empresa.cuenta_retefuente_id),
        "cuenta_reteica": resolver(empresa.cuenta_reteica_id),
        "cuenta_reteiva": resolver(empresa.cuenta_reteiva_id),
        "cuenta_inc": resolver(empresa.cuenta_inc_id),
    }
