"""
Relación Excel DIAN <-> documentos del ZIP (sección 4) y detección de
duplicados (sección 26).

No depende de un único campo: intenta CUFE primero (el identificador
más confiable), luego número+NIT+fecha, luego NIT+fecha+total como
último recurso. Si ninguno da una coincidencia suficientemente segura,
la fila queda marcada para revisión manual — nunca se relaciona "a la
fuerza".
"""
import io
import json
import re
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import Factura, FuenteExtraccion, EstadoFactura
from app.services.zip_processing_service import DocumentoExtraido
from app.services.excel_utils import resolver_columna, leer_dataframe_excel
from app.services.clasificacion_dian_service import clasificar_desde_excel, es_tipo_descartable
from app.services.mapeo_dian_service import detectar_mapeo_excel_dian
from app.services.document_format_service import folio_sin_prefijo


def _leer_excel_dian(contenido: bytes, nombre_archivo: str) -> pd.DataFrame:
    return leer_dataframe_excel(contenido, nombre_archivo)


def _norm(v) -> str:
    return str(v).strip() if v not in (None, "") else ""


_PATRON_FECHA_ISO = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")


def _parse_fecha(v) -> Optional[datetime]:
    v = _norm(v)
    if not v:
        return None
    try:
        if _PATRON_FECHA_ISO.match(v):
            # Formato ISO (AAAA-MM-DD): no ambiguo, el año va primero.
            # dayfirst=True aquí produciría el error contrario al que
            # se quería corregir (confundiría mes y día).
            return pd.to_datetime(v, dayfirst=False).to_pydatetime()
        # Cualquier otro formato (ej. el DD-MM-AAAA que usa el Excel de
        # la DIAN) sí es ambiguo para pandas sin dayfirst=True.
        return pd.to_datetime(v, dayfirst=True).to_pydatetime()
    except Exception:
        return None


def _parse_valor(v) -> Optional[float]:
    """Convierte valores DIAN sin perder décimas/centavos por separadores locales."""
    txt = _norm(v)
    if not txt:
        return None
    txt = re.sub(r"[^0-9,.-]", "", txt)
    if not txt or txt in ("-", ".", ","):
        return None
    # Si existen punto y coma, el último separador se toma como decimal.
    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        partes = txt.split(",")
        if len(partes) == 2 and 1 <= len(partes[1]) <= 4:
            txt = partes[0].replace(".", "") + "." + partes[1]
        else:
            txt = txt.replace(",", "")
    try:
        return float(txt)
    except ValueError:
        return None


def _buscar_documento_para_fila(fila: dict, documentos: list[DocumentoExtraido]):
    """
    Intenta relacionar una fila del Excel con un documento del ZIP,
    probando varios identificadores en orden de confiabilidad.
    Devuelve (documento | None, metodo | None).
    """
    cufe_excel = _norm(fila.get("cufe")).lower()
    if cufe_excel:
        for doc in documentos:
            cufe_doc = str(doc.campos.get("cufe", "") or doc.campos.get("cufe_pdf", "")).lower()
            if cufe_doc and cufe_doc == cufe_excel:
                return doc, "cufe"
            if doc.clave_agrupacion == cufe_excel:
                return doc, "cufe"

    numero_excel = _norm(fila.get("numero_factura"))
    nit_excel = _norm(fila.get("nit_emisor"))
    if numero_excel and nit_excel:
        for doc in documentos:
            numero_doc = _norm(doc.campos.get("numero_factura"))
            nit_doc = _norm(doc.campos.get("nit_emisor"))
            if numero_doc and nit_doc and numero_doc == numero_excel and nit_doc == nit_excel:
                return doc, "numero_nit"

    fecha_excel = _norm(fila.get("fecha"))
    total_excel = _parse_valor(fila.get("valor_total"))
    if nit_excel and fecha_excel and total_excel is not None:
        for doc in documentos:
            nit_doc = _norm(doc.campos.get("nit_emisor"))
            fecha_doc = _norm(doc.campos.get("fecha_emision"))
            total_doc = doc.campos.get("total")
            try:
                total_doc = float(total_doc) if total_doc not in (None, "") else None
            except (ValueError, TypeError):
                total_doc = None
            if (nit_doc == nit_excel and fecha_doc[:10] == fecha_excel[:10]
                    and total_doc is not None and total_excel is not None
                    and abs(total_doc - total_excel) < 1):
                return doc, "nit_fecha_total"

    return None, None


def _buscar_duplicado(db: Session, empresa_id: str, cufe: str, numero_factura: str,
                       nit_emisor: str, fecha_emision, total) -> Optional[Factura]:
    q = db.query(Factura).filter(Factura.empresa_id == empresa_id)
    if cufe:
        existente = q.filter(Factura.cufe == cufe).first()
        if existente:
            return existente
    if numero_factura and nit_emisor:
        existente = q.filter(
            Factura.numero_factura == numero_factura,
            Factura.nit_emisor == nit_emisor,
        ).first()
        if existente:
            return existente
    return None


def _crear_factura_desde_documento(db: Session, empresa_id: str, carga_id: str,
                                    doc: DocumentoExtraido, relacionada: bool,
                                    metodo: Optional[str], motivo_no_relacionada: Optional[str],
                                    excel_fila: Optional[dict],
                                    naturaleza_override: Optional[str] = None,
                                    direccion_override: Optional[str] = None) -> Factura:
    c = dict(doc.campos or {})
    cufe = _norm(c.get("cufe"))
    numero = _norm(c.get("numero_factura"))
    prefijo = _norm(c.get("prefijo"))
    nit_emisor = _norm(c.get("nit_emisor"))
    nombre_emisor = _norm(c.get("nombre_emisor"))
    nomina_detalle = None
    if doc.naturaleza == "nomina" and c.get("nit_trabajador"):
        # El "tercero" de una nómina debe ser el EMPLEADO (para poder
        # cruzarlo con su ficha en el módulo de Empleados y armar el
        # asiento multilínea), no el empleador — la propia empresa. El
        # NIT/nombre del empleador se conserva en nomina_detalle_json
        # por si se necesita más adelante; nit_emisor/nombre_emisor (de
        # donde sale "tercero_nit"/"tercero_nombre") pasan a ser los
        # del trabajador.
        nomina_detalle = {
            "empleador_nit": nit_emisor, "empleador_nombre": nombre_emisor,
            "devengado_basico": c.get("devengado_basico", 0.0),
            "devengado_transporte": c.get("devengado_transporte", 0.0),
            "deduccion_salud": c.get("deduccion_salud", 0.0),
            "deduccion_pension": c.get("deduccion_pension", 0.0),
            "sueldo_base": c.get("sueldo_base", 0.0),
        }
        nit_emisor = _norm(c.get("nit_trabajador"))
        nombre_emisor = _norm(c.get("nombre_trabajador"))
    total = c.get("total")
    try:
        total = float(total) if total not in (None, "") else None
    except (ValueError, TypeError):
        total = None
    fecha_emision = _parse_fecha(c.get("fecha_emision"))
    nit_receptor = _norm(c.get("nit_receptor"))
    nombre_receptor = _norm(c.get("nombre_receptor"))

    # Si el documento SÍ se relacionó con una fila del Excel de la DIAN
    # pero el XML (por alguna variante de estructura) no trajo el NIT,
    # el nombre, el número, la fecha o el total, se completa con lo que
    # traiga esa fila del Excel en vez de dejarlo vacío — es la misma
    # factura, y la DIAN ya tiene ese dato aunque el XML no lo haya
    # expuesto en el lugar donde lo buscamos. Esto es especialmente
    # importante para el RECEPTOR: si la factura no vino acompañada de
    # su XML (solo la fila del Excel), antes se quedaba sin NIT/nombre
    # de receptor — y para una factura EMITIDA (venta), el receptor es
    # el dato que de verdad importa (el emisor ahí somos nosotros mismos).
    if excel_fila:
        if not nit_emisor:
            nit_emisor = _norm(excel_fila.get("nit_emisor"))
        if not nombre_emisor:
            nombre_emisor = _norm(excel_fila.get("nombre_emisor"))
        if not nit_receptor:
            nit_receptor = _norm(excel_fila.get("nit_receptor"))
        if not nombre_receptor:
            nombre_receptor = _norm(excel_fila.get("nombre_receptor"))
        if not numero:
            numero = _norm(excel_fila.get("numero_factura"))
        if not prefijo:
            prefijo = _norm(excel_fila.get("prefijo"))
        if not fecha_emision:
            fecha_emision = _parse_fecha(excel_fila.get("fecha"))

        # XML/PDF siguen siendo la fuente principal cuando traen el dato.
        # El Excel DIAN completa únicamente valores ausentes, sin recalcularlos.
        for campo in ("subtotal", "iva", "inc"):
            if c.get(campo) in (None, "") and excel_fila.get(campo) not in (None, ""):
                c[campo] = _parse_valor(excel_fila.get(campo))
        ret = dict(c.get("retenciones") or {})
        for campo in ("retefuente", "reteica", "reteiva"):
            if ret.get(campo) in (None, "", 0, 0.0) and excel_fila.get(campo) not in (None, ""):
                valor_ret = _parse_valor(excel_fila.get(campo))
                if valor_ret is not None:
                    ret[campo] = valor_ret
        c["retenciones"] = ret

    if total is None:
        total = _parse_valor(excel_fila.get("valor_total")) if excel_fila else None

    # Almacenar Prefijo y Folio realmente separados cuando el XML traía ambos
    # pegados (AR33356 / AR-33356) y el Excel DIAN suministró Prefijo=AR.
    if prefijo and numero:
        numero = folio_sin_prefijo(prefijo, numero)

    # Si no se pudo extraer un SUBTOTAL (pasa siempre con nómina — su
    # esquema XML no trae desglose de IVA — y a veces con facturas que
    # solo vinieron acompañadas de la fila del Excel), pero SÍ se tiene
    # el TOTAL, se usa el total como subtotal cuando no hay IVA/INC
    # registrado — evita generar una línea de partida en $0 mientras la
    # lista muestra el total correcto (bug real: el total se veía bien
    # en Facturas pero la partida generada quedaba en $0 porque la
    # partida doble siempre se calcula sobre el subtotal, no el total).
    subtotal_valor = c.get("subtotal")
    if subtotal_valor in (None, 0) and total not in (None, 0) and not c.get("iva") and not c.get("inc"):
        subtotal_valor = total

    duplicado = _buscar_duplicado(db, empresa_id, cufe, numero, nit_emisor, fecha_emision, total)

    # La clasificación del Excel de la DIAN ("Tipo de documento", "Grupo")
    # es más confiable que la inferida del XML — la DIAN ya resolvió la
    # ambigüedad de NIT/formato al generarlo. Si el usuario mapeó esas
    # columnas, tiene prioridad sobre lo que dedujimos del XML.
    naturaleza = naturaleza_override or doc.naturaleza
    direccion = direccion_override or doc.direccion

    estado = EstadoFactura.extraida
    if duplicado:
        estado = EstadoFactura.duplicada
    elif naturaleza == "nomina":
        # Esquema XML distinto al de factura; no se extraen conceptos de
        # nómina automáticamente — siempre requiere revisión manual.
        # Esta clasificación pesa más que el estado de relación con Excel.
        estado = EstadoFactura.pendiente_clasificacion
    elif direccion == "emitida":
        # Es una venta, no una compra: necesita cuentas de ingreso, no de
        # gasto — se deja para clasificación explícita en vez de arriesgar
        # una contabilización automática incorrecta.
        estado = EstadoFactura.pendiente_clasificacion
    elif doc.confianza < 70 or not relacionada:
        estado = EstadoFactura.pendiente_revision
    elif doc.fuente_extraccion in ("pdf_texto", "pdf_ocr"):
        # Sección 6: una factura obtenida únicamente de PDF NUNCA se
        # contabiliza automáticamente sin aprobación del usuario.
        estado = EstadoFactura.pendiente_revision

    fuente_map = {"xml": FuenteExtraccion.xml, "pdf_texto": FuenteExtraccion.pdf_texto,
                  "pdf_ocr": FuenteExtraccion.pdf_ocr}

    factura = Factura(
        empresa_id=empresa_id,
        carga_id=carga_id,
        cufe=cufe or None,
        numero_factura=numero or None,
        prefijo=prefijo or None,
        fecha_emision=fecha_emision,
        hora_emision=_norm(c.get("hora_emision")) or None,
        nit_emisor=nit_emisor or None,
        nombre_emisor=nombre_emisor or None,
        direccion_emisor=_norm(c.get("direccion_emisor")) or None,
        nit_receptor=nit_receptor or None,
        nombre_receptor=nombre_receptor or None,
        subtotal=subtotal_valor,
        base_gravable=c.get("base_gravable"),
        iva=c.get("iva"),
        inc=c.get("inc"),
        retenciones_json=json.dumps(c.get("retenciones", {}), default=str),
        total=total,
        moneda=_norm(c.get("moneda")) or "COP",
        forma_pago=_norm(c.get("forma_pago")) or None,
        conceptos_json=json.dumps(c.get("conceptos", []), ensure_ascii=False, default=str),
        nomina_detalle_json=json.dumps(nomina_detalle, ensure_ascii=False, default=str) if nomina_detalle else None,
        archivo_xml_path=doc.nombre_xml,
        archivo_pdf_path=doc.nombre_pdf,
        excel_fila_json=json.dumps(excel_fila, ensure_ascii=False, default=str) if excel_fila else None,
        fuente_extraccion=fuente_map.get(doc.fuente_extraccion, FuenteExtraccion.excel_dian),
        confianza_extraccion=doc.confianza,
        campos_extraidos_json=json.dumps(list(c.keys()), ensure_ascii=False),
        naturaleza_documento=naturaleza,
        direccion_documento=direccion,
        relacionada_con_excel=relacionada,
        metodo_relacion=metodo,
        motivo_no_relacionada=motivo_no_relacionada,
        es_posible_duplicado=bool(duplicado),
        duplicado_de_id=duplicado.id if duplicado else None,
        estado=estado,
        datos_originales_json=json.dumps(c, ensure_ascii=False, default=str),
    )
    db.add(factura)
    db.flush()
    return factura


def procesar_carga(db: Session, empresa_id: str, carga_id: str,
                    documentos_zip: list[DocumentoExtraido],
                    excel_bytes: Optional[bytes], excel_nombre: Optional[str],
                    mapeo_excel: Optional[dict]) -> dict:
    """
    Orquesta la relación completa y crea las Facturas resultantes.
    Devuelve contadores para el resumen de la carga (sección 30).
    """
    documentos_descartados = [d for d in documentos_zip if d.descartado_info is not None]
    documentos_validos = [d for d in documentos_zip if d.error is None and d.descartado_info is None]
    documentos_con_error = [d for d in documentos_zip if d.error is not None]

    filas_excel = []
    if excel_bytes:
        df = _leer_excel_dian(excel_bytes, excel_nombre or "excel.xlsx")
        columnas = list(df.columns)
        automatico = detectar_mapeo_excel_dian(columnas).get("mapeo", {})
        # El mapeo explícito del usuario manda; lo no indicado se completa
        # automáticamente con los títulos estándar reconocidos de la DIAN.
        solicitado = {k: v for k, v in (mapeo_excel or {}).items() if v}
        combinado = {**automatico, **solicitado}
        if not combinado:
            raise ValueError(
                "No se reconocieron columnas del Excel DIAN. Usa el mapeo avanzado para indicar al menos Folio/CUFE y los campos disponibles."
            )
        mapeo_resuelto = {}
        no_encontradas = []
        for c_interno, c_archivo in combinado.items():
            columna_real = resolver_columna(c_archivo, columnas)
            if not columna_real:
                no_encontradas.append(f"'{c_archivo}' (campo '{c_interno}')")
            else:
                mapeo_resuelto[c_interno] = columna_real
        if no_encontradas:
            raise ValueError(
                f"No se encontraron estas columnas en el archivo: {', '.join(no_encontradas)}. "
                f"Columnas disponibles en tu Excel: {columnas}"
            )
        for _, row in df.iterrows():
            fila = {campo: row.get(col) for campo, col in mapeo_resuelto.items()}
            # Ignorar líneas totalmente vacías del reporte.
            if any(_norm(v) for v in fila.values()):
                filas_excel.append(fila)

    # Filas del Excel que la propia DIAN marca como no-contables (ej.
    # "Application response") — se descartan aquí, antes de intentar
    # relacionarlas o crear cualquier factura con ellas.
    filas_descartadas_excel = []
    if any("tipo_documento" in f for f in filas_excel):
        filas_utiles = []
        for fila in filas_excel:
            tipo_doc = fila.get("tipo_documento")
            if tipo_doc and es_tipo_descartable(str(tipo_doc)):
                filas_descartadas_excel.append(fila)
            else:
                filas_utiles.append(fila)
        filas_excel = filas_utiles

    documentos_usados = set()
    relacionados = 0
    pendientes_revision = 0
    pendientes_clasificacion = 0
    duplicados = 0
    facturas_creadas = []

    # 1) Recorrer filas del Excel y buscar su documento correspondiente
    for fila in filas_excel:
        naturaleza_ov = direccion_ov = None
        if fila.get("tipo_documento") or fila.get("grupo"):
            c = clasificar_desde_excel(str(fila.get("tipo_documento") or ""), str(fila.get("grupo") or ""))
            naturaleza_ov = c["naturaleza"] or None
            direccion_ov = c["direccion"] or None

        doc, metodo = _buscar_documento_para_fila(fila, documentos_validos)
        if doc:
            documentos_usados.add(doc.clave_agrupacion)
            factura = _crear_factura_desde_documento(
                db, empresa_id, carga_id, doc, relacionada=True, metodo=metodo,
                motivo_no_relacionada=None, excel_fila=fila,
                naturaleza_override=naturaleza_ov, direccion_override=direccion_ov,
            )
            relacionados += 1
        else:
            # Fila del Excel sin XML/PDF asociado -> factura basada solo
            # en el Excel, marcada explícitamente para revisión.
            campos = {
                "numero_factura": _norm(fila.get("numero_factura")),
                "prefijo": _norm(fila.get("prefijo")),
                "cufe": _norm(fila.get("cufe")),
                "nit_emisor": _norm(fila.get("nit_emisor")),
                "nombre_emisor": _norm(fila.get("nombre_emisor")),
                "nit_receptor": _norm(fila.get("nit_receptor")),
                "nombre_receptor": _norm(fila.get("nombre_receptor")),
                "fecha_emision": _norm(fila.get("fecha")),
                "subtotal": _parse_valor(fila.get("subtotal")),
                "iva": _parse_valor(fila.get("iva")),
                "inc": _parse_valor(fila.get("inc")),
                "retenciones": {
                    "retefuente": _parse_valor(fila.get("retefuente")) or 0.0,
                    "reteica": _parse_valor(fila.get("reteica")) or 0.0,
                    "reteiva": _parse_valor(fila.get("reteiva")) or 0.0,
                },
                "total": _parse_valor(fila.get("valor_total")),
            }
            doc_ficticio = DocumentoExtraido(
                clave_agrupacion=f"excel::{campos['cufe'] or campos['numero_factura']}",
                fuente_extraccion="excel_dian", confianza=0.0, campos=campos,
            )
            factura = _crear_factura_desde_documento(
                db, empresa_id, carga_id, doc_ficticio, relacionada=False, metodo=None,
                motivo_no_relacionada="No se encontró un XML/PDF en el ZIP que coincida con "
                                       "esta fila del Excel por CUFE, número+NIT, ni NIT+fecha+total.",
                excel_fila=fila, naturaleza_override=naturaleza_ov, direccion_override=direccion_ov,
            )
        facturas_creadas.append(factura)
        if factura.estado == EstadoFactura.duplicada:
            duplicados += 1
        elif factura.estado == EstadoFactura.pendiente_revision:
            pendientes_revision += 1
        elif factura.estado == EstadoFactura.pendiente_clasificacion:
            pendientes_clasificacion += 1

    # 2) Documentos del ZIP que no se relacionaron con ninguna fila del Excel
    for doc in documentos_validos:
        if doc.clave_agrupacion in documentos_usados:
            continue
        motivo = (
            "No hay Excel cargado en esta sesión." if not filas_excel else
            "Este documento no coincide con ninguna fila del Excel de la DIAN cargado."
        )
        factura = _crear_factura_desde_documento(
            db, empresa_id, carga_id, doc, relacionada=False, metodo=None,
            motivo_no_relacionada=motivo, excel_fila=None,
        )
        facturas_creadas.append(factura)
        if factura.estado == EstadoFactura.duplicada:
            duplicados += 1
        elif factura.estado == EstadoFactura.pendiente_revision:
            pendientes_revision += 1
        elif factura.estado == EstadoFactura.pendiente_clasificacion:
            pendientes_clasificacion += 1

    desglose: dict[str, int] = {}
    for f in facturas_creadas:
        clave = f"{f.naturaleza_documento}_{f.direccion_documento}"
        desglose[clave] = desglose.get(clave, 0) + 1

    return {
        "facturas": facturas_creadas,
        "total_filas_excel": len(filas_excel) + len(filas_descartadas_excel),
        "total_archivos_zip_validos": len(documentos_validos),
        "total_archivos_zip_error": len(documentos_con_error),
        "errores_zip": [{"clave": d.clave_agrupacion, "error": d.error} for d in documentos_con_error],
        "total_descartados": len(documentos_descartados) + len(filas_descartadas_excel),
        "avisos_descarte": (
            [{"clave": d.clave_agrupacion, "aviso": d.descartado_info} for d in documentos_descartados]
            + [{"clave": f.get("cufe") or f.get("numero_factura") or "(sin identificar)",
                "aviso": f"Fila del Excel de tipo '{f.get('tipo_documento')}' — no es un documento contable, se omitió."}
               for f in filas_descartadas_excel]
        ),
        "desglose_clasificacion": desglose,
        "total_relacionados": relacionados,
        "total_pendientes_revision": pendientes_revision,
        "total_pendientes_clasificacion": pendientes_clasificacion,
        "total_duplicados": duplicados,
    }
