from tests.test_documentos import _xml, _zip_bytes
from tests.test_clasificacion_documentos import _nota_credito, _factura


# ------------------------------------------------------------------- PUC
def test_puc_tiene_catalogo_sembrado(client):
    r = client.get("/puc/buscar", params={"q": "caja"})
    assert r.status_code == 200
    codigos = [c["codigo"] for c in r.json()]
    assert "110505" in codigos


def test_buscar_puc_por_codigo(client):
    r = client.get("/puc/buscar", params={"q": "220501"})
    resultados = r.json()
    assert len(resultados) == 1
    assert resultados[0]["nombre"] == "Proveedores nacionales"


def test_buscar_puc_por_nombre_parcial(client):
    r = client.get("/puc/buscar", params={"q": "retencion"})
    nombres = [c["nombre"].lower() for c in r.json()]
    assert any("retenci" in n for n in nombres)


def test_buscar_puc_sin_texto_devuelve_resultados_limitados(client):
    r = client.get("/puc/buscar")
    assert r.status_code == 200
    assert len(r.json()) <= 20


# --------------------------------------------------- Comprobantes por tipo
def test_configurar_y_obtener_comprobantes_por_tipo(client, empresa_a):
    r = client.patch(f"/empresas/{empresa_a['id']}/comprobantes-por-tipo", json={
        "comprobante_factura_recibida": "CC",
        "comprobante_factura_emitida": "FV",
        "comprobante_nota_credito": "NC",
        "comprobante_nomina": "NI",
    })
    assert r.status_code == 200

    r2 = client.get(f"/empresas/{empresa_a['id']}/comprobantes-por-tipo")
    body = r2.json()
    assert body["comprobante_factura_recibida"] == "CC"
    assert body["comprobante_factura_emitida"] == "FV"
    assert body["comprobante_nota_credito"] == "NC"
    assert body["comprobante_nomina"] == "NI"


def _preparar_factura_recibida(client, empresa_id, numero, cufe, nit, cuenta="513595"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal="90000", total="90000")})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]
    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": cuenta, "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": cuenta, "contrapartida": "proveedores"})
    return client.get(f"/empresas/{empresa_id}/documentos/{factura['id']}").json()


COLUMNAS_CON_TIPO_COMPROBANTE = [
    {"label": "TipoComp", "source": "tipo_comprobante", "valor_fijo": ""},
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def test_exportacion_usa_comprobante_de_compra_para_factura_recibida(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/comprobantes-por-tipo", json={
        "comprobante_factura_recibida": "CC", "comprobante_factura_emitida": "FV",
    })
    factura = _preparar_factura_recibida(client, empresa_a["id"], "FTC001", "cufe-tc-1", "900971971")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Con tipo comprobante", "sistema_contable": "siigo_pyme",
        "columnas": COLUMNAS_CON_TIPO_COMPROBANTE,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    lineas = resp.content.decode("utf-8").strip().split("\r\n")
    for fila in lineas[1:]:
        assert fila.split("|")[0] == "CC"  # comprobante de compra, no el de venta


def test_exportacion_usa_comprobante_de_venta_para_factura_emitida(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/comprobantes-por-tipo", json={
        "comprobante_factura_recibida": "CC", "comprobante_factura_emitida": "FV",
    })
    zip_contenido = _zip_bytes({"FTC002.xml": _factura("FTC002", "cufe-tc-2", empresa_a["nit"],
                                                         subtotal="150000", total="150000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"direccion": "emitida"}).json()[0]
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "413501", "nombre": "Ingresos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_clientes": "130505"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "413501", "contrapartida": "clientes"})

    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Con tipo comprobante venta", "sistema_contable": "siigo_pyme",
        "columnas": COLUMNAS_CON_TIPO_COMPROBANTE,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    lineas = resp.content.decode("utf-8").strip().split("\r\n")
    for fila in lineas[1:]:
        assert fila.split("|")[0] == "FV"  # comprobante de venta, no el de compra


def test_exportacion_usa_comprobante_de_nota_credito(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/comprobantes-por-tipo", json={
        "comprobante_factura_recibida": "CC", "comprobante_nota_credito": "NC",
    })
    zip_contenido = _zip_bytes({"NC003.xml": _nota_credito("NC003", "cufe-tc-3", "900972972",
                                                             subtotal="30000", total="30000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nota_credito"}).json()[0]
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores"})

    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Con tipo comprobante NC", "sistema_contable": "siigo_pyme",
        "columnas": COLUMNAS_CON_TIPO_COMPROBANTE,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    lineas = resp.content.decode("utf-8").strip().split("\r\n")
    for fila in lineas[1:]:
        assert fila.split("|")[0] == "NC"


def test_comprobante_no_configurado_queda_vacio_sin_inventar(client, empresa_a):
    """Si la empresa no configuró el comprobante para ese tipo, la columna sale vacía — no se inventa un código."""
    factura = _preparar_factura_recibida(client, empresa_a["id"], "FTC004", "cufe-tc-4", "900973973")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Sin comprobante configurado", "sistema_contable": "siigo_pyme",
        "columnas": COLUMNAS_CON_TIPO_COMPROBANTE,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    lineas = resp.content.decode("utf-8").strip().split("\r\n")
    for fila in lineas[1:]:
        assert fila.split("|")[0] == ""
