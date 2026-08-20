import io
import pandas as pd


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _configurar_cuentas_nomina(client, empresa_id):
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={
        "cuenta_nomina_por_pagar": "2505050000", "cuenta_salud_por_pagar": "2370050000",
        "cuenta_pension_por_pagar": "2380300000", "cuenta_arl_por_pagar": "2370060000",
    })


def _cargar_historial(client, empresa_id, filas):
    df = pd.DataFrame(filas)
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_id}/historial/importar",
        files={"archivo": ("h.xlsx", contenido, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA", "mapeo_nombre": "NOMBRE",
              "mapeo_numero_documento": "DOCUMENTO"},
    )
    assert r.status_code == 201, r.text


def test_detectar_empleados_desde_un_comprobante_real_de_nomina(client, empresa_a):
    _configurar_cuentas_nomina(client, empresa_a["id"])
    _cargar_historial(client, empresa_a["id"], {
        "NIT": ["1093216007", "860066942", "800229739"],
        "CUENTA": ["2505050000", "2370050000", "2380300000"],
        "NOMBRE": ["ANGELA ROSA ALVAREZ GIRALDO", "EPS SURA", "PORVENIR"],
        "DOCUMENTO": ["NOM-100", "NOM-100", "NOM-100"],
    })

    r = client.get(f"/empresas/{empresa_a['id']}/historial/detectar-empleados")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["candidatos"]) == 1
    candidato = body["candidatos"][0]
    assert candidato["nit"] == "1093216007"
    assert candidato["nombre"] == "ANGELA ROSA ALVAREZ GIRALDO"
    assert candidato["eps_nit"] == "860066942"
    assert candidato["eps_nombre"] == "EPS SURA"
    assert candidato["afp_nit"] == "800229739"
    assert candidato["afp_nombre"] == "PORVENIR"
    assert candidato["arl_nit"] is None


def test_detectar_empleados_agrupa_varios_comprobantes_del_mismo_empleado(client, empresa_a):
    _configurar_cuentas_nomina(client, empresa_a["id"])
    _cargar_historial(client, empresa_a["id"], {
        "NIT": ["30334248", "900156264", "30334248", "900336004"],
        "CUENTA": ["2505050000", "2370050000", "2505050000", "2380300000"],
        "NOMBRE": ["ZORAIDA MUÑOZ CARMONA", "NUEVA EPS", "ZORAIDA MUÑOZ CARMONA", "COLPENSIONES"],
        "DOCUMENTO": ["NOM-200", "NOM-200", "NOM-201", "NOM-201"],
    })

    r = client.get(f"/empresas/{empresa_a['id']}/historial/detectar-empleados")
    candidatos = r.json()["candidatos"]
    assert len(candidatos) == 1
    c = candidatos[0]
    assert c["eps_nit"] == "900156264"
    assert c["afp_nit"] == "900336004"
    assert c["comprobantes_detectados"] == 2


def test_detectar_empleados_no_repite_empleados_ya_creados(client, empresa_a):
    _configurar_cuentas_nomina(client, empresa_a["id"])
    client.post(f"/empresas/{empresa_a['id']}/empleados", json={"nit": "1093216007", "nombre": "Angela"})
    _cargar_historial(client, empresa_a["id"], {
        "NIT": ["1093216007", "860066942"],
        "CUENTA": ["2505050000", "2370050000"],
        "NOMBRE": ["ANGELA", "EPS SURA"],
        "DOCUMENTO": ["NOM-300", "NOM-300"],
    })
    r = client.get(f"/empresas/{empresa_a['id']}/historial/detectar-empleados")
    assert r.json()["candidatos"] == []


def test_detectar_empleados_sin_cuenta_nomina_por_pagar_configurada_avisa(client, empresa_a):
    r = client.get(f"/empresas/{empresa_a['id']}/historial/detectar-empleados")
    assert r.status_code == 200
    body = r.json()
    assert body["candidatos"] == []
    assert body["aviso"] is not None
