import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import (
    Empresa, CuentaContable, ConfiguracionComprobanteSiigo, ParametrizacionCuentaSiigo,
)
from app.schemas.schemas import (
    ConfiguracionComprobantesSiigoUpdate, ParametrizacionCuentaSiigoUpdate,
)
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.siigo_config_service import TIPOS_DOCUMENTO, configuraciones_empresa

router = APIRouter(prefix="/empresas/{empresa_id}/siigo", tags=["configuracion-siigo"])


@router.get("/comprobantes")
def obtener_configuraciones_comprobante(empresa_id: str, db: Session = Depends(get_db),
                                         empresa: Empresa = Depends(get_empresa_activa)):
    cfgs = configuraciones_empresa(db, empresa)
    salida = []
    for clave in TIPOS_DOCUMENTO:
        cfg = dict(cfgs[clave])
        # La numeración interna ya no tiene memoria persistente.
        cfg["ultimo_consecutivo_usado"] = None
        salida.append(cfg)
    return salida


@router.put("/comprobantes")
def guardar_configuraciones_comprobante(empresa_id: str, payload: ConfiguracionComprobantesSiigoUpdate,
                                          db: Session = Depends(get_db),
                                          empresa: Empresa = Depends(get_empresa_activa),
                                          usuario: str = Depends(usuario_actual)):
    legacy_attr = {
        "factura_recibida": "comprobante_factura_recibida",
        "factura_emitida": "comprobante_factura_emitida",
        "nota_credito_recibida": "comprobante_nota_credito",
        "nota_credito_emitida": None,
        "nota_debito_recibida": "comprobante_nota_debito",
        "nota_debito_emitida": None,
        "nomina": "comprobante_nomina",
        "documento_equivalente_recibido": "comprobante_documento_equivalente",
        "documento_equivalente_emitido": None,
    }
    cambios = []
    for item in payload.configuraciones:
        if item.tipo_documento not in TIPOS_DOCUMENTO:
            raise HTTPException(status_code=422, detail=f"Tipo documental SIIGO desconocido: {item.tipo_documento}")
        fila = db.query(ConfiguracionComprobanteSiigo).filter(
            ConfiguracionComprobanteSiigo.empresa_id == empresa_id,
            ConfiguracionComprobanteSiigo.tipo_documento == item.tipo_documento,
        ).first()
        if not fila:
            fila = ConfiguracionComprobanteSiigo(empresa_id=empresa_id, tipo_documento=item.tipo_documento)
            db.add(fila)
        datos = item.model_dump(exclude={"ultimo_consecutivo_usado"})
        if datos.get("modo_numeracion") not in ("interna", "folio_dian"):
            raise HTTPException(status_code=422, detail="La numeración debe ser 'interna' o 'folio_dian'.")
        for campo, valor in datos.items():
            if campo != "tipo_documento":
                setattr(fila, campo, valor)
        # Compatibilidad con campos legacy. Las direcciones nuevas viven en la tabla SIIGO.
        attr_legacy = legacy_attr.get(item.tipo_documento)
        if attr_legacy:
            setattr(empresa, attr_legacy, item.tipo_comprobante)

        cambios.append(item.model_dump())

    # El número inicial se informa al generar cada archivo; aquí no se guarda ningún contador.
    auditoria_registrar(db, empresa_id, "ConfiguracionComprobanteSiigo", None,
                         "configuracion_siigo_comprobantes", {"configuraciones": cambios}, usuario)
    db.commit()
    return obtener_configuraciones_comprobante(empresa_id, db, empresa)


@router.get("/cuentas")
def listar_parametrizacion_cuentas(empresa_id: str, db: Session = Depends(get_db),
                                    empresa: Empresa = Depends(get_empresa_activa)):
    cuentas = db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa_id, CuentaContable.activa.is_(True)
    ).order_by(CuentaContable.codigo).all()
    params = db.query(ParametrizacionCuentaSiigo).filter(
        ParametrizacionCuentaSiigo.empresa_id == empresa_id
    ).all()
    por_cuenta = {p.cuenta_id: p for p in params}
    salida = []
    for c in cuentas:
        p = por_cuenta.get(c.id)
        salida.append({
            "id": p.id if p else None,
            "empresa_id": empresa_id,
            "cuenta_id": c.id,
            "cuenta_codigo": c.codigo,
            "cuenta_nombre": c.nombre,
            "configurada": bool(p),
            "maneja_tercero": bool(p.maneja_tercero) if p else True,
            "nit_tecnico_exportacion": p.nit_tecnico_exportacion if p else "0",
            "codigo_vendedor": p.codigo_vendedor if p else None,
            "codigo_ciudad": p.codigo_ciudad if p else None,
            "codigo_zona": p.codigo_zona if p else None,
            "centro_costo": p.centro_costo if p else None,
            "subcentro_costo": p.subcentro_costo if p else None,
            "sucursal": p.sucursal if p else None,
            "activa": bool(p.activa) if p else True,
        })
    return salida


@router.put("/cuentas/{cuenta_id}")
def guardar_parametrizacion_cuenta(empresa_id: str, cuenta_id: str, payload: ParametrizacionCuentaSiigoUpdate,
                                     db: Session = Depends(get_db),
                                     empresa: Empresa = Depends(get_empresa_activa),
                                     usuario: str = Depends(usuario_actual)):
    cuenta = db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa_id, CuentaContable.id == cuenta_id
    ).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada en esta empresa.")
    fila = db.query(ParametrizacionCuentaSiigo).filter(
        ParametrizacionCuentaSiigo.empresa_id == empresa_id,
        ParametrizacionCuentaSiigo.cuenta_id == cuenta_id,
    ).first()
    if not fila:
        fila = ParametrizacionCuentaSiigo(empresa_id=empresa_id, cuenta_id=cuenta_id)
        db.add(fila)
    for campo, valor in payload.model_dump().items():
        setattr(fila, campo, valor)
    auditoria_registrar(db, empresa_id, "ParametrizacionCuentaSiigo", fila.id,
                         "parametrizacion_cuenta_siigo", {"cuenta": cuenta.codigo, **payload.model_dump()}, usuario)
    db.commit()
    return {"guardada": True, "cuenta_id": cuenta_id, "cuenta_codigo": cuenta.codigo}
