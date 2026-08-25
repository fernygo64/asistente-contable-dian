"""
Generación del archivo de exportación (secciones 22-23, 39).

Flujo: CONTABILIZACIÓN INTERNA -> PLANTILLA DE LA EMPRESA -> ARCHIVO.
La lógica contable (movimientos, cuentas, valores) nunca depende de
las columnas de Siigo o World Office — eso se resuelve aquí, en la
capa de exportación, aplicando la plantilla configurada.
"""
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import Empresa, Factura, Movimiento, PlantillaExportacion, EstadoFactura
from app.services.siigo_config_service import (
    configuraciones_empresa, tipo_documento_clave, parametros_cuentas_empresa, proyectar_numeros,
)
from app.services.export_adapters import obtener_adaptador


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



def _descripcion_exportacion_siigo(factura: Factura) -> str:
    """Descripción uniforme por comprobante sin alterar Movimiento.descripcion histórico."""
    partes = [str(x).strip() for x in (factura.prefijo, factura.numero_factura) if x and str(x).strip()]
    documento = "-".join(partes)
    concepto = factura.concepto_resumen or ""
    texto = " ".join(x for x in (documento, concepto) if x).strip()
    if not texto:
        texto = f"Factura {factura.numero_factura or ''}".strip()
    # El archivo real usa un campo corto de descripción. Se conserva un ancho estable de 50.
    texto = " ".join(texto.upper().split())[:50]
    return texto.ljust(50)


def _valor_columna(columna: dict, factura: Factura, movimiento: Movimiento,
                    equivalencias: dict, formato_fecha: str, empresa: Optional[Empresa] = None,
                    numero_documento_calculado: Optional[str] = None,
                    config_siigo: Optional[dict] = None, param_cuenta_siigo=None) -> str:
    source = columna.get("source")
    fijo = columna.get("valor_fijo", "")

    if source == "fijo":
        if fijo not in (None, ""):
            return str(fijo)
        # Respaldo de seguridad: en Siigo Pyme ninguna celda del archivo
        # real queda genuinamente vacía — las que no se pueden llenar
        # con certeza (ej. si una columna nueva de Siigo no calza con
        # ninguna de las reconocidas) llevan un espacio, nunca nada.
        # Confirmado por el usuario contra su propio archivo real
        # (verificado exhaustivamente: 0/espacio/texto en blanco, jamás
        # una celda vacía de la S en adelante).
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
        return _descripcion_exportacion_siigo(factura)
    if source == "concepto":
        if empresa and empresa.sistema_contable == "siigo_pyme":
            return _descripcion_exportacion_siigo(factura)
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


def validar_exportacion(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                         facturas: list[Factura]) -> list[str]:
    """Sección 23: nunca se genera el archivo como válido si hay errores."""
    errores = []
    adaptador = obtener_adaptador(plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value")
                                   else plantilla.sistema_contable)
    columnas = json.loads(plantilla.columnas_json)

    errores += adaptador.validar_plantilla(columnas)
    if not columnas:
        errores.append("La plantilla no tiene columnas configuradas.")

    es_siigo = (plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value") else plantilla.sistema_contable) == "siigo_pyme"
    cfgs_siigo = configuraciones_empresa(db, empresa) if es_siigo else {}
    params_siigo = parametros_cuentas_empresa(db, empresa.id) if es_siigo else {}
    sources = {c.get("source") for c in columnas}
    plantilla_siigo_completa = es_siigo and len(columnas) >= 100

    filas_por_validar = []
    for f in facturas:
        if f.estado not in (EstadoFactura.lista_para_contabilizar, EstadoFactura.contabilizada, EstadoFactura.exportada):
            errores.append(
                f"La factura {f.numero_factura or f.id} está en estado '{f.estado.value}' — "
                f"debe generar y aprobar su partida doble antes de exportarla."
            )
            continue
        if plantilla_siigo_completa:
            cfg = cfgs_siigo.get(tipo_documento_clave(f), {})
            tipo_efectivo = f.tipo_comprobante_override or cfg.get("tipo_comprobante")
            if not tipo_efectivo:
                errores.append(f"La factura {f.numero_factura or f.id} no tiene Tipo SIIGO configurado para su clase documental.")
            if not cfg.get("codigo_comprobante"):
                errores.append(f"La factura {f.numero_factura or f.id} no tiene Código SIIGO configurado para su clase documental.")
        movimientos = db.query(Movimiento).filter(Movimiento.factura_id == f.id).order_by(Movimiento.orden).all()
        if not movimientos:
            errores.append(f"La factura {f.numero_factura or f.id} no tiene movimientos contables generados.")
            continue
        total_d = sum(float(m.valor) for m in movimientos if m.tipo == "debito")
        total_c = sum(float(m.valor) for m in movimientos if m.tipo == "credito")
        if abs(total_d - total_c) >= 0.01:
            errores.append(f"La factura {f.numero_factura or f.id} no está balanceada (débito {total_d} "
                            f"vs crédito {total_c}).")
        if not f.fecha_emision:
            errores.append(f"La factura {f.numero_factura or f.id} no tiene fecha de emisión válida.")
        if not f.tercero_nit:
            errores.append(f"La factura {f.numero_factura or f.id} no tiene NIT de tercero "
                            f"({'receptor' if f.direccion_documento == 'emitida' else 'emisor'}).")

        for m in movimientos:
            if plantilla_siigo_completa and int(getattr(plantilla, "version_formato", 1) or 1) >= 2 and m.cuenta_id not in params_siigo:
                errores.append(
                    f"Cuenta {m.cuenta.codigo} ({m.cuenta.nombre}) sin parametrización SIIGO. "
                    f"Define si maneja tercero y sus códigos técnicos antes de exportar."
                )
            filas_por_validar.append({
                "Fecha": f.fecha_emision.strftime(plantilla.formato_fecha) if f.fecha_emision else "",
                "Cuenta": m.cuenta.codigo, "Nit": f.tercero_nit or "", "Tercero": f.tercero_nombre or "",
                "Debito": float(m.valor) if m.tipo == "debito" else 0,
                "Credito": float(m.valor) if m.tipo == "credito" else 0,
            })

    if filas_por_validar:
        errores += adaptador.validar_negocio(filas_por_validar)

    return errores


_ORDEN_TIPO_DOCUMENTO = {
    ("recibida", "factura"): 1,
    ("recibida", "documento_equivalente"): 2,
    ("recibida", "nota_credito"): 3,
    ("recibida", "nota_debito"): 4,
    ("emitida", "factura"): 5,
    ("emitida", "documento_equivalente"): 6,
    ("emitida", "nota_credito"): 7,
    ("emitida", "nota_debito"): 8,
    ("no_aplica", "nomina"): 9,
}


def _clave_tipo_documento(f: Factura) -> tuple:
    direccion = f.direccion_documento or "no_aplica"
    naturaleza = f.naturaleza_documento or "factura"
    return _ORDEN_TIPO_DOCUMENTO.get((direccion, naturaleza), 99)


def agrupar_y_ordenar_facturas(facturas: list[Factura]) -> list[Factura]:
    """
    Agrupa las facturas por tipo de documento (recibidas, emitidas,
    notas crédito/débito, nómina — en ese orden) para que el archivo
    plano no salga "todo mezclado" (pedido explícito del usuario: antes
    tocaba organizarlo a mano después de exportar). Dentro de cada
    grupo, ordena según los mismos títulos que usa el Excel de la DIAN,
    en el orden exacto pedido por el usuario:
    1. Fecha Emisión (por día) Z-A
    2. Prefijo Z-A
    3. Folio Z-A
    4. Nombre Emisor Z-A
    5. Nit Emisor Z-A
    "Z-A" = descendente. Un valor vacío/None siempre queda al final de
    su grupo (nunca se inventa un valor para ordenar).
    """
    return sorted(
        facturas,
        key=lambda f: (
            _clave_tipo_documento(f),
            f.fecha_emision is None, _NegarFecha(f.fecha_emision),
            f.prefijo is None or f.prefijo == "", _NegarTexto(f.prefijo),
            f.numero_factura is None or f.numero_factura == "", _NegarTexto(f.numero_factura),
            f.nombre_emisor is None or f.nombre_emisor == "", _NegarTexto(f.nombre_emisor),
            f.nit_emisor is None or f.nit_emisor == "", _NegarTexto(f.nit_emisor),
        ),
    )


class _NegarTexto:
    """Envoltorio para poder ordenar texto de forma descendente (Z-A) dentro de sorted()."""
    __slots__ = ("valor",)

    def __init__(self, valor):
        self.valor = valor or ""

    def __lt__(self, otro):
        return self.valor > otro.valor

    def __eq__(self, otro):
        return self.valor == otro.valor


class _NegarFecha:
    """Igual que _NegarTexto, pero para fechas (más reciente primero)."""
    __slots__ = ("valor",)

    def __init__(self, valor):
        self.valor = valor

    def __lt__(self, otro):
        a = self.valor.date() if self.valor else None
        b = otro.valor.date() if otro.valor else None
        if a is None:
            return False
        if b is None:
            return True
        return a > b

    def __eq__(self, otro):
        a = self.valor.date() if self.valor else None
        b = otro.valor.date() if otro.valor else None
        return a == b


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


def generar_archivo(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                     facturas: list[Factura], numeros_documento: Optional[dict[str, str]] = None) -> tuple[bytes, int]:
    """Devuelve (contenido_bytes, cantidad_de_filas). Se asume ya validado."""
    facturas = agrupar_y_ordenar_facturas(facturas)
    columnas = json.loads(plantilla.columnas_json)
    equivalencias = json.loads(plantilla.equivalencias_cuentas_json or "{}")
    delimitador = "\t" if plantilla.delimitador == "\\t" else plantilla.delimitador
    es_siigo = (plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value") else plantilla.sistema_contable) == "siigo_pyme"
    cfgs_siigo = configuraciones_empresa(db, empresa) if es_siigo else {}
    params_siigo = parametros_cuentas_empresa(db, empresa.id) if es_siigo else {}
    if numeros_documento is None:
        numeros_documento = proyectar_numeros(db, empresa, facturas) if es_siigo else _calcular_numeros_documento(empresa, facturas)

    lineas = []
    if plantilla.incluir_encabezado:
        lineas.append(delimitador.join(c["label"] for c in columnas))

    total_filas = 0
    for f in facturas:
        movimientos = db.query(Movimiento).filter(Movimiento.factura_id == f.id).order_by(Movimiento.orden).all()
        cfg_siigo = cfgs_siigo.get(tipo_documento_clave(f), {}) if es_siigo else None
        for m in movimientos:
            param_siigo = params_siigo.get(m.cuenta_id) if es_siigo else None
            valores = [
                _valor_columna(c, f, m, equivalencias, plantilla.formato_fecha, empresa,
                                numeros_documento.get(f.id), cfg_siigo, param_siigo).replace(delimitador, " ")
                for c in columnas
            ]
            lineas.append(delimitador.join(valores))
            total_filas += 1

    # Windows-1252 (ANSI) — el importador de escritorio de Siigo Pyme
    # espera esta codificación, no UTF-8: con UTF-8 cada tilde/ñ ocupa
    # 2 bytes y Siigo los interpreta mal (ej. "Ó" se ve como "Ã"" en su
    # ventana de importación), lo cual hace que ni siquiera reconozca
    # la línea de títulos. errors="replace" evita que un carácter
    # verdaderamente exótico (fuera de este alfabeto) rompa todo el
    # archivo — se cambia por "?" en ese caso puntual, en vez de fallar.
    contenido = ("\r\n".join(lineas)).encode("cp1252", errors="replace")
    return contenido, total_filas
