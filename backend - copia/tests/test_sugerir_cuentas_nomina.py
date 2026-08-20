def test_sugerir_cuentas_nomina_por_nombre_real(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "5105060000", "nombre": "SALARIO INTEGRAL"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "2505050000", "nombre": "NOMINA POR PAGAR"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "2370050000", "nombre": "SALUD POR PAGAR"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "5105300000", "nombre": "CESANTIAS"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "220501", "nombre": "PROVEEDORES NACIONALES"})

    r = client.get(f"/empresas/{empresa_a['id']}/historial/sugerir-cuentas-nomina")
    assert r.status_code == 200, r.text
    sugerencias = r.json()["sugerencias"]
    assert sugerencias["cuenta_salario"]["codigo"] == "5105060000"
    assert sugerencias["cuenta_nomina_por_pagar"]["codigo"] == "2505050000"
    assert sugerencias["cuenta_salud_por_pagar"]["codigo"] == "2370050000"
    assert sugerencias["cuenta_cesantias"]["codigo"] == "5105300000"
    assert "cuenta_prima" not in sugerencias


def test_sugerir_cuentas_nomina_ambiguedad_no_arriesga(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "5105300001", "nombre": "CESANTIAS EMPLEADOS PLANTA"})
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "5105300002", "nombre": "CESANTIAS EMPLEADOS ADMINISTRATIVOS"})

    r = client.get(f"/empresas/{empresa_a['id']}/historial/sugerir-cuentas-nomina")
    assert "cuenta_cesantias" not in r.json()["sugerencias"]


def test_sugerir_cuentas_nomina_sin_cuentas_no_falla(client, empresa_a):
    r = client.get(f"/empresas/{empresa_a['id']}/historial/sugerir-cuentas-nomina")
    assert r.status_code == 200
    assert r.json()["sugerencias"] == {}
