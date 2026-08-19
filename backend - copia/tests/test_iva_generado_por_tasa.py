from tests.test_documentos import _zip_bytes
from tests.test_iva_por_tasa import _xml_con_iva


def test_iva_generado_se_selecciona_automaticamente_por_tasa_en_ventas(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240802019", "nombre": "IVA Descontable Compras 19%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "240801019", "nombre": "IVA Generado 19%"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413595", "nombre": "Ingresos por servicios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_clientes": "130505"})

    zip_contenido = _zip_bytes({"FVTA001.xml": _xml_con_iva("FVTA001", "cufe-vta-1", empresa_a["nit"],
                                                             subtotal="100000", iva="19000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "413595"})
    body = r.json()
    assert body["balanceado"] is True, body
    codigos = [l["cuenta_codigo"] for l in body["lineas"]]
    assert "240801019" in codigos
    assert "240802019" not in codigos

    linea_ingreso = next(l for l in body["lineas"] if l["cuenta_codigo"] == "413595")
    assert linea_ingreso["tipo"] == "credito"
