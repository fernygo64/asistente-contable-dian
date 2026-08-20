def test_crear_y_listar_empleado(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/empleados", json={
        "nit": "1093216007", "nombre": "ANGELA ROSA ALVAREZ GIRALDO",
        "eps_nit": "860066942", "eps_nombre": "EPS SURA",
        "afp_nit": "800229739", "afp_nombre": "PORVENIR",
        "arl_nit": "860011153", "arl_nombre": "ARL SURA",
        "caja_compensacion_nit": "860066942", "caja_compensacion_nombre": "COMPENSAR",
    })
    assert r.status_code == 201, r.text
    empleado = r.json()
    assert empleado["nit"] == "1093216007"
    assert empleado["eps_nombre"] == "EPS SURA"
    assert empleado["activo"] is True

    r2 = client.get(f"/empresas/{empresa_a['id']}/empleados")
    assert len(r2.json()) == 1


def test_no_se_puede_duplicar_nit_de_empleado_en_la_misma_empresa(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/empleados", json={"nit": "30334248", "nombre": "Zoraida"})
    r = client.post(f"/empresas/{empresa_a['id']}/empleados", json={"nit": "30334248", "nombre": "Otro nombre"})
    assert r.status_code == 409


def test_mismo_nit_permitido_en_empresas_distintas(client, empresa_a, empresa_b):
    r1 = client.post(f"/empresas/{empresa_a['id']}/empleados", json={"nit": "30334248", "nombre": "Zoraida"})
    r2 = client.post(f"/empresas/{empresa_b['id']}/empleados", json={"nit": "30334248", "nombre": "Zoraida en otra empresa"})
    assert r1.status_code == 201
    assert r2.status_code == 201


def test_actualizar_empleado(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/empleados", json={"nit": "30334248", "nombre": "Zoraida"})
    empleado_id = r.json()["id"]

    r2 = client.patch(f"/empresas/{empresa_a['id']}/empleados/{empleado_id}", json={
        "nit": "30334248", "nombre": "Zoraida Muñoz Carmona", "eps_nit": "900156264", "eps_nombre": "NUEVA EPS",
    })
    assert r2.status_code == 200
    assert r2.json()["eps_nombre"] == "NUEVA EPS"


def test_eliminar_empleado(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/empleados", json={"nit": "30334248", "nombre": "Zoraida"})
    empleado_id = r.json()["id"]
    r2 = client.delete(f"/empresas/{empresa_a['id']}/empleados/{empleado_id}")
    assert r2.status_code == 200
    assert client.get(f"/empresas/{empresa_a['id']}/empleados").json() == []


def test_configurar_cuentas_de_nomina(client, empresa_a):
    r = client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={
        "cuenta_salario": "5105060000", "cuenta_nomina_por_pagar": "2505050000",
        "cuenta_salud_por_pagar": "2370050000", "cuenta_pension_por_pagar": "2380300000",
        "cuenta_cesantias": "5105300000", "cuenta_cesantias_por_pagar": "2610050000",
        "cuenta_arl": "5105680000", "cuenta_arl_por_pagar": "2370060000",
    })
    assert r.status_code == 200, r.text

    r2 = client.get(f"/empresas/{empresa_a['id']}/cuentas-base")
    body = r2.json()
    assert body["cuenta_salario"]["codigo"] == "5105060000"
    assert body["cuenta_nomina_por_pagar"]["codigo"] == "2505050000"
    assert body["cuenta_arl"]["codigo"] == "5105680000"
