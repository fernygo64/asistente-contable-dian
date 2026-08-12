import io
import zipfile

import pandas as pd
import pytest


XML_TEMPLATE = """<?xml version="1.0"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>{numero}</cbc:ID>
  <cbc:UUID>{cufe}</cbc:UUID>
  <cbc:IssueDate>{fecha}</cbc:IssueDate>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID>{nit}</cbc:ID></cac:PartyIdentification>
      <cac:PartyLegalEntity><cbc:RegistrationName>{nombre}</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
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


def _xml(numero, cufe, nit, nombre="Proveedor Test SAS", fecha="2026-08-01",
         subtotal="100000", total="119000") -> bytes:
    return XML_TEMPLATE.format(numero=numero, cufe=cufe, fecha=fecha, nit=nit,
                                nombre=nombre, subtotal=subtotal, total=total).encode()


def _zip_bytes(archivos: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, contenido in archivos.items():
            zf.writestr(nombre, contenido)
    return buf.getvalue()


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_carga_solo_zip_sin_excel_crea_facturas_pendientes_revision(client, empresa_a):
    zip_contenido = _zip_bytes({"FE001.xml": _xml("FE001", "cufe-aaa", "900111111")})
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("docs.zip", zip_contenido, "application/zip"))],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_archivos_zip"] == 1
    assert body["total_relacionados"] == 0  # no había Excel para relacionar
    assert body["total_pendientes_revision"] == 1

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 1
    assert facturas[0]["cufe"] == "cufe-aaa"
    assert facturas[0]["fuente_extraccion"] == "xml"
    assert facturas[0]["confianza_extraccion"] == 100.0
    assert facturas[0]["relacionada_con_excel"] is False


def test_relacion_excel_zip_por_cufe(client, empresa_a):
    zip_contenido = _zip_bytes({"FE002.xml": _xml("FE002", "cufe-bbb", "900222222", total="238000")})
    df = pd.DataFrame({"CUFE_DIAN": ["cufe-bbb"], "Total": ["238000"]})
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("docs.zip", zip_contenido, "application/zip")),
            ("excel", ("dian.xlsx", excel_contenido,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
        data={"mapeo_cufe": "CUFE_DIAN", "mapeo_valor_total": "Total"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_filas_excel"] == 1
    assert body["total_relacionados"] == 1

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 1
    assert facturas[0]["relacionada_con_excel"] is True
    assert facturas[0]["metodo_relacion"] == "cufe"


def test_relacion_por_numero_y_nit_cuando_no_hay_cufe_en_excel(client, empresa_a):
    zip_contenido = _zip_bytes({"FE003.xml": _xml("FE003", "cufe-ccc", "900333333")})
    df = pd.DataFrame({"Numero": ["FE003"], "Nit": ["900333333"]})
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("docs.zip", zip_contenido, "application/zip")),
            ("excel", ("dian.xlsx", excel_contenido,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
        data={"mapeo_numero_factura": "Numero", "mapeo_nit_emisor": "Nit"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_relacionados"] == 1

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert facturas[0]["metodo_relacion"] == "numero_nit"


def test_fila_excel_sin_documento_zip_queda_para_revision(client, empresa_a):
    zip_contenido = _zip_bytes({"FE004.xml": _xml("FE004", "cufe-ddd", "900444444")})
    df = pd.DataFrame({"CUFE_DIAN": ["cufe-que-no-existe-en-el-zip"]})
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("docs.zip", zip_contenido, "application/zip")),
            ("excel", ("dian.xlsx", excel_contenido,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ],
        data={"mapeo_cufe": "CUFE_DIAN"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # 1 fila del excel sin relacionar + 1 documento del zip sin relacionar = 2 facturas
    assert body["total_pendientes_revision"] == 2

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos",
                           params={"estado": "pendiente_revision"}).json()
    assert len(facturas) == 2
    motivos = [f["motivo_no_relacionada"] for f in facturas]
    assert all(m for m in motivos)


def test_xml_tiene_prioridad_sobre_pdf_cuando_ambos_existen(client, empresa_a):
    # mismo nombre base -> se asocian como un solo documento; el XML manda.
    zip_contenido = _zip_bytes({
        "FE005.xml": _xml("FE005", "cufe-eee", "900555555", nombre="Nombre Correcto XML"),
    })
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("docs.zip", zip_contenido, "application/zip"))],
    )
    assert r.status_code == 201
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert facturas[0]["nombre_emisor"] == "Nombre Correcto XML"
    assert facturas[0]["fuente_extraccion"] == "xml"
    assert facturas[0]["confianza_extraccion"] == 100.0


def test_deteccion_duplicados_mismo_cufe_en_dos_cargas(client, empresa_a):
    zip1 = _zip_bytes({"FE006.xml": _xml("FE006", "cufe-duplicado", "900666666")})
    r1 = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                      files=[("documentos", ("docs1.zip", zip1, "application/zip"))])
    assert r1.status_code == 201
    assert r1.json()["total_duplicados"] == 0

    # se vuelve a cargar el MISMO cufe en una carga distinta
    zip2 = _zip_bytes({"FE006_otra_vez.xml": _xml("FE006", "cufe-duplicado", "900666666")})
    r2 = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                      files=[("documentos", ("docs2.zip", zip2, "application/zip"))])
    assert r2.status_code == 201
    body2 = r2.json()
    assert body2["total_duplicados"] == 1

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos",
                           params={"estado": "duplicada"}).json()
    assert len(facturas) == 1
    assert facturas[0]["es_posible_duplicado"] is True


def test_resolver_duplicado_como_falso_positivo(client, empresa_a):
    zip1 = _zip_bytes({"FE007.xml": _xml("FE007", "cufe-resolver", "900777777")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d1.zip", zip1, "application/zip"))])
    zip2 = _zip_bytes({"FE007b.xml": _xml("FE007", "cufe-resolver", "900777777")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d2.zip", zip2, "application/zip"))])

    dup = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"estado": "duplicada"}).json()[0]
    r = client.patch(f"/empresas/{empresa_a['id']}/documentos/{dup['id']}/resolver-duplicado",
                      json={"es_duplicado": False})
    assert r.status_code == 200
    assert r.json()["es_posible_duplicado"] is False
    assert r.json()["estado"] != "duplicada"


def test_correccion_manual_no_pierde_dato_original(client, empresa_a):
    zip1 = _zip_bytes({"FE008.xml": _xml("FE008", "cufe-correccion", "900888888")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d1.zip", zip1, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos").json()[0]

    r = client.patch(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/corregir",
                      json={"nit_emisor": "900888899", "nuevo_estado": "clasificada"})
    assert r.status_code == 200
    assert r.json()["nit_emisor"] == "900888899"
    assert r.json()["estado"] == "clasificada"

    detalle = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}").json()
    assert detalle["datos_originales"]["nit_emisor"] == "900888888"  # el original NUNCA cambia
    assert detalle["datos_corregidos"]["nit_emisor"] == "900888899"


def test_documentos_no_se_filtran_entre_empresas(client, empresa_a, empresa_b):
    zip1 = _zip_bytes({"FE009.xml": _xml("FE009", "cufe-aislamiento", "900999999")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d1.zip", zip1, "application/zip"))])
    facturas_b = client.get(f"/empresas/{empresa_b['id']}/documentos").json()
    assert len(facturas_b) == 0


def test_xml_invalido_se_reporta_como_error_pero_no_rompe_la_carga(client, empresa_a):
    zip_contenido = _zip_bytes({
        "bueno.xml": _xml("FE010", "cufe-bueno", "900101010"),
        "malo.xml": b"<esto no es xml valido <<<",
    })
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("docs.zip", zip_contenido, "application/zip"))])
    assert r.status_code == 201
    body = r.json()
    assert body["total_archivos_zip"] == 2
    assert len(body["errores_zip"]) == 1

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 1  # solo el XML válido generó una factura
    assert facturas[0]["cufe"] == "cufe-bueno"
