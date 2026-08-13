from app.services.xml_extraction_service import extraer_factura_xml

XML_SIN_PARTY_IDENTIFICATION = """<?xml version="1.0"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>FRESP001</cbc:ID>
  <cbc:UUID>cufe-respaldo-1</cbc:UUID>
  <cbc:IssueDate>2026-08-01</cbc:IssueDate>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyTaxScheme><cbc:CompanyID>900555444</cbc:CompanyID></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Proveedor Sin PartyIdentification SAS</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount>50000</cbc:LineExtensionAmount>
    <cbc:TaxInclusiveAmount>50000</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount>50000</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID><cbc:InvoicedQuantity>1</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount>50000</cbc:LineExtensionAmount>
    <cac:Item><cbc:Description>Servicio</cbc:Description></cac:Item>
    <cac:Price><cbc:PriceAmount>50000</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>
</Invoice>"""


def test_extrae_nit_desde_party_tax_scheme_cuando_no_hay_party_identification():
    """
    Algunos XML de facturas colombianas no traen PartyIdentification y
    solo ponen el NIT en PartyTaxScheme/CompanyID — antes esto dejaba
    el NIT vacío en la factura resultante (una de las causas posibles
    de "facturas sin NIT" reportadas por el usuario).
    """
    r = extraer_factura_xml(XML_SIN_PARTY_IDENTIFICATION.encode())
    assert r["ok"] is True
    assert r["campos"]["nit_emisor"] == "900555444"
    assert r["campos"]["nombre_emisor"] == "Proveedor Sin PartyIdentification SAS"
