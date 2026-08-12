import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import Empresa, CuentaContable, Proveedor, CentroCosto, ReglaContable
from app.schemas.schemas import (
    CuentaCreate, CuentaOut, ProveedorOut, CentroCostoCreate, CentroCostoOut,
    ReglaCreate, ReglaOut,
)
from app.services.historial_service import get_or_create_cuenta

router = APIRouter(prefix="/empresas/{empresa_id}", tags=["configuracion-empresa"])


# ------------------------------------------------------------------ Cuentas
@router.post("/cuentas", response_model=CuentaOut, status_code=201)
def crear_cuenta(empresa_id: str, payload: CuentaCreate, db: Session = Depends(get_db),
                  empresa: Empresa = Depends(get_empresa_activa)):
    existente = db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa_id, CuentaContable.codigo == payload.codigo
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail=f"La cuenta {payload.codigo} ya existe en esta empresa.")
    cuenta = CuentaContable(empresa_id=empresa_id, codigo=payload.codigo,
                             nombre=payload.nombre, tipo=payload.tipo)
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return cuenta


@router.get("/cuentas", response_model=list[CuentaOut])
def listar_cuentas(empresa_id: str, db: Session = Depends(get_db),
                    empresa: Empresa = Depends(get_empresa_activa)):
    return db.query(CuentaContable).filter(CuentaContable.empresa_id == empresa_id).order_by(CuentaContable.codigo).all()


# --------------------------------------------------------------- Proveedores
@router.get("/proveedores", response_model=list[ProveedorOut])
def listar_proveedores(empresa_id: str, db: Session = Depends(get_db),
                        empresa: Empresa = Depends(get_empresa_activa)):
    return db.query(Proveedor).filter(Proveedor.empresa_id == empresa_id).order_by(Proveedor.nombre).all()


# ------------------------------------------------------------- Centro costo
@router.post("/centros-costo", response_model=CentroCostoOut, status_code=201)
def crear_centro_costo(empresa_id: str, payload: CentroCostoCreate, db: Session = Depends(get_db),
                        empresa: Empresa = Depends(get_empresa_activa)):
    existente = db.query(CentroCosto).filter(
        CentroCosto.empresa_id == empresa_id, CentroCosto.codigo == payload.codigo
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail=f"El centro de costo {payload.codigo} ya existe en esta empresa.")
    cc = CentroCosto(empresa_id=empresa_id, codigo=payload.codigo, nombre=payload.nombre, activo=payload.activo)
    db.add(cc)
    db.commit()
    db.refresh(cc)
    return cc


@router.get("/centros-costo", response_model=list[CentroCostoOut])
def listar_centros_costo(empresa_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa)):
    return db.query(CentroCosto).filter(CentroCosto.empresa_id == empresa_id).order_by(CentroCosto.codigo).all()


# ------------------------------------------------------------------- Reglas
@router.post("/reglas", response_model=ReglaOut, status_code=201)
def crear_regla(empresa_id: str, payload: ReglaCreate, db: Session = Depends(get_db),
                 empresa: Empresa = Depends(get_empresa_activa),
                 usuario: str = Depends(usuario_actual)):
    cuenta = get_or_create_cuenta(db, empresa_id, payload.cuenta_codigo)
    regla = ReglaContable(
        empresa_id=empresa_id, nombre=payload.nombre,
        criterio_json=json.dumps(payload.criterio, ensure_ascii=False),
        cuenta_id=cuenta.id, activa=payload.activa,
    )
    db.add(regla)
    db.commit()
    db.refresh(regla)
    return regla


@router.get("/reglas", response_model=list[ReglaOut])
def listar_reglas(empresa_id: str, db: Session = Depends(get_db),
                   empresa: Empresa = Depends(get_empresa_activa)):
    return db.query(ReglaContable).filter(ReglaContable.empresa_id == empresa_id).order_by(ReglaContable.nombre).all()
