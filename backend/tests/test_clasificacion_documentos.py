import io
import zipfile

from tests.test_documentos import _zip_bytes


INVOICE_TEMPLATE = """<?xml version="1.0"?>
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
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>{subtotal}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount>{subtotal}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>{total}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>{total}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>{subtotal}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Description>Servicio</cbc:Description></cac:Item>
    <cac:Price><cbc:PriceAmount>{subtotal}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>"""

CREDIT_NOTE_TEMPLATE = """<?xml version="1.0"?>
<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
            xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
            xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{numero}</cbc:ID>
  <cbc:UUID>{cufe}</cbc:UUID>
  <cbc:IssueDate>2026-08-05</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID>{nit}</cbc:ID></cac:PartyIdentification>
    <cac:PartyLegalEntity><cbc:RegistrationName>{nombre}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>{subtotal}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount>{subtotal}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount>{total}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>{total}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:CreditNoteLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>{subtotal}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Description>Devolución</cbc:Description></cac:Item>
    <cac:Price><cbc:PriceAmount>{subtotal}</cbc:PriceAmount></cac:Price>
  </cac:CreditNoteLine>
</CreditNote>"""

APPLICATION_RESPONSE_TEMPLATE = """<?xml version="1.0"?>
<ApplicationResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2"
                      xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>{numero}</cbc:ID>
  <cbc:UUID>{cufe}</cbc:UUID>
</ApplicationResponse>"""

NOMINA_TEMPLATE = """<?xml version="1.0"?>
<NominaIndividual xmlns="dian:gov:co:facturaelectronica:NominaIndividual">
  <Periodo>2026-07</Periodo>
</NominaIndividual>"""


def _factura(numero, cufe, nit, nombre="Proveedor SAS", subtotal="100000", total="100000") -> bytes:
    return INVOICE_TEMPLATE.format(numero=numero, cufe=cufe, nit=nit, nombre=nombre,
                                    subtotal=subtotal, total=total).encode()


def _nota_credito(numero, cufe, nit, nombre="Proveedor SAS", subtotal="100000", total="100000") -> bytes:
    return CREDIT_NOTE_TEMPLATE.format(numero=numero, cufe=cufe, nit=nit, nombre=nombre,
                                        subtotal=subtotal, total=total).encode()


def _acuse_recibo(numero, cufe) -> bytes:
    return APPLICATION_RESPONSE_TEMPLATE.format(numero=numero, cufe=cufe).encode()


def _configurar_cuentas_compra(client, empresa_id):
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={
        "cuenta_proveedores": "220501", "cuenta_iva_descontable": "240802",
    })


def _configurar_cuentas_venta(client, empresa_id):
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={
        "cuenta_clientes": "130505", "cuenta_ingresos": "413595", "cuenta_iva_generado": "240801",
    })


# --------------------------------------------------- Application Response
def test_application_response_se_descarta_sin_crear_factura(client, empresa_a):
    zip_contenido = _zip_bytes({"acuse.xml": _acuse_recibo("EV001", "cufe-acuse-1")})
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_descartados"] == 1
    assert len(body["avisos_descarte"]) == 1
    assert "acuse de recibo" in body["avisos_descarte"][0]["aviso"].lower()

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 0  # no debe generar ninguna factura


def test_application_response_no_bloquea_facturas_reales_en_la_misma_carga(client, empresa_a):
    zip_contenido = _zip_bytes({
        "acuse.xml": _acuse_recibo("EV002", "cufe-acuse-2"),
        "factura.xml": _factura("FAC001", "cufe-real-1", "900700700"),
    })
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    body = r.json()
    assert body["total_descartados"] == 1
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 1
    assert facturas[0]["cufe"] == "cufe-real-1"


# --------------------------------------------------------------- Nómina
def test_nomina_se_marca_pendiente_clasificacion_y_no_se_trata_como_compra(client, empresa_a):
    zip_contenido = _zip_bytes({"nomina.xml": NOMINA_TEMPLATE.encode()})
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    assert r.status_code == 201, r.text
    assert r.json()["total_pendientes_clasificacion"] == 1

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nomina"}).json()
    assert len(facturas) == 1
    assert facturas[0]["estado"] == "pendiente_clasificacion"
    assert facturas[0]["naturaleza_documento"] == "nomina"


def test_generar_partida_rechaza_documento_de_nomina(client, empresa_a):
    zip_contenido = _zip_bytes({"nomina2.xml": NOMINA_TEMPLATE.encode()})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nomina"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is False
    assert any("nómina" in e.lower() for e in body["errores"])


# ------------------------------------------------------ Emitida vs recibida
def test_factura_emitida_se_marca_pendiente_clasificacion_no_como_gasto(client, empresa_a):
    """La empresa activa emite (nit_emisor == nit de la empresa, '900111111') -> es una venta, no una compra."""
    zip_contenido = _zip_bytes({"venta.xml": _factura("VTA001", "cufe-venta-1", empresa_a["nit"])})
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    assert r.status_code == 201, r.text
    assert r.json()["total_pendientes_clasificacion"] == 1

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()
    assert len(facturas) == 1
    assert facturas[0]["direccion_documento"] == "emitida"
    assert facturas[0]["estado"] == "pendiente_clasificacion"


def test_factura_recibida_de_un_tercero_sigue_como_antes(client, empresa_a):
    """Un NIT distinto al de la empresa -> sigue siendo una compra normal, sin romper el flujo anterior."""
    zip_contenido = _zip_bytes({"compra.xml": _factura("CMP001", "cufe-compra-1", "900888777")})
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "recibida"}).json()
    assert any(f["cufe"] == "cufe-compra-1" for f in facturas)


def test_generar_partida_de_factura_emitida_usa_cuentas_de_ingreso(client, empresa_a):
    zip_contenido = _zip_bytes({"venta2.xml": _factura("VTA002", "cufe-venta-2", empresa_a["nit"],
                                                         subtotal="200000", total="200000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    _configurar_cuentas_venta(client, empresa_a["id"])
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413595", "contrapartida": "clientes"})
    body = r.json()
    assert body["balanceado"] is True, body
    codigos_credito = [l["cuenta_codigo"] for l in body["lineas"] if l["tipo"] == "credito"]
    codigos_debito = [l["cuenta_codigo"] for l in body["lineas"] if l["tipo"] == "debito"]
    assert "413595" in codigos_credito       # ingreso va en crédito, no en débito
    assert "130505" in codigos_debito        # clientes (contrapartida) en débito
    assert "220501" not in (codigos_credito + codigos_debito)  # nunca usa la cuenta de proveedores


def test_generar_partida_de_emitida_rechaza_contrapartida_proveedores(client, empresa_a):
    """'Proveedores' no tiene sentido como contrapartida de una venta — debe rechazarse con error claro."""
    zip_contenido = _zip_bytes({"venta3.xml": _factura("VTA003", "cufe-venta-3", empresa_a["nit"])})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]
    _configurar_cuentas_venta(client, empresa_a["id"])

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413595", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is False
    assert any("contrapartida inválida" in e.lower() for e in body["errores"])


# --------------------------------------------------------------- Notas crédito
def test_nota_credito_invierte_debito_y_credito(client, empresa_a):
    zip_contenido = _zip_bytes({"nc.xml": _nota_credito("NC001", "cufe-nc-1", "900666555", subtotal="50000", total="50000")})
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    assert r.status_code == 201, r.text
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nota_credito"}).json()
    assert len(facturas) == 1
    assert facturas[0]["naturaleza_documento"] == "nota_credito"

    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    _configurar_cuentas_compra(client, empresa_a["id"])

    r2 = client.post(f"/empresas/{empresa_a['id']}/documentos/{facturas[0]['id']}/partida/generar",
                      json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores"})
    body = r2.json()
    assert body["balanceado"] is True, body
    # en una compra normal, el gasto (519530) va en DÉBITO; en la nota crédito debe quedar invertido a CRÉDITO
    linea_gasto = next(l for l in body["lineas"] if l["cuenta_codigo"] == "519530")
    assert linea_gasto["tipo"] == "credito"
    linea_proveedores = next(l for l in body["lineas"] if l["cuenta_codigo"] == "220501")
    assert linea_proveedores["tipo"] == "debito"

