import io
import pandas as pd

from app.services.excel_utils import leer_columnas_excel, leer_dataframe_excel


def _excel_con_preambulo() -> bytes:
    """Reproduce exactamente la estructura real reportada: nombre de la
    empresa en la fila 0, título en la fila 1, rango de fechas en la
    fila 2, fila vacía, encabezado real en la fila 4."""
    filas = [
        ["FERNELY GOMEZ MOSQUERA"] + [None] * 5,
        ["MODELO PARA LA IMPORTACION DE MOVIMIENTO CONTABLE"] + [None] * 5,
        ["De :  ENE  1/2026   A :  JUL 31/2026"] + [None] * 5,
        [None] * 6,
        ["TIPO DE COMPROBANTE", "CUENTA CONTABLE", "DÉBITO O CRÉDITO", "VALOR", "NIT", "DESCRIPCIÓN"],
        ["P", "5120950000", "D", "1669130", "900608161", "Honorarios"],
        ["P", "2205010000", "C", "1669130", "900608161", "Honorarios"],
    ]
    df = pd.DataFrame(filas)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=False)
    return buf.getvalue()


def test_no_confunde_el_nombre_de_la_empresa_con_el_encabezado():
    """
    Bug real reportado por el usuario: el módulo de Historial mostraba
    'FERNELY GOMEZ MOSQUERA' (el nombre de su empresa, que Siigo pone
    como primera línea del archivo) como si fuera el nombre de TODAS
    las columnas.
    """
    contenido = _excel_con_preambulo()
    columnas = leer_columnas_excel(contenido, "movimientocontable.xlsx")
    assert "FERNELY GOMEZ MOSQUERA" not in columnas
    assert "CUENTA CONTABLE" in columnas
    assert "DÉBITO O CRÉDITO" in columnas
    assert len(columnas) == 6


def test_leer_dataframe_con_preambulo_usa_los_datos_reales_no_el_titulo():
    contenido = _excel_con_preambulo()
    df = leer_dataframe_excel(contenido, "movimientocontable.xlsx")
    assert len(df) == 2  # las 2 filas de datos reales, no las de título
    assert list(df["CUENTA CONTABLE"]) == ["5120950000", "2205010000"]


def test_endpoint_excel_columnas_no_confunde_nombre_de_empresa(client, empresa_a):
    contenido = _excel_con_preambulo()
    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/excel-columnas",
        files={"archivo": ("movimientocontable.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    columnas = r.json()["columnas"]
    assert "FERNELY GOMEZ MOSQUERA" not in columnas
    assert "CUENTA CONTABLE" in columnas


def test_importar_historico_con_preambulo_lee_los_datos_reales(client, empresa_a):
    """El fix debe funcionar de punta a punta: detectar Y usar la columna correcta al importar."""
    contenido = _excel_con_preambulo()
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("movimientocontable.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA CONTABLE", "cuentas_excluir": "2205"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_registros"] == 2
    assert body["registros_validos"] == 1  # solo la de gasto (5120950000), la de "2205..." excluida

    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900608161"}).json()
    assert sug["cuenta_sugerida"] == "5120950000"
