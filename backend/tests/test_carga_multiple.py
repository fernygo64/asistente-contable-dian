from tests.test_documentos import _xml, _zip_bytes


def test_varios_zip_en_una_sola_carga(client, empresa_a):
    """La DIAN a veces entrega la descarga partida en varios ZIP."""
    zip1 = _zip_bytes({"FEM001.xml": _xml("FEM001", "cufe-multi-1", "900811811")})
    zip2 = _zip_bytes({"FEM002.xml": _xml("FEM002", "cufe-multi-2", "900822822")})
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("parte1.zip", zip1, "application/zip")),
            ("documentos", ("parte2.zip", zip2, "application/zip")),
        ],
    )
    assert r.status_code == 201, r.text
    assert r.json()["total_archivos_zip"] == 2
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    cufes = {f["cufe"] for f in facturas}
    assert {"cufe-multi-1", "cufe-multi-2"} <= cufes


def test_archivos_xml_sueltos_sin_zip(client, empresa_a):
    """El usuario puede subir XML sueltos directamente, sin necesidad de comprimirlos."""
    xml_bytes = _xml("FEM003", "cufe-suelto-1", "900833833")
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("FEM003.xml", xml_bytes, "application/xml"))],
    )
    assert r.status_code == 201, r.text
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert facturas[0]["cufe"] == "cufe-suelto-1"
    assert facturas[0]["fuente_extraccion"] == "xml"


def test_mezcla_zip_y_xml_suelto_en_la_misma_carga(client, empresa_a):
    zip1 = _zip_bytes({"FEM004.xml": _xml("FEM004", "cufe-mix-1", "900844844")})
    xml_suelto = _xml("FEM005", "cufe-mix-2", "900855855")
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("docs.zip", zip1, "application/zip")),
            ("documentos", ("FEM005.xml", xml_suelto, "application/xml")),
        ],
    )
    assert r.status_code == 201, r.text
    assert r.json()["total_archivos_zip"] == 2
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    cufes = {f["cufe"] for f in facturas}
    assert {"cufe-mix-1", "cufe-mix-2"} <= cufes


def test_zip_corrupto_no_bloquea_el_resto_de_la_carga(client, empresa_a):
    """Antes esto abortaba toda la carga con 422; ahora sigue con lo válido."""
    zip_bueno = _zip_bytes({"FEM006.xml": _xml("FEM006", "cufe-resiliente", "900866866")})
    zip_corrupto = b"esto no es un zip de verdad, esta corrupto o mal descargado"
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("bueno.zip", zip_bueno, "application/zip")),
            ("documentos", ("corrupto.zip", zip_corrupto, "application/zip")),
        ],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["errores_zip"]) == 1
    assert "corrupto.zip" in body["errores_zip"][0]["error"] or "no es un archivo ZIP válido" in body["errores_zip"][0]["error"]

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert any(f["cufe"] == "cufe-resiliente" for f in facturas)


def test_no_permite_carga_sin_ningun_archivo(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar", files=[])
    assert r.status_code in (422, 400)


def test_archivo_de_extension_no_soportada_se_reporta_sin_bloquear(client, empresa_a):
    zip_bueno = _zip_bytes({"FEM007.xml": _xml("FEM007", "cufe-otro-bueno", "900877877")})
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[
            ("documentos", ("bueno.zip", zip_bueno, "application/zip")),
            ("documentos", ("notas.txt", b"esto no es un documento de factura", "text/plain")),
        ],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["errores_zip"]) == 1
    assert "notas.txt" in body["errores_zip"][0]["error"]
