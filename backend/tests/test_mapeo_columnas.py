import io
import pandas as pd

from tests.test_documentos import _xml, _zip_bytes
from app.services.excel_utils import resolver_columna


def test_resolver_columna_ignora_mayusculas():
    assert resolver_columna("FOLIO", ["Folio", "Otra"]) == "Folio"


def test_resolver_columna_ignora_espacios_sobrantes():
    assert resolver_columna("  Folio  ", ["Folio"]) == "Folio"


def test_resolver_columna_ignora_tildes():
    assert resolver_columna("Fecha Emision", ["Fecha Emisión", "Fecha Recepción"]) == "Fecha Emisión"


def test_resolver_columna_no_encontrada_devuelve_none():
    assert resolver_columna("Columna Que No Existe", ["Folio", "Total"]) is None


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_endpoint_previsualizar_columnas(client, empresa_a):
    df = pd.DataFrame({"CUFE/CUDE": ["x"], "Folio": ["1"], "NIT Emisor": ["900"], "Total": ["100"]})
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/excel-columnas",
        files={"archivo": ("dian.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["columnas"] == ["CUFE/CUDE", "Folio", "NIT Emisor", "Total"]


def test_carga_dian_acepta_mapeo_con_mayusculas_distintas(client, empresa_a):
    """Reproduce exactamente el caso reportado: el usuario escribió 'FOLIO' pero la
    columna real en el Excel se llama 'Folio' (y 'NIT EMISOR' vs 'NIT Emisor')."""
    zip_contenido = _zip_bytes({"FEC001.xml": _xml("FEC001", "cufe-case-1", "900900900")})
    df = pd.DataFrame({"Folio": ["FEC001"], "NIT Emisor": ["900900900"]})
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("docs.zip", zip_contenido, "application/zip")),
            ("excel", ("dian.xlsx", excel_contenido,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
        data={"mapeo_numero_factura": "FOLIO", "mapeo_nit_emisor": "NIT EMISOR"},  # mayúsculas distintas a propósito
    )
    assert r.status_code == 201, r.text
    assert r.json()["total_relacionados"] == 1


def test_carga_dian_columna_realmente_inexistente_sigue_dando_error_claro(client, empresa_a):
    zip_contenido = _zip_bytes({"FEC002.xml": _xml("FEC002", "cufe-case-2", "900900901")})
    df = pd.DataFrame({"Folio": ["FEC002"]})
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("docs.zip", zip_contenido, "application/zip")),
            ("excel", ("dian.xlsx", excel_contenido,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
        data={"mapeo_numero_factura": "Columna Inventada"},
    )
    assert r.status_code == 422
    assert "Columna Inventada" in str(r.json()["detail"])
