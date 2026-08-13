import json
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import (
    Empresa, PlantillaExportacion, Factura, Exportacion, EstadoExportacion,
    EstadoFactura, SistemaContable,
)
from app.schemas.schemas import (
    PlantillaCreate, PlantillaOut, GenerarExportacionRequest, ExportacionResumen,
)
from app.services import export_service
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.plantilla_inferencia_service import detectar_estructura_archivo_plano

router = APIRouter(prefix="/empresas/{empresa_id}", tags=["exportacion"])


@router.post("/plantillas/inferir-desde-ejemplo")
async def inferir_plantilla_desde_ejemplo(empresa_id: str, archivo: UploadFile = File(...),
                                           empresa: Empresa = Depends(get_empresa_activa)):
    """
    Sección 20: "el usuario podrá cargar un archivo de ejemplo
    proporcionado por su Siigo Pyme". Detecta delimitador y columnas
    reales del archivo plano exportado por el software contable, y
    sugiere a qué campo interno corresponde cada una — el usuario
    revisa y ajusta, nunca se asume ciegamente.
    """
    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")
    resultado = detectar_estructura_archivo_plano(contenido)
    if not resultado["columnas"]:
        raise HTTPException(status_code=422, detail="No se pudo leer ninguna línea del archivo de ejemplo.")
    return resultado


def _plantilla_a_out(p: PlantillaExportacion) -> PlantillaOut:
    return PlantillaOut(
        id=p.id, empresa_id=p.empresa_id, nombre=p.nombre,
        sistema_contable=p.sistema_contable.value if hasattr(p.sistema_contable, "value") else p.sistema_contable,
        delimitador=p.delimitador, extension=p.extension, incluir_encabezado=p.incluir_encabezado,
        formato_fecha=p.formato_fecha, columnas=json.loads(p.columnas_json),
        equivalencias_cuentas=json.loads(p.equivalencias_cuentas_json or "{}"), activa=p.activa,
    )


@router.post("/plantillas", response_model=PlantillaOut, status_code=201)
def crear_plantilla(empresa_id: str, payload: PlantillaCreate, db: Session = Depends(get_db),
                     empresa: Empresa = Depends(get_empresa_activa)):
    if payload.sistema_contable not in (SistemaContable.siigo_pyme.value, SistemaContable.world_office.value):
        raise HTTPException(status_code=422, detail="sistema_contable debe ser 'siigo_pyme' o 'world_office'.")
    existente = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.nombre == payload.nombre
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail=f"Ya existe una plantilla llamada '{payload.nombre}' en esta empresa.")

    p = PlantillaExportacion(
        empresa_id=empresa_id, nombre=payload.nombre, sistema_contable=payload.sistema_contable,
        delimitador=payload.delimitador, extension=payload.extension,
        incluir_encabezado=payload.incluir_encabezado, formato_fecha=payload.formato_fecha,
        columnas_json=json.dumps([c.model_dump() for c in payload.columnas], ensure_ascii=False),
        equivalencias_cuentas_json=json.dumps(payload.equivalencias_cuentas, ensure_ascii=False),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _plantilla_a_out(p)


@router.get("/plantillas", response_model=list[PlantillaOut])
def listar_plantillas(empresa_id: str, db: Session = Depends(get_db),
                       empresa: Empresa = Depends(get_empresa_activa)):
    plantillas = db.query(PlantillaExportacion).filter(PlantillaExportacion.empresa_id == empresa_id).all()
    return [_plantilla_a_out(p) for p in plantillas]


@router.delete("/plantillas/{plantilla_id}")
def eliminar_plantilla(empresa_id: str, plantilla_id: str, db: Session = Depends(get_db),
                        empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Elimina una plantilla mal configurada. Si ya se usó para generar al
    menos una exportación real, se rechaza — borrarla dejaría ese
    registro de auditoría (sección 39) sin poder mostrar qué plantilla
    se usó. En ese caso, crea una plantilla nueva en vez de modificar
    la existente.
    """
    plantilla = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.id == plantilla_id
    ).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en esta empresa.")

    ya_usada = db.query(Exportacion).filter(Exportacion.plantilla_id == plantilla_id).first()
    if ya_usada:
        raise HTTPException(
            status_code=422,
            detail=f"No se puede eliminar: la plantilla '{plantilla.nombre}' ya se usó para generar "
                   f"una exportación (queda en el historial de auditoría). Crea una plantilla nueva si "
                   f"necesitas otra configuración.",
        )

    nombre = plantilla.nombre
    db.delete(plantilla)
    auditoria_registrar(db, empresa_id, "PlantillaExportacion", plantilla_id, "plantilla_eliminada",
                         {"nombre": nombre}, usuario)
    db.commit()
    return {"eliminada": True, "id": plantilla_id}


@router.post("/exportaciones/validar")
def validar_exportacion(empresa_id: str, payload: GenerarExportacionRequest, db: Session = Depends(get_db),
                         empresa: Empresa = Depends(get_empresa_activa)):
    """Previsualización de errores (sección 23-24) sin generar el archivo todavía."""
    plantilla = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.id == payload.plantilla_id
    ).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en esta empresa.")
    facturas = db.query(Factura).filter(Factura.empresa_id == empresa_id,
                                         Factura.id.in_(payload.factura_ids)).all()
    if len(facturas) != len(payload.factura_ids):
        raise HTTPException(status_code=422, detail="Alguna factura indicada no existe en esta empresa.")

    errores = export_service.validar_exportacion(db, empresa, plantilla, facturas)
    return {"valido": len(errores) == 0, "errores": errores}


@router.post("/exportaciones/generar")
def generar_exportacion(empresa_id: str, payload: GenerarExportacionRequest, db: Session = Depends(get_db),
                         empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Genera el archivo final (sección 22, 39). Si hay CUALQUIER error de
    validación, NO se genera archivo — se devuelve 422 con el detalle
    exacto de qué falla en qué factura (sección 23).
    """
    plantilla = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.id == payload.plantilla_id
    ).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en esta empresa.")
    facturas = db.query(Factura).filter(Factura.empresa_id == empresa_id,
                                         Factura.id.in_(payload.factura_ids)).all()
    if len(facturas) != len(payload.factura_ids):
        raise HTTPException(status_code=422, detail="Alguna factura indicada no existe en esta empresa.")

    errores = export_service.validar_exportacion(db, empresa, plantilla, facturas)

    exportacion = Exportacion(
        empresa_id=empresa_id, plantilla_id=plantilla.id, sistema_contable=plantilla.sistema_contable,
        usuario=payload.usuario or usuario,
        facturas_incluidas_json=json.dumps(payload.factura_ids),
        estado=EstadoExportacion.error if errores else EstadoExportacion.generada,
        errores_json=json.dumps(errores, ensure_ascii=False),
    )

    if errores:
        db.add(exportacion)
        auditoria_registrar(db, empresa_id, "Exportacion", exportacion.id, "exportacion_fallida",
                             {"errores": errores}, payload.usuario or usuario)
        db.commit()
        raise HTTPException(status_code=422, detail={"mensaje": "No se generó el archivo por errores de validación.",
                                                       "errores": errores})

    contenido, total_filas = export_service.generar_archivo(db, plantilla, facturas)
    db.add(exportacion)
    db.flush()  # necesario para que exportacion.id exista antes de usarlo en el nombre del archivo
    nombre_archivo = f"exportacion_{plantilla.sistema_contable.value}_{exportacion.id[:8]}.{plantilla.extension}"
    exportacion.cantidad_registros = total_filas
    exportacion.archivo_nombre = nombre_archivo

    for f in facturas:
        f.estado = EstadoFactura.exportada

    auditoria_registrar(db, empresa_id, "Exportacion", exportacion.id, "exportacion_generada",
                         {"archivo": nombre_archivo, "registros": total_filas,
                          "facturas": payload.factura_ids},
                         payload.usuario or usuario)
    db.commit()

    return Response(
        content=contenido,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"',
                 "X-Exportacion-Id": exportacion.id, "X-Cantidad-Registros": str(total_filas)},
    )


@router.get("/exportaciones", response_model=list[ExportacionResumen])
def listar_exportaciones(empresa_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa)):
    filas = db.query(Exportacion).filter(Exportacion.empresa_id == empresa_id).order_by(Exportacion.creado_en.desc()).all()
    return [
        ExportacionResumen(
            id=e.id, sistema_contable=e.sistema_contable.value if hasattr(e.sistema_contable, "value") else e.sistema_contable,
            cantidad_registros=e.cantidad_registros, estado=e.estado.value if hasattr(e.estado, "value") else e.estado,
            errores=json.loads(e.errores_json) if e.errores_json else [],
            archivo_nombre=e.archivo_nombre, creado_en=e.creado_en,
        )
        for e in filas
    ]
