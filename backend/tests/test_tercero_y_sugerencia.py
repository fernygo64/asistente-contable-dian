from tests.test_documentos import _xml, _zip_bytes
from tests.test_clasificacion_documentos import _factura


def test_factura_recibida_usa_emisor_como_tercero(client, empresa_a):
    zip_contenido = _zip_bytes({"FTR001.xml": _xml("FTR001", "cufe-ter-1", "900980980", nombre="Proveedor Real SAS")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"nit_emisor": "900980980"}).json()[0]
    assert factura["tercero_nit"] == "900980980"
    assert factura["tercero_nombre"] == "Proveedor Real SAS"


def test_factura_emitida_usa_receptor_como_tercero_no_la_propia_empresa(client, empresa_a):
    """El bug real reportado: antes siempre mostraba el emisor (la propia empresa en una venta)."""
    zip_contenido = _zip_bytes({"FTR002.xml": _factura("FTR002", "cufe-ter-2", empresa_a["nit"])})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]
    assert factura["nit_emisor"] == empresa_a["nit"]
    assert factura["tercero_nit"] != empresa_a["nit"]


def test_historial_de_venta_se_registra_contra_el_cliente_no_la_propia_empresa(client, empresa_a):
    zip_contenido = _zip_bytes({"FTR003.xml": _factura("FTR003", "cufe-ter-3", empresa_a["nit"], subtotal="80000", total="80000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]
    cliente_nit = factura["tercero_nit"]

    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413501", "nombre": "Ingresos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_clientes": "130505"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "413501", "contrapartida": "clientes"})

    sug_cliente = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": cliente_nit}).json()
    assert sug_cliente["total_documentos_historicos"] == 1
    sug_propia = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": empresa_a["nit"]}).json()
    assert sug_propia["total_documentos_historicos"] == 0


def test_sugerencia_prioriza_coincidencia_de_concepto_sobre_frecuencia_general(client, empresa_a):
    nit = "900990990"
    for _ in range(3):
        r = client.post(f"/empresas/{empresa_a['id']}/historial/decision", json={
            "proveedor_nit": nit, "cuenta_codigo": "519530", "origen": "manual", "descripcion": "papeleria oficina",
        })
        assert r.status_code == 201
    r2 = client.post(f"/empresas/{empresa_a['id']}/historial/decision", json={
        "proveedor_nit": nit, "cuenta_codigo": "522035", "origen": "manual", "descripcion": "transporte de mercancia",
    })
    assert r2.status_code == 201

    sug_general = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": nit}).json()
    assert sug_general["cuenta_sugerida"] == "519530"
    assert sug_general["fuente"] == "historial"

    sug_transporte = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                                 params={"nit": nit, "descripcion": "transporte urgente"}).json()
    assert sug_transporte["cuenta_sugerida"] == "522035"
    assert sug_transporte["fuente"] == "historial_nit_concepto"


def test_sugerencia_sin_coincidencia_de_concepto_cae_a_frecuencia_general(client, empresa_a):
    nit = "900991991"
    client.post(f"/empresas/{empresa_a['id']}/historial/decision", json={
        "proveedor_nit": nit, "cuenta_codigo": "519530", "origen": "manual", "descripcion": "papeleria oficina",
    })
    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                      params={"nit": nit, "descripcion": "concepto totalmente distinto sin relacion"}).json()
    assert sug["fuente"] == "historial"
    assert "frecuencia general" in sug["motivo"]


def test_sin_historial_ni_regla_sugiere_candidatos_del_puc_por_concepto(client, empresa_a):
    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                      params={"nit": "900992992", "descripcion": "pago de honorarios profesionales"}).json()
    assert sug["fuente"] == "puc_catalogo"
    assert sug["cuenta_sugerida"] is None
    codigos = [o["cuenta_codigo"] for o in sug["opciones"]]
    assert "511005" in codigos


def test_sin_historial_regla_ni_coincidencia_puc_no_inventa_nada(client, empresa_a):
    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                      params={"nit": "900993993"}).json()
    assert sug["fuente"] == "sin_informacion"
    assert sug["cuenta_sugerida"] is None
