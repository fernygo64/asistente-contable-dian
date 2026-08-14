import io
import pandas as pd

from app.services.balance_jerarquico_service import (
    detectar_columnas_balance_terceros, parsear_balance_terceros_jerarquico,
)


def _construir_balance_jerarquico() -> pd.DataFrame:
    filas = [
        {"GRUPO": "13", "CUENTA": None, "SUBCUENT": None, "AUXILIAR": None, "SUBAUXIL": None,
         "NIT": None, "DESCRIPCION": "DEUDORES", "NUEVO SALDO": 1000000},
        {"GRUPO": "13", "CUENTA": "05", "SUBCUENT": None, "AUXILIAR": None, "SUBAUXIL": None,
         "NIT": None, "DESCRIPCION": "CLIENTES", "NUEVO SALDO": 900000},
        {"GRUPO": "13", "CUENTA": "05", "SUBCUENT": "06", "AUXILIAR": None, "SUBAUXIL": None,
         "NIT": None, "DESCRIPCION": "CLIENTES", "NUEVO SALDO": 900000},
        {"GRUPO": None, "CUENTA": None, "SUBCUENT": None, "AUXILIAR": None, "SUBAUXIL": None,
         "NIT": "900100100", "DESCRIPCION": "PROVEEDOR UNO SAS", "NUEVO SALDO": 500000},
        {"GRUPO": None, "CUENTA": None, "SUBCUENT": None, "AUXILIAR": None, "SUBAUXIL": None,
         "NIT": "900200200", "DESCRIPCION": "CLIENTE DOS SAS", "NUEVO SALDO": 400000},
        {"GRUPO": "24", "CUENTA": "08", "SUBCUENT": "05", "AUXILIAR": "02", "SUBAUXIL": "08",
         "NIT": None, "DESCRIPCION": "IVA DESCONTABLE COMPRAS 19%", "NUEVO SALDO": 50000},
        {"GRUPO": None, "CUENTA": None, "SUBCUENT": None, "AUXILIAR": None, "SUBAUXIL": None,
         "NIT": "900300300", "DESCRIPCION": "PROVEEDOR TRES SAS", "NUEVO SALDO": 50000},
    ]
    return pd.DataFrame(filas)


def test_detecta_columnas_del_formato_jerarquico():
    columnas = ["GRUPO", "CUENTA", "SUBCUENT", "AUXILIAR", "SUBAUXIL", "NIT", "DESCRIPCION", "NUEVO SALDO"]
    r = detectar_columnas_balance_terceros(columnas)
    assert r is not None
    assert r["grupo"] == "GRUPO"
    assert r["nit"] == "NIT"
    assert r["saldo"] == "NUEVO SALDO"


def test_no_detecta_formato_jerarquico_en_un_archivo_plano_comun():
    columnas = ["NIT", "Nombre Tercero", "Cuenta", "Nombre Cuenta", "Saldo"]
    r = detectar_columnas_balance_terceros(columnas)
    assert r is None


def test_reconstruye_codigo_jerarquico_y_hereda_en_filas_de_detalle():
    df = _construir_balance_jerarquico()
    columnas = detectar_columnas_balance_terceros(list(df.columns))
    registros = parsear_balance_terceros_jerarquico(df, columnas)

    assert len(registros) == 3

    r1, r2, r3 = registros
    assert r1["nit"] == "900100100"
    assert r1["cuenta_codigo"] == "130506"
    assert r1["nombre_cuenta"] == "CLIENTES"
    assert r1["nombre_tercero"] == "PROVEEDOR UNO SAS"
    assert r1["valor"] == 500000

    assert r2["cuenta_codigo"] == "130506"

    assert r3["nit"] == "900300300"
    assert r3["cuenta_codigo"] == "2408050208"
    assert r3["nombre_cuenta"] == "IVA DESCONTABLE COMPRAS 19%"


def test_endpoint_importar_balance_reconoce_formato_siigo_nube_automaticamente(client, empresa_a):
    df = _construir_balance_jerarquico()
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    contenido = buf.getvalue()

    r = client.post(f"/empresas/{empresa_a['id']}/historial/importar-balance",
                     files={"archivo": ("balance_siigo_nube.xlsx", contenido,
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["registros_validos"] == 3

    cuentas = client.get(f"/empresas/{empresa_a['id']}/cuentas").json()
    nombres = {c["codigo"]: c["nombre"] for c in cuentas}
    assert nombres["130506"] == "CLIENTES"
    assert nombres["2408050208"] == "IVA DESCONTABLE COMPRAS 19%"

    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900100100"}).json()
    assert sug["cuenta_sugerida"] == "130506"
