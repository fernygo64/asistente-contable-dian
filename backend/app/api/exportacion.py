import json
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import (
    Empresa, PlantillaExportacion, Factura, Exportacion, EstadoExportacion,
    EstadoFactura, SistemaContable, ExportacionFactura,
)
from app.schemas.schemas import (
    PlantillaCreate, PlantillaOut, GenerarExportacionRequest, ExportacionResumen,
)
from app.services import export_service
from app.services.document_format_service import referencia_documento
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.plantilla_inferencia_service import detectar_estructura_archivo_plano
from app.services.siigo_pyme_extendido import reprocesar_columnas_siigo
from app.services.siigo_excel_service import generar_xlsx as generar_xlsx_siigo, columnas_modelo_general
from app.services.siigo_config_service import (
    asignar_numeros, proyectar_numeros, configuraciones_empresa, tipo_documento_clave,
)

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
        version_formato=int(getattr(p, "version_formato", 1) or 1),
        plantilla_origen_id=getattr(p, "plantilla_origen_id", None),
    )


def _asegurar_plantilla_siigo(db: Session, empresa_id: str) -> PlantillaExportacion:
    nombre = "SIIGO Pyme · Modelo General automático"
    p = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id,
        PlantillaExportacion.nombre == nombre,
    ).first()
    columnas = columnas_modelo_general()
    if not p:
        p = PlantillaExportacion(
            empresa_id=empresa_id, nombre=nombre, sistema_contable=SistemaContable.siigo_pyme,
            delimitador=";", extension="xlsx", incluir_encabezado=True, formato_fecha="%Y-%m-%d",
            columnas_json=json.dumps(columnas, ensure_ascii=False), equivalencias_cuentas_json="{}",
            version_formato=5, activa=True,
        )
        db.add(p); db.flush()
    else:
        # La plantilla automática sí puede autoactualizarse porque no es una plantilla histórica manual.
        p.columnas_json = json.dumps(columnas, ensure_ascii=False)
        p.extension = "xlsx"; p.version_formato = 5; p.activa = True
    return p


@router.get("/plantillas/siigo-automatica", response_model=PlantillaOut)
def plantilla_siigo_automatica(empresa_id: str, db: Session = Depends(get_db),
                                empresa: Empresa = Depends(get_empresa_activa)):
    if empresa.sistema_contable != SistemaContable.siigo_pyme:
        raise HTTPException(status_code=422, detail="La empresa activa no usa SIIGO Pyme.")
    p = _asegurar_plantilla_siigo(db, empresa_id)
    db.commit(); db.refresh(p)
    return _plantilla_a_out(p)


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

    columnas = [c.model_dump() for c in payload.columnas]
    version_formato = 1
    # Solo el Modelo General completo (≈123 columnas) se reprocesa automáticamente.
    # Las plantillas cortas/personalizadas conservan exactamente los sources elegidos por el usuario.
    if payload.sistema_contable == SistemaContable.siigo_pyme.value and len(columnas) >= 100:
        columnas = reprocesar_columnas_siigo(columnas)
        version_formato = 2
    p = PlantillaExportacion(
        empresa_id=empresa_id, nombre=payload.nombre, sistema_contable=payload.sistema_contable,
        delimitador=payload.delimitador, extension=payload.extension,
        incluir_encabezado=payload.incluir_encabezado, formato_fecha=payload.formato_fecha,
        columnas_json=json.dumps(columnas, ensure_ascii=False),
        equivalencias_cuentas_json=json.dumps(payload.equivalencias_cuentas, ensure_ascii=False),
        version_formato=version_formato,
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


@router.patch("/plantillas/{plantilla_id}/renombrar", response_model=PlantillaOut)
def renombrar_plantilla(empresa_id: str, plantilla_id: str, nombre: str, db: Session = Depends(get_db),
                         empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Corrige el nombre de una plantilla — útil sobre todo para una que
    haya quedado con el nombre vacío y ya no se pueda eliminar por estar
    referenciada en el historial de exportaciones. Renombrar no afecta
    la auditoría: las exportaciones guardan el ID de la plantilla, no
    una copia de su nombre.
    """
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacío.")
    plantilla = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.id == plantilla_id
    ).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en esta empresa.")
    existente = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.nombre == nombre,
        PlantillaExportacion.id != plantilla_id,
    ).first()
    if existente:
        raise HTTPException(status_code=409, detail=f"Ya existe otra plantilla llamada '{nombre}' en esta empresa.")

    nombre_anterior = plantilla.nombre
    plantilla.nombre = nombre
    auditoria_registrar(db, empresa_id, "PlantillaExportacion", plantilla_id, "plantilla_renombrada",
                         {"nombre_anterior": nombre_anterior, "nombre_nuevo": nombre}, usuario)
    db.commit()
    db.refresh(plantilla)
    return _plantilla_a_out(plantilla)


@router.post("/plantillas/{plantilla_id}/reprocesar-siigo", response_model=PlantillaOut, status_code=201)
def reprocesar_plantilla_siigo(empresa_id: str, plantilla_id: str, db: Session = Depends(get_db),
                                empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    original = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.id == plantilla_id
    ).first()
    if not original:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en esta empresa.")
    sistema = original.sistema_contable.value if hasattr(original.sistema_contable, "value") else original.sistema_contable
    if sistema != "siigo_pyme":
        raise HTTPException(status_code=422, detail="Solo las plantillas de Siigo Pyme se reprocesan con esta función.")
    columnas = reprocesar_columnas_siigo(json.loads(original.columnas_json))
    base_nombre = f"{original.nombre} · SIIGO v2"
    nombre = base_nombre
    i = 2
    while db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.nombre == nombre
    ).first():
        nombre = f"{base_nombre}.{i}"
        i += 1
    nueva = PlantillaExportacion(
        empresa_id=empresa_id, nombre=nombre, sistema_contable=original.sistema_contable,
        delimitador=original.delimitador, extension=original.extension,
        incluir_encabezado=original.incluir_encabezado, formato_fecha=original.formato_fecha,
        columnas_json=json.dumps(columnas, ensure_ascii=False),
        equivalencias_cuentas_json=original.equivalencias_cuentas_json or "{}",
        version_formato=2, plantilla_origen_id=original.id,
    )
    db.add(nueva)
    db.flush()
    auditoria_registrar(db, empresa_id, "PlantillaExportacion", nueva.id, "plantilla_siigo_reprocesada",
                         {"plantilla_origen_id": original.id, "version": 2}, usuario)
    db.commit()
    db.refresh(nueva)
    return _plantilla_a_out(nueva)


@router.get("/exportaciones/pendientes/{plantilla_id}")
def facturas_pendientes_exportacion(empresa_id: str, plantilla_id: str, db: Session = Depends(get_db),
                                     empresa: Empresa = Depends(get_empresa_activa)):
    plantilla = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.id == plantilla_id
    ).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en esta empresa.")
    sistema = plantilla.sistema_contable
    ya = db.query(ExportacionFactura.factura_id).filter(
        ExportacionFactura.empresa_id == empresa_id,
        ExportacionFactura.sistema_contable == sistema,
    ).all()
    ya_ids = {x[0] for x in ya}
    q = db.query(Factura).filter(
        Factura.empresa_id == empresa_id,
        Factura.estado.in_([EstadoFactura.contabilizada, EstadoFactura.exportada]),
    )
    facturas = [f for f in export_service.agrupar_y_ordenar_facturas(q.all()) if f.id not in ya_ids]
    return [{
        "id": f.id, "numero_factura": f.numero_factura, "prefijo": f.prefijo,
        "fecha_emision": f.fecha_emision.isoformat() if f.fecha_emision else None,
        "tercero_nit": f.tercero_nit, "tercero_nombre": f.tercero_nombre,
        "estado": f.estado.value if hasattr(f.estado, "value") else f.estado,
        "referencia_documento": referencia_documento(f.fecha_emision, f.prefijo, f.numero_factura, f.tercero_nombre),
    } for f in facturas]


@router.delete("/plantillas/{plantilla_id}")
def eliminar_plantilla(empresa_id: str, plantilla_id: str, db: Session = Depends(get_db),
                        empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Elimina una plantilla mal configurada. Si ya se usó para generar al
    menos una exportación real, se rechaza — borrarla dejaría ese
    registro de auditoría (sección 39) sin poder mostrar qué plantilla
    se usó. En ese caso, usa "renombrar" si solo necesitas corregirle
    el nombre, o crea una plantilla nueva para otra configuración.
    """
    plantilla = db.query(PlantillaExportacion).filter(
        PlantillaExportacion.empresa_id == empresa_id, PlantillaExportacion.id == plantilla_id
    ).first()
    if not plantilla:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada en esta empresa.")

    ya_usada = db.query(Exportacion).filter(Exportacion.plantilla_id == plantilla_id).first()
    if ya_usada:
        nombre_mostrar = plantilla.nombre or "(sin nombre)"
        raise HTTPException(
            status_code=422,
            detail=f"No se puede eliminar: la plantilla '{nombre_mostrar}' ya se usó para generar "
                   f"una exportación (queda en el historial de auditoría). Usa 'renombrar' si solo "
                   f"necesitas corregirle el nombre, o crea una plantilla nueva para otra configuración.",
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

    revision = export_service.validar_exportacion_detallada(db, empresa, plantilla, facturas)
    bloqueantes = revision["bloqueantes"]
    advertencias = revision["advertencias"]
    valido = not bloqueantes and (not advertencias or payload.omitir_advertencias)
    return {
        "valido": valido,
        "errores": bloqueantes + ([] if payload.omitir_advertencias else advertencias),
        "bloqueantes": bloqueantes,
        "advertencias": advertencias,
        "puede_generar_bajo_responsabilidad": bool(advertencias and not bloqueantes),
    }


@router.post("/exportaciones/previsualizar")
def previsualizar_exportacion(empresa_id: str, payload: GenerarExportacionRequest, db: Session = Depends(get_db),
                               empresa: Empresa = Depends(get_empresa_activa)):
    """
    Genera el contenido REAL del archivo (con las cuentas que se
    escogieron para las facturas nuevas) pero sin descargarlo ni
    marcar nada como exportado — para que el usuario apruebe cómo va a
    quedar antes de confirmar la descarga definitiva (sección 24).
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

    revision = export_service.validar_exportacion_detallada(db, empresa, plantilla, facturas)
    bloqueantes = revision["bloqueantes"]
    advertencias = revision["advertencias"]
    if bloqueantes or (advertencias and not payload.omitir_advertencias):
        return {
            "valido": False,
            "errores": bloqueantes + ([] if payload.omitir_advertencias else advertencias),
            "bloqueantes": bloqueantes,
            "advertencias": advertencias,
            "puede_generar_bajo_responsabilidad": bool(advertencias and not bloqueantes),
            "encabezado": [], "filas": [],
        }

    columnas_plantilla = json.loads(plantilla.columnas_json)
    sistema = plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value") else plantilla.sistema_contable
    facturas_ordenadas = export_service.agrupar_y_ordenar_facturas(facturas)
    numeros = proyectar_numeros(db, empresa, facturas_ordenadas, payload.consecutivo_inicial) if sistema == "siigo_pyme" else None
    _, filas, total_filas = export_service.generar_filas(db, empresa, plantilla, facturas, numeros_documento=numeros)
    encabezado = [c["label"] for c in columnas_plantilla]

    tipos_codigos = []
    if sistema == "siigo_pyme":
        cfgs = configuraciones_empresa(db, empresa)
        vistos = set()
        for f in facturas_ordenadas:
            cfg = cfgs[tipo_documento_clave(f)]
            par = (cfg.get("tipo_comprobante"), cfg.get("codigo_comprobante"))
            if par not in vistos:
                vistos.add(par); tipos_codigos.append({"tipo": par[0], "codigo": par[1]})
    nums_int = []
    if sistema == "siigo_pyme":
        cfgs = configuraciones_empresa(db, empresa)
        for f in facturas_ordenadas:
            cfg = cfgs[tipo_documento_clave(f)]
            if cfg.get("modo_numeracion") == "interna":
                n = (numeros or {}).get(f.id)
                if str(n or "").isdigit(): nums_int.append(int(n))
    total_debito = total_credito = 0.0
    from app.models.models import Movimiento
    for f in facturas:
        for m in db.query(Movimiento).filter(Movimiento.factura_id == f.id).all():
            if str(getattr(m.tipo, "value", m.tipo)) == "debito": total_debito += float(m.valor or 0)
            else: total_credito += float(m.valor or 0)
    return {
        "valido": True, "errores": [],
        "bloqueantes": [], "advertencias": advertencias,
        "puede_generar_bajo_responsabilidad": bool(advertencias),
        "encabezado": encabezado, "filas": filas[:500],
        "total_filas": total_filas, "total_documentos": len(facturas),
        "total_debito": total_debito, "total_credito": total_credito,
        "diferencia": round(total_debito-total_credito, 2),
        "tipos_codigos": tipos_codigos,
        "consecutivo_inicial_proyectado": min(nums_int) if nums_int else None,
        "consecutivo_final_proyectado": max(nums_int) if nums_int else None,
        "plantilla_version": int(getattr(plantilla, "version_formato", 1) or 1),
        "formato_salida": ("xlsx" if sistema == "siigo_pyme" and len(columnas_plantilla) == 123 else plantilla.extension),
    }


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

    revision = export_service.validar_exportacion_detallada(db, empresa, plantilla, facturas)
    bloqueantes = revision["bloqueantes"]
    advertencias = revision["advertencias"]
    no_aceptadas = bool(advertencias and not payload.omitir_advertencias)
    errores_rechazo = bloqueantes + (advertencias if no_aceptadas else [])

    exportacion = Exportacion(
        empresa_id=empresa_id, plantilla_id=plantilla.id, sistema_contable=plantilla.sistema_contable,
        usuario=payload.usuario or usuario,
        facturas_incluidas_json=json.dumps(payload.factura_ids),
        estado=EstadoExportacion.error if errores_rechazo else EstadoExportacion.generada,
        errores_json=json.dumps(advertencias if not errores_rechazo else errores_rechazo, ensure_ascii=False),
    )

    if errores_rechazo:
        db.add(exportacion)
        mensaje = (
            "No se generó el archivo porque existen errores contables/estructurales que no se pueden omitir."
            if bloqueantes else
            "Hay advertencias corregibles. Activa 'Generar bajo mi responsabilidad' para descargar el archivo y corregirlas en el programa contable."
        )
        auditoria_registrar(db, empresa_id, "Exportacion", exportacion.id, "exportacion_fallida",
                             {"bloqueantes": bloqueantes, "advertencias": advertencias}, payload.usuario or usuario)
        db.commit()
        raise HTTPException(status_code=422, detail={
            "mensaje": mensaje, "errores": errores_rechazo,
            "bloqueantes": bloqueantes, "advertencias": advertencias,
            "puede_generar_bajo_responsabilidad": bool(advertencias and not bloqueantes),
        })

    sistema = plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value") else plantilla.sistema_contable
    try:
        facturas_ordenadas = export_service.agrupar_y_ordenar_facturas(facturas)
        numeros = None
        cfg_por_factura = {}
        if sistema == "siigo_pyme":
            numeros, cfg_por_factura = asignar_numeros(db, empresa, facturas_ordenadas, payload.consecutivo_inicial)
        columnas_count = len(json.loads(plantilla.columnas_json or "[]"))
        es_modelo_general_siigo = sistema == "siigo_pyme" and columnas_count == 123
        if es_modelo_general_siigo:
            contenido, total_filas = generar_xlsx_siigo(
                db, empresa, plantilla, facturas_ordenadas, numeros_documento=numeros
            )
        else:
            contenido, total_filas = export_service.generar_archivo(
                db, empresa, plantilla, facturas_ordenadas, numeros_documento=numeros
            )
        db.add(exportacion)
        db.flush()
        nombre_archivo = (f"movimientocontable_{exportacion.id[:8]}.xlsx" if es_modelo_general_siigo
                          else f"exportacion_{sistema}_{exportacion.id[:8]}.{plantilla.extension}")
        exportacion.cantidad_registros = total_filas
        exportacion.archivo_nombre = nombre_archivo

        for f in facturas_ordenadas:
            cfg = cfg_por_factura.get(f.id, {})
            db.add(ExportacionFactura(
                empresa_id=empresa_id, exportacion_id=exportacion.id, factura_id=f.id,
                sistema_contable=plantilla.sistema_contable,
                tipo_comprobante=cfg.get("tipo_comprobante") if sistema == "siigo_pyme" else None,
                codigo_comprobante=cfg.get("codigo_comprobante") if sistema == "siigo_pyme" else None,
                numero_documento=(numeros or {}).get(f.id) if sistema == "siigo_pyme" else None,
                usuario=payload.usuario or usuario,
            ))

        # Compatibilidad visual con versiones anteriores: se conserva el estado legacy
        # "exportada", pero YA NO se usa como fuente de verdad para pendientes por destino.
        for f in facturas_ordenadas:
            f.estado = EstadoFactura.exportada

        auditoria_registrar(db, empresa_id, "Exportacion", exportacion.id, "exportacion_generada",
                             {"archivo": nombre_archivo, "registros": total_filas,
                              "facturas": payload.factura_ids, "sistema": sistema,
                              "advertencias_asumidas": advertencias if payload.omitir_advertencias else [],
                              "consecutivo_inicial": payload.consecutivo_inicial},
                             payload.usuario or usuario)
        db.commit()
    except Exception:
        db.rollback()
        raise

    media = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
             if es_modelo_general_siigo else "text/plain")
    return Response(
        content=contenido,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"',
                 "X-Exportacion-Id": exportacion.id, "X-Cantidad-Registros": str(total_filas),
                 "X-Advertencias-Asumidas": str(len(advertencias) if payload.omitir_advertencias else 0)},
    )


@router.get("/exportaciones", response_model=list[ExportacionResumen])
def listar_exportaciones(empresa_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa)):
    filas = db.query(Exportacion).filter(Exportacion.empresa_id == empresa_id).order_by(Exportacion.creado_en.desc()).all()
    resultado = []
    for e in filas:
        errores = json.loads(e.errores_json) if e.errores_json else []
        # El historial operativo muestra solo exportaciones vigentes. Las eliminadas
        # siguen en base de datos y auditoría para conservar trazabilidad, pero no
        # ocupan espacio en la lista de trabajo del usuario. También ocultamos las
        # antiguas marcas [ANULADA] creadas por V10/V10.1 por compatibilidad.
        eliminada_historial = any(
            str(x).startswith("[ELIMINADA_HISTORIAL]") or str(x).startswith("[ANULADA]")
            for x in errores
        )
        if eliminada_historial:
            continue
        resultado.append(ExportacionResumen(
            id=e.id, sistema_contable=e.sistema_contable.value if hasattr(e.sistema_contable, "value") else e.sistema_contable,
            cantidad_registros=e.cantidad_registros,
            estado=e.estado.value if hasattr(e.estado, "value") else e.estado,
            errores=errores,
            archivo_nombre=e.archivo_nombre, creado_en=e.creado_en,
        ))
    return resultado


@router.delete("/exportaciones/{exportacion_id}")
def eliminar_exportacion(empresa_id: str, exportacion_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """Elimina una exportación del historial operativo sin destruir su evidencia.

    La fila, las relaciones con facturas, la plantilla y los números utilizados se
    conservan en base de datos para auditoría. El usuario deja de verla en el
    historial cotidiano y puede volver a generar el archivo con el consecutivo
    inicial que decida, porque los consecutivos internos no tienen memoria.
    """
    exportacion = db.query(Exportacion).filter(
        Exportacion.empresa_id == empresa_id, Exportacion.id == exportacion_id
    ).first()
    if not exportacion:
        raise HTTPException(status_code=404, detail="Exportación no encontrada en esta empresa.")

    errores = json.loads(exportacion.errores_json) if exportacion.errores_json else []
    ya_eliminada = any(
        str(x).startswith("[ELIMINADA_HISTORIAL]") or str(x).startswith("[ANULADA]")
        for x in errores
    )
    if not ya_eliminada:
        errores.append(
            f"[ELIMINADA_HISTORIAL] Exportación retirada del historial visible por {usuario or 'usuario'}; "
            "se conserva como evidencia técnica."
        )
        exportacion.errores_json = json.dumps(errores, ensure_ascii=False)
        auditoria_registrar(
            db, empresa_id, "Exportacion", exportacion_id, "exportacion_eliminada_historial",
            {"archivo": exportacion.archivo_nombre, "plantilla_id": exportacion.plantilla_id,
             "cantidad_registros": exportacion.cantidad_registros, "evidencia_conservada": True}, usuario,
        )
        db.commit()
    return {"eliminada_historial": True, "id": exportacion_id, "trazabilidad_conservada": True}
