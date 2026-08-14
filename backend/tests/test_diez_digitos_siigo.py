from tests.test_documentos import _xml, _zip_bytes

COLUMNAS_SOLO_CUENTA = [
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def _preparar_factura(client, empresa_id, numero, cufe, nit, cuenta_gasto, subtotal="60000", total="60000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]
    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": cuenta_gasto, "nombre": "Gasto"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": cuenta_gasto, "contrapartida": "proveedores"})
    return factura


def test_codigo_corto_se_rellena_a_10_digitos_en_siigo_pyme(client, empresa_a):
    factura = _preparar_factura(client, empresa_a["id"], "FDIG001", "cufe-dig-1", "900960001", cuenta_gasto="513595")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Dígitos", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS_SOLO_CUENTA,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    lineas = resp.content.decode("utf-8").strip().split("\r\n")
    codigos = [l.split("|")[0] for l in lineas[1:]]
    assert "5135950000" in codigos
    assert "2205010000" in codigos


def test_codigo_ya_de_10_digitos_no_se_toca(client, empresa_a):
    factura = _preparar_factura(client, empresa_a["id"], "FDIG002", "cufe-dig-2", "900960002", cuenta_gasto="5135950000")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Dígitos ya completos", "sistema_contable": "siigo_pyme", "columnas": COLUMNAS_SOLO_CUENTA,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    lineas = resp.content.decode("utf-8").strip().split("\r\n")
    codigos = [l.split("|")[0] for l in lineas[1:]]
    assert "5135950000" in codigos


def test_regla_de_10_digitos_es_exclusiva_de_empresas_configuradas_como_siigo_pyme(client):
    r_emp = client.post("/empresas", json={"nit": "900960004", "nombre": "Empresa World Office",
                                            "sistema_contable": "world_office"})
    empresa_wo = r_emp.json()

    columnas_con_nit = [
        {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
        {"label": "Nit", "source": "nit", "valor_fijo": ""},
        {"label": "Debito", "source": "debito", "valor_fijo": ""},
        {"label": "Credito", "source": "credito", "valor_fijo": ""},
    ]
    factura = _preparar_factura(client, empresa_wo["id"], "FDIG003", "cufe-dig-3", "900960003", cuenta_gasto="513595")
    r = client.post(f"/empresas/{empresa_wo['id']}/plantillas", json={
        "nombre": "Sin regla", "sistema_contable": "world_office", "columnas": columnas_con_nit,
    })
    resp = client.post(f"/empresas/{empresa_wo['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    lineas = resp.content.decode("utf-8").strip().split("\r\n")
    codigos = [l.split("|")[0] for l in lineas[1:]]
    assert "513595" in codigos
    assert "5135950000" not in codigos
