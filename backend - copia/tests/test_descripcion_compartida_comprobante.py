import io
import zipfile


def _zip_con(nombre, contenido):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(nombre, contenido)
    return buf.getvalue()


XML_CON_PREFIJO_Y_ITEM = '''<?xml version="1.0"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>BELA34112</cbc:ID><cbc:UUID>cufe-desc-compartida</cbc:UUID><cbc:IssueDate>2026-08-01</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID>900980900</cbc:ID></cac:PartyIdentification>
    <cac:PartyLegalEntity><cbc:RegistrationName>Proveedor Aseo SAS</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount>100000</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount>119000</cbc:TaxInclusiveAmount><cbc:PayableAmount>119000</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:TaxTotal><cbc:TaxAmount>19000</cbc:TaxAmount></cac:TaxTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>100000</cbc:LineExtensionAmount>
    <cac:Item><cbc:Description>ELEMENTOS DE ASEO Y CAFETERIA</cbc:Description></cac:Item>
    <cac:Price><cbc:PriceAmount>100000</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</Invoice>'''


def test_todas_las_lineas_del_comprobante_comparten_la_misma_descripcion(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={
        "cuenta_proveedores": "220501", "cuenta_iva_descontable": "240801",
    })
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "5195250000", "nombre": "Elementos de aseo"})

    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", _zip_con("F.xml", XML_CON_PREFIJO_Y_ITEM), "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980900"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "5195250000", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is True, body
    descripciones = {l["descripcion"] for l in body["lineas"]}
    assert len(descripciones) == 1  # las 3 líneas (gasto, IVA, proveedores) comparten la misma
    descripcion = descripciones.pop()
    assert "ELEMENTOS DE ASEO Y CAFETERIA" in descripcion  # el producto real de la factura
    assert "34112" in descripcion  # el folio (número de factura)
