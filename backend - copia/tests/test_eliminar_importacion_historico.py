import io
import pandas as pd


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def _importar(client, empresa_id, nit, cuenta):
    df = pd.DataFrame({"NIT": [nit], "CUENTA": [cuenta]})
    contenido = _excel_bytes(df)
    r = client.post(
        f"/empresas/{empresa_id}/historial/importar",
        files={"archivo": ("h.xlsx", contenido, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapeo_nit": "NIT", "mapeo_cuenta": "CUENTA"},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_eliminar_importacion_borra_sus_decisiones_de_historial(client, empresa_a):
    importacion_id = _importar(client, empresa_a["id"], "900700700", "513595")

    sug_antes = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900700700"}).json()
    assert sug_antes["cuenta_sugerida"] == "513595"

    r = client.delete(f"/empresas/{empresa_a['id']}/historial/importaciones/{importacion_id}")
    assert r.status_code == 200
    assert r.json()["decisiones_borradas"] == 1

    sug_despues = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900700700"}).json()
    assert sug_despues["total_documentos_historicos"] == 0

    importaciones = client.get(f"/empresas/{empresa_a['id']}/historial/importaciones").json()
    assert all(i["id"] != importacion_id for i in importaciones)


def test_eliminar_importacion_no_afecta_otra_importacion_distinta(client, empresa_a):
    importacion_1 = _importar(client, empresa_a["id"], "900700701", "513595")
    _importar(client, empresa_a["id"], "900700702", "513595")

    client.delete(f"/empresas/{empresa_a['id']}/historial/importaciones/{importacion_1}")

    sug_otro = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia", params={"nit": "900700702"}).json()
    assert sug_otro["cuenta_sugerida"] == "513595"


def test_eliminar_importacion_no_borra_la_cuenta_ni_el_proveedor(client, empresa_a):
    importacion_id = _importar(client, empresa_a["id"], "900700703", "513595")
    client.delete(f"/empresas/{empresa_a['id']}/historial/importaciones/{importacion_id}")

    cuentas = client.get(f"/empresas/{empresa_a['id']}/cuentas").json()
    assert any(c["codigo"] == "513595" for c in cuentas)


def test_eliminar_importacion_inexistente_da_404(client, empresa_a):
    r = client.delete(f"/empresas/{empresa_a['id']}/historial/importaciones/no-existe")
    assert r.status_code == 404
