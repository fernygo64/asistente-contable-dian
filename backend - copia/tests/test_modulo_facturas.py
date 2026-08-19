from tests.test_documentos import _xml, _zip_bytes
from tests.test_clasificacion_documentos import _factura


def _nomina_zip(numero):
    xml = f'<NominaIndividual xmlns="dian:gov:co:facturaelectronica:NominaIndividual"><Periodo>2026-07</Periodo><Folio>{numero}</Folio></NominaIndividual>'
    return _zip_bytes({f"{numero}.xml": xml})


def test_modulo_recibidas_incluye_nomina_aunque_este_marcada_emitida(client, empresa_a):
    zip_recibida = _zip_bytes({"FR001.xml": _xml("FR001", "cufe-mod-1", "900980201", subtotal="30000", total="30000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_recibida, "application/zip"))])

    zip_nomina = _nomina_zip("NOM901")
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_nomina, "application/zip"))])

    r = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"modulo": "recibidas"})
    numeros = [(f["numero_factura"] or "").lower() for f in r.json()]
    assert "fr001" in numeros
    assert "nom901" in numeros


def test_modulo_emitidas_nunca_incluye_nomina(client, empresa_a):
    zip_emitida = _zip_bytes({"FE001.xml": _factura("FE001", "cufe-mod-2", empresa_a["nit"], subtotal="40000", total="40000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_emitida, "application/zip"))])

    zip_nomina = _nomina_zip("NOM902")
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_nomina, "application/zip"))])

    r = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"modulo": "emitidas"})
    numeros = [(f["numero_factura"] or "").lower() for f in r.json()]
    assert "fe001" in numeros
    assert "nom902" not in numeros


def test_modulo_recibidas_no_incluye_facturas_emitidas_normales(client, empresa_a):
    zip_emitida = _zip_bytes({"FE002.xml": _factura("FE002", "cufe-mod-3", empresa_a["nit"], subtotal="40000", total="40000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_emitida, "application/zip"))])

    r = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"modulo": "recibidas"})
    numeros = [f["numero_factura"] for f in r.json()]
    assert "FE002" not in numeros


def test_panel_clasificacion_respeta_el_modulo(client, empresa_a):
    zip_nomina = _nomina_zip("NOM903")
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_nomina, "application/zip"))])

    panel_recibidas = client.get(f"/empresas/{empresa_a['id']}/documentos/panel-clasificacion",
                                  params={"modulo": "recibidas"}).json()
    todos_recibidas = panel_recibidas["listas"] + panel_recibidas["con_sugerencia"] + panel_recibidas["necesita_revision"]
    assert any((f["numero_factura"] or "").lower() == "nom903" for f in todos_recibidas)

    panel_emitidas = client.get(f"/empresas/{empresa_a['id']}/documentos/panel-clasificacion",
                                 params={"modulo": "emitidas"}).json()
    todos_emitidas = panel_emitidas["listas"] + panel_emitidas["con_sugerencia"] + panel_emitidas["necesita_revision"]
    assert not any((f["numero_factura"] or "").lower() == "nom903" for f in todos_emitidas)
