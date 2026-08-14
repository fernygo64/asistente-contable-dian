from tests.test_documentos import _xml, _zip_bytes


def test_lista_de_facturas_expone_concepto_resumen(client, empresa_a):
    """
    El usuario necesita ver de un vistazo qué se compró para decidir
    manualmente la cuenta cuando el sistema no tiene sugerencia.
    """
    zip_contenido = _zip_bytes({"FCR001.xml": _xml("FCR001", "cufe-concepto-1", "900950111")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    factura = next(f for f in facturas if f["cufe"] == "cufe-concepto-1")
    assert factura["concepto_resumen"]
    assert len(factura["concepto_resumen"]) <= 151


def test_concepto_resumen_presente_en_respuesta(client, empresa_a):
    zip_contenido = _zip_bytes({"FCR002.xml": _xml("FCR002", "cufe-concepto-2", "900950112")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos",
                          params={"nit_emisor": "900950112"}).json()[0]
    assert "concepto_resumen" in factura
