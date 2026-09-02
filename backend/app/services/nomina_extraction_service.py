"""
Extracción de datos reales del XML de Nómina Individual Electrónica de la
DIAN — verificado contra dos archivos reales (Siigo, Ral Energy SAS,
nóminas DNE108 y DNE109). A diferencia de las facturas UBL, en este
esquema TODO el dato va en ATRIBUTOS de las etiquetas, no en texto de
nodo — y las etiquetas de un concepto (ej. <Transporte>) solo aparecen
si ese concepto tuvo valor en ese período; si no aparece, es $0, nunca
se inventa.

Confirmado por cálculo exacto contra un comprobante contable real: las
provisiones de CESANTÍAS, INTERESES SOBRE CESANTÍAS, PRIMA y VACACIONES
NO vienen en el XML de la DIAN — son porcentajes fijos de ley sobre el
salario devengado (8.3333%, 12% anual sobre las cesantías, 8.3333% y
4.1667% respectivamente), calculados por el software contable, no
reportados por período. Por eso este extractor solo lee del XML lo que
el XML realmente trae (salario, auxilio de transporte, deducciones de
salud y pensión) — las provisiones se calculan aparte, en
partida_doble_service, con esas mismas fórmulas ya verificadas.
"""
import re
from xml.etree import ElementTree as ET


def _f(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def es_nomina_xml(contenido: bytes) -> bool:
    inicio = contenido[:400].decode("utf-8", errors="ignore")
    return "NominaIndividual" in inicio


def extraer_nomina_xml(contenido: bytes) -> dict:
    try:
        root = ET.fromstring(contenido)
    except ET.ParseError:
        return {"ok": False, "fuente": "xml", "confianza": 0.0, "campos": {}, "error": "XML de nómina inválido"}

    ns_actual = re.match(r"\{(.*)\}", root.tag)
    ns = {"n": ns_actual.group(1)} if ns_actual else {}

    def tag(nombre):
        return f"n:{nombre}" if ns else nombre

    trabajador = root.find(tag("Trabajador"), ns)
    empleador = root.find(tag("Empleador"), ns)
    periodo = root.find(tag("Periodo"), ns)
    info_general = root.find(tag("InformacionGeneral"), ns)
    numero_seq = root.find(tag("NumeroSecuenciaXML"), ns)
    devengados = root.find(tag("Devengados"), ns)
    deducciones = root.find(tag("Deducciones"), ns)

    if trabajador is None or empleador is None:
        return {"ok": False, "fuente": "xml", "confianza": 0.0, "campos": {},
                "error": "El XML no trae los datos del Trabajador o del Empleador."}

    nombre_trabajador = " ".join(filter(None, [
        trabajador.get("PrimerNombre"), trabajador.get("SegundoNombre"),
        trabajador.get("PrimerApellido"), trabajador.get("SegundoApellido"),
    ])).strip()

    campos = {
        "cufe": (info_general.get("CUNE") if info_general is not None else None),
        "numero_factura": (numero_seq.get("Numero") if numero_seq is not None else None),
        "prefijo": (numero_seq.get("Prefijo") if numero_seq is not None else None),
        "nit_emisor": empleador.get("NIT"),
        "nombre_emisor": empleador.get("RazonSocial"),
        "nit_trabajador": trabajador.get("NumeroDocumento"),
        "nombre_trabajador": nombre_trabajador or None,
        "sueldo_base": _f(trabajador.get("Sueldo")),
        "fecha": (periodo.get("FechaGen") if periodo is not None else
                  (info_general.get("FechaGen") if info_general is not None else None)),
        "devengado_basico": 0.0,
        "devengado_transporte": 0.0,
        "deduccion_salud": 0.0,
        "deduccion_pension": 0.0,
        "total_devengado": 0.0,
        "total_deduccion": 0.0,
        "total": 0.0,
    }

    if devengados is not None:
        basico = devengados.find(tag("Basico"), ns)
        if basico is not None:
            campos["devengado_basico"] = _f(basico.get("SueldoTrabajado"))
        transporte = devengados.find(tag("Transporte"), ns)
        if transporte is not None:
            campos["devengado_transporte"] = _f(transporte.get("AuxilioTransporte"))

    if deducciones is not None:
        salud = deducciones.find(tag("Salud"), ns)
        if salud is not None:
            campos["deduccion_salud"] = _f(salud.get("Deduccion"))
        pension = deducciones.find(tag("FondoPension"), ns)
        if pension is not None:
            campos["deduccion_pension"] = _f(pension.get("Deduccion"))

    total_dev_el = root.find(tag("DevengadosTotal"), ns)
    total_ded_el = root.find(tag("DeduccionesTotal"), ns)
    total_el = root.find(tag("ComprobanteTotal"), ns)
    campos["total_devengado"] = _f(total_dev_el.text) if total_dev_el is not None else campos["devengado_basico"] + campos["devengado_transporte"]
    campos["total_deduccion"] = _f(total_ded_el.text) if total_ded_el is not None else campos["deduccion_salud"] + campos["deduccion_pension"]
    campos["total"] = _f(total_el.text) if total_el is not None else (campos["total_devengado"] - campos["total_deduccion"])

    if not campos["nit_trabajador"] or campos["total_devengado"] <= 0:
        return {"ok": False, "fuente": "xml", "confianza": 0.0, "campos": campos,
                "error": "El XML de nómina no trae NIT del trabajador o valor devengado."}

    return {"ok": True, "fuente": "xml", "confianza": 100.0, "campos": campos}
