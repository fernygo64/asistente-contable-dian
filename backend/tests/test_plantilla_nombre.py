from tests.test_documentos import _xml, _zip_bytes

SIIGO_COLUMNAS_SIMPLES = [
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def test_no_permite_crear_plantilla_con_nombre_vacio(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    assert r.status_code == 422


def test_no_permite_crear_plantilla_con_nombre_solo_espacios(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "   ", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    assert r.status_code == 422


def test_renombrar_plantilla(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Nombre original", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    plantilla_id = r.json()["id"]

    r2 = client.patch(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_id}/renombrar",
                       params={"nombre": "Nombre corregido"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["nombre"] == "Nombre corregido"

    plantillas = client.get(f"/empresas/{empresa_a['id']}/plantillas").json()
    assert any(p["id"] == plantilla_id and p["nombre"] == "Nombre corregido" for p in plantillas)


def test_renombrar_plantilla_que_ya_se_uso_en_una_exportacion(client, empresa_a):
    """El caso real reportado: una plantilla con nombre vacío que ya no se puede eliminar."""
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Temporal", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    plantilla_id = r.json()["id"]

    zip_contenido = _zip_bytes({"FRN001.xml": _xml("FRN001", "cufe-renom-1", "900960960", subtotal="40000", total="40000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900960960"}).json()[0]
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "513595", "contrapartida": "proveedores"})
    client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                json={"plantilla_id": plantilla_id, "factura_ids": [factura["id"]]})

    # no se puede eliminar...
    r_del = client.delete(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_id}")
    assert r_del.status_code == 422

    # ...pero sí se puede renombrar, sin romper nada
    r_ren = client.patch(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_id}/renombrar",
                          params={"nombre": "Siigo Pyme corregida"})
    assert r_ren.status_code == 200
    assert r_ren.json()["nombre"] == "Siigo Pyme corregida"


def test_no_permite_renombrar_a_nombre_ya_usado_por_otra_plantilla(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Plantilla A", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    r2 = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Plantilla B", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS_SIMPLES,
    })
    plantilla_b_id = r2.json()["id"]

    r3 = client.patch(f"/empresas/{empresa_a['id']}/plantillas/{plantilla_b_id}/renombrar",
                       params={"nombre": "Plantilla A"})
    assert r3.status_code == 409
