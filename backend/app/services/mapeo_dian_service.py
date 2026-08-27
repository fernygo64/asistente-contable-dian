"""Detección automática de columnas del Excel de documentos electrónicos DIAN.

La detección es deliberadamente tolerante a tildes, mayúsculas y pequeñas
variaciones de título. Si una columna no se reconoce con suficiente confianza,
no se inventa: queda disponible para mapeo manual.
"""
import re

from app.services.excel_utils import _normalizar

_PATRONES = {
    "cufe": re.compile(r"^cufe\b|^cude\b|cufe.?cude|codigo unico.*factura"),
    "numero_factura": re.compile(r"^folio$|\bfolio\b|numero.*factura|num[_ ]?factura|nro.*factura"),
    "nit_emisor": re.compile(r"nit.*emisor|identificacion.*emisor|documento.*emisor"),
    "nombre_emisor": re.compile(r"nombre.*emisor|razon social.*emisor"),
    "nit_receptor": re.compile(r"nit.*receptor|nit.*adquiriente|identificacion.*receptor|identificacion.*adquiriente"),
    "nombre_receptor": re.compile(r"nombre.*receptor|razon social.*receptor|nombre.*adquiriente|razon social.*adquiriente"),
    "fecha": re.compile(r"fecha.*emision|fecha documento"),
    "valor_total": re.compile(r"^total$|valor total|total documento|valor facturado$"),
    "subtotal": re.compile(r"^subtotal$|valor antes.*iva|total antes.*impuesto|line extension"),
    "iva": re.compile(r"^iva$|valor.*iva|total.*iva"),
    "inc": re.compile(r"^inc$|impuesto.*consumo|valor.*inc"),
    "retefuente": re.compile(r"rete.*fuente|retencion.*fuente"),
    "reteica": re.compile(r"rete.*ica|retencion.*ica|retencion.*industria.*comercio"),
    "reteiva": re.compile(r"rete.*iva|retencion.*iva"),
    "tipo_documento": re.compile(r"tipo.*documento|codigo.*tipo.*documento|document type"),
    "grupo": re.compile(r"^grupo$|grupo.*documento|tipo.*grupo|direccion.*documento"),
    "prefijo": re.compile(r"^prefijo$|prefijo.*documento|prefijo.*factura"),
}


def detectar_mapeo_excel_dian(columnas_reales: list[str]) -> dict:
    """Devuelve ``mapeo`` + lista de campos reconocidos automáticamente."""
    normalizadas = [(c, _normalizar(str(c))) for c in columnas_reales]
    mapeo = {}
    for campo, patron in _PATRONES.items():
        candidatos = [c for c, n in normalizadas if patron.search(n)]
        if len(candidatos) == 1:
            mapeo[campo] = candidatos[0]
    return {"mapeo": mapeo, "reconocidas": list(mapeo.keys())}
