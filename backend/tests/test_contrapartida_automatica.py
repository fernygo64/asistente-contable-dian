from tests.test_documentos import _xml, _zip_bytes
from tests.test_clasificacion_documentos import _factura


def test_contrapartida_se_deriva_sola_para_factura_recibida(client, empresa_a):
    zip_contenido = _zip_bytes({"FCP001.xml": _xml("FCP001", "cufe-cp-1", "900970970", subtotal="70000", total="70000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900970970"}).json()[0]
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["balanceado"] is True, body
    assert "220501" in [l["cuenta_codigo"] for l in body["lineas"]]


def test_contrapartida_se_deriva_sola_para_factura_emitida(client, empresa_a):
    zip_contenido = _zip_bytes({"FCP002.xml": _factura("FCP002", "cufe-cp-2", empresa_a["nit"], subtotal="80000", total="80000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413501", "nombre": "Ingresos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_clientes": "130505"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413501"})
    body = r.json()
    assert body["balanceado"] is True, body
    assert "130505" in [l["cuenta_codigo"] for l in body["lineas"]]


def test_contrapartida_se_puede_seguir_forzando_manualmente(client, empresa_a):
    zip_contenido = _zip_bytes({"FCP003.xml": _xml("FCP003", "cufe-cp-3", "900970971", subtotal="30000", total="30000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900970971"}).json()[0]
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_caja": "110505"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595", "contrapartida": "caja"})
    body = r.json()
    assert body["balanceado"] is True, body
    assert "110505" in [l["cuenta_codigo"] for l in body["lineas"]]
