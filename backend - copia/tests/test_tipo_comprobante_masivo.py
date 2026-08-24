from tests.test_documentos import _zip_bytes, _xml

COLUMNAS_TIPO_COMPROBANTE = [
    {"label": "Tipo", "source": "tipo_comprobante", "valor_fijo": ""},
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def _factura_recibida(client, empresa_id, numero, cufe, nit, cuenta_gasto="513595"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal="50000", total="50000")})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]
    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": cuenta_gasto, "nombre": "Gasto"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": cuenta_gasto, "contrapartida": "proveedores"})
    return factura


def test_aplicar_tipo_comprobante_en_bloque(client, empresa_a):
    f1 = _factura_recibida(client, empresa_a["id"], "FTC001", "cufe-tc-1", "900980600")
    f2 = _factura_recibida(client, empresa_a["id"], "FTC002", "cufe-tc-2", "900980601")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/tipo-comprobante-masivo",
                     json={"factura_ids": [f1["id"], f2["id"]], "tipo_comprobante": "G"})
    assert r.status_code == 200, r.text
    assert r.json()["aplicadas"] == 2

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    for f in facturas:
        if f["id"] in (f1["id"], f2["id"]):
            assert f["tipo_comprobante_override"] == "G"


def test_tipo_comprobante_forzado_manda_sobre_la_regla_automatica_en_exportacion(client, empresa_a):
    factura = _factura_recibida(client, empresa_a["id"], "FTC003", "cufe-tc-3", "900980602")

    client.post(f"/empresas/{empresa_a['id']}/documentos/tipo-comprobante-masivo",
                json={"factura_ids": [factura["id"]], "tipo_comprobante": "XYZ"})

    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Con tipo forzado", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS_TIPO_COMPROBANTE,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    lineas = resp.content.decode("cp1252").strip().split("\r\n")
    tipos = {l.split("|")[0] for l in lineas[1:]}
    assert tipos == {"XYZ"}


def test_quitar_el_forzado_vuelve_a_la_regla_automatica(client, empresa_a):
    factura = _factura_recibida(client, empresa_a["id"], "FTC004", "cufe-tc-4", "900980603")
    client.post(f"/empresas/{empresa_a['id']}/documentos/tipo-comprobante-masivo",
                json={"factura_ids": [factura["id"]], "tipo_comprobante": "G"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/tipo-comprobante-masivo",
                json={"factura_ids": [factura["id"]], "tipo_comprobante": ""})

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    f = next(f for f in facturas if f["id"] == factura["id"])
    assert f["tipo_comprobante_override"] is None


def test_tipo_comprobante_masivo_sin_ids_da_error(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/tipo-comprobante-masivo",
                     json={"factura_ids": [], "tipo_comprobante": "G"})
    assert r.status_code == 422
