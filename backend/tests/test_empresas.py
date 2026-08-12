def test_crear_empresa(client):
    r = client.post("/empresas", json={"nit": "900333333", "nombre": "Nueva Empresa"})
    assert r.status_code == 201
    body = r.json()
    assert body["nit"] == "900333333"
    assert body["activa"] is True


def test_no_permite_nit_duplicado(client, empresa_a):
    r = client.post("/empresas", json={"nit": empresa_a["nit"], "nombre": "Otra"})
    assert r.status_code == 409


def test_crear_empresa_no_requiere_tocar_codigo(client):
    """Crear una empresa nueva debe ser puramente un POST — sin cambios de código."""
    r1 = client.post("/empresas", json={"nit": "900444444", "nombre": "Empresa X"})
    r2 = client.post("/empresas", json={"nit": "900555555", "nombre": "Empresa Y"})
    assert r1.status_code == 201 and r2.status_code == 201
    listado = client.get("/empresas").json()
    nits = [e["nit"] for e in listado]
    assert "900444444" in nits and "900555555" in nits


def test_empresa_inexistente_da_404(client):
    r = client.get("/empresas/no-existe-este-id/cuentas")
    assert r.status_code == 404
