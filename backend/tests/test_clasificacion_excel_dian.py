import io
import pandas as pd

from tests.test_clasificacion_documentos import _factura, _acuse_recibo
from tests.test_documentos import _zip_bytes
from app.services.clasificacion_dian_service import clasificar_desde_excel, es_tipo_descartable


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


MAPEO_COMPLETO = {
    "mapeo_cufe": "CUFE/CUDE", "mapeo_numero_factura": "Folio",
    "mapeo_nit_emisor": "NIT Emisor", "mapeo_nombre_emisor": "Nombre Emisor",
    "mapeo_fecha": "Fecha Emisión", "mapeo_valor_total": "Total",
    "mapeo_tipo_documento": "Tipo de documento", "mapeo_grupo": "Grupo",
}


# --------------------------------------- Clasificación pura (sin API)
def test_clasificar_desde_excel_factura_electronica():
    r = clasificar_desde_excel("Factura electrónica", "Recibido")
    assert r == {"naturaleza": "factura", "direccion": "recibida"}


def test_clasificar_desde_excel_documento_equivalente():
    r = clasificar_desde_excel("Documento equivalente - Transporte aéreo de pasajeros", "Recibido")
    assert r["naturaleza"] == "documento_equivalente"
    assert r["direccion"] == "recibida"


def test_clasificar_desde_excel_nomina():
    r = clasificar_desde_excel("Nomina Individual", "Recibido")
    assert r["naturaleza"] == "nomina"


def test_es_tipo_descartable_application_response():
    assert es_tipo_descartable("Application response") is True
    assert es_tipo_descartable("Factura electrónica") is False


# ------------------------------------------------ Integración vía API
def test_excel_con_columnas_reales_de_dian_clasifica_documento_equivalente(client, empresa_a):
    """Reproduce el caso real: un 'Documento equivalente' (tiquete aéreo) en el Excel de la DIAN."""
    zip_contenido = _zip_bytes({"EFCC001.xml": _factura("EFCC001", "cufe-equiv-1", "890704196",
                                                          nombre="Aerovias SA", subtotal="400000", total="478180")})
    df = pd.DataFrame({
        "Tipo de documento": ["Documento equivalente - Transporte aéreo de pasajeros"],
        "CUFE/CUDE": ["cufe-equiv-1"], "Folio": ["EFCC001"],
        "NIT Emisor": ["890704196"], "Nombre Emisor": ["Aerovias SA"],
        "Fecha Emisión": ["2026-07-29"], "Total": ["478180"], "Grupo": ["Recibido"],
    })
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("d.zip", zip_contenido, "application/zip")),
               ("excel", ("dian.xlsx", excel_contenido,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data=MAPEO_COMPLETO,
    )
    assert r.status_code == 201, r.text
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 1
    assert facturas[0]["naturaleza_documento"] == "documento_equivalente"
    assert facturas[0]["direccion_documento"] == "recibida"


def test_excel_grupo_emitido_prevalece_sobre_clasificacion_xml(client, empresa_a):
    """
    El Excel dice Grupo=Emitido — esto debe prevalecer incluso si el NIT
    del XML no coincidiera exactamente con el de la empresa (la DIAN ya
    resolvió esa ambigüedad; confiar solo en comparar NITs es frágil).
    """
    zip_contenido = _zip_bytes({"FV001.xml": _factura("FV001", "cufe-emit-real-1", "900999111",
                                                        subtotal="500000", total="500000")})
    df = pd.DataFrame({
        "Tipo de documento": ["Factura electrónica"], "CUFE/CUDE": ["cufe-emit-real-1"], "Folio": ["FV001"],
        "NIT Emisor": ["900999111"], "Nombre Emisor": ["Cliente cualquiera"],
        "Fecha Emisión": ["2026-07-01"], "Total": ["500000"], "Grupo": ["Emitido"],
    })
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("d.zip", zip_contenido, "application/zip")),
               ("excel", ("dian.xlsx", excel_contenido,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data=MAPEO_COMPLETO,
    )
    assert r.status_code == 201, r.text
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert facturas[0]["direccion_documento"] == "emitida"
    assert facturas[0]["estado"] == "pendiente_clasificacion"


def test_application_response_en_excel_no_genera_factura_ni_aunque_no_este_en_el_zip(client, empresa_a):
    """
    Caso real: el ZIP puede no incluir el XML del acuse de recibo, pero
    el Excel sí lo lista. Antes esto creaba una factura fantasma
    'pendiente_revision'; ahora se descarta desde el Excel también.
    """
    zip_contenido = _zip_bytes({"real.xml": _factura("REAL001", "cufe-real-2", "900333222")})
    df = pd.DataFrame({
        "Tipo de documento": ["Application response", "Factura electrónica"],
        "CUFE/CUDE": ["cufe-acuse-no-en-zip", "cufe-real-2"],
        "Folio": ["ACE99", "REAL001"],
        "NIT Emisor": ["900333222", "900333222"],
        "Nombre Emisor": ["X", "X"],
        "Fecha Emisión": ["2026-07-01", "2026-07-01"],
        "Total": ["0", "100000"],
        "Grupo": ["Recibido", "Recibido"],
    })
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("d.zip", zip_contenido, "application/zip")),
               ("excel", ("dian.xlsx", excel_contenido,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data=MAPEO_COMPLETO,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_filas_excel"] == 2
    assert body["total_descartados"] == 1  # la fila "Application response" del Excel

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert len(facturas) == 1  # solo la factura real, nunca se creó la fantasma del acuse
    assert facturas[0]["cufe"] == "cufe-real-2"


def test_reproduce_archivo_real_completo_del_usuario(client, empresa_a):
    """
    Prueba de regresión con una muestra representativa del Excel REAL
    que subió el usuario (mismas columnas, mismos tipos, mismo patrón
    Emitido/Recibido) — sin depender del archivo binario original.
    """
    df = pd.DataFrame({
        "Tipo de documento": [
            "Application response", "Application response",
            "Factura electrónica", "Factura electrónica",
            "Nomina Individual",
            "Documento equivalente - Transporte aéreo de pasajeros",
            "Documento equivalente - Servicios públicos domiciliarios",
        ],
        "CUFE/CUDE": ["c1", "c2", "c3", "c4", "c5", "c6", "c7"],
        "Folio": ["ACE1", "ACE2", "F1", "F2", "N1", "E1", "E2"],
        "NIT Emisor": ["16699962", "16699962", "16699962", "900999888", "901006130", "890704196", "800130907"],
        "Nombre Emisor": ["Empresa Propia"] * 2 + ["Empresa Propia", "Proveedor X", "Nomina SAS", "Aerovias", "EPM"],
        "Fecha Emisión": ["2026-07-21"] * 7,
        "Total": ["0", "0", "1956360", "300000", "3213643", "478180", "150000"],
        "Grupo": ["Emitido", "Recibido", "Emitido", "Recibido", "Recibido", "Recibido", "Recibido"],
    })
    excel_contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("excel", ("dian.xlsx", excel_contenido,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
               ("documentos", ("F1.xml", _factura("F1", "c3", "16699962", subtotal="1644000", total="1956360"), "application/xml")),
               ("documentos", ("F2.xml", _factura("F2", "c4", "900999888", subtotal="252101", total="300000"), "application/xml"))],
        data=MAPEO_COMPLETO,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # 2 acuses de recibo se descartan del Excel
    assert body["total_descartados"] == 2

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    naturalezas = sorted((f["naturaleza_documento"], f["direccion_documento"]) for f in facturas)
    assert ("documento_equivalente", "recibida") in naturalezas
    assert ("nomina", "recibida") in naturalezas
    # las 2 facturas electrónicas: una emitida, una recibida
    assert naturalezas.count(("factura", "emitida")) == 1
    assert naturalezas.count(("factura", "recibida")) == 1
