from tests.test_documentos import _xml, _zip_bytes


def _preparar_factura(client, empresa_id, numero, cufe, nit, subtotal="70000", total="70000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    return client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]


def test_crear_centro_de_costo(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/centros-costo", json={"codigo": "CC01", "nombre": "Sucursal Norte"})
    assert r.status_code == 201
    assert r.json()["codigo"] == "CC01"


def test_generar_partida_con_centro_de_costo_lo_asigna_a_la_linea_de_gasto(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/centros-costo", json={"codigo": "CC01", "nombre": "Sucursal Norte"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    factura = _preparar_factura(client, empresa_a["id"], "FCC001", "cufe-cc-1", "900950950")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores",
                           "centro_costo_codigo": "CC01"})
    body = r.json()
    assert body["balanceado"] is True, body
    linea_gasto = next(l for l in body["lineas"] if l["cuenta_codigo"] == "519530")
    assert linea_gasto["centro_costo_codigo"] == "CC01"
    # la contrapartida (proveedores) NO debe llevar centro de costo
    linea_prov = next(l for l in body["lineas"] if l["cuenta_codigo"] == "220501")
    assert linea_prov["centro_costo_codigo"] is None


def test_centro_de_costo_inexistente_da_error_claro_sin_inventarlo(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    factura = _preparar_factura(client, empresa_a["id"], "FCC002", "cufe-cc-2", "900950951")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores",
                           "centro_costo_codigo": "NO_EXISTE"})
    assert r.status_code == 422
    assert "no existe" in r.json()["detail"].lower()


def test_centro_de_costo_es_opcional(client, empresa_a):
    """La partida debe seguir funcionando normalmente si no se indica centro de costo."""
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    factura = _preparar_factura(client, empresa_a["id"], "FCC003", "cufe-cc-3", "900950952")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is True
    assert all(l["centro_costo_codigo"] is None for l in body["lineas"])


def test_centro_de_costo_persiste_y_se_puede_consultar(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/centros-costo", json={"codigo": "CC02", "nombre": "Bodega"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    factura = _preparar_factura(client, empresa_a["id"], "FCC004", "cufe-cc-4", "900950953")

    client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores",
                      "centro_costo_codigo": "CC02"})

    r = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida")
    linea_gasto = next(l for l in r.json()["lineas"] if l["cuenta_codigo"] == "519530")
    assert linea_gasto["centro_costo_codigo"] == "CC02"


def test_centro_de_costo_de_otra_empresa_no_es_valido(client, empresa_a, empresa_b):
    client.post(f"/empresas/{empresa_b['id']}/centros-costo", json={"codigo": "SOLO_B", "nombre": "De la empresa B"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    factura = _preparar_factura(client, empresa_a["id"], "FCC005", "cufe-cc-5", "900950954")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores",
                           "centro_costo_codigo": "SOLO_B"})
    assert r.status_code == 422
