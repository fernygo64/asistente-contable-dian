from tests.test_documentos import _zip_bytes
from tests.test_clasificacion_documentos import _factura


def test_modo_solo_gastos_permite_contabilizar_factura_emitida_como_gasto(client, empresa_a):
    r_modo = client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    assert r_modo.status_code == 200
    assert r_modo.json()["modo_contable"] == "solo_gastos"

    zip_contenido = _zip_bytes({"FSG002.xml": _factura("FSG002", "cufe-sg-2", empresa_a["nit"],
                                                         subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Gastos varios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595", "contrapartida": "clientes"})
    body = r.json()
    assert body["balanceado"] is True, body
    codigos_usados = [l["cuenta_codigo"] for l in body["lineas"]]
    assert "220501" in codigos_usados


def test_modo_invalido_es_rechazado(client, empresa_a):
    r = client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "otro"})
    assert r.status_code == 422
