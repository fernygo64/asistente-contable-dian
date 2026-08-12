import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import Empresa, Factura, CargaDocumentosDian, EstadoFactura, Movimiento, OrigenDecision
from app.schemas.schemas import (
    FacturaOut, CargaResumen, CorreccionFactura, ResolucionDuplicado,
    GenerarPartidaRequest, PartidaOut, LineaPartidaOut,
)
from app.services.zip_processing_service import procesar_archivos_mixtos
from app.services import documentos_service, partida_doble_service, historial_service
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.excel_utils import leer_columnas_excel

router = APIRouter(prefix="/empresas/{empresa_id}/documentos", tags=["documentos"])


@router.post("/excel-columnas")
async def previsualizar_columnas_excel(empresa_id: str, archivo: UploadFile = File(...),
                                        empresa: Empresa = Depends(get_empresa_activa)):
    """
    Lee únicamente los encabezados del Excel/CSV subido, sin procesar
    filas todavía — para que la interfaz pueda ofrecer las columnas
    reales como lista desplegable en vez de que el usuario tenga que
    escribir el nombre exacto a ciegas (fuente típica de errores como
    'FOLIO' vs 'Folio').
    """
    contenido = await archivo.read()
    try:
        columnas = leer_columnas_excel(contenido, archivo.filename or "archivo.xlsx")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"No se pudo leer el archivo: {e}")
    return {"columnas": columnas}


@router.post("/cargar", response_model=CargaResumen, status_code=201)
async def cargar_documentos(
    empresa_id: str,
    documentos: list[UploadFile] = File(..., description="Uno o varios .zip, y/o .xml/.pdf sueltos"),
    excel_file: UploadFile | None = File(default=None, alias="excel"),
    mapeo_cufe: str | None = Form(default=None),
    mapeo_numero_factura: str | None = Form(default=None),
    mapeo_nit_emisor: str | None = Form(default=None),
    mapeo_nombre_emisor: str | None = Form(default=None),
    mapeo_fecha: str | None = Form(default=None),
    mapeo_valor_total: str | None = Form(default=None),
    mapeo_tipo_documento: str | None = Form(default=None, description="Columna 'Tipo de documento' del Excel de la DIAN"),
    mapeo_grupo: str | None = Form(default=None, description="Columna 'Grupo' (Emitido/Recibido) del Excel de la DIAN"),
    db: Session = Depends(get_db),
    empresa: Empresa = Depends(get_empresa_activa),
    usuario: str = Depends(usuario_actual),
):
    """
    Flujo manual completo (sección 3): el usuario sube uno o varios ZIP
    de la DIAN, y/o archivos XML/PDF sueltos sin comprimir (la DIAN a
    veces entrega la descarga partida en varios ZIP, o el usuario los
    tiene sueltos porque los bajó del correo uno por uno). Opcionalmente
    también el Excel de la DIAN con el mapeo de sus columnas.
    """
    if not documentos:
        raise HTTPException(status_code=422, detail="Debes subir al menos un archivo .zip, .xml o .pdf.")

    archivos_leidos = []
    for f in documentos:
        contenido = await f.read()
        archivos_leidos.append((f.filename or "archivo_sin_nombre", contenido))

    try:
        documentos_zip = procesar_archivos_mixtos(archivos_leidos, nit_empresa=empresa.nit)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"No se pudieron leer los archivos: {e}")

    excel_contenido = None
    mapeo = None
    if excel_file is not None:
        excel_contenido = await excel_file.read()
        mapeo = {
            "cufe": mapeo_cufe, "numero_factura": mapeo_numero_factura,
            "nit_emisor": mapeo_nit_emisor, "nombre_emisor": mapeo_nombre_emisor,
            "fecha": mapeo_fecha, "valor_total": mapeo_valor_total,
            "tipo_documento": mapeo_tipo_documento, "grupo": mapeo_grupo,
        }
        if not any(mapeo.values()):
            raise HTTPException(
                status_code=422,
                detail="Se cargó un Excel pero no se indicó el mapeo de ninguna columna "
                       "(al menos 'mapeo_cufe' o 'mapeo_numero_factura' + 'mapeo_nit_emisor').",
            )

    carga = CargaDocumentosDian(
        empresa_id=empresa_id,
        archivo_excel_nombre=excel_file.filename if excel_file else None,
        archivo_zip_nombre=", ".join(nombre for nombre, _ in archivos_leidos)[:300],
        usuario=usuario,
    )
    db.add(carga)
    db.flush()

    try:
        resultado = documentos_service.procesar_carga(
            db, empresa_id, carga.id, documentos_zip, excel_contenido,
            excel_file.filename if excel_file else None, mapeo,
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))

    carga.total_filas_excel = resultado["total_filas_excel"]
    carga.total_archivos_zip = resultado["total_archivos_zip_validos"] + resultado["total_archivos_zip_error"]
    carga.total_relacionados = resultado["total_relacionados"]
    carga.total_pendientes_revision = resultado["total_pendientes_revision"]
    carga.total_pendientes_clasificacion = resultado["total_pendientes_clasificacion"]
    carga.total_descartados = resultado["total_descartados"]
    carga.total_duplicados = resultado["total_duplicados"]

    auditoria_registrar(
        db, empresa_id, "CargaDocumentosDian", carga.id, "carga_documentos_dian",
        {
            "archivo_excel": carga.archivo_excel_nombre, "archivo_zip": carga.archivo_zip_nombre,
            "relacionados": carga.total_relacionados, "pendientes_revision": carga.total_pendientes_revision,
            "pendientes_clasificacion": carga.total_pendientes_clasificacion,
            "descartados": carga.total_descartados,
            "duplicados": carga.total_duplicados, "errores_zip": resultado["errores_zip"],
        },
        usuario,
    )
    db.commit()
    db.refresh(carga)

    return CargaResumen(
        id=carga.id, archivo_excel_nombre=carga.archivo_excel_nombre,
        archivo_zip_nombre=carga.archivo_zip_nombre,
        total_filas_excel=carga.total_filas_excel, total_archivos_zip=carga.total_archivos_zip,
        total_relacionados=carga.total_relacionados,
        total_pendientes_revision=carga.total_pendientes_revision,
        total_pendientes_clasificacion=carga.total_pendientes_clasificacion,
        total_descartados=carga.total_descartados,
        total_duplicados=carga.total_duplicados,
        errores_zip=resultado["errores_zip"], avisos_descarte=resultado["avisos_descarte"],
        creado_en=carga.creado_en,
    )


@router.get("", response_model=list[FacturaOut])
def listar_facturas(
    empresa_id: str, estado: str | None = None, nit_emisor: str | None = None,
    numero_factura: str | None = None, confianza_max: float | None = None,
    naturaleza: str | None = None, direccion: str | None = None,
    db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa),
):
    """Filtros de la sección 29."""
    q = db.query(Factura).filter(Factura.empresa_id == empresa_id)
    if estado:
        q = q.filter(Factura.estado == estado)
    if nit_emisor:
        q = q.filter(Factura.nit_emisor == nit_emisor)
    if numero_factura:
        q = q.filter(Factura.numero_factura == numero_factura)
    if confianza_max is not None:
        q = q.filter(Factura.confianza_extraccion <= confianza_max)
    if naturaleza:
        q = q.filter(Factura.naturaleza_documento == naturaleza)
    if direccion:
        q = q.filter(Factura.direccion_documento == direccion)
    return q.order_by(Factura.creado_en.desc()).all()


@router.get("/{factura_id}")
def obtener_factura(empresa_id: str, factura_id: str, db: Session = Depends(get_db),
                     empresa: Empresa = Depends(get_empresa_activa)):
    f = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada en esta empresa.")
    return {
        "id": f.id, "estado": f.estado, "fuente_extraccion": f.fuente_extraccion,
        "confianza_extraccion": float(f.confianza_extraccion),
        "relacionada_con_excel": f.relacionada_con_excel, "metodo_relacion": f.metodo_relacion,
        "motivo_no_relacionada": f.motivo_no_relacionada,
        "es_posible_duplicado": f.es_posible_duplicado, "duplicado_de_id": f.duplicado_de_id,
        "cufe": f.cufe, "numero_factura": f.numero_factura, "nit_emisor": f.nit_emisor,
        "nombre_emisor": f.nombre_emisor, "direccion_emisor": f.direccion_emisor,
        "fecha_emision": f.fecha_emision, "subtotal": f.subtotal, "iva": f.iva, "inc": f.inc,
        "retenciones": json.loads(f.retenciones_json) if f.retenciones_json else {},
        "total": f.total, "conceptos": json.loads(f.conceptos_json) if f.conceptos_json else [],
        "datos_originales": json.loads(f.datos_originales_json) if f.datos_originales_json else {},
        "datos_corregidos": json.loads(f.datos_corregidos_json) if f.datos_corregidos_json else None,
        "archivo_xml": f.archivo_xml_path, "archivo_pdf": f.archivo_pdf_path,
        "excel_fila": json.loads(f.excel_fila_json) if f.excel_fila_json else None,
    }


@router.patch("/{factura_id}/corregir", response_model=FacturaOut)
def corregir_factura(empresa_id: str, factura_id: str, payload: CorreccionFactura,
                      db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa),
                      usuario: str = Depends(usuario_actual)):
    """
    Corrección manual (sección 6): el dato original extraído NUNCA se
    modifica (queda intacto en datos_originales_json) — la corrección se
    guarda aparte, con trazabilidad de quién y cuándo (sección 27).
    """
    f = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada en esta empresa.")

    cambios = payload.model_dump(exclude={"nuevo_estado", "usuario"}, exclude_none=True)
    if cambios:
        for campo, valor in cambios.items():
            if hasattr(f, campo):
                setattr(f, campo, valor)
        f.datos_corregidos_json = json.dumps(cambios, ensure_ascii=False, default=str)

    if payload.nuevo_estado:
        try:
            f.estado = EstadoFactura(payload.nuevo_estado)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Estado inválido: {payload.nuevo_estado}")

    auditoria_registrar(
        db, empresa_id, "Factura", f.id, "correccion_manual", cambios,
        payload.usuario or usuario,
    )
    db.commit()
    db.refresh(f)
    return f


@router.patch("/{factura_id}/resolver-duplicado", response_model=FacturaOut)
def resolver_duplicado(empresa_id: str, factura_id: str, payload: ResolucionDuplicado,
                        db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa),
                        usuario: str = Depends(usuario_actual)):
    f = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada en esta empresa.")
    if not f.es_posible_duplicado:
        raise HTTPException(status_code=422, detail="Esta factura no está marcada como posible duplicado.")

    if payload.es_duplicado:
        f.estado = EstadoFactura.duplicada
    else:
        f.es_posible_duplicado = False
        f.duplicado_de_id = None
        f.estado = EstadoFactura.pendiente_revision if float(f.confianza_extraccion) < 70 else EstadoFactura.extraida

    auditoria_registrar(
        db, empresa_id, "Factura", f.id, "resolucion_duplicado",
        {"es_duplicado": payload.es_duplicado}, payload.usuario or usuario,
    )
    db.commit()
    db.refresh(f)
    return f


# --------------------------------------------------------------- Partida doble
@router.post("/{factura_id}/partida/generar", response_model=PartidaOut)
def generar_partida(empresa_id: str, factura_id: str, payload: GenerarPartidaRequest,
                     db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa),
                     usuario: str = Depends(usuario_actual)):
    """
    Genera la propuesta de partida doble (sección 16) a partir de la
    cuenta de gasto elegida (sugerida o corregida por el usuario) y la
    contrapartida seleccionada. Si cuadra, se persiste y la factura
    queda 'lista_para_contabilizar'; si no cuadra o faltan cuentas
    configuradas, se devuelven los errores y NO se persiste nada
    (sección 16: nunca un comprobante descuadrado).
    Además alimenta el historial de aprendizaje con esta decisión
    (secciones 9 y 11) — nunca sobreescribe decisiones anteriores.
    """
    f = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada en esta empresa.")
    if f.estado == EstadoFactura.duplicada:
        raise HTTPException(status_code=422, detail="No se puede generar partida para una factura marcada como duplicada.")

    if payload.origen_decision not in ("manual", "sugerencia_aceptada"):
        raise HTTPException(status_code=422, detail="origen_decision debe ser 'manual' o 'sugerencia_aceptada'.")

    cuenta_gasto = historial_service.get_or_create_cuenta(db, empresa_id, payload.cuenta_gasto_codigo)

    resultado = partida_doble_service.generar_partida(
        db, empresa, f, cuenta_gasto.id, payload.contrapartida
    )

    if resultado.balanceado:
        partida_doble_service.persistir_partida(db, empresa_id, f, resultado)
        f.estado = EstadoFactura.lista_para_contabilizar

        if f.nit_emisor:
            proveedor = historial_service.get_or_create_proveedor(db, empresa_id, f.nit_emisor, f.nombre_emisor)
            historial_service.registrar_decision(
                db, empresa_id, proveedor.id, cuenta_gasto.id,
                origen=OrigenDecision(payload.origen_decision),
                fecha_documento=f.fecha_emision, numero_documento=f.numero_factura,
                valor=f.subtotal, importacion_id=None,
            )

        auditoria_registrar(db, empresa_id, "Factura", f.id, "partida_generada",
                             {"cuenta_gasto": cuenta_gasto.codigo, "contrapartida": payload.contrapartida,
                              "total_debito": resultado.total_debito},
                             payload.usuario or usuario)
        db.commit()
    else:
        db.rollback()

    return PartidaOut(
        factura_id=factura_id,
        lineas=[LineaPartidaOut(cuenta_codigo=l.cuenta_codigo, cuenta_nombre=l.cuenta_nombre,
                                 tipo=l.tipo, valor=l.valor, descripcion=l.descripcion)
                for l in resultado.lineas],
        total_debito=resultado.total_debito, total_credito=resultado.total_credito,
        balanceado=resultado.balanceado, errores=resultado.errores,
    )


@router.get("/{factura_id}/partida", response_model=PartidaOut)
def obtener_partida(empresa_id: str, factura_id: str, db: Session = Depends(get_db),
                     empresa: Empresa = Depends(get_empresa_activa)):
    f = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada en esta empresa.")
    movimientos = (
        db.query(Movimiento).filter(Movimiento.factura_id == factura_id).order_by(Movimiento.orden).all()
    )
    if not movimientos:
        raise HTTPException(status_code=404, detail="Esta factura todavía no tiene una partida generada.")
    total_debito = sum(float(m.valor) for m in movimientos if m.tipo == "debito")
    total_credito = sum(float(m.valor) for m in movimientos if m.tipo == "credito")
    return PartidaOut(
        factura_id=factura_id,
        lineas=[LineaPartidaOut(cuenta_codigo=m.cuenta.codigo, cuenta_nombre=m.cuenta.nombre,
                                 tipo=m.tipo, valor=float(m.valor), descripcion=m.descripcion or "")
                for m in movimientos],
        total_debito=round(total_debito, 2), total_credito=round(total_credito, 2),
        balanceado=abs(total_debito - total_credito) < 0.01, errores=[],
    )


@router.post("/{factura_id}/contabilizar", response_model=FacturaOut)
def contabilizar_factura(empresa_id: str, factura_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa),
                          usuario: str = Depends(usuario_actual)):
    """Aprobación final (sección 25, pasos 11-12) — deja registro de quién aprobó (sección 27)."""
    f = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada en esta empresa.")
    if f.estado != EstadoFactura.lista_para_contabilizar:
        raise HTTPException(
            status_code=422,
            detail=f"La factura está en estado '{f.estado}', debe estar 'lista_para_contabilizar' "
                   f"(genera la partida doble primero).",
        )
    f.estado = EstadoFactura.contabilizada
    auditoria_registrar(db, empresa_id, "Factura", f.id, "contabilizacion_aprobada", {}, usuario)
    db.commit()
    db.refresh(f)
    return f
