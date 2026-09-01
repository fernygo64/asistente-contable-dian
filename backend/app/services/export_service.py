"""
Generación del archivo de exportación (secciones 22-23, 39).

Flujo: CONTABILIZACIÓN INTERNA -> PLANTILLA DE LA EMPRESA -> ARCHIVO.
La lógica contable (movimientos, cuentas, valores) nunca depende de
las columnas de Siigo o World Office — eso se resuelve aquí, en la
capa de exportación, aplicando la plantilla configurada.
"""
import json
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import Empresa, Factura, Movimiento, PlantillaExportacion, EstadoFactura
from app.services.siigo_config_service import (
    configuraciones_empresa, tipo_documento_clave, parametros_cuentas_empresa, proyectar_numeros, folio_dian_factura,
)
from app.services.export_adapters import obtener_adaptador
from app.services.siigo_historial_service import construir_indice_historial_siigo, inferir_parametros_movimiento
from app.services.document_format_service import ordenar_documentos, prefijo_folio


def _tipo_comprobante_para_factura(empresa: Empresa, factura: Factura) -> str:
    """
    Resuelve el tipo de comprobante configurado en la empresa según la
    clasificación real del documento — nunca el mismo para compras,
    ventas, notas y nómina (sección 19-21, confirmado con archivos
    reales de Siigo/World Office que usan comprobantes distintos).

    Si el usuario forzó manualmente un tipo de comprobante en bloque
    para esta factura (sección pedida: escoger masivamente en qué tipo
    de documento se contabiliza, sin hacerlo factura por factura), ese
    valor manda sobre la regla automática.
    """
    if factura.tipo_comprobante_override:
        return factura.tipo_comprobante_override
    if factura.naturaleza_documento == "nota_credito":
        return empresa.comprobante_nota_credito or ""
    if factura.naturaleza_documento == "nota_debito":
        return empresa.comprobante_nota_debito or ""
    if factura.naturaleza_documento == "nomina":
        return empresa.comprobante_nomina or ""
    if factura.naturaleza_documento == "documento_equivalente":
        return empresa.comprobante_documento_equivalente or ""
    if factura.direccion_documento == "emitida":
        return empresa.comprobante_factura_emitida or ""
    return empresa.comprobante_factura_recibida or ""


def _formatear_codigo_cuenta(codigo: str, empresa: Optional[Empresa]) -> str:
    """
    Regla real de Siigo Pyme (confirmada por el usuario y visible en su
    archivo de "Movimiento Contable" real: códigos como "5120950000",
    "2205010000"): la cuenta contable SIEMPRE se exporta con exactamente
    10 dígitos, rellenando con CEROS A LA DERECHA si el código propio es
    más corto (ej. "110505" -> "1105050000"). Nunca se rellena por la
    izquierda (eso cambiaría el significado del código) ni se recorta un
    código que ya sea de 10 o más dígitos.
    """
    if not empresa or empresa.sistema_contable != "siigo_pyme":
        return codigo
    if not codigo.isdigit():
        return codigo  # un código no numérico no sigue esta regla; se deja tal cual
    if len(codigo) >= 10:
        return codigo
    return codigo.ljust(10, "0")



def _descripcion_exportacion_siigo(factura: Factura, param_cuenta_siigo=None) -> str:
    """Descripción SIIGO sin mezclarla con la clave interna de orden.

    Si el historial compatible muestra un formato estable, reutilizamos solo
    el texto que rodea el número de factura y colocamos el PREFIJO-FOLIO
    actual. Si no hay evidencia, usamos ``PREFIJO-FOLIO + concepto breve``.
    """
    documento = prefijo_folio(factura.prefijo, factura.numero_factura)
    pref_hist = str(getattr(param_cuenta_siigo, "descripcion_prefijo", "") or "").strip()
    suf_hist = str(getattr(param_cuenta_siigo, "descripcion_sufijo", "") or "").strip()
    if documento and (pref_hist or suf_hist):
        texto = " ".join(x for x in (pref_hist, documento, suf_hist) if x).strip()
    else:
        concepto = str(factura.concepto_resumen or "").strip()
        texto = " ".join(x for x in (documento, concepto) if x).strip()
    if not texto:
        texto = f"Factura {factura.numero_factura or ''}".strip()
    texto = " ".join(texto.upper().split())[:50]
    return texto.ljust(50)

def _valor_relacion_aprendida(relacion: str, factura: Factura, numero_documento_calculado: Optional[str],
                               config_siigo: Optional[dict] = None) -> Optional[str]:
    """Resuelve relaciones aprendidas sin copiar números/fechas históricos."""
    if relacion == "tipo_codigo_comprobante":
        tipo = factura.tipo_comprobante_override or (config_siigo or {}).get("tipo_comprobante") or ""
        codigo = (config_siigo or {}).get("codigo_comprobante") or ""
        if not tipo or not codigo:
            return None
        try:
            codigo = f"{int(str(codigo)) :03d}"
        except Exception:
            codigo = str(codigo).zfill(3)
        return f"{tipo}-{codigo}"
    if relacion == "numero_documento":
        return numero_documento_calculado or ""
    if not factura.fecha_emision:
        return None
    if relacion == "anio":
        return str(factura.fecha_emision.year)
    if relacion == "mes":
        return str(factura.fecha_emision.month)
    if relacion == "dia":
        return str(factura.fecha_emision.day)
    return None


def _valor_columna(columna: dict, factura: Factura, movimiento: Movimiento,
                    equivalencias: dict, formato_fecha: str, empresa: Optional[Empresa] = None,
                    numero_documento_calculado: Optional[str] = None,
                    config_siigo: Optional[dict] = None, param_cuenta_siigo=None) -> str:
    source = columna.get("source")
    fijo = columna.get("valor_fijo", "")

    if source == "fijo":
        # SIIGO no usa un único default universal por columna: el historial
        # real demuestra que algunas cuentas/tipos de comprobante exigen
        # producto, bodega, forma de pago, cruce, etc. La fila histórica
        # completa se consulta ANTES del default global. Solo llegan aquí
        # valores que el motor de aprendizaje encontró estables.
        if empresa and empresa.sistema_contable == "siigo_pyme" and param_cuenta_siigo is not None:
            relacion = param_cuenta_siigo.relacion_tecnica(columna.get("label", "")) \
                if hasattr(param_cuenta_siigo, "relacion_tecnica") else None
            if relacion:
                resuelto = _valor_relacion_aprendida(relacion, factura, numero_documento_calculado, config_siigo)
                if resuelto is not None:
                    return str(resuelto)
            aprendido = param_cuenta_siigo.valor_tecnico(columna.get("label", "")) \
                if hasattr(param_cuenta_siigo, "valor_tecnico") else None
            if aprendido is not None:
                return str(aprendido)
        if fijo not in (None, ""):
            return str(fijo)
        # Respaldo de seguridad: si la plantilla SIIGO trae una columna
        # desconocida, nunca se elimina la posición; se deja un espacio.
        if empresa and empresa.sistema_contable == "siigo_pyme":
            return " "
        return ""
    if source == "fecha_generacion":
        # Fecha en que se genera ESTE archivo (no la de la factura) —
        # columna real de Siigo Pyme "FECHA ACTUALIZACIÓN DEL DOCUMENTO",
        # formato YYYYMMDD confirmado contra archivo real.
        return datetime.now().strftime("%Y%m%d")
    if source == "hora_generacion":
        # Misma idea, columna "HORA DE ACTUALIZACIÓN DEL DOCUMENTO",
        # formato HHMMSS confirmado contra archivo real.
        return datetime.now().strftime("%H%M%S")
    if source == "tipo_comprobante":
        if factura.tipo_comprobante_override:
            return factura.tipo_comprobante_override
        valor = (config_siigo or {}).get("tipo_comprobante") if config_siigo else None
        if not valor:
            valor = _tipo_comprobante_para_factura(empresa, factura) if empresa else ""
        return valor or fijo
    if source == "codigo_comprobante_siigo":
        return str((config_siigo or {}).get("codigo_comprobante") or fijo or " ")
    if source == "codigo_vendedor_siigo":
        valor = getattr(param_cuenta_siigo, "codigo_vendedor", None) if param_cuenta_siigo else None
        return str(valor or (config_siigo or {}).get("codigo_vendedor_default") or fijo or " ")
    if source == "codigo_ciudad_siigo":
        valor = getattr(param_cuenta_siigo, "codigo_ciudad", None) if param_cuenta_siigo else None
        return str(valor or (config_siigo or {}).get("codigo_ciudad_default") or fijo or " ")
    if source == "codigo_zona_siigo":
        valor = getattr(param_cuenta_siigo, "codigo_zona", None) if param_cuenta_siigo else None
        return str(valor or (config_siigo or {}).get("codigo_zona_default") or fijo or "0")
    if source == "subcentro_siigo":
        valor = getattr(param_cuenta_siigo, "subcentro_costo", None) if param_cuenta_siigo else None
        return str(valor or (config_siigo or {}).get("subcentro_costo_default") or fijo or "0")
    if source == "sucursal_siigo":
        valor = getattr(param_cuenta_siigo, "sucursal", None) if param_cuenta_siigo else None
        return str(valor or (config_siigo or {}).get("sucursal_default") or fijo or "0")
    if source == "centro_costo_siigo":
        if movimiento.centro_costo:
            return str(movimiento.centro_costo.codigo)
        valor = getattr(param_cuenta_siigo, "centro_costo", None) if param_cuenta_siigo else None
        return str(valor or (config_siigo or {}).get("centro_costo_default") or fijo or "0")
    if source == "numero_documento":
        # El consecutivo INTERNO de Siigo que agrupa las líneas de un
        # mismo comprobante (verificado contra archivo real del
        # usuario: 1,1,1 -> 2,2,2,2 -> 3,3... reinicia en 1 por cada
        # tipo de comprobante) — NUNCA es el número real de la factura,
        # salvo para ventas emitidas (tipo "F"), donde Siigo sí usa el
        # número real. Ver _calcular_numeros_documento().
        return numero_documento_calculado or fijo
    if source == "fecha":
        return factura.fecha_emision.strftime(formato_fecha) if factura.fecha_emision else fijo
    if source == "anio":
        return str(factura.fecha_emision.year) if factura.fecha_emision else fijo
    if source == "mes":
        return str(factura.fecha_emision.month) if factura.fecha_emision else fijo
    if source == "dia":
        return str(factura.fecha_emision.day) if factura.fecha_emision else fijo
    if source == "cuenta":
        codigo = movimiento.cuenta.codigo
        codigo = equivalencias.get(codigo, codigo)
        return _formatear_codigo_cuenta(codigo, empresa)
    if source == "nombre_cuenta":
        return movimiento.cuenta.nombre
    if source == "nit":
        if movimiento.tercero_nit_override:
            return movimiento.tercero_nit_override
        if empresa and empresa.sistema_contable == "siigo_pyme" and param_cuenta_siigo is not None:
            if not bool(param_cuenta_siigo.maneja_tercero):
                return str(param_cuenta_siigo.nit_tecnico_exportacion or "0")
        return factura.tercero_nit or fijo
    if source == "tercero":
        return movimiento.tercero_nombre_override or factura.tercero_nombre or fijo
    if source == "numero_factura":
        return factura.numero_factura or fijo
    if source == "cufe":
        return factura.cufe or fijo
    if source == "concepto_siigo":
        return _descripcion_exportacion_siigo(factura, param_cuenta_siigo)
    if source == "concepto":
        if empresa and empresa.sistema_contable == "siigo_pyme":
            return _descripcion_exportacion_siigo(factura, param_cuenta_siigo)
        return movimiento.descripcion or f"Factura {factura.numero_factura or ''}"
    if source == "debito_credito":
        # Estructura real de Siigo Pyme (Movimiento Contable): una sola
        # columna con "D" o "C" en vez de dos columnas separadas.
        return "D" if movimiento.tipo == "debito" else "C"
    if source == "valor":
        # El valor del movimiento sin importar si es débito o crédito —
        # se usa junto con "debito_credito" (columna aparte indica el lado).
        return f"{float(movimiento.valor):.2f}"
    if source == "debito":
        return f"{float(movimiento.valor):.2f}" if movimiento.tipo == "debito" else ""
    if source == "credito":
        return f"{float(movimiento.valor):.2f}" if movimiento.tipo == "credito" else ""
    if source == "centro_costo":
        # Código real del centro de costo de ESTA línea, o "0" cuando no
        # aplica — confirmado contra archivo real de Siigo Pyme (columna
        # "CENTRO DE COSTO" usa 0 para las líneas sin centro de costo).
        return movimiento.centro_costo.codigo if movimiento.centro_costo else (str(fijo) if fijo else "0")
    if source == "secuencia_linea":
        # Posición de esta línea dentro de su propio comprobante (1, 2,
        # 3...) — columna real "SECUENCIA" de Siigo Pyme, ya se rastrea
        # como Movimiento.orden (0-indexado, aquí se muestra 1-indexado).
        return str((movimiento.orden or 0) + 1)
    return fijo


def validar_exportacion_detallada(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                                  facturas: list[Factura]) -> dict[str, list[str]]:
    """Separa bloqueos contables/estructurales de advertencias corregibles.

    ``bloqueantes`` jamás pueden omitirse (por ejemplo Débito != Crédito).
    ``advertencias`` pueden asumirse al generar el XLSX bajo responsabilidad
    del usuario y corregirse posteriormente en el software contable.
    """
    bloqueantes: list[str] = []
    advertencias: list[str] = []
    sistema = plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value") else plantilla.sistema_contable
    adaptador = obtener_adaptador(sistema)
    columnas = json.loads(plantilla.columnas_json)

    bloqueantes += adaptador.validar_plantilla(columnas)
    if not columnas:
        bloqueantes.append("La plantilla no tiene columnas configuradas.")

    es_siigo = sistema == "siigo_pyme"
    cfgs_siigo = configuraciones_empresa(db, empresa) if es_siigo else {}
    plantilla_siigo_completa = es_siigo and len(columnas) >= 100
    indice_siigo = construir_indice_historial_siigo(db, empresa.id) if plantilla_siigo_completa else None
    campos_criticos = {
        "CENTRO DE COSTO", "SUBCENTRO DE COSTO",
        "LÍNEA PRODUCTO", "GRUPO PRODUCTO", "CÓDIGO PRODUCTO",
        "CÓDIGO DE LA BODEGA", "CÓDIGO DE LA UBICACIÓN",
        "TIPO Y COMPROBANTE CRUCE", "NÚMERO DE DOCUMENTO CRUCE",
    }

    filas_por_validar = []
    for f in facturas:
        if f.estado not in (EstadoFactura.lista_para_contabilizar, EstadoFactura.contabilizada, EstadoFactura.exportada):
            bloqueantes.append(
                f"La factura {f.numero_factura or f.id} está en estado '{f.estado.value}' — "
                f"debe generar y aprobar su partida doble antes de exportarla."
            )
            continue
        if plantilla_siigo_completa:
            cfg = cfgs_siigo.get(tipo_documento_clave(f), {})
            tipo_efectivo = f.tipo_comprobante_override or cfg.get("tipo_comprobante")
            if not tipo_efectivo:
                bloqueantes.append(f"La factura {f.numero_factura or f.id} no tiene Tipo SIIGO configurado para su clase documental.")
            if not cfg.get("codigo_comprobante"):
                bloqueantes.append(f"La factura {f.numero_factura or f.id} no tiene Código SIIGO configurado para su clase documental.")
            if cfg.get("modo_numeracion") == "folio_dian" and not folio_dian_factura(f):
                bloqueantes.append(f"La factura {f.numero_factura or f.id} usa numeración Folio DIAN, pero no tiene un Folio numérico utilizable.")

        movimientos = db.query(Movimiento).filter(Movimiento.factura_id == f.id).order_by(Movimiento.orden).all()
        if not movimientos:
            bloqueantes.append(f"La factura {f.numero_factura or f.id} no tiene movimientos contables generados.")
            continue
        total_d = sum(float(m.valor) for m in movimientos if str(getattr(m.tipo, "value", m.tipo)) == "debito")
        total_c = sum(float(m.valor) for m in movimientos if str(getattr(m.tipo, "value", m.tipo)) == "credito")
        if abs(total_d - total_c) >= 0.01:
            bloqueantes.append(f"La factura {f.numero_factura or f.id} no está balanceada (débito {total_d} vs crédito {total_c}).")

        # Estar balanceado NO basta: una partida anterior puede cuadrar por
        # sí sola y aun así omitir un cargo, descuento o ajuste del Total DIAN.
        # Antes de exportar, ambos lados deben reproducir también el valor
        # fiscal final del documento. Si no, se obliga a regenerar la partida
        # con las reglas actuales en vez de sacar un XLSX contablemente
        # balanceado pero distinto de la DIAN.
        total_dian = float(f.total or 0)
        if abs(total_d - total_dian) >= 0.01 or abs(total_c - total_dian) >= 0.01:
            bloqueantes.append(
                f"La factura {f.numero_factura or f.id} tiene movimientos por "
                f"{round(total_d, 2)} pero el Total DIAN es {round(total_dian, 2)}. "
                f"Regenera la partida antes de exportar; puede existir un cargo, descuento o ajuste no incorporado."
            )
        if not any(str(getattr(m.tipo, "value", m.tipo)) == "debito" for m in movimientos) or not any(str(getattr(m.tipo, "value", m.tipo)) == "credito" for m in movimientos):
            bloqueantes.append(f"La factura {f.numero_factura or f.id} debe tener al menos una línea Débito y una Crédito, incluso si el valor es $0.")
        if not f.fecha_emision:
            bloqueantes.append(f"La factura {f.numero_factura or f.id} no tiene fecha de emisión válida.")
        if not f.tercero_nit:
            mensaje = (f"La factura {f.numero_factura or f.id} no tiene NIT de tercero "
                       f"({'receptor' if f.direccion_documento == 'emitida' else 'emisor'}).")
            (advertencias if es_siigo else bloqueantes).append(mensaje)

        for m in movimientos:
            if plantilla_siigo_completa and indice_siigo is not None:
                cfg = cfgs_siigo.get(tipo_documento_clave(f), {})
                tipo_efectivo = f.tipo_comprobante_override or cfg.get("tipo_comprobante") or ""
                param = inferir_parametros_movimiento(
                    indice_siigo, m.cuenta.codigo, m.tercero_nit_override or f.tercero_nit,
                    tipo_efectivo, cfg.get("codigo_comprobante") or "",
                    f.concepto_resumen or m.descripcion,
                )
                ambiguos = [x for x in param.ambiguos if " ".join(str(x).upper().split()) in campos_criticos]
                if ambiguos:
                    advertencias.append(
                        f"{f.numero_factura or f.id} · cuenta {m.cuenta.codigo}: el historial muestra más de un valor posible para "
                        + ", ".join(sorted(set(ambiguos))) + ". Puedes corregirlo al cargar en el programa contable."
                    )
            filas_por_validar.append({
                "Fecha": f.fecha_emision.strftime(plantilla.formato_fecha) if f.fecha_emision else "",
                "Cuenta": m.cuenta.codigo, "Nit": f.tercero_nit or "", "Tercero": f.tercero_nombre or "",
                "Debito": float(m.valor) if str(getattr(m.tipo, "value", m.tipo)) == "debito" else 0,
                "Credito": float(m.valor) if str(getattr(m.tipo, "value", m.tipo)) == "credito" else 0,
            })

    if filas_por_validar:
        validaciones_destino = adaptador.validar_negocio(filas_por_validar)
        if es_siigo:
            advertencias += validaciones_destino
        else:
            bloqueantes += validaciones_destino

    return {"bloqueantes": bloqueantes, "advertencias": advertencias}


def validar_exportacion(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                         facturas: list[Factura]) -> list[str]:
    """Compatibilidad con llamadas anteriores: devuelve todos los mensajes."""
    r = validar_exportacion_detallada(db, empresa, plantilla, facturas)
    return r["bloqueantes"] + r["advertencias"]


def agrupar_y_ordenar_facturas(facturas: list[Factura]) -> list[Factura]:
    """Compatibilidad de nombre: ya NO agrupa por tipo documental.

    Orden canónico: Fecha Emisión completa ascendente -> Prefijo -> Folio ->
    Nombre Emisor. La Nota Crédito/Débito conserva su clase y comprobante, pero
    no altera la secuencia cronológica del lote.
    """
    return ordenar_documentos(list(facturas))



def _calcular_numeros_documento(empresa: Optional[Empresa], facturas: list[Factura]) -> dict[str, str]:
    """
    El "NÚMERO DE DOCUMENTO" de Siigo NO es el número real de la
    factura — es un consecutivo INTERNO que agrupa las líneas de un
    mismo comprobante, y reinicia en 1 por cada tipo de comprobante
    (verificado al detalle contra un archivo real de ejemplo del
    usuario: G iba 1,1,1 -> 2,2,2,2,2 -> 3,3...; R reiniciaba en 1 por
    su cuenta; N -aunque tuviera 10 líneas- usaba un solo consecutivo
    para toda la nómina). La ÚNICA excepción real observada: las
    facturas EMITIDAS que no son nómina (tipo "F" = ventas) sí usan el
    número real de la factura tal cual, no un consecutivo.

    Devuelve {factura_id: "numero_a_usar"} — se calcula UNA vez por
    archivo completo, en el mismo orden ya agrupado/ordenado que
    generar_archivo() usa para las filas, para que el agrupamiento por
    tipo de comprobante coincida con lo que el usuario ve en el archivo.
    """
    contadores: dict[str, int] = {}
    resultado: dict[str, str] = {}
    for f in facturas:
        es_venta_real = f.direccion_documento == "emitida" and f.naturaleza_documento != "nomina"
        if es_venta_real:
            resultado[f.id] = f.numero_factura or ""
            continue
        tipo = _tipo_comprobante_para_factura(empresa, f) if empresa else ""
        contadores[tipo] = contadores.get(tipo, 0) + 1
        resultado[f.id] = str(contadores[tipo])
    return resultado


def generar_filas(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                   facturas: list[Factura], numeros_documento: Optional[dict[str, str]] = None):
    """Devuelve (columnas, filas, cantidad). Mantiene las 123 posiciones sin serializar."""
    facturas = agrupar_y_ordenar_facturas(facturas)
    columnas = json.loads(plantilla.columnas_json)
    equivalencias = json.loads(plantilla.equivalencias_cuentas_json or "{}")
    es_siigo = (plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value") else plantilla.sistema_contable) == "siigo_pyme"
    cfgs_siigo = configuraciones_empresa(db, empresa) if es_siigo else {}
    if numeros_documento is None:
        numeros_documento = proyectar_numeros(db, empresa, facturas) if es_siigo else _calcular_numeros_documento(empresa, facturas)
    indice_historial_siigo = construir_indice_historial_siigo(db, empresa.id) if es_siigo else None
    params_manual_siigo = parametros_cuentas_empresa(db, empresa.id) if es_siigo else {}

    filas = []
    for f in facturas:
        movimientos = db.query(Movimiento).filter(Movimiento.factura_id == f.id).order_by(Movimiento.orden).all()
        cfg_siigo = cfgs_siigo.get(tipo_documento_clave(f), {}) if es_siigo else None
        for m in movimientos:
            param_siigo = None
            if es_siigo:
                cuenta_exportada = equivalencias.get(m.cuenta.codigo, m.cuenta.codigo)
                cuenta_exportada = _formatear_codigo_cuenta(cuenta_exportada, empresa)
                nit_actual = m.tercero_nit_override or f.tercero_nit
                param_siigo = inferir_parametros_movimiento(
                    indice_historial_siigo, cuenta_exportada, nit_actual,
                    f.tipo_comprobante_override or (cfg_siigo or {}).get("tipo_comprobante"),
                    (cfg_siigo or {}).get("codigo_comprobante"),
                    f.concepto_resumen or m.descripcion or _descripcion_exportacion_siigo(f),
                )
                if getattr(param_siigo, "coincidencias", 0) == 0 and m.cuenta_id in params_manual_siigo:
                    param_siigo = params_manual_siigo[m.cuenta_id]
            valores = [
                _valor_columna(c, f, m, equivalencias, plantilla.formato_fecha, empresa,
                               numeros_documento.get(f.id), cfg_siigo, param_siigo)
                for c in columnas
            ]
            filas.append(valores)
    return columnas, filas, len(filas)


def generar_archivo(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                     facturas: list[Factura], numeros_documento: Optional[dict[str, str]] = None) -> tuple[bytes, int]:
    """Archivo plano, conservado principalmente para World Office y compatibilidad."""
    columnas, filas, total_filas = generar_filas(db, empresa, plantilla, facturas, numeros_documento)
    delimitador = "\t" if plantilla.delimitador == "\\t" else plantilla.delimitador
    lineas = []
    if plantilla.incluir_encabezado:
        lineas.append(delimitador.join(c["label"] for c in columnas))
    for fila in filas:
        lineas.append(delimitador.join(str(v).replace(delimitador, " ") for v in fila))
    contenido = ("\r\n".join(lineas)).encode("cp1252", errors="replace")
    return contenido, total_filas

