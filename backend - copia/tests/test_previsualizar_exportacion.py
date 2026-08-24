from tests.test_documentos import _xml, _zip_bytes


def _preparar_factura_lista(client, empresa_id, numero, cufe, nit, cuenta_gasto="513595",
                             subtotal="80000", total="80000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]
    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": cuenta_gasto, "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})
    r = client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": cuenta_gasto, "contrapartida": "proveedores"})
    assert r.json()["balanceado"] is True
    return factura


COLUMNAS = [
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def test_previsualizar_exportacion_muestra_filas_reales(client, empresa_a):
    factura = _preparar_factura_lista(client, empresa_a["id"], "FPV001", "cufe-pv-1", "900810810")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Preview test", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/previsualizar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valido"] is True
    assert body["encabezado"] == ["Cuenta", "Debito", "Credito"]
    assert len(body["filas"]) == 2


def test_previsualizar_no_marca_facturas_como_exportadas(client, empresa_a):
    factura = _preparar_factura_lista(client, empresa_a["id"], "FPV002", "cufe-pv-2", "900820820")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Preview no marca", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS,
    })
    client.post(f"/empresas/{empresa_a['id']}/exportaciones/previsualizar",
                json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    factura_despues = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}").json()
    assert factura_despues["estado"] == "lista_para_contabilizar"


def test_previsualizar_no_genera_registro_de_exportacion(client, empresa_a):
    factura = _preparar_factura_lista(client, empresa_a["id"], "FPV003", "cufe-pv-3", "900830830")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Preview sin auditoria", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS,
    })
    client.post(f"/empresas/{empresa_a['id']}/exportaciones/previsualizar",
                json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    exportaciones = client.get(f"/empresas/{empresa_a['id']}/exportaciones").json()
    assert len(exportaciones) == 0


def test_previsualizar_con_errores_no_muestra_filas(client, empresa_a):
    zip_contenido = _zip_bytes({"FPV004.xml": _xml("FPV004", "cufe-pv-4", "900840840")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900840840"}).json()[0]
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Preview con error", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/previsualizar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    body = resp.json()
    assert body["valido"] is False
    assert body["filas"] == []
    assert len(body["errores"]) > 0


def test_previsualizar_con_columnas_y_texto_con_tildes(client, empresa_a):
    """
    Bug real reportado por el usuario: 500 Internal Server Error al dar
    "Ver vista previa". Causa: generar_archivo() codifica el archivo en
    Windows-1252 (necesario para que Siigo lo acepte), pero este
    endpoint seguía decodificando como UTF-8 — con texto sin tildes
    (como en las demás pruebas de este archivo) nunca se notaba, pero
    con títulos reales de Siigo ("CÓDIGO", "NÚMERO", etc.) sí revienta.
    """
    factura = _preparar_factura_lista(client, empresa_a["id"], "FPV900", "cufe-pv-900", "900900900")
    columnas_con_tildes = [
        {"label": "CÓDIGO COMPROBANTE  (OBLIGATORIO)", "source": "cuenta", "valor_fijo": ""},
        {"label": "DÉBITO O CRÉDITO (OBLIGATORIO)", "source": "debito", "valor_fijo": ""},
        {"label": "AÑO DEL DOCUMENTO", "source": "credito", "valor_fijo": ""},
    ]
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Preview con tildes", "sistema_contable": "siigo_pyme", "columnas": columnas_con_tildes,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/previsualizar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valido"] is True
    assert body["encabezado"] == [c["label"] for c in columnas_con_tildes]
    assert len(body["filas"]) == 2
