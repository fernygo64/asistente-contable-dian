from tests.test_documentos import _xml, _zip_bytes


# ------------------------------------------------------------------ Empresas
def test_desactivar_empresa_es_reversible(client, empresa_a):
    r = client.patch(f"/empresas/{empresa_a['id']}/desactivar")
    assert r.status_code == 200
    assert r.json()["activa"] is False

    # una empresa desactivada ya no se puede usar
    r2 = client.get(f"/empresas/{empresa_a['id']}/cuentas")
    assert r2.status_code == 403

    r3 = client.patch(f"/empresas/{empresa_a['id']}/reactivar")
    assert r3.status_code == 200
    assert r3.json()["activa"] is True

    r4 = client.get(f"/empresas/{empresa_a['id']}/cuentas")
    assert r4.status_code == 200


def test_eliminar_empresa_exige_confirmacion_explicita(client, empresa_a):
    r = client.delete(f"/empresas/{empresa_a['id']}")
    assert r.status_code == 422
    # sin confirmar, la empresa debe seguir existiendo
    r2 = client.get(f"/empresas/{empresa_a['id']}")
    assert r2.status_code == 200


def test_eliminar_empresa_con_confirmacion_borra_todo(client, empresa_a):
    # generar datos reales: cuenta, proveedor/historial, factura, plantilla
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    zip_contenido = _zip_bytes({"FEL001.xml": _xml("FEL001", "cufe-elim-1", "900900111")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])

    r = client.delete(f"/empresas/{empresa_a['id']}", params={"confirmar": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["eliminada"] is True

    r2 = client.get(f"/empresas/{empresa_a['id']}")
    assert r2.status_code == 404


def test_eliminar_empresa_no_afecta_otra_empresa(client, empresa_a, empresa_b):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "999999", "nombre": "Solo de A"})
    client.delete(f"/empresas/{empresa_a['id']}", params={"confirmar": "true"})

    r = client.get(f"/empresas/{empresa_b['id']}")
    assert r.status_code == 200  # empresa_b sigue intacta


# ---------------------------------------------------------------- Plantillas
SIIGO_COLUMNAS_SIMPLES = [
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def test_eliminar_plantilla_no_usada(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Borrar esta", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    plantilla_id = r.json()["id"]

    r2 = client.delete(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_id}")
    assert r2.status_code == 200
    assert r2.json()["eliminada"] is True

    plantillas = client.get(f"/empresas/{empresa_a['id']}/plantillas").json()
    assert all(p["id"] != plantilla_id for p in plantillas)


def test_no_se_puede_eliminar_plantilla_ya_usada_en_una_exportacion(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Ya usada", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    plantilla_id = r.json()["id"]

    zip_contenido = _zip_bytes({"FEL002.xml": _xml("FEL002", "cufe-elim-2", "900900222", subtotal="60000", total="60000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900900222"}).json()[0]
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "513595", "contrapartida": "proveedores"})
    client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                json={"plantilla_id": plantilla_id, "factura_ids": [factura["id"]]})

    r2 = client.delete(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_id}")
    assert r2.status_code == 422
    assert "auditoría" in r2.json()["detail"] or "exportación" in r2.json()["detail"]

    plantillas = client.get(f"/empresas/{empresa_a['id']}/plantillas").json()
    assert any(p["id"] == plantilla_id for p in plantillas)  # sigue existiendo
