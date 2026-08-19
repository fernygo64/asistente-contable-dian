from tests.test_documentos import _zip_bytes, _xml
from tests.test_clasificacion_documentos import _factura


def test_modo_solo_gastos_sigue_funcionando_para_compras_reales(client, empresa_a):
    """
    El modo "solo_gastos" sigue siendo útil para su caso real: una
    factura RECIBIDA (compra genuina) de una persona natural que no
    maneja proveedores, solo caja/banco.
    """
    r_modo = client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    assert r_modo.status_code == 200
    assert r_modo.json()["modo_contable"] == "solo_gastos"

    zip_contenido = _zip_bytes({"FSG002.xml": _xml("FSG002", "cufe-sg-2", "900980400",
                                                     subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980400"}).json()[0]

    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Gastos varios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595"})
    body = r.json()
    assert body["balanceado"] is True, body
    codigos_usados = [l["cuenta_codigo"] for l in body["lineas"]]
    assert "220501" in codigos_usados


def test_modo_solo_gastos_no_afecta_una_emitida_real(client, empresa_a):
    """
    Una factura EMITIDA real (venta genuina) siempre usa el camino de
    venta, incluso con modo_contable="solo_gastos" — ver también
    test_validacion_clase_cuenta.py para el caso completo con cuentas
    de ingreso reales.
    """
    client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    zip_contenido = _zip_bytes({"FSG003.xml": _factura("FSG003", "cufe-sg-3", empresa_a["nit"],
                                                         subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413595", "nombre": "Ingresos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_clientes": "130505"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413595"})
    body = r.json()
    assert body["balanceado"] is True, body
    linea = next(l for l in body["lineas"] if l["cuenta_codigo"] == "413595")
    assert linea["tipo"] == "credito"


def test_modo_invalido_es_rechazado(client, empresa_a):
    r = client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "otro"})
    assert r.status_code == 422
