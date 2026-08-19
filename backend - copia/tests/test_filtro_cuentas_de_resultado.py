import io
import pandas as pd


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_filtro_excluye_retencion_del_historial_como_candidato_de_gasto(client, empresa_a):
    df = pd.DataFrame({
        "NIT": ["900690656", "900690656", "900690656"],
        "CUENTA": ["510506", "13551508", "510503"],
        "NOMBRE CUENTA": ["SUELDOS", "RETEFUENTE SALARIOS ART 383", "PRIMA"],
    })
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("h.xlsx", contenido, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA", "mapeo_nombre_cuenta": "NOMBRE CUENTA"},
    )
    assert r.status_code == 201

    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900690656"}).json()
    codigos = [o["cuenta_codigo"] for o in sug["opciones"]]
    assert "13551508" not in codigos
    assert "510506" in codigos
    assert "510503" in codigos
    assert sug["cuenta_sugerida"] in ("510506", "510503")


def test_filtro_excluye_proveedores_clientes_caja_banco_del_historial(client, empresa_a):
    df = pd.DataFrame({
        "NIT": ["900700800", "900700800"],
        "CUENTA": ["220501", "513595"],
        "NOMBRE CUENTA": ["PROVEEDORES NACIONALES", "HONORARIOS"],
    })
    contenido = _excel_bytes(df)
    client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("h.xlsx", contenido, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA", "mapeo_nombre_cuenta": "NOMBRE CUENTA"},
    )
    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900700800"}).json()
    codigos = [o["cuenta_codigo"] for o in sug["opciones"]]
    assert "220501" not in codigos
    assert "513595" in codigos
    assert sug["cuenta_sugerida"] == "513595"


def test_filtro_no_afecta_cuenta_de_ingreso_clase_4(client, empresa_a):
    df = pd.DataFrame({
        "NIT": ["900800900", "900800900"],
        "CUENTA": ["413595", "130505"],
        "NOMBRE CUENTA": ["INGRESOS POR SERVICIOS", "CLIENTES NACIONALES"],
    })
    contenido = _excel_bytes(df)
    client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("h.xlsx", contenido, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA", "mapeo_nombre_cuenta": "NOMBRE CUENTA"},
    )
    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900800900"}).json()
    codigos = [o["cuenta_codigo"] for o in sug["opciones"]]
    assert "413595" in codigos
    assert "130505" not in codigos
