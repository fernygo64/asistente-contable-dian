import io
import pandas as pd


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_importar_excluyendo_cuentas_de_control(client, empresa_a):
    """
    Simula un archivo de Movimiento Contable real: por cada comprobante,
    una línea de gasto real y una de contrapartida (proveedores) — sin
    excluir, el sistema aprendería "proveedores" como si fuera una
    cuenta de gasto típica de ese NIT, lo cual es ruido.
    """
    df = pd.DataFrame({
        "NIT": ["900100100", "900100100", "900200200", "900200200"],
        "CUENTA": ["513595", "220501", "519530", "220501"],  # gasto, proveedores, gasto, proveedores
    })
    contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("historico.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA", "cuentas_excluir": "220501"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_registros"] == 4
    assert body["registros_validos"] == 2  # solo las 2 líneas de gasto real, no las de proveedores

    sug1 = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900100100"}).json()
    assert sug1["cuenta_sugerida"] == "513595"
    codigos1 = [o["cuenta_codigo"] for o in sug1["opciones"]]
    assert "220501" not in codigos1  # proveedores nunca debe aparecer como cuenta aprendida

    sug2 = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900200200"}).json()
    assert sug2["cuenta_sugerida"] == "519530"


def test_importar_sin_exclusion_incluye_todas_las_cuentas(client, empresa_a):
    """Sin cuentas_excluir, el comportamiento sigue siendo el de siempre (compatibilidad)."""
    df = pd.DataFrame({"NIT": ["900300300"], "CUENTA": ["220501"]})
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("h2.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA"},
    )
    assert r.status_code == 201
    assert r.json()["registros_validos"] == 1


def test_exclusion_por_prefijo(client, empresa_a):
    """Excluir '24' debe descartar cualquier cuenta que empiece por 24 (IVA, retenciones), sin listar cada código."""
    df = pd.DataFrame({
        "NIT": ["900400400", "900400400", "900400400"],
        "CUENTA": ["513595", "240802", "236540"],  # gasto, IVA, retefuente
    })
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("h3.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA", "cuentas_excluir": "24,2365"},
    )
    assert r.status_code == 201
    assert r.json()["registros_validos"] == 1  # solo la de gasto (513595)


def test_listar_importaciones(client, empresa_a):
    df = pd.DataFrame({"NIT": ["900500500"], "CUENTA": ["513595"]})
    contenido = _excel_bytes(df)
    client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("h4.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA"},
    )
    r = client.get(f"/empresas/{empresa_a['id']}/historial/importaciones")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["archivo_nombre"] == "h4.xlsx"
    assert body[0]["registros_validos"] == 1
