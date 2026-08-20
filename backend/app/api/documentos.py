import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import or_
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
from app.services.mapeo_dian_service import detectar_mapeo_excel_dian

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


@router.post("/excel-sugerir-mapeo")
async def sugerir_mapeo_excel_dian(empresa_id: str, archivo: UploadFile = File(...),
                                    empresa: Empresa = Depends(get_empresa_activa)):
    """
    El Excel que la DIAN entrega al descargar el histórico de
    documentos sigue un formato bastante estable (a diferencia de un
    auxiliar contable, que varía por software) — se reconocen sus
    columnas típicas por nombre y se propone el mapeo completo, para
    que el usuario no tenga que elegir cada campo a mano cada vez que
    carga un Excel nuevo. Solo sugiere lo que reconoce con confianza;
    el usuario revisa y ajusta antes de cargar.
    """
    contenido = await archivo.read()
    try:
        columnas = leer_columnas_excel(contenido, archivo.filename or "archivo.xlsx")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"No se pudo leer el archivo: {e}")
    resultado = detectar_mapeo_excel_dian(columnas)
    return {"columnas": columnas, **resultado}


@router.get("/resumen-por-tipo")
def resumen_por_tipo(empresa_id: str, db: Session = Depends(get_db),
                      empresa: Empresa = Depends(get_empresa_activa)):
    """
    Totales (cantidad y valor) agrupados por tipo de documento — para
    tener de un vistazo el control de gastos e ingresos pedido por el
    usuario, sin tener que sumar manualmente en Excel. Nunca cuenta los
    duplicados (es_posible_duplicado=True) para no inflar los totales.
    """
    facturas = db.query(Factura).filter(
        Factura.empresa_id == empresa_id, Factura.es_posible_duplicado.is_(False),
    ).all()

    grupos: dict[str, dict] = {}
    etiquetas = {
        ("recibida", "factura"): "Facturas recibidas (compras)",
        ("recibida", "documento_equivalente"): "Documento equivalente recibido",
        ("recibida", "nota_credito"): "Notas crédito recibidas",
        ("recibida", "nota_debito"): "Notas débito recibidas",
        ("emitida", "factura"): "Facturas emitidas (ventas)",
        ("emitida", "documento_equivalente"): "Documento equivalente emitido",
        ("emitida", "nota_credito"): "Notas crédito emitidas",
        ("emitida", "nota_debito"): "Notas débito emitidas",
        ("no_aplica", "nomina"): "Nómina electrónica",
    }
    for f in facturas:
        clave = (f.direccion_documento or "no_aplica", f.naturaleza_documento or "factura")
        etiqueta = etiquetas.get(clave, f"{f.naturaleza_documento or '?'} ({f.direccion_documento or '?'})")
        g = grupos.setdefault(etiqueta, {"tipo": etiqueta, "cantidad": 0, "total": 0.0,
                                          "es_gasto": clave[0] == "recibida" or clave[1] == "nomina"})
        g["cantidad"] += 1
        g["total"] += float(f.total or 0)

    resultado = sorted(grupos.values(), key=lambda g: -g["total"])
    total_gastos = sum(g["total"] for g in resultado if g["es_gasto"])
    total_ingresos = sum(g["total"] for g in resultado if not g["es_gasto"])
    return {"grupos": resultado, "total_gastos": total_gastos, "total_ingresos": total_ingresos}


@router.post("/cargar", response_model=CargaResumen, status_code=201)
async def cargar_documentos(
    empresa_id: str,
    documentos: list[UploadFile] = File(..., description="Uno o varios .zip, y/o .xml/.pdf sueltos"),
    excel_file: UploadFile | None = File(default=None, alias="excel"),
    mapeo_cufe: str | None = Form(default=None),
    mapeo_numero_factura: str | None = Form(default=None),
    mapeo_nit_emisor: str | None = Form(default=None),
    mapeo_nombre_emisor: str | None = Form(default=None),
    mapeo_nit_receptor: str | None = Form(default=None, description="Necesario para que las facturas EMITIDAS (ventas) queden con el NIT del cliente cuando no hay XML que las respalde"),
    mapeo_nombre_receptor: str | None = Form(default=None),
    mapeo_fecha: str | None = Form(default=None),
    mapeo_prefijo: str | None = Form(default=None, description="Columna 'Prefijo' del Excel de la DIAN — usado para ordenar el archivo plano exportado"),
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
            "nit_receptor": mapeo_nit_receptor, "nombre_receptor": mapeo_nombre_receptor,
            "fecha": mapeo_fecha, "prefijo": mapeo_prefijo, "valor_total": mapeo_valor_total,
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
        desglose_clasificacion=resultado["desglose_clasificacion"],
        creado_en=carga.creado_en,
    )


@router.get("/panel-clasificacion")
def panel_clasificacion(empresa_id: str, modulo: str | None = None,
                         db: Session = Depends(get_db),
                         empresa: Empresa = Depends(get_empresa_activa)):
    """
    Agrupa las facturas pendientes de acción en tres bloques, para que
    el usuario no tenga que abrir una por una para saber qué hacer con
    cada una — pero SIN saltarse nunca la aprobación humana final
    (sección pedida: "más automatizado... igual sí dejarlo para
    revisión de un humano y aprobación"):

    - "listas": ya tienen partida generada y balanceada — solo falta
      un clic de "Contabilizar" para aprobarlas.
    - "con_sugerencia": no tienen partida generada todavía, pero el
      historial (o las cuentas propias con nombre reconocible) da una
      sugerencia confiable — se puede generar la propuesta en bloque,
      pero igual queda como "lista" (no contabilizada) hasta que el
      humano la apruebe.
    - "necesita_revision": no hay sugerencia confiable (proveedor nuevo,
      o solo candidatos genéricos del PUC) — requiere criterio humano,
      nunca se le inventa una cuenta.

    La nómina nunca entra en "con_sugerencia" (no se contabiliza
    automáticamente, sección ya existente).
    """
    q = db.query(Factura).filter(
        Factura.empresa_id == empresa_id,
        Factura.estado.in_([
            EstadoFactura.pendiente_revision, EstadoFactura.pendiente_clasificacion,
            EstadoFactura.extraida, EstadoFactura.clasificada, EstadoFactura.lista_para_contabilizar,
        ]),
        Factura.es_posible_duplicado.is_(False),
    )
    if modulo == "recibidas":
        q = q.filter(or_(Factura.naturaleza_documento == "nomina", Factura.direccion_documento == "recibida"))
    elif modulo == "emitidas":
        q = q.filter(Factura.direccion_documento == "emitida", Factura.naturaleza_documento != "nomina")
    facturas = q.order_by(Factura.creado_en.desc()).all()

    listas, con_sugerencia, necesita_revision = [], [], []

    for f in facturas:
        if f.estado == EstadoFactura.lista_para_contabilizar:
            listas.append({"id": f.id, "tercero_nombre": f.tercero_nombre, "tercero_nit": f.tercero_nit,
                            "numero_factura": f.numero_factura, "total": f.total,
                            "concepto_resumen": f.concepto_resumen})
            continue

        if f.naturaleza_documento == "nomina" or not f.tercero_nit:
            necesita_revision.append({"id": f.id, "tercero_nombre": f.tercero_nombre, "tercero_nit": f.tercero_nit,
                                       "numero_factura": f.numero_factura, "total": f.total,
                                       "concepto_resumen": f.concepto_resumen,
                                       "motivo": "Nómina electrónica — requiere registro manual." if f.naturaleza_documento == "nomina"
                                                 else "Sin NIT de tercero identificado."})
            continue

        sug = historial_service.sugerir_cuenta(db, empresa_id, f.tercero_nit, f.concepto_resumen, f.direccion_documento)
        if sug["fuente"] in ("historial", "historial_nit_concepto", "cuentas_propias") and sug["cuenta_sugerida"]:
            con_sugerencia.append({"id": f.id, "tercero_nombre": f.tercero_nombre, "tercero_nit": f.tercero_nit,
                                    "numero_factura": f.numero_factura, "total": f.total,
                                    "concepto_resumen": f.concepto_resumen,
                                    "cuenta_sugerida": sug["cuenta_sugerida"], "motivo_sugerencia": sug["motivo"],
                                    "fuente_sugerencia": sug["fuente"]})
        else:
            necesita_revision.append({"id": f.id, "tercero_nombre": f.tercero_nombre, "tercero_nit": f.tercero_nit,
                                       "numero_factura": f.numero_factura, "total": f.total,
                                       "concepto_resumen": f.concepto_resumen,
                                       "motivo": sug["motivo"]})

    return {"listas": listas, "con_sugerencia": con_sugerencia, "necesita_revision": necesita_revision}


@router.get("", response_model=list[FacturaOut])
def listar_facturas(
    empresa_id: str, estado: str | None = None, nit_emisor: str | None = None,
    numero_factura: str | None = None, confianza_max: float | None = None,
    naturaleza: str | None = None, direccion: str | None = None,
    modulo: str | None = None,
    db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa),
):
    """
    Filtros de la sección 29. `modulo` ("recibidas" | "emitidas") aplica
    la regla de negocio pedida por el usuario para separar los dos
    módulos de Facturas: la nómina SIEMPRE cae del lado de "recibidas"
    (porque contablemente siempre es un gasto), sin importar cómo la
    haya etiquetado la DIAN — nunca aparece en "emitidas", aunque su
    dirección cruda diga "emitida".
    """
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
    if modulo == "recibidas":
        q = q.filter(or_(Factura.naturaleza_documento == "nomina", Factura.direccion_documento == "recibida"))
    elif modulo == "emitidas":
        q = q.filter(Factura.direccion_documento == "emitida", Factura.naturaleza_documento != "nomina")
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
def _aplicar_partida_a_factura(db: Session, empresa: Empresa, empresa_id: str, f: Factura,
                                cuenta_gasto_codigo: Optional[str], contrapartida: str, origen_decision: str,
                                centro_costo_codigo: Optional[str], usuario: str):
    """
    Lógica compartida entre el endpoint individual y el masivo — genera
    la partida, la persiste si cuadra, y alimenta el historial. Devuelve
    (resultado_partida, error_o_None). Nunca decide una cuenta por su
    cuenta: cuenta_gasto_codigo siempre viene explícito de quien llama,
    salvo para nómina con el asiento multilínea automático (ahí no hace
    falta — las cuentas ya están configuradas en la empresa).
    """
    if f.estado == EstadoFactura.duplicada:
        return None, "Factura marcada como duplicada."
    if origen_decision not in ("manual", "sugerencia_aceptada"):
        return None, "origen_decision debe ser 'manual' o 'sugerencia_aceptada'."

    cuenta_gasto = historial_service.get_or_create_cuenta(db, empresa_id, cuenta_gasto_codigo) if cuenta_gasto_codigo else None
    if not cuenta_gasto and f.naturaleza_documento != "nomina":
        return None, "Debes indicar la cuenta de gasto/ingreso."

    # Contrapartida: si no se indicó explícitamente, se deriva de lo que
    # la empresa ya parametrizó (sección 38) — no hay que volver a
    # elegirla en cada factura. Una EMITIDA real (no nómina) siempre usa
    # clientes, sin importar el modo contable (misma prioridad que en
    # generar_partida — una venta real nunca debe ir por "proveedores").
    if not contrapartida:
        if f.direccion_documento == "emitida":
            contrapartida = "clientes"
        elif empresa.modo_contable == "solo_gastos":
            contrapartida = partida_doble_service._elegir_contrapartida_configurada(
                empresa, ("proveedores", "caja", "banco")) or "proveedores"
        else:
            contrapartida = "proveedores"

    centro_costo = None
    if centro_costo_codigo:
        from app.models.models import CentroCosto
        centro_costo = db.query(CentroCosto).filter(
            CentroCosto.empresa_id == empresa_id, CentroCosto.codigo == centro_costo_codigo
        ).first()
        if not centro_costo:
            return None, f"El centro de costo '{centro_costo_codigo}' no existe en esta empresa."

    resultado = partida_doble_service.generar_partida(
        db, empresa, f, cuenta_gasto.id if cuenta_gasto else None, contrapartida, centro_costo
    )

    if resultado.balanceado:
        partida_doble_service.persistir_partida(db, empresa_id, f, resultado)
        f.estado = EstadoFactura.lista_para_contabilizar

        if f.tercero_nit and cuenta_gasto:
            # Solo se alimenta el historial cuando el usuario SÍ eligió
            # una cuenta a mano — el asiento multilínea de nómina no
            # tiene "una" cuenta de gasto única que aprender, ya está
            # todo resuelto por configuración de la empresa.
            proveedor = historial_service.get_or_create_proveedor(db, empresa_id, f.tercero_nit, f.tercero_nombre)
            concepto_factura = None
            if f.conceptos_json:
                try:
                    items = json.loads(f.conceptos_json)
                    concepto_factura = "; ".join(i.get("descripcion", "") for i in items if i.get("descripcion"))[:500] or None
                except (ValueError, TypeError):
                    concepto_factura = None
            historial_service.registrar_decision(
                db, empresa_id, proveedor.id, cuenta_gasto.id,
                origen=OrigenDecision(origen_decision),
                fecha_documento=f.fecha_emision, numero_documento=f.numero_factura,
                descripcion=concepto_factura,
                valor=f.subtotal, importacion_id=None,
            )

        auditoria_registrar(db, empresa_id, "Factura", f.id, "partida_generada",
                             {"cuenta_gasto": cuenta_gasto.codigo if cuenta_gasto else "(asiento multilínea de nómina)",
                              "contrapartida": contrapartida, "total_debito": resultado.total_debito},
                             usuario)
        return resultado, None
    else:
        return resultado, "; ".join(resultado.errores)


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

    resultado, error = _aplicar_partida_a_factura(
        db, empresa, empresa_id, f, payload.cuenta_gasto_codigo, payload.contrapartida,
        payload.origen_decision, payload.centro_costo_codigo, payload.usuario or usuario,
    )
    if error and resultado is None:
        raise HTTPException(status_code=422, detail=error)

    if resultado.balanceado:
        db.commit()
    else:
        db.rollback()

    return PartidaOut(
        factura_id=factura_id,
        lineas=[LineaPartidaOut(cuenta_codigo=l.cuenta_codigo, cuenta_nombre=l.cuenta_nombre,
                                 tipo=l.tipo, valor=l.valor, descripcion=l.descripcion,
                                 centro_costo_codigo=l.centro_costo_codigo)
                for l in resultado.lineas],
        total_debito=resultado.total_debito, total_credito=resultado.total_credito,
        balanceado=resultado.balanceado, errores=resultado.errores,
    )


@router.post("/partida/generar-masivo")
def generar_partida_masivo(empresa_id: str, payload: dict, db: Session = Depends(get_db),
                            empresa: Empresa = Depends(get_empresa_activa),
                            usuario: str = Depends(usuario_actual)):
    """
    Genera partida doble para varias facturas en una sola llamada.

    Dos modos, según el cuerpo recibido:
    - {"factura_ids": [...], "cuenta_gasto_codigo": "513595", "contrapartida": "proveedores"}
      Aplica la MISMA cuenta a todas las facturas indicadas — útil
      cuando varias facturas del mismo NIT/tipo van a la misma cuenta.
    - {"factura_ids": [...], "usar_sugerencia": true}
      Para cada factura usa la sugerencia del historial — pero SOLO si
      la fuente es "historial" o "historial_nit_concepto" (confianza
      real, no un candidato genérico del PUC ni "sin información").
      Las que no tengan una sugerencia confiable se omiten y quedan
      reportadas con el motivo — nunca se inventa una cuenta al hacerlo
      en lote, igual que al hacerlo una por una.

    Devuelve el detalle de cada factura: aplicada, omitida (con motivo)
    o con error — nada se aplica en silencio.
    """
    factura_ids = payload.get("factura_ids") or []
    if not factura_ids:
        raise HTTPException(status_code=422, detail="factura_ids no puede estar vacío.")

    usar_sugerencia = bool(payload.get("usar_sugerencia"))
    cuenta_fija = payload.get("cuenta_gasto_codigo")
    contrapartida_fija = payload.get("contrapartida")
    centro_costo_codigo = payload.get("centro_costo_codigo")
    origen_decision = "sugerencia_aceptada" if usar_sugerencia else "manual"

    if not usar_sugerencia and not cuenta_fija:
        raise HTTPException(
            status_code=422,
            detail="Indica 'cuenta_gasto_codigo' (para aplicar la misma cuenta a todas), o "
                   "'usar_sugerencia: true' (para que cada una use su propia sugerencia del historial).",
        )

    facturas = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id.in_(factura_ids)).all()
    encontradas = {f.id: f for f in facturas}

    resultados = []
    aplicadas = 0
    for fid in factura_ids:
        f = encontradas.get(fid)
        if not f:
            resultados.append({"factura_id": fid, "estado": "no_encontrada"})
            continue

        cuenta_codigo = cuenta_fija
        if contrapartida_fija:
            contrapartida = contrapartida_fija
        elif f.direccion_documento == "emitida":
            contrapartida = "clientes"
        elif empresa.modo_contable == "solo_gastos":
            contrapartida = partida_doble_service._elegir_contrapartida_configurada(
                empresa, ("proveedores", "caja", "banco")) or "proveedores"
        else:
            contrapartida = "proveedores"

        if usar_sugerencia:
            if f.naturaleza_documento == "nomina":
                resultados.append({"factura_id": fid, "estado": "omitida",
                                    "motivo": "Es un documento de nómina, no se contabiliza automáticamente."})
                continue
            if not f.tercero_nit:
                resultados.append({"factura_id": fid, "estado": "omitida",
                                    "motivo": "La factura no tiene NIT de tercero."})
                continue
            concepto = None
            if f.conceptos_json:
                try:
                    items = json.loads(f.conceptos_json)
                    concepto = "; ".join(i.get("descripcion", "") for i in items if i.get("descripcion"))[:500] or None
                except (ValueError, TypeError):
                    concepto = None
            sug = historial_service.sugerir_cuenta(db, empresa_id, f.tercero_nit, concepto, f.direccion_documento)
            if sug["fuente"] not in ("historial", "historial_nit_concepto") or not sug["cuenta_sugerida"]:
                resultados.append({"factura_id": fid, "estado": "omitida",
                                    "motivo": f"Sin sugerencia confiable del historial (fuente: {sug['fuente']}) "
                                              f"— revísala manualmente en Facturas."})
                continue
            cuenta_codigo = sug["cuenta_sugerida"]

        resultado, error = _aplicar_partida_a_factura(
            db, empresa, empresa_id, f, cuenta_codigo, contrapartida, origen_decision,
            centro_costo_codigo, usuario,
        )
        if error and resultado is None:
            resultados.append({"factura_id": fid, "estado": "error", "motivo": error})
        elif not resultado.balanceado:
            db.rollback()
            resultados.append({"factura_id": fid, "estado": "descuadrada", "motivo": "; ".join(resultado.errores)})
        else:
            aplicadas += 1
            resultados.append({"factura_id": fid, "estado": "aplicada", "cuenta_usada": cuenta_codigo})

    db.commit()
    return {"total": len(factura_ids), "aplicadas": aplicadas,
            "omitidas": len(factura_ids) - aplicadas, "detalle": resultados}


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
                                 tipo=m.tipo, valor=float(m.valor), descripcion=m.descripcion or "",
                                 centro_costo_codigo=m.centro_costo.codigo if m.centro_costo else None)
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


@router.post("/tipo-comprobante-masivo")
def aplicar_tipo_comprobante_masivo(empresa_id: str, payload: dict, db: Session = Depends(get_db),
                                     empresa: Empresa = Depends(get_empresa_activa),
                                     usuario: str = Depends(usuario_actual)):
    """
    Fuerza manualmente, en bloque, en qué tipo de comprobante de Siigo
    se va a contabilizar un grupo de facturas seleccionadas — sin tener
    que hacerlo factura por factura. Si `tipo_comprobante` viene vacío
    o null, se QUITA el forzado (vuelve a usar la regla automática de
    la empresa según naturaleza/dirección del documento).
    """
    factura_ids = payload.get("factura_ids") or []
    tipo_comprobante = (payload.get("tipo_comprobante") or "").strip() or None
    if not factura_ids:
        raise HTTPException(status_code=422, detail="factura_ids no puede estar vacío.")

    facturas = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id.in_(factura_ids)).all()
    encontradas = {f.id: f for f in facturas}

    aplicadas = 0
    resultados = []
    for fid in factura_ids:
        f = encontradas.get(fid)
        if not f:
            resultados.append({"factura_id": fid, "estado": "no_encontrada"})
            continue
        f.tipo_comprobante_override = tipo_comprobante
        aplicadas += 1

    auditoria_registrar(db, empresa_id, "Factura", None, "tipo_comprobante_masivo_aplicado",
                         {"factura_ids": factura_ids, "tipo_comprobante": tipo_comprobante, "aplicadas": aplicadas},
                         usuario)
    db.commit()
    return {"aplicadas": aplicadas, "tipo_comprobante": tipo_comprobante, "resultados": resultados}


@router.post("/contabilizar-masivo")
def contabilizar_masivo(empresa_id: str, payload: dict, db: Session = Depends(get_db),
                         empresa: Empresa = Depends(get_empresa_activa),
                         usuario: str = Depends(usuario_actual)):
    """
    Aprueba varias facturas de una vez. Solo contabiliza las que ya
    están en 'lista_para_contabilizar' (con partida generada y
    balanceada) — las demás quedan reportadas como omitidas con el
    motivo, nada se fuerza.
    """
    factura_ids = payload.get("factura_ids") or []
    if not factura_ids:
        raise HTTPException(status_code=422, detail="factura_ids no puede estar vacío.")

    facturas = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id.in_(factura_ids)).all()
    encontradas = {f.id: f for f in facturas}

    resultados = []
    aprobadas = 0
    for fid in factura_ids:
        f = encontradas.get(fid)
        if not f:
            resultados.append({"factura_id": fid, "estado": "no_encontrada"})
            continue
        if f.estado != EstadoFactura.lista_para_contabilizar:
            resultados.append({"factura_id": fid, "estado": "omitida",
                                "motivo": f"Está en estado '{f.estado.value}', no 'lista_para_contabilizar'."})
            continue
        f.estado = EstadoFactura.contabilizada
        auditoria_registrar(db, empresa_id, "Factura", f.id, "contabilizacion_aprobada", {}, usuario)
        aprobadas += 1
        resultados.append({"factura_id": fid, "estado": "aprobada"})

    db.commit()
    return {"total": len(factura_ids), "aprobadas": aprobadas,
            "omitidas": len(factura_ids) - aprobadas, "detalle": resultados}


@router.delete("/{factura_id}")
def eliminar_factura(empresa_id: str, factura_id: str, db: Session = Depends(get_db),
                      empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Elimina una factura cargada por error o que ya no se necesita (ej.
    pruebas, duplicados de una carga fallida). Se borran también sus
    movimientos de partida doble asociados, si los tenía. El historial
    de aprendizaje (decisiones ya registradas) NO se toca — es una
    bitácora permanente independiente de si la factura sigue existiendo
    (secciones 11-12). Queda registro en auditoría de la eliminación.
    """
    f = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id == factura_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Factura no encontrada en esta empresa.")

    resumen = {"numero_factura": f.numero_factura, "cufe": f.cufe, "nit_emisor": f.nit_emisor, "estado": f.estado.value}
    db.query(Movimiento).filter(Movimiento.factura_id == factura_id).delete()
    db.delete(f)
    auditoria_registrar(db, empresa_id, "Factura", factura_id, "factura_eliminada", resumen, usuario)
    db.commit()
    return {"eliminada": True, "id": factura_id}


@router.post("/eliminar-multiples")
def eliminar_facturas_multiples(empresa_id: str, factura_ids: list[str], db: Session = Depends(get_db),
                                 empresa: Empresa = Depends(get_empresa_activa),
                                 usuario: str = Depends(usuario_actual)):
    """Elimina varias facturas de una vez (ej. limpiar una carga de prueba completa)."""
    if not factura_ids:
        raise HTTPException(status_code=422, detail="No se indicó ninguna factura para eliminar.")
    facturas = db.query(Factura).filter(Factura.empresa_id == empresa_id, Factura.id.in_(factura_ids)).all()
    if not facturas:
        raise HTTPException(status_code=404, detail="Ninguna de las facturas indicadas existe en esta empresa.")

    eliminadas = []
    for f in facturas:
        db.query(Movimiento).filter(Movimiento.factura_id == f.id).delete()
        eliminadas.append({"numero_factura": f.numero_factura, "cufe": f.cufe})
        db.delete(f)

    auditoria_registrar(db, empresa_id, "Factura", None, "facturas_eliminadas_lote",
                         {"cantidad": len(eliminadas), "facturas": eliminadas}, usuario)
    db.commit()
    return {"eliminadas": len(facturas), "no_encontradas": len(factura_ids) - len(facturas)}
