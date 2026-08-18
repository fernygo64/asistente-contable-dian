"""
Detección automática de columnas del Excel que la DIAN entrega al
descargar el histórico de documentos electrónicos — a diferencia de un
auxiliar contable (que varía mucho según el software), este archivo
sigue un formato bastante estable con nombres de columna conocidos
(confirmado contra archivos reales de la DIAN a lo largo de este
proyecto: "CUFE/CUDE", "Folio", "NIT Emisor", "Nombre Emisor",
"Fecha Emisión", "Total", "Tipo de documento", "Grupo", etc.).

Igual que con los balances (balance_service.py, balance_jerarquico_
service.py): solo se sugiere lo que se reconoce con confianza — nunca
se inventa una columna que no exista en el archivo real.
"""
import re

from app.services.excel_utils import _normalizar

_PATRONES = {
    "cufe": re.compile(r"^cufe|^cude|cufe.?cude"),
    "numero_factura": re.compile(r"^folio$|numero de factura|n[uú]mero factura"),
    "nit_emisor": re.compile(r"nit emisor|nit del emisor"),
    "nombre_emisor": re.compile(r"nombre emisor|raz[oó]n social emisor"),
    "nit_receptor": re.compile(r"nit receptor|nit adquiriente|nit del receptor|nit del adquiriente"),
    "nombre_receptor": re.compile(r"nombre receptor|raz[oó]n social receptor|nombre adquiriente|raz[oó]n social adquiriente"),
    "fecha": re.compile(r"fecha emisi[oó]n|fecha de emisi[oó]n"),
    "valor_total": re.compile(r"^total$|valor total"),
    "tipo_documento": re.compile(r"tipo de documento|tipo documento"),
    "grupo": re.compile(r"^grupo$"),
    "prefijo": re.compile(r"^prefijo$"),
}


def detectar_mapeo_excel_dian(columnas_reales: list[str]) -> dict:
    """
    Devuelve {"mapeo": {campo: columna_real, ...}, "reconocidas": [...]}.
    No exige ningún campo obligatorio (a diferencia del balance) — el
    usuario puede tener un Excel con solo algunas columnas y de todas
    formas aprovechar lo que sí se reconoce; el mapeo resultante se usa
    exactamente igual que si el usuario lo hubiera elegido a mano.
    """
    normalizadas = [(c, _normalizar(c)) for c in columnas_reales]
    mapeo = {}
    for campo, patron in _PATRONES.items():
        candidatos = [c for c, n in normalizadas if patron.search(n)]
        if len(candidatos) == 1:
            mapeo[campo] = candidatos[0]
    return {"mapeo": mapeo, "reconocidas": list(mapeo.keys())}
