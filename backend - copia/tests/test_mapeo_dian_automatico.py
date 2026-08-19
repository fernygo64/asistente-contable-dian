import io
import pandas as pd


def test_detectar_mapeo_excel_dian_columnas_reales():
    from app.services.mapeo_dian_service import detectar_mapeo_excel_dian
    columnas = ["CUFE/CUDE", "Folio", "Prefijo", "NIT Emisor", "Nombre Emisor", "NIT Receptor",
                "Nombre Receptor", "Fecha Emisión", "Total", "Tipo de documento", "Grupo"]
    r = detectar_mapeo_excel_dian(columnas)
    assert r["mapeo"]["cufe"] == "CUFE/CUDE"
    assert r["mapeo"]["numero_factura"] == "Folio"
    assert r["mapeo"]["prefijo"] == "Prefijo"
    assert r["mapeo"]["nit_emisor"] == "NIT Emisor"
    assert r["mapeo"]["nit_receptor"] == "NIT Receptor"
    assert r["mapeo"]["fecha"] == "Fecha Emisión"
    assert r["mapeo"]["valor_total"] == "Total"


def test_endpoint_sugerir_mapeo_excel_dian(client, empresa_a):
    df = pd.DataFrame({
        "CUFE/CUDE": ["c1"], "Folio": ["F1"], "Prefijo": ["FG"], "NIT Emisor": [empresa_a["nit"]],
        "Nombre Emisor": ["Empresa"], "Total": ["100000"], "Tipo de documento": ["Factura electrónica"],
        "Grupo": ["Emitido"],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/excel-sugerir-mapeo",
                     files={"archivo": ("dian.xlsx", buf.getvalue(),
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mapeo"]["cufe"] == "CUFE/CUDE"
    assert body["mapeo"]["prefijo"] == "Prefijo"


def test_prefijo_se_captura_desde_el_excel(client, empresa_a):
    from tests.test_documentos import _xml, _zip_bytes

    zip_contenido = _zip_bytes({"FPRE001.xml": _xml("FPRE001", "cufe-pre-1", "900950555")})
    df = pd.DataFrame({
        "CUFE": ["cufe-pre-1"], "Folio": ["FPRE001"], "Prefijo": ["FG"],
        "NIT Emisor": ["900950555"], "Nombre Emisor": ["Proveedor Test"], "Total": ["50000"],
    })
    excel_buf = io.BytesIO()
    df.to_excel(excel_buf, index=False)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("d.zip", zip_contenido, "application/zip")),
               ("excel", ("dian.xlsx", excel_buf.getvalue(),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data={"mapeo_cufe": "CUFE", "mapeo_numero_factura": "Folio", "mapeo_prefijo": "Prefijo",
              "mapeo_nit_emisor": "NIT Emisor", "mapeo_nombre_emisor": "Nombre Emisor",
              "mapeo_valor_total": "Total"},
    )
    assert r.status_code == 201, r.text

    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900950555"}).json()[0]
    assert factura["prefijo"] == "FG"
