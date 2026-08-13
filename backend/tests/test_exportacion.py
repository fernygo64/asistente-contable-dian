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
    assert r.json()["balanceado"] is True, r.json()
    return factura


SIIGO_COLUMNAS = [
    {"label": "Fecha", "source": "fecha", "valor_fijo": ""},
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Nit", "source": "nit", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]

WORLD_OFFICE_COLUMNAS = SIIGO_COLUMNAS + [{"label": "Tercero", "source": "tercero", "valor_fijo": ""}]


def test_crear_plantilla_siigo(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo estándar", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS,
    })
    assert r.status_code == 201, r.text
    assert r.json()["sistema_contable"] == "siigo_pyme"


def test_plantilla_sin_columnas_obligatorias_falla_validacion_de_adaptador(client, empresa_a):
    """Siigo exige Fecha/Cuenta/Nit/Debito/Credito; una plantilla incompleta debe fallar."""
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Incompleta", "sistema_contable": "siigo_pyme",
        "columnas": [{"label": "Cuenta", "source": "cuenta", "valor_fijo": ""}],
    })
    plantilla_id = r.json()["id"]

    factura = _preparar_factura_lista(client, empresa_a["id"], "FEX001", "cufe-exp-1", "900711711")
    r2 = client.post(f"/empresas/{empresa_a['id']}/exportaciones/validar",
                      json={"plantilla_id": plantilla_id, "factura_ids": [factura["id"]]})
    body = r2.json()
    assert body["valido"] is False
    assert any("valor del movimiento" in e for e in body["errores"])


def test_siigo_acepta_debito_credito_combinado_world_office_no(client, empresa_a):
    """
    Diferencia estructural real confirmada con archivos reales de ambos
    sistemas (sección 21: adaptadores genuinamente distintos, no la
    misma lógica con otro nombre): Siigo Pyme (Movimiento Contable) usa
    una sola columna D/C + Valor; World Office siempre usa Débito y
    Crédito como columnas separadas — una plantilla con solo el
    indicador combinado es válida para Siigo pero no para World Office.
    """
    columnas_combinadas = [
        {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
        {"label": "Nit", "source": "nit", "valor_fijo": ""},
        {"label": "DC", "source": "debito_credito", "valor_fijo": ""},
        {"label": "Valor", "source": "valor", "valor_fijo": ""},
    ]
    r_siigo = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo combinado", "sistema_contable": "siigo_pyme", "columnas": columnas_combinadas,
    })
    r_wo = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "WO combinado", "sistema_contable": "world_office", "columnas": columnas_combinadas,
    })

    factura = _preparar_factura_lista(client, empresa_a["id"], "FEX002", "cufe-exp-2", "900722722")

    val_siigo = client.post(f"/empresas/{empresa_a['id']}/exportaciones/validar",
                             json={"plantilla_id": r_siigo.json()["id"], "factura_ids": [factura["id"]]}).json()
    val_wo = client.post(f"/empresas/{empresa_a['id']}/exportaciones/validar",
                          json={"plantilla_id": r_wo.json()["id"], "factura_ids": [factura["id"]]}).json()

    assert val_siigo["valido"] is True     # Siigo sí acepta el indicador D/C combinado
    assert val_wo["valido"] is False       # World Office exige Débito y Crédito como columnas separadas


def test_no_permite_exportar_factura_sin_partida_generada(client, empresa_a):
    zip_contenido = _zip_bytes({"FEX003.xml": _xml("FEX003", "cufe-exp-3", "900733733")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900733733"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo test3", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS,
    })
    val = client.post(f"/empresas/{empresa_a['id']}/exportaciones/validar",
                       json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]}).json()
    assert val["valido"] is False
    assert any("partida doble" in e for e in val["errores"])


def test_generar_exportacion_produce_archivo_real_y_balanceado(client, empresa_a):
    factura = _preparar_factura_lista(client, empresa_a["id"], "FEX004", "cufe-exp-4", "900744744",
                                       subtotal="90000", total="90000")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo export real", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS,
    })
    plantilla_id = r.json()["id"]

    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": plantilla_id, "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    contenido = resp.content.decode("utf-8")
    lineas = contenido.strip().split("\r\n")
    assert lineas[0] == "Fecha|Cuenta|Nit|Debito|Credito"  # encabezado en el orden configurado
    assert len(lineas) == 3  # encabezado + 2 movimientos (gasto + proveedores)

    total_debito = sum(float(l.split("|")[3]) for l in lineas[1:] if l.split("|")[3])
    total_credito = sum(float(l.split("|")[4]) for l in lineas[1:] if l.split("|")[4])
    assert abs(total_debito - total_credito) < 0.01

    factura_final = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}").json()
    assert factura_final["estado"] == "exportada"


def test_exportacion_queda_registrada_en_historial_de_exportaciones(client, empresa_a):
    factura = _preparar_factura_lista(client, empresa_a["id"], "FEX005", "cufe-exp-5", "900755755")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo export log", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS,
    })
    client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})

    exportaciones = client.get(f"/empresas/{empresa_a['id']}/exportaciones").json()
    assert len(exportaciones) == 1
    assert exportaciones[0]["estado"] == "generada"
    assert exportaciones[0]["cantidad_registros"] == 2


def test_equivalencia_de_cuentas_se_aplica_en_el_archivo(client, empresa_a):
    """Sección 22: dos plantillas del mismo sistema pueden usar códigos de cuenta distintos."""
    factura = _preparar_factura_lista(client, empresa_a["id"], "FEX006", "cufe-exp-6", "900766766",
                                       cuenta_gasto="513595")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo con equivalencia", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS,
        "equivalencias_cuentas": {"513595": "999888"},   # este software usa otro código para esa cuenta
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    contenido = resp.content.decode("utf-8")
    assert "999888" in contenido
    assert "513595" not in contenido  # el código interno no debe filtrarse al archivo final


def test_exportacion_no_se_filtra_entre_empresas(client, empresa_a, empresa_b):
    r = client.post(f"/empresas/{empresa_b['id']}/plantillas", json={
        "nombre": "Plantilla de B", "sistema_contable": "siigo_pyme", "columnas": SIIGO_COLUMNAS,
    })
    plantillas_a = client.get(f"/empresas/{empresa_a['id']}/plantillas").json()
    assert all(p["nombre"] != "Plantilla de B" for p in plantillas_a)
