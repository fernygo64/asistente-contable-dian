from tests.test_documentos import _zip_bytes, _xml
from tests.test_clasificacion_documentos import _factura

COLUMNAS_CON_NUMERO_DOCUMENTO = [
    {"label": "Tipo", "source": "tipo_comprobante", "valor_fijo": ""},
    {"label": "Numero", "source": "numero_documento", "valor_fijo": ""},
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def _preparar_compra(client, empresa_id, numero, cufe, nit, subtotal="50000", total="50000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]
    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": "513595", "nombre": "Gasto"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "513595", "contrapartida": "proveedores"})
    return factura


def _preparar_venta(client, empresa_id, numero, cufe, nit_propio, subtotal="50000", total="50000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _factura(numero, cufe, nit_propio, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"direccion": "emitida"}).json()
    factura = next(f for f in factura if f["numero_factura"] == numero)
    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": "413595", "nombre": "Ingresos"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_clientes": "130505"})
    client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "413595"})
    return factura


def _exportar(client, empresa_id, factura_ids):
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})
    r = client.post(f"/empresas/{empresa_id}/plantillas", json={
        "nombre": "Prueba numero documento", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS_CON_NUMERO_DOCUMENTO,
    })
    resp = client.post(f"/empresas/{empresa_id}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": factura_ids})
    assert resp.status_code == 200, resp.text
    return resp.content.decode("cp1252").strip().split("\r\n")[1:]


def test_numero_documento_es_consecutivo_no_el_numero_real_de_la_factura(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    f1 = _preparar_compra(client, empresa_a["id"], "FG9001", "cufe-nd-1", "900980900")
    f2 = _preparar_compra(client, empresa_a["id"], "FG9002", "cufe-nd-2", "900980901")

    lineas = _exportar(client, empresa_a["id"], [f1["id"], f2["id"]])
    numeros = [l.split("|")[1] for l in lineas]
    assert numeros == ["1", "1", "2", "2"]


def test_numero_documento_reinicia_por_tipo_de_comprobante(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={
        "cuenta_proveedores": "220501", "comprobante_factura_recibida": "G",
    })
    f1 = _preparar_compra(client, empresa_a["id"], "FG9003", "cufe-nd-3", "900980902")

    client.post(f"/empresas/{empresa_a['id']}/documentos/tipo-comprobante-masivo",
                json={"factura_ids": [f1["id"]], "tipo_comprobante": "G"})
    f2 = _preparar_compra(client, empresa_a["id"], "FG9004", "cufe-nd-4", "900980903")
    client.post(f"/empresas/{empresa_a['id']}/documentos/tipo-comprobante-masivo",
                json={"factura_ids": [f2["id"]], "tipo_comprobante": "R"})

    lineas = _exportar(client, empresa_a["id"], [f1["id"], f2["id"]])
    filas = {(l.split("|")[0], l.split("|")[1]) for l in lineas}
    # cada tipo (G y R) debe tener su PROPIO consecutivo empezando en "1"
    # — sin importar el orden en que salgan las filas del archivo
    assert ("G", "1") in filas
    assert ("R", "1") in filas


def test_numero_documento_usa_el_numero_real_solo_para_ventas_emitidas(client, empresa_a):
    f_venta = _preparar_venta(client, empresa_a["id"], "330", "cufe-nd-5", empresa_a["nit"])
    lineas = _exportar(client, empresa_a["id"], [f_venta["id"]])
    numeros = [l.split("|")[1] for l in lineas]
    assert numeros == ["330", "330"]
