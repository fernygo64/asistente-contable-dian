from tests.test_documentos import _xml, _zip_bytes


def test_listar_cargas_muestra_solo_nombre_y_fecha(client, empresa_a):
    zip1 = _zip_bytes({"FR001.xml": _xml("FR001", "cufe-carga-1", "900980950", subtotal="30000", total="30000")})
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                     files=[("documentos", ("primer_lote.zip", zip1, "application/zip"))])
    assert r.status_code == 201

    zip2 = _zip_bytes({"FR002.xml": _xml("FR002", "cufe-carga-2", "900980951", subtotal="30000", total="30000")})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("segundo_lote.zip", zip2, "application/zip"))])

    r2 = client.get(f"/empresas/{empresa_a['id']}/documentos/cargas")
    assert r2.status_code == 200
    cargas = r2.json()
    assert len(cargas) == 2
    nombres = [c["archivo_zip_nombre"] for c in cargas]
    assert "segundo_lote.zip" in nombres
    assert "primer_lote.zip" in nombres
    assert cargas[0]["archivo_zip_nombre"] == "segundo_lote.zip"


def test_listar_cargas_vacio_sin_cargas(client, empresa_a):
    r = client.get(f"/empresas/{empresa_a['id']}/documentos/cargas")
    assert r.status_code == 200
    assert r.json() == []
