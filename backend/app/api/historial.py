from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import Empresa, OrigenDecision
from app.schemas.schemas import SugerenciaCuenta, ImportacionResumen, HistorialManualCreate
from app.services import historial_service, importacion_service

router = APIRouter(prefix="/empresas/{empresa_id}/historial", tags=["historial"])


@router.post("/importar", response_model=ImportacionResumen, status_code=201)
async def importar_historico(
    empresa_id: str,
    archivo: UploadFile = File(...),
    mapeo_nit: str = Form(...),
    mapeo_cuenta: str = Form(...),
    mapeo_nombre: str | None = Form(default=None),
    mapeo_fecha: str | None = Form(default=None),
    mapeo_numero_documento: str | None = Form(default=None),
    mapeo_tipo_documento: str | None = Form(default=None),
    mapeo_descripcion: str | None = Form(default=None),
    mapeo_valor: str | None = Form(default=None),
    db: Session = Depends(get_db),
    empresa: Empresa = Depends(get_empresa_activa),
    usuario: str = Depends(usuario_actual),
):
    mapeo = {
        "nit": mapeo_nit, "cuenta": mapeo_cuenta, "nombre": mapeo_nombre,
        "fecha": mapeo_fecha, "numero_documento": mapeo_numero_documento,
        "tipo_documento": mapeo_tipo_documento, "descripcion": mapeo_descripcion,
        "valor": mapeo_valor,
    }
    contenido = await archivo.read()
    try:
        importacion = importacion_service.importar_historico(
            db, empresa_id, contenido, archivo.filename, mapeo, usuario
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    import json
    return ImportacionResumen(
        id=importacion.id,
        archivo_nombre=importacion.archivo_nombre,
        total_registros=importacion.total_registros,
        registros_validos=importacion.registros_validos,
        registros_rechazados=importacion.registros_rechazados,
        detalle_rechazos=json.loads(importacion.detalle_rechazos_json or "[]"),
        importado_en=importacion.importado_en,
    )


@router.get("/sugerencia", response_model=SugerenciaCuenta)
def sugerir(empresa_id: str, nit: str, descripcion: str | None = None,
            db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa)):
    resultado = historial_service.sugerir_cuenta(db, empresa_id, nit, descripcion)
    return SugerenciaCuenta(**resultado)


@router.post("/decision", status_code=201)
def registrar_decision_manual(empresa_id: str, payload: HistorialManualCreate,
                               db: Session = Depends(get_db),
                               empresa: Empresa = Depends(get_empresa_activa),
                               usuario: str = Depends(usuario_actual)):
    """
    Registra una decisión de contabilización (manual o sugerencia aceptada).
    Nunca modifica el historial anterior — siempre agrega una fila nueva,
    para que el aprendizaje evolucione conservando la trazabilidad
    (secciones 11 y 41).
    """
    if payload.origen not in ("manual", "sugerencia_aceptada"):
        raise HTTPException(status_code=422, detail="origen debe ser 'manual' o 'sugerencia_aceptada'.")

    proveedor = historial_service.get_or_create_proveedor(
        db, empresa_id, payload.proveedor_nit, payload.proveedor_nombre
    )
    cuenta = historial_service.get_or_create_cuenta(db, empresa_id, payload.cuenta_codigo)

    fila = historial_service.registrar_decision(
        db, empresa_id, proveedor.id, cuenta.id,
        origen=OrigenDecision(payload.origen),
        fecha_documento=payload.fecha_documento,
        numero_documento=payload.numero_documento,
        tipo_documento=payload.tipo_documento,
        descripcion=payload.descripcion,
        valor=payload.valor,
    )
    db.commit()
    return {
        "id": fila.id,
        "proveedor_id": proveedor.id,
        "cuenta_id": cuenta.id,
        "mensaje": "Decisión registrada. El historial se actualizó sin borrar decisiones anteriores.",
    }
