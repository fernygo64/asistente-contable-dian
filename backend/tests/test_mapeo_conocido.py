import io
import pandas as pd

from app.services.mapeo_conocido_service import sugerir_mapeo


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def test_sugerir_mapeo_siigo_reconoce_columnas_reales():
    columnas = [
        "TIPO DE COMPROBANTE (OBLIGATORIO)", "CUENTA CONTABLE   (OBLIGATORIO)", "NIT",
        "DESCRIPCIÓN DE LA SECUENCIA", "NÚMERO DE DOCUMENTO", "VALOR DE LA SECUENCIA   (OBLIGATORIO)",
        "VALOR DEL CARGO 1 DE LA SECUENCIA", "VALOR DE IVA DE LA SECUENCIA",
        "AÑO DEL DOCUMENTO", "MES DEL DOCUMENTO", "DÍA DEL DOCUMENTO",
    ]
    r = sugerir_mapeo("siigo_pyme", columnas)
    assert r["mapeo"]["nit"] == "NIT"
    assert r["mapeo"]["cuenta"] == "CUENTA CONTABLE   (OBLIGATORIO)"
    assert r["mapeo"]["valor"] == "VALOR DE LA SECUENCIA   (OBLIGATORIO)"
    assert r["mapeo"]["descripcion"] == "DESCRIPCIÓN DE LA SECUENCIA"
    assert r["mapeo"]["anio"] == "AÑO DEL DOCUMENTO"


def test_sugerir_mapeo_world_office_reconoce_debito_credito_separados():
    columnas = ["Detalle Con: IdCuentaContable", "Detalle Con: Tercero_Externo",
                "Detalle Con: Débito", "Detalle Con: Crédito", "Detalle Con: Nota", "Encab: Fecha"]
    r = sugerir_mapeo("world_office", columnas)
    assert r["mapeo"]["nit"] == "Detalle Con: Tercero_Externo"
    assert r["mapeo"]["valor_debito"] == "Detalle Con: Débito"
    assert r["mapeo"]["valor_credito"] == "Detalle Con: Crédito"


def test_sugerir_mapeo_sistema_desconocido_no_sugiere_nada():
    r = sugerir_mapeo("otro_sistema", ["NIT", "CUENTA"])
    assert r["mapeo"] == {}


def test_endpoint_sugerir_mapeo_incluye_cuentas_excluir_desde_cuentas_base(client, empresa_a):
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={
        "cuenta_proveedores": "220501", "cuenta_iva_descontable": "240802",
    })
    df = pd.DataFrame({"NIT": ["900100100"], "CUENTA CONTABLE": ["513595"]})
    contenido = _excel_bytes(df)
    r = client.post(f"/empresas/{empresa_a['id']}/historial/sugerir-mapeo",
                     files={"archivo": ("h.xlsx", contenido,
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sistema_contable"] == "siigo_pyme"
    assert "220501" in body["cuentas_excluir_sugeridas"]
    assert "240802" in body["cuentas_excluir_sugeridas"]


def test_importar_con_debito_credito_separados_toma_el_que_no_esta_vacio(client, empresa_a):
    df = pd.DataFrame({
        "NIT": ["900700700", "900700700"],
        "CUENTA": ["513595", "220501"],
        "DEBITO": ["50000", ""],
        "CREDITO": ["", "50000"],
    })
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("wo.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA",
              "mapeo_valor_debito": "DEBITO", "mapeo_valor_credito": "CREDITO",
              "cuentas_excluir": "220501"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["registros_validos"] == 1


def test_importar_con_anio_mes_dia_reconstruye_la_fecha(client, empresa_a):
    df = pd.DataFrame({
        "NIT": ["900800800"], "CUENTA": ["513595"],
        "ANIO": ["2026"], "MES": ["7"], "DIA": ["15"],
    })
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_a['id']}/historial/importar",
        files={"archivo": ("f.xlsx", contenido,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA",
              "mapeo_anio": "ANIO", "mapeo_mes": "MES", "mapeo_dia": "DIA"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["registros_validos"] == 1
