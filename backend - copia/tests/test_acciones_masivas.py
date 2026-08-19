from tests.test_documentos import _xml, _zip_bytes


def _cargar_factura(client, empresa_id, numero, cufe, nit, subtotal="80000", total="80000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    return client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]


def test_generar_partida_masivo_misma_cuenta_para_varias(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    f1 = _cargar_factura(client, empresa_a["id"], "FM001", "cufe-masivo-1", "900700700")
    f2 = _cargar_factura(client, empresa_a["id"], "FM002", "cufe-masivo-2", "900700701")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/partida/generar-masivo", json={
        "factura_ids": [f1["id"], f2["id"]],
        "cuenta_gasto_codigo": "513595", "contrapartida": "proveedores",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["aplicadas"] == 2
    assert body["omitidas"] == 0

    f1_actualizada = client.get(f"/empresas/{empresa_a['id']}/documentos/{f1['id']}").json()
    assert f1_actualizada["estado"] == "lista_para_contabilizar"


def test_generar_partida_masivo_usa_sugerencia_confiable_y_omite_las_que_no_tienen(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    nit_conocido = "900700800"
    client.post(f"/empresas/{empresa_a['id']}/historial/decision", json={
        "proveedor_nit": nit_conocido, "cuenta_codigo": "513595", "origen": "manual",
    })
    f_conocida = _cargar_factura(client, empresa_a["id"], "FM003", "cufe-masivo-3", nit_conocido)
    f_nueva = _cargar_factura(client, empresa_a["id"], "FM004", "cufe-masivo-4", "900700900")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/partida/generar-masivo", json={
        "factura_ids": [f_conocida["id"], f_nueva["id"]], "usar_sugerencia": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["aplicadas"] == 1
    assert body["omitidas"] == 1
    detalle = {d["factura_id"]: d for d in body["detalle"]}
    assert detalle[f_conocida["id"]]["estado"] == "aplicada"
    assert detalle[f_conocida["id"]]["cuenta_usada"] == "513595"
    assert detalle[f_nueva["id"]]["estado"] == "omitida"


def test_generar_partida_masivo_exige_cuenta_o_usar_sugerencia(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/partida/generar-masivo", json={
        "factura_ids": ["algo"],
    })
    assert r.status_code == 422


def test_generar_partida_masivo_factura_inexistente_se_reporta_sin_tumbar_las_demas(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    f1 = _cargar_factura(client, empresa_a["id"], "FM005", "cufe-masivo-5", "900701000")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/partida/generar-masivo", json={
        "factura_ids": [f1["id"], "id-que-no-existe"],
        "cuenta_gasto_codigo": "513595", "contrapartida": "proveedores",
    })
    body = r.json()
    assert body["aplicadas"] == 1
    detalle = {d["factura_id"]: d for d in body["detalle"]}
    assert detalle["id-que-no-existe"]["estado"] == "no_encontrada"


def test_contabilizar_masivo(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    f1 = _cargar_factura(client, empresa_a["id"], "FM006", "cufe-masivo-6", "900701100")
    f2 = _cargar_factura(client, empresa_a["id"], "FM007", "cufe-masivo-7", "900701200")

    client.post(f"/empresas/{empresa_a['id']}/documentos/partida/generar-masivo", json={
        "factura_ids": [f1["id"], f2["id"]], "cuenta_gasto_codigo": "513595", "contrapartida": "proveedores",
    })

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/contabilizar-masivo", json={
        "factura_ids": [f1["id"], f2["id"]],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["aprobadas"] == 2

    f1_actualizada = client.get(f"/empresas/{empresa_a['id']}/documentos/{f1['id']}").json()
    assert f1_actualizada["estado"] == "contabilizada"


def test_contabilizar_masivo_omite_las_que_no_tienen_partida(client, empresa_a):
    f1 = _cargar_factura(client, empresa_a["id"], "FM008", "cufe-masivo-8", "900701300")
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/contabilizar-masivo", json={
        "factura_ids": [f1["id"]],
    })
    body = r.json()
    assert body["aprobadas"] == 0
    assert body["detalle"][0]["estado"] == "omitida"
