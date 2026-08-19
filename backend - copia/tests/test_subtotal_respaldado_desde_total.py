import io
import zipfile
import pandas as pd


def _zip_bytes(archivos: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, contenido in archivos.items():
            zf.writestr(nombre, contenido)
    return buf.getvalue()


def test_nomina_con_total_del_excel_sin_subtotal_no_genera_partida_en_cero(client, empresa_a):
    zip_contenido = _zip_bytes({"NOM1.xml": '<NominaIndividual xmlns="dian:gov:co:facturaelectronica:NominaIndividual"><Periodo>2026-07</Periodo></NominaIndividual>'})

    df = pd.DataFrame({
        "CUFE": ["NOM1"], "Folio": ["NOM1"], "NIT Emisor": [empresa_a["nit"]], "Nombre Emisor": ["Empresa"],
        "Total": ["16490000"], "Tipo de documento": ["Nomina Individual"], "Grupo": ["Emitido"],
    })
    excel_buf = io.BytesIO()
    df.to_excel(excel_buf, index=False)

    client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("d.zip", zip_contenido, "application/zip")),
               ("excel", ("dian.xlsx", excel_buf.getvalue(),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data={"mapeo_cufe": "CUFE", "mapeo_numero_factura": "Folio", "mapeo_nit_emisor": "NIT Emisor",
              "mapeo_nombre_emisor": "Nombre Emisor", "mapeo_valor_total": "Total",
              "mapeo_tipo_documento": "Tipo de documento", "mapeo_grupo": "Grupo"},
    )

    f = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nomina"}).json()[0]
    assert f["total"] == 16490000.0
    assert f["subtotal"] == 16490000.0

    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "510506", "nombre": "Sueldos"})
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{f['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "510506", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is True, body
    linea_gasto = next(l for l in body["lineas"] if l["cuenta_codigo"] == "510506")
    assert linea_gasto["valor"] == 16490000.0
