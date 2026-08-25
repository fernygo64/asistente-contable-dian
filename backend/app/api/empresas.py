from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Empresa
from app.schemas.schemas import EmpresaCreate, EmpresaOut, EmpresaCuentasBase, EmpresaComprobantesPorTipo, EmpleadoCreate, EmpleadoOut
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
        "cuenta_ingresos": "cuenta_ingresos_id",
        "cuenta_clientes": "cuenta_clientes_id",
        "cuenta_iva_generado": "cuenta_iva_generado_id",
        "cuenta_nomina": "cuenta_nomina_id",
        "cuenta_salario": "cuenta_salario_id",
        "cuenta_auxilio_transporte": "cuenta_auxilio_transporte_id",
        "cuenta_nomina_por_pagar": "cuenta_nomina_por_pagar_id",
        "cuenta_salud_por_pagar": "cuenta_salud_por_pagar_id",
        "cuenta_pension_por_pagar": "cuenta_pension_por_pagar_id",
        "cuenta_cesantias": "cuenta_cesantias_id",
        "cuenta_cesantias_por_pagar": "cuenta_cesantias_por_pagar_id",
        "cuenta_intereses_cesantias": "cuenta_intereses_cesantias_id",
        "cuenta_intereses_cesantias_por_pagar": "cuenta_intereses_cesantias_por_pagar_id",
        "cuenta_prima": "cuenta_prima_id",
        "cuenta_prima_por_pagar": "cuenta_prima_por_pagar_id",
        "cuenta_vacaciones": "cuenta_vacaciones_id",
        "cuenta_vacaciones_por_pagar": "cuenta_vacaciones_por_pagar_id",
        "cuenta_arl": "cuenta_arl_id",
        "cuenta_arl_por_pagar": "cuenta_arl_por_pagar_id",
        "cuenta_caja_compensacion": "cuenta_caja_compensacion_id",
        "cuenta_caja_compensacion_por_pagar": "cuenta_caja_compensacion_por_pagar_id",
    }
    cambios = payload.model_dump(exclude_none=True)
    for campo, codigo in cambios.items():
        cuenta = get_or_create_cuenta(db, empresa_id, codigo)
        setattr(empresa, campo_a_columna[campo], cuenta.id)

    auditoria_registrar(db, empresa_id, "Empresa", empresa.id, "configurar_cuentas_base", cambios, usuario)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.patch("/{empresa_id}/modo-contable", response_model=EmpresaOut)
def configurar_modo_contable(empresa_id: str, modo: str, db: Session = Depends(get_db),
                              empresa: Empresa = Depends(get_empresa_activa),
                              usuario: str = Depends(usuario_actual)):
    """
    "mixto" (por defecto): las facturas recibidas se contabilizan como
    gasto y las emitidas como ingreso, cada una con sus propias cuentas
    — el caso normal de una empresa que compra y también vende.
    "solo_gastos": TODO se contabiliza por el lado de gasto, sin
    importar si la DIAN marcó el documento como emitido o recibido —
    pensado para una persona natural que solo usa el sistema para
    llevar sus propios gastos y no tiene (ni necesita) cuentas de
    ingresos/clientes configuradas.
    """
    if modo not in ("mixto", "solo_gastos"):
        raise HTTPException(status_code=422, detail="modo debe ser 'mixto' o 'solo_gastos'.")
    empresa.modo_contable = modo
    auditoria_registrar(db, empresa_id, "Empresa", empresa.id, "configurar_modo_contable", {"modo": modo}, usuario)
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
        "cuenta_ingresos": resolver(empresa.cuenta_ingresos_id),
        "cuenta_clientes": resolver(empresa.cuenta_clientes_id),
        "cuenta_iva_generado": resolver(empresa.cuenta_iva_generado_id),
        "cuenta_nomina": resolver(empresa.cuenta_nomina_id),
        "cuenta_salario": resolver(empresa.cuenta_salario_id),
        "cuenta_auxilio_transporte": resolver(empresa.cuenta_auxilio_transporte_id),
        "cuenta_nomina_por_pagar": resolver(empresa.cuenta_nomina_por_pagar_id),
        "cuenta_salud_por_pagar": resolver(empresa.cuenta_salud_por_pagar_id),
        "cuenta_pension_por_pagar": resolver(empresa.cuenta_pension_por_pagar_id),
        "cuenta_cesantias": resolver(empresa.cuenta_cesantias_id),
        "cuenta_cesantias_por_pagar": resolver(empresa.cuenta_cesantias_por_pagar_id),
        "cuenta_intereses_cesantias": resolver(empresa.cuenta_intereses_cesantias_id),
        "cuenta_intereses_cesantias_por_pagar": resolver(empresa.cuenta_intereses_cesantias_por_pagar_id),
        "cuenta_prima": resolver(empresa.cuenta_prima_id),
        "cuenta_prima_por_pagar": resolver(empresa.cuenta_prima_por_pagar_id),
        "cuenta_vacaciones": resolver(empresa.cuenta_vacaciones_id),
        "cuenta_vacaciones_por_pagar": resolver(empresa.cuenta_vacaciones_por_pagar_id),
        "cuenta_arl": resolver(empresa.cuenta_arl_id),
        "cuenta_arl_por_pagar": resolver(empresa.cuenta_arl_por_pagar_id),
        "cuenta_caja_compensacion": resolver(empresa.cuenta_caja_compensacion_id),
        "cuenta_caja_compensacion_por_pagar": resolver(empresa.cuenta_caja_compensacion_por_pagar_id),
    }


@router.patch("/{empresa_id}/comprobantes-por-tipo", response_model=EmpresaOut)
def configurar_comprobantes_por_tipo(empresa_id: str, payload: EmpresaComprobantesPorTipo, db: Session = Depends(get_db),
                                      empresa: Empresa = Depends(get_empresa_activa),
                                      usuario: str = Depends(usuario_actual)):
    """
    Define el tipo de comprobante (texto libre, según la parametrización
    propia de cada empresa en su software) que debe usarse al exportar
    según la clasificación real del documento — nunca uno solo para todo.
    """
    cambios = payload.model_dump(exclude_none=True)
    for campo, valor in cambios.items():
        setattr(empresa, campo, valor)
    auditoria_registrar(db, empresa_id, "Empresa", empresa.id, "configurar_comprobantes_por_tipo", cambios, usuario)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("/{empresa_id}/comprobantes-por-tipo")
def obtener_comprobantes_por_tipo(empresa_id: str, db: Session = Depends(get_db),
                                   empresa: Empresa = Depends(get_empresa_activa)):
    return {
        "comprobante_factura_recibida": empresa.comprobante_factura_recibida,
        "comprobante_factura_emitida": empresa.comprobante_factura_emitida,
        "comprobante_nota_credito": empresa.comprobante_nota_credito,
        "comprobante_nota_debito": empresa.comprobante_nota_debito,
        "comprobante_nomina": empresa.comprobante_nomina,
        "comprobante_documento_equivalente": empresa.comprobante_documento_equivalente,
    }


@router.patch("/{empresa_id}/desactivar", response_model=EmpresaOut)
def desactivar_empresa(empresa_id: str, db: Session = Depends(get_db),
                        empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Opción segura y reversible: la empresa deja de aparecer como
    utilizable (ninguna ruta que dependa de get_empresa_activa la
    aceptará) pero sus datos NO se borran — se puede reactivar en
    cualquier momento. Pensada para "esto no debí crearlo así" sin
    perder nada por si acaso.
    """
    empresa.activa = False
    auditoria_registrar(db, empresa_id, "Empresa", empresa.id, "empresa_desactivada", {}, usuario)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.patch("/{empresa_id}/reactivar", response_model=EmpresaOut)
def reactivar_empresa(empresa_id: str, db: Session = Depends(get_db), usuario: str = Depends(usuario_actual)):
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    empresa.activa = True
    auditoria_registrar(db, empresa_id, "Empresa", empresa.id, "empresa_reactivada", {}, usuario)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.delete("/{empresa_id}")
def eliminar_empresa(empresa_id: str, confirmar: bool = False, db: Session = Depends(get_db),
                      usuario: str = Depends(usuario_actual)):
    """
    Elimina la empresa y TODO lo que le pertenece (cuentas, proveedores,
    facturas, movimientos, historial, reglas, centros de costo,
    plantillas, exportaciones, cargas y auditoría) — irreversible. Exige
    confirmar=true a propósito, para que nunca sea un clic accidental.
    Si solo fue un error reciente sin datos reales todavía, considera
    mejor "desactivar" (reversible) en vez de esto.
    """
    from app.models.models import (
        CuentaContable, Proveedor, CentroCosto, ReglaContable, ImportacionHistorico,
        HistorialContable, CargaDocumentosDian, Factura, Movimiento, PlantillaExportacion,
        Exportacion, Auditoria, Empleado, ConfiguracionComprobanteSiigo, ConsecutivoSiigo,
        ParametrizacionCuentaSiigo, ExportacionFactura,
    )

    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    if not confirmar:
        raise HTTPException(
            status_code=422,
            detail="Esta acción borra TODOS los datos de la empresa (facturas, historial, exportaciones, "
                   "auditoría) de forma irreversible. Vuelve a llamar con ?confirmar=true si estás seguro, "
                   "o usa 'desactivar' si prefieres algo reversible.",
        )

    resumen = {"nit": empresa.nit, "nombre": empresa.nombre}

    # Se limpian primero las referencias de Empresa hacia CuentaContable
    # (cuenta_proveedores_id, etc.) para poder borrar las cuentas después
    # sin violar la llave foránea.
    for campo in ("cuenta_proveedores_id", "cuenta_caja_id", "cuenta_banco_id", "cuenta_iva_descontable_id",
                  "cuenta_retefuente_id", "cuenta_reteica_id", "cuenta_reteiva_id", "cuenta_inc_id",
                  "cuenta_ingresos_id", "cuenta_clientes_id", "cuenta_iva_generado_id", "cuenta_nomina_id"):
        setattr(empresa, campo, None)
    db.flush()

    db.query(ExportacionFactura).filter(ExportacionFactura.empresa_id == empresa_id).delete()
    db.query(ParametrizacionCuentaSiigo).filter(ParametrizacionCuentaSiigo.empresa_id == empresa_id).delete()
    db.query(ConsecutivoSiigo).filter(ConsecutivoSiigo.empresa_id == empresa_id).delete()
    db.query(ConfiguracionComprobanteSiigo).filter(ConfiguracionComprobanteSiigo.empresa_id == empresa_id).delete()
    db.query(Movimiento).filter(Movimiento.empresa_id == empresa_id).delete()
    db.query(HistorialContable).filter(HistorialContable.empresa_id == empresa_id).delete()
    db.query(Factura).filter(Factura.empresa_id == empresa_id).delete()
    db.query(CargaDocumentosDian).filter(CargaDocumentosDian.empresa_id == empresa_id).delete()
    db.query(ImportacionHistorico).filter(ImportacionHistorico.empresa_id == empresa_id).delete()
    db.query(Exportacion).filter(Exportacion.empresa_id == empresa_id).delete()
    db.query(PlantillaExportacion).filter(PlantillaExportacion.empresa_id == empresa_id).delete()
    db.query(ReglaContable).filter(ReglaContable.empresa_id == empresa_id).delete()
    db.query(Proveedor).filter(Proveedor.empresa_id == empresa_id).delete()
    db.query(Empleado).filter(Empleado.empresa_id == empresa_id).delete()
    db.query(CentroCosto).filter(CentroCosto.empresa_id == empresa_id).delete()
    db.query(CuentaContable).filter(CuentaContable.empresa_id == empresa_id).delete()
    db.query(Auditoria).filter(Auditoria.empresa_id == empresa_id).delete()

    db.delete(empresa)
    db.commit()
    return {"eliminada": True, "id": empresa_id, "resumen": resumen}


# ------------------------------------------------------------- Empleados --
@router.get("/{empresa_id}/empleados", response_model=list[EmpleadoOut])
def listar_empleados(empresa_id: str, db: Session = Depends(get_db),
                      empresa: Empresa = Depends(get_empresa_activa)):
    from app.models.models import Empleado
    return db.query(Empleado).filter(Empleado.empresa_id == empresa_id).order_by(Empleado.nombre).all()


@router.post("/{empresa_id}/empleados", response_model=EmpleadoOut, status_code=201)
def crear_empleado(empresa_id: str, payload: EmpleadoCreate, db: Session = Depends(get_db),
                    empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Ficha de empleado, reutilizable en cualquier empresa que use el
    sistema (nunca datos fijos de una empresa en particular). Solo el
    NIT es obligatorio — el resto de campos (afiliaciones) se pueden
    completar después; mientras falten, las líneas de pasivo que
    dependan de ellos simplemente no se generan.
    """
    from app.models.models import Empleado
    existente = db.query(Empleado).filter(Empleado.empresa_id == empresa_id, Empleado.nit == payload.nit).first()
    if existente:
        raise HTTPException(status_code=409, detail=f"Ya existe un empleado con NIT {payload.nit} en esta empresa.")
    empleado = Empleado(empresa_id=empresa_id, **payload.model_dump())
    db.add(empleado)
    auditoria_registrar(db, empresa_id, "Empleado", empleado.id, "empleado_creado", payload.model_dump(), usuario)
    db.commit()
    db.refresh(empleado)
    return empleado


@router.patch("/{empresa_id}/empleados/{empleado_id}", response_model=EmpleadoOut)
def actualizar_empleado(empresa_id: str, empleado_id: str, payload: EmpleadoCreate, db: Session = Depends(get_db),
                         empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    from app.models.models import Empleado
    empleado = db.query(Empleado).filter(Empleado.empresa_id == empresa_id, Empleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado en esta empresa.")
    for campo, valor in payload.model_dump().items():
        setattr(empleado, campo, valor)
    auditoria_registrar(db, empresa_id, "Empleado", empleado.id, "empleado_actualizado", payload.model_dump(), usuario)
    db.commit()
    db.refresh(empleado)
    return empleado


@router.delete("/{empresa_id}/empleados/{empleado_id}")
def eliminar_empleado(empresa_id: str, empleado_id: str, db: Session = Depends(get_db),
                       empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    from app.models.models import Empleado
    empleado = db.query(Empleado).filter(Empleado.empresa_id == empresa_id, Empleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado en esta empresa.")
    db.delete(empleado)
    auditoria_registrar(db, empresa_id, "Empleado", empleado_id, "empleado_eliminado", {}, usuario)
    db.commit()
    return {"eliminado": True, "id": empleado_id}
