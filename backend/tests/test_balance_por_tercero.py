import io
import pandas as pd


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _importar_balance(client, empresa_id, filas):
    df = pd.DataFrame(filas)
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_id}/historial/importar",
        files={"archivo": ("balance_terceros.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA", "mapeo_nombre_cuenta": "NOMBRE CUENTA"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_balance_por_tercero_ensena_nombres_reales_de_cuentas(client, empresa_a):
    body = _importar_balance(client, empresa_a["id"], {
        "NIT": ["900100100"], "CUENTA": ["240802001"], "NOMBRE CUENTA": ["IVA Descontable 19%"],
    })
    assert body["registros_validos"] == 1

    r = client.get(f"/empresas/{empresa_a['id']}/cuentas")
    cuenta = next(c for c in r.json() if c["codigo"] == "240802001")
    assert cuenta["nombre"] == "IVA Descontable 19%"


def test_actualiza_nombre_de_cuenta_existente_que_solo_tenia_el_codigo(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "513595"})
    _importar_balance(client, empresa_a["id"], {
        "NIT": ["900200200"], "CUENTA": ["513595"], "NOMBRE CUENTA": ["Honorarios Profesionales"],
    })
    r = client.get(f"/empresas/{empresa_a['id']}/cuentas")
    cuenta = next(c for c in r.json() if c["codigo"] == "513595")
    assert cuenta["nombre"] == "Honorarios Profesionales"


def test_no_pisa_un_nombre_real_que_el_usuario_ya_habia_puesto_a_mano(client, empresa_a):
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Mi nombre elegido"})
    _importar_balance(client, empresa_a["id"], {
        "NIT": ["900300300"], "CUENTA": ["513595"], "NOMBRE CUENTA": ["Otro nombre del balance"],
    })
    r = client.get(f"/empresas/{empresa_a['id']}/cuentas")
    cuenta = next(c for c in r.json() if c["codigo"] == "513595")
    assert cuenta["nombre"] == "Mi nombre elegido"


def test_sugerencia_distingue_iva_19_de_iva_5_por_nombre_de_cuenta_propia(client, empresa_a):
    _importar_balance(client, empresa_a["id"], {
        "NIT": ["900400400", "900400400"],
        "CUENTA": ["240802019", "240802005"],
        "NOMBRE CUENTA": ["IVA Descontable Compras 19%", "IVA Descontable Compras 5%"],
    })

    sug_19 = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                         params={"nit": "900999888", "descripcion": "compras con IVA 19%"}).json()
    assert sug_19["fuente"] == "cuentas_propias"
    codigos_19 = [o["cuenta_codigo"] for o in sug_19["opciones"]]
    assert "240802019" in codigos_19

    sug_5 = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                        params={"nit": "900999888", "descripcion": "compras con IVA 5%"}).json()
    codigos_5 = [o["cuenta_codigo"] for o in sug_5["opciones"]]
    assert "240802005" in codigos_5


def test_sugerencia_distingue_servicio_de_compra_por_nombre_de_cuenta_propia(client, empresa_a):
    _importar_balance(client, empresa_a["id"], {
        "NIT": ["900500500", "900500500"],
        "CUENTA": ["613501", "511005"],
        "NOMBRE CUENTA": ["Compra de mercancía", "Servicios prestados por terceros"],
    })

    sug_servicio = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                               params={"nit": "900999777", "descripcion": "pago de servicios de aseo"}).json()
    codigos = [o["cuenta_codigo"] for o in sug_servicio["opciones"]]
    assert "511005" in codigos
    assert "613501" not in codigos


def test_cuentas_propias_tiene_prioridad_sobre_catalogo_puc_generico(client, empresa_a):
    _importar_balance(client, empresa_a["id"], {
        "NIT": ["900600600"], "CUENTA": ["511099888"], "NOMBRE CUENTA": ["Honorarios Contador Externo"],
    })
    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                      params={"nit": "900999666", "descripcion": "honorarios del mes"}).json()
    assert sug["fuente"] == "cuentas_propias"
