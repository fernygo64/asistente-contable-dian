def _xml_con_iva(numero, cufe, nit, subtotal, iva, nombre="Proveedor Test SAS") -> bytes:
    total = round(float(subtotal) + float(iva), 2)
    plantilla = """<?xml version="1.0"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{numero}</cbc:ID>
  <cbc:UUID>{cufe}</cbc:UUID>
  <cbc:IssueDate>2026-08-01</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID>{nit}</cbc:ID></cac:PartyIdentification>
    <cac:PartyLegalEntity><cbc:RegistrationName>{nombre}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:TaxTotal>
    <cbc:TaxAmount>{iva}</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxAmount>{iva}</cbc:TaxAmount>
      <cac:TaxCategory><cac:TaxScheme><cbc:Name>IVA</cbc:Name></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>{subtotal}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount>{subtotal}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>{total}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>{total}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>{subtotal}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Description>Honorarios profesionales</cbc:Description></cac:Item>
    <cac:Price><cbc:PriceAmount>{subtotal}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>"""
    return plantilla.format(numero=numero, cufe=cufe, nit=nit, nombre=nombre,
                             subtotal=subtotal, iva=iva, total=total).encode()


from tests.test_documentos import _zip_bytes


def test_selecciona_automaticamente_la_cuenta_de_iva_19_por_ciento(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802019", "nombre": "IVA Descontable Compras 19%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802005", "nombre": "IVA Descontable Compras 5%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    zip_contenido = _zip_bytes({"FIVA001.xml": _xml_con_iva("FIVA001", "cufe-iva-1", "900980001",
                                                              subtotal="100000", iva="19000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980001"}).json()[0]
    assert factura["iva"] == 19000.0  # confirma que el XML de prueba sí trae IVA real

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["balanceado"] is True, body
    codigos = [l["cuenta_codigo"] for l in body["lineas"]]
    assert "240802019" in codigos
    assert "240802005" not in codigos


def test_selecciona_automaticamente_la_cuenta_de_iva_5_por_ciento(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802019", "nombre": "IVA Descontable Compras 19%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802005", "nombre": "IVA Descontable Compras 5%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    zip_contenido = _zip_bytes({"FIVA002.xml": _xml_con_iva("FIVA002", "cufe-iva-2", "900980002",
                                                              subtotal="100000", iva="5000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980002"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["balanceado"] is True, body
    codigos = [l["cuenta_codigo"] for l in body["lineas"]]
    assert "240802005" in codigos
    assert "240802019" not in codigos


def test_sin_cuenta_2408_especifica_cae_a_la_configurada_como_antes(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={
        "cuenta_proveedores": "220501", "cuenta_iva_descontable": "240802",
    })
    zip_contenido = _zip_bytes({"FIVA003.xml": _xml_con_iva("FIVA003", "cufe-iva-3", "900980003",
                                                              subtotal="100000", iva="19000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980003"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["balanceado"] is True, body
    assert "240802" in [l["cuenta_codigo"] for l in body["lineas"]]


def test_dos_cuentas_2408_de_la_misma_tasa_no_arriesga_una_eleccion_ambigua(client, empresa_a):
    """Si hay dos cuentas 2408 que mencionan la misma tasa, no se arriesga a elegir mal — cae a la configurada."""
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802019", "nombre": "IVA Compras 19%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802020", "nombre": "IVA Servicios 19%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={
        "cuenta_proveedores": "220501", "cuenta_iva_descontable": "240802001",
    })
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802001", "nombre": "IVA Descontable General"})

    zip_contenido = _zip_bytes({"FIVA004.xml": _xml_con_iva("FIVA004", "cufe-iva-4", "900980004",
                                                              subtotal="100000", iva="19000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980004"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["balanceado"] is True, body
    assert "240802001" in [l["cuenta_codigo"] for l in body["lineas"]]  # la configurada, no una ambigua
