from tests.test_documentos import _xml, _zip_bytes


def test_panel_clasifica_en_los_tres_bloques(client, empresa_a):
    zip1 = _zip_bytes({"FPN001.xml": _xml("FPN001", "cufe-pn-1", "900991001", subtotal="50000", total="50000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip1, "application/zip"))])

    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.post(f"/empresas/{empresa_a['id']}/historial/decision", json={
        "proveedor_nit": "900991002", "cuenta_codigo": "513595", "origen": "manual",
    })
    zip2 = _zip_bytes({"FPN002.xml": _xml("FPN002", "cufe-pn-2", "900991002", subtotal="60000", total="60000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip2, "application/zip"))])

    zip3 = _zip_bytes({"FPN003.xml": _xml("FPN003", "cufe-pn-3", "900991003", subtotal="70000", total="70000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip3, "application/zip"))])
    f3 = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900991003"}).json()[0]
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/{f3['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "513595"})

    panel = client.get(f"/empresas/{empresa_a['id']}/documentos/panel-clasificacion").json()

    assert any(f["tercero_nit"] == "900991001" for f in panel["necesita_revision"])
    assert any(f["tercero_nit"] == "900991002" and f["cuenta_sugerida"] == "513595" for f in panel["con_sugerencia"])
    assert any(f["tercero_nit"] == "900991003" for f in panel["listas"])


def test_nomina_siempre_va_a_necesita_revision(client, empresa_a):
    import zipfile, io
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("NOM001.xml", '<NominaIndividual xmlns="dian:gov:co:facturaelectronica:NominaIndividual"><Periodo>2026-07</Periodo></NominaIndividual>')
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_buf.getvalue(), "application/zip"))])

    panel = client.get(f"/empresas/{empresa_a['id']}/documentos/panel-clasificacion").json()
    assert any("Nómina" in f["motivo"] for f in panel["necesita_revision"])
