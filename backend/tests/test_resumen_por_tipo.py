from tests.test_documentos import _xml, _zip_bytes
from tests.test_clasificacion_documentos import _factura


def test_resumen_agrupa_por_tipo_con_cantidad_y_total(client, empresa_a):
    zip1 = _zip_bytes({"FR001.xml": _xml("FR001", "cufe-res-1", "900970001", subtotal="50000", total="50000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip1, "application/zip"))])
    zip2 = _zip_bytes({"FR002.xml": _xml("FR002", "cufe-res-2", "900970002", subtotal="30000", total="30000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip2, "application/zip"))])
    zip3 = _zip_bytes({"FR003.xml": _factura("FR003", "cufe-res-3", empresa_a["nit"], subtotal="80000", total="80000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip3, "application/zip"))])

    r = client.get(f"/empresas/{empresa_a['id']}/documentos/resumen-por-tipo")
    assert r.status_code == 200, r.text
    body = r.json()

    recibidas = next(g for g in body["grupos"] if g["tipo"] == "Facturas recibidas (compras)")
    assert recibidas["cantidad"] == 2
    assert recibidas["total"] == 80000.0
    assert recibidas["es_gasto"] is True

    emitidas = next(g for g in body["grupos"] if g["tipo"] == "Facturas emitidas (ventas)")
    assert emitidas["cantidad"] == 1
    assert emitidas["total"] == 80000.0
    assert emitidas["es_gasto"] is False

    assert body["total_gastos"] == 80000.0
    assert body["total_ingresos"] == 80000.0


def test_resumen_nunca_cuenta_duplicados(client, empresa_a):
    zip1 = _zip_bytes({"FD001.xml": _xml("FD001", "cufe-dup-1", "900970003", subtotal="20000", total="20000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip1, "application/zip"))])
    zip2 = _zip_bytes({"FD001b.xml": _xml("FD001", "cufe-dup-1", "900970003", subtotal="20000", total="20000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", zip2, "application/zip"))])

    r = client.get(f"/empresas/{empresa_a['id']}/documentos/resumen-por-tipo")
    body = r.json()
    recibidas = next((g for g in body["grupos"] if g["tipo"] == "Facturas recibidas (compras)"), None)
    assert recibidas["cantidad"] == 1


def test_resumen_vacio_sin_facturas(client, empresa_a):
    r = client.get(f"/empresas/{empresa_a['id']}/documentos/resumen-por-tipo")
    assert r.status_code == 200
    body = r.json()
    assert body["grupos"] == []
    assert body["total_gastos"] == 0
    assert body["total_ingresos"] == 0
