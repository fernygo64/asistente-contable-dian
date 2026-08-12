from tests.test_aislamiento import registrar


def test_sin_historial_no_inventa_cuenta(client, empresa_a):
    r = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900000000"})
    body = r.json()
    assert body["cuenta_sugerida"] is None
    assert body["fuente"] == "sin_informacion"
    assert "Sin historial suficiente" in body["motivo"]


def test_sugerencia_replica_ejemplo_del_documento(client, empresa_a):
    """
    Reproduce el ejemplo textual de la sección 1:
    42 documentos: 35 -> 513595, 5 -> 519595, 2 -> 513520
    Sugerencia esperada: 513595, con 83.3% en el motivo.
    """
    nit = "900123456"
    registrar(client, empresa_a["id"], nit, "513595", veces=35)
    registrar(client, empresa_a["id"], nit, "519595", veces=5)
    registrar(client, empresa_a["id"], nit, "513520", veces=2)

    body = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": nit}).json()

    assert body["total_documentos_historicos"] == 42
    assert body["cuenta_sugerida"] == "513595"
    assert body["fuente"] == "historial"
    principal = next(o for o in body["opciones"] if o["cuenta_codigo"] == "513595")
    assert principal["usos"] == 35
    assert principal["porcentaje"] == 83.3
    assert "83.3" in body["motivo"] or "83,3" in body["motivo"]
    # las cuentas minoritarias deben seguir apareciendo, no se eliminan (sección 10)
    codigos = [o["cuenta_codigo"] for o in body["opciones"]]
    assert "519595" in codigos and "513520" in codigos


def test_correccion_del_usuario_no_borra_historial_previo(client, empresa_a):
    """
    Sección 11: el usuario cambia la sugerencia -> se agrega una nueva
    decisión, la anterior se conserva íntegra.
    """
    nit = "900123456"
    registrar(client, empresa_a["id"], nit, "513595", veces=1)

    sugerencia_inicial = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                                     params={"nit": nit}).json()
    assert sugerencia_inicial["cuenta_sugerida"] == "513595"

    # el usuario corrige por 519595
    r = client.post(f"/empresas/{empresa_a['id']}/historial/decision",
                     json={"proveedor_nit": nit, "cuenta_codigo": "519595", "origen": "manual"})
    assert r.status_code == 201

    sugerencia_final = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                                   params={"nit": nit}).json()
    # ahora hay 2 documentos en total: el historial no se borró, se sumó
    assert sugerencia_final["total_documentos_historicos"] == 2
    codigos = [o["cuenta_codigo"] for o in sugerencia_final["opciones"]]
    assert "513595" in codigos  # la decisión original sigue existiendo
    assert "519595" in codigos


def test_regla_se_usa_cuando_no_hay_historial(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/reglas", json={
        "nombre": "Proveedores de transporte",
        "criterio": {"nit": "900777777"},
        "cuenta_codigo": "522035",
    })
    assert r.status_code == 201

    body = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                       params={"nit": "900777777"}).json()
    assert body["cuenta_sugerida"] == "522035"
    assert body["fuente"] == "regla"
    assert "Regla de empresa" in body["motivo"]


def test_historial_tiene_prioridad_sobre_regla(client, empresa_a):
    nit = "900777777"
    client.post(f"/empresas/{empresa_a['id']}/reglas", json={
        "nombre": "Regla genérica", "criterio": {"nit": nit}, "cuenta_codigo": "522035",
    })
    registrar(client, empresa_a["id"], nit, "513595", veces=4)

    body = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": nit}).json()
    assert body["fuente"] == "historial"
    assert body["cuenta_sugerida"] == "513595"
