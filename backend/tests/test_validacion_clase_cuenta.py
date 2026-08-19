from tests.test_documentos import _zip_bytes
from tests.test_clasificacion_documentos import _factura


def test_venta_real_con_ingreso_funciona_incluso_en_modo_solo_gastos(client, empresa_a):
    """
    Caso real reportado por el usuario: una factura EMITIDA genuina
    (venta real, no nómina) en una empresa configurada como
    "solo_gastos" quedaba rechazada al intentar usar su propia cuenta
    de INGRESO — porque el modo contable forzaba el camino de gasto
    incluso para ventas reales. Ahora una EMITIDA real (nunca nómina)
    siempre va por el camino de venta, sin importar el modo contable —
    el módulo "Facturas Emitidas" ya garantiza que solo llegan ventas
    genuinas aquí.
    """
    client.patch(f"/empresas/{empresa_a['id']}/modo-contable", params={"modo": "solo_gastos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_clientes": "130505"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413595", "nombre": "Ingresos por servicios"})

    zip_contenido = _zip_bytes({"FVTA002.xml": _factura("FVTA002", "cufe-vta-2", empresa_a["nit"],
                                                          subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413595"})
    body = r.json()
    assert body["balanceado"] is True, body
    linea_ingreso = next(l for l in body["lineas"] if l["cuenta_codigo"] == "413595")
    assert linea_ingreso["tipo"] == "credito"
    assert "130505" in [l["cuenta_codigo"] for l in body["lineas"]]


def test_cuenta_de_ingreso_sigue_rechazada_en_una_compra_real(client, empresa_a):
    """La validación sigue protegiendo el caso genuino: una cuenta de INGRESO no sirve para una COMPRA real."""
    from tests.test_documentos import _xml
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413595", "nombre": "Ingresos por servicios"})

    zip_contenido = _zip_bytes({"FCOM001.xml": _xml("FCOM001", "cufe-com-1", "900980300", subtotal="60000", total="60000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980300"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413595", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is False
    assert any("INGRESO" in e for e in body["errores"])


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
