import io
import pandas as pd


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_importar_excel_con_columnas_en_orden_no_estandar(client, empresa_a):
    # Columnas deliberadamente en un orden distinto al que "se esperaría",
    # y con nombres que no coinciden con los campos internos —
    # exactamente el escenario de la sección 8.
    df = pd.DataFrame({
        "Detalle": ["Compra papelería", "Servicio transporte", "Compra papelería"],
        "Cta Contable": ["519530", "522035", "519530"],
        "Identificacion": ["900123456", "900123456", "900987654"],
        "Nombre Tercero": ["Prov Uno", "Prov Uno", "Prov Dos"],
        "Fecha Doc": ["2025-01-10", "2025-02-15", "2025-03-01"],
    })
    contenido = _excel_bytes(df)

    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("historico.xlsx", contenido,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "mapeo_nit": "Identificacion",
            "mapeo_cuenta": "Cta Contable",
            "mapeo_nombre": "Nombre Tercero",
            "mapeo_fecha": "Fecha Doc",
            "mapeo_descripcion": "Detalle",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_registros"] == 3
    assert body["registros_validos"] == 3
    assert body["registros_rechazados"] == 0

    # ahora debe existir historial real y una sugerencia basada en él
    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                      params={"nit": "900123456"}).json()
    assert sug["cuenta_sugerida"] == "519530"
    assert sug["total_documentos_historicos"] == 2


def test_importar_rechaza_filas_sin_nit_o_cuenta_pero_continua(client, empresa_a):
    df = pd.DataFrame({
        "NIT": ["900111222", "", "900333444"],
        "CUENTA": ["513595", "519595", ""],
    })
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("historico2.xlsx", contenido,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["total_registros"] == 3
    assert body["registros_validos"] == 1
    assert body["registros_rechazados"] == 2
    assert len(body["detalle_rechazos"]) == 2


def test_importar_columna_inexistente_da_error_claro(client, empresa_a):
    df = pd.DataFrame({"NIT": ["900111222"], "CUENTA": ["513595"]})
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("historico3.xlsx", contenido,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT_QUE_NO_EXISTE", "mapeo_cuenta": "CUENTA"},
    )
    assert r.status_code == 422
    assert "NIT_QUE_NO_EXISTE" in r.json()["detail"]


def test_importacion_queda_registrada_en_auditoria(client, empresa_a):
    df = pd.DataFrame({"NIT": ["900111222"], "CUENTA": ["513595"]})
    contenido = _excel_bytes(df)
    client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("historico4.xlsx", contenido,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA"},
    )
    auditoria = client.get(f"/empresas/{empresa_a['id']}/auditoria").json()
    acciones = [ev["accion"] for ev in auditoria]
    assert "importacion_historico" in acciones
