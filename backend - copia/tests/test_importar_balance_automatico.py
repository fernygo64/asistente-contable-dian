import io
import pandas as pd


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_importar_balance_solo_con_el_archivo_sin_mapeo(client, empresa_a):
    """El caso pedido: el usuario NO configura nada, solo sube el Excel."""
    df = pd.DataFrame({
        "NIT": ["900100100", "900200200"],
        "Nombre Tercero": ["Proveedor Uno", "Proveedor Dos"],
        "Cuenta": ["513595", "240802019"],
        "Nombre Cuenta": ["Honorarios", "IVA Descontable Compras 19%"],
        "Saldo": ["500000", "95000"],
    })
    contenido = _excel_bytes(df)

    r = client.post(f"/empresas/{empresa_a['id']}/historial/importar-balance",
                     files={"archivo": ("balance.xlsx", contenido,
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["registros_validos"] == 2

    cuentas = client.get(f"/empresas/{empresa_a['id']}/cuentas").json()
    nombres = {c["codigo"]: c["nombre"] for c in cuentas}
    assert nombres["240802019"] == "IVA Descontable Compras 19%"

    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900100100"}).json()
    assert sug["cuenta_sugerida"] == "513595"


def test_balance_sin_columna_cuenta_reconocible_falla_con_mensaje_claro(client, empresa_a):
    df = pd.DataFrame({"NIT": ["900100100"], "Algo": ["x"], "Otro dato": ["y"]})
    contenido = _excel_bytes(df)

    r = client.post(f"/empresas/{empresa_a['id']}/historial/importar-balance",
                     files={"archivo": ("balance_raro.xlsx", contenido,
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 422
    assert "cuenta" in r.json()["detail"].lower()
    assert "Auxiliar" in r.json()["detail"]  # sugiere la alternativa manual


def test_balance_con_variantes_de_nombres_de_columna(client, empresa_a):
    """Confirma que reconoce variantes razonables, no solo el nombre exacto 'NIT'/'Cuenta'."""
    df = pd.DataFrame({
        "Identificación": ["900300300"],
        "Código Cuenta": ["511005"],
        "Descripción Cuenta": ["Servicios prestados"],
        "Razón Social": ["Cliente X"],
        "Valor": ["100000"],
    })
    contenido = _excel_bytes(df)

    r = client.post(f"/empresas/{empresa_a['id']}/historial/importar-balance",
                     files={"archivo": ("balance2.xlsx", contenido,
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    assert r.json()["registros_validos"] == 1
