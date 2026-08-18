from tests.test_documentos import _xml, _zip_bytes

COLUMNAS_SIMPLES = [
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def _preparar_factura_exportada(client, empresa_id, numero, cufe, nit, plantilla_id, subtotal="50000", total="50000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]
    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "513595", "contrapartida": "proveedores"})
    client.post(f"/empresas/{empresa_id}/exportaciones/generar",
                json={"plantilla_id": plantilla_id, "factura_ids": [factura["id"]]})
    return factura


def test_eliminar_exportacion(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Plantilla exportacion test", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS_SIMPLES,
    })
    plantilla_id = r.json()["id"]
    _preparar_factura_exportada(client, empresa_a["id"], "FEXP001", "cufe-exp-1", "900980101", plantilla_id)

    exportaciones = client.get(f"/empresas/{empresa_a['id']}/exportaciones").json()
    assert len(exportaciones) == 1
    exportacion_id = exportaciones[0]["id"]

    r_del = client.delete(f"/empresas/{empresa_a['id']}/exportaciones/{exportacion_id}")
    assert r_del.status_code == 200
    assert r_del.json()["eliminada"] is True

    exportaciones_despues = client.get(f"/empresas/{empresa_a['id']}/exportaciones").json()
    assert len(exportaciones_despues) == 0


def test_eliminar_exportacion_desbloquea_borrar_la_plantilla(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Plantilla atrapada", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS_SIMPLES,
    })
    plantilla_id = r.json()["id"]
    _preparar_factura_exportada(client, empresa_a["id"], "FEXP002", "cufe-exp-2", "900980102", plantilla_id)

    r_bloqueada = client.delete(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_id}")
    assert r_bloqueada.status_code == 422

    exportaciones = client.get(f"/empresas/{empresa_a['id']}/exportaciones").json()
    for e in exportaciones:
        client.delete(f"/empresas/{empresa_a['id']}/exportaciones/{e['id']}")

    r_ahora = client.delete(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_id}")
    assert r_ahora.status_code == 200


def test_eliminar_exportacion_inexistente_da_404(client, empresa_a):
    r = client.delete(f"/empresas/{empresa_a['id']}/exportaciones/no-existe")
    assert r.status_code == 404
