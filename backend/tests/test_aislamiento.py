"""
Reproduce EXACTAMENTE el ejemplo de la sección 2 del documento:

Empresa A: NIT proveedor 900123456 -> cuenta 513595
Empresa B: NIT proveedor 900123456 -> cuenta 520505

Ambas deben quedar completamente independientes.
"""


def registrar(client, empresa_id, nit, cuenta, veces=1):
    for _ in range(veces):
        r = client.post(
            f"/empresas/{empresa_id}/historial/decision",
            json={"proveedor_nit": nit, "cuenta_codigo": cuenta, "origen": "manual"},
        )
        assert r.status_code == 201


def test_mismo_nit_dos_empresas_no_se_mezcla(client, empresa_a, empresa_b):
    nit_compartido = "900123456"

    registrar(client, empresa_a["id"], nit_compartido, "513595", veces=3)
    registrar(client, empresa_b["id"], nit_compartido, "520505", veces=2)

    sug_a = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                        params={"nit": nit_compartido}).json()
    sug_b = client.get(f"/empresas/{empresa_b['id']}/historial/sugerencia",
                        params={"nit": nit_compartido}).json()

    assert sug_a["cuenta_sugerida"] == "513595"
    assert sug_a["total_documentos_historicos"] == 3
    assert sug_b["cuenta_sugerida"] == "520505"
    assert sug_b["total_documentos_historicos"] == 2

    # La cuenta 513595 de la empresa A no debe aparecer para nada en B
    codigos_b = [o["cuenta_codigo"] for o in sug_b["opciones"]]
    assert "513595" not in codigos_b


def test_proveedores_no_se_filtran_entre_empresas(client, empresa_a, empresa_b):
    registrar(client, empresa_a["id"], "900999888", "519595")
    proveedores_b = client.get(f"/empresas/{empresa_b['id']}/proveedores").json()
    nits_b = [p["nit"] for p in proveedores_b]
    assert "900999888" not in nits_b


def test_cuentas_no_se_filtran_entre_empresas(client, empresa_a, empresa_b):
    client.post(f"/empresas/{empresa_a['id']}/cuentas",
                json={"codigo": "111111", "nombre": "Cuenta exclusiva de A"})
    cuentas_b = client.get(f"/empresas/{empresa_b['id']}/cuentas").json()
    codigos_b = [c["codigo"] for c in cuentas_b]
    assert "111111" not in codigos_b


def test_auditoria_no_se_filtra_entre_empresas(client, empresa_a, empresa_b):
    registrar(client, empresa_a["id"], "900123456", "513595")
    audit_b = client.get(f"/empresas/{empresa_b['id']}/auditoria").json()
    assert all(ev["entidad_id"] != empresa_a["id"] for ev in audit_b)
