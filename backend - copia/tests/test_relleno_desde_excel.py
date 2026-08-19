import io
import zipfile

from tests.test_documentos import _zip_bytes


XML_SIN_NIT_NI_NOMBRE = """<?xml version="1.0"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{numero}</cbc:ID>
  <cbc:UUID>{cufe}</cbc:UUID>
  <cbc:IssueDate>2026-08-01</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>100000</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount>100000</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>100000</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>100000</cbc:LineExtensionAmount>
    <cac:Item><cbc:Description>Servicio</cbc:Description></cac:Item>
    <cac:Price><cbc:PriceAmount>100000</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>"""


def _xml_sin_nit(numero, cufe) -> bytes:
    return XML_SIN_NIT_NI_NOMBRE.format(numero=numero, cufe=cufe).encode()


def test_completa_nit_y_nombre_desde_excel_cuando_el_xml_no_los_trae(client, empresa_a):
    """
    Reproduce el problema reportado: un XML real cuya estructura no
    trae el NIT/nombre del emisor en el lugar esperado. Si el Excel de
    la DIAN (que sí relacionamos con este documento) trae esos datos,
    deben completarse en vez de quedar en blanco.
    """
    zip_contenido = _zip_bytes({"FSN001.xml": _xml_sin_nit("FSN001", "cufe-sinnit-1")})

    import pandas as pd
    df = pd.DataFrame({
        "CUFE": ["cufe-sinnit-1"], "Folio": ["FSN001"],
        "NIT Emisor": ["900456456"], "Nombre Emisor": ["Proveedor Del Excel SAS"],
        "Fecha Emisión": ["2026-08-01"], "Total": ["100000"],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    excel_contenido = buf.getvalue()

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("d.zip", zip_contenido, "application/zip")),
               ("excel", ("dian.xlsx", excel_contenido,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data={"mapeo_cufe": "CUFE", "mapeo_numero_factura": "Folio",
              "mapeo_nit_emisor": "NIT Emisor", "mapeo_nombre_emisor": "Nombre Emisor",
              "mapeo_fecha": "Fecha Emisión", "mapeo_valor_total": "Total"},
    )
    assert r.status_code == 201, r.text

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 1
    assert facturas[0]["nit_emisor"] == "900456456"
    assert facturas[0]["nombre_emisor"] == "Proveedor Del Excel SAS"
