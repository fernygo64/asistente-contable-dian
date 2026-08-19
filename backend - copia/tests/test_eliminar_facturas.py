from tests.test_documentos import _xml, _zip_bytes
from tests.test_partida_doble import _configurar_cuentas_base, _cargar_una_factura


def test_eliminar_factura_individual(client, empresa_a):
    zip_contenido = _zip_bytes({"DEL001.xml": _xml("DEL001", "cufe-del-1", "900444555")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900444555"}).json()[0]

    r = client.delete(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["eliminada"] is True

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert all(f["id"] != factura["id"] for f in facturas)


def test_eliminar_factura_inexistente_da_404(client, empresa_a):
    r = client.delete(f"/empresas/{empresa_a['id']}/documentos/no-existe-este-id")
    assert r.status_code == 404


def test_eliminar_factura_tambien_borra_sus_movimientos(client, empresa_a):
    factura = _cargar_una_factura(client, empresa_a["id"], numero="DEL002", cufe="cufe-del-2",
                                   nit="900444556", subtotal="80000", total="80000")
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    _configurar_cuentas_base(client, empresa_a["id"], cuenta_proveedores="220501")
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores"})
    assert r.json()["balanceado"] is True

    r2 = client.delete(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}")
    assert r2.status_code == 200

    r3 = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}")
    assert r3.status_code == 404


def test_eliminar_factura_no_afecta_otra_empresa(client, empresa_a, empresa_b):
    zip_contenido = _zip_bytes({"DEL003.xml": _xml("DEL003", "cufe-del-3", "900444557")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900444557"}).json()[0]

    r = client.delete(f"/empresas/{empresa_b['id']}/documentos/{factura['id']}")
    assert r.status_code == 404  # no existe EN ESA empresa, aunque el id sea válido en otra

    sigue_existiendo = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}")
    assert sigue_existiendo.status_code == 200


def test_eliminar_multiples_facturas(client, empresa_a):
    zip_contenido = _zip_bytes({
        "DEL004.xml": _xml("DEL004", "cufe-del-4", "900444558"),
        "DEL005.xml": _xml("DEL005", "cufe-del-5", "900444559"),
    })
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    ids = [f["id"] for f in facturas if f["cufe"] in ("cufe-del-4", "cufe-del-5")]
    assert len(ids) == 2

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/eliminar-multiples", json=ids)
    assert r.status_code == 200, r.text
    assert r.json()["eliminadas"] == 2

    restantes = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    assert all(f["id"] not in ids for f in restantes)


def test_eliminar_queda_registrado_en_auditoria(client, empresa_a):
    zip_contenido = _zip_bytes({"DEL006.xml": _xml("DEL006", "cufe-del-6", "900444560")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900444560"}).json()[0]
    client.delete(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}")

    auditoria = client.get(f"/empresas/{empresa_a['id']}/auditoria").json()
    assert any(ev["accion"] == "factura_eliminada" for ev in auditoria)
