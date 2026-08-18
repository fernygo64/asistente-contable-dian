from tests.test_documentos import _zip_bytes
from tests.test_clasificacion_documentos import _factura


def test_solo_gastos_usa_caja_si_proveedores_no_esta_configurado(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_caja": "110505"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})

    zip_contenido = _zip_bytes({"FSC001.xml": _factura("FSC001", "cufe-sc-1", empresa_a["nit"],
                                                         subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595", "contrapartida": "clientes"})
    body = r.json()
    assert body["balanceado"] is True, body
    assert "110505" in [l["cuenta_codigo"] for l in body["lineas"]]


def test_solo_gastos_sin_nada_configurado_da_error_claro(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})

    zip_contenido = _zip_bytes({"FSC002.xml": _factura("FSC002", "cufe-sc-2", empresa_a["nit"],
                                                         subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595", "contrapartida": "clientes"})
    body = r.json()
    assert body["balanceado"] is False
    assert any("proveedores" in e.lower() for e in body["errores"])


def test_solo_gastos_masivo_sin_contrapartida_usa_caja_configurada(client, empresa_a):
    """Misma corrección pero por la ruta MASIVA (generar-masivo), sin indicar contrapartida en absoluto."""
    client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_caja": "110505"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})

    zip_contenido = _zip_bytes({"FSC003.xml": _factura("FSC003", "cufe-sc-3", empresa_a["nit"],
                                                         subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/partida/generar-masivo",
                     json={"factura_ids": [factura["id"]], "cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["aplicadas"] == 1, body
