from tests.test_documentos import _zip_bytes
from tests.test_clasificacion_documentos import _factura


def test_no_se_puede_usar_cuenta_de_ingreso_como_cuenta_de_gasto(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413595", "nombre": "Ingresos por servicios"})

    zip_contenido = _zip_bytes({"FVTA002.xml": _factura("FVTA002", "cufe-vta-2", empresa_a["nit"],
                                                          subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413595", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is False
    assert any("INGRESO" in e for e in body["errores"])
    assert any("modo contable" in e.lower() for e in body["errores"])


def test_no_se_puede_usar_cuenta_de_gasto_como_cuenta_de_ingreso(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_clientes": "130505"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})

    zip_contenido = _zip_bytes({"FVTA003.xml": _factura("FVTA003", "cufe-vta-3", empresa_a["nit"],
                                                          subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["balanceado"] is False
    assert any("GASTO" in e for e in body["errores"])
