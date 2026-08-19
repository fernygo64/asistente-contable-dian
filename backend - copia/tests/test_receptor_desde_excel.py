from tests.test_documentos import _zip_bytes


def test_factura_emitida_solo_desde_excel_captura_nit_y_nombre_del_receptor(client, empresa_a):
    """
    El bug real reportado: una factura emitida (venta) que solo viene en
    el Excel de la DIAN, sin XML que la respalde, se quedaba sin NIT ni
    nombre del cliente porque el formulario de carga no tenía cómo
    mapear esas columnas.
    """
    import pandas as pd
    import io

    df = pd.DataFrame({
        "CUFE": ["cufe-receptor-excel-1"],
        "Folio": ["FEX001"],
        "NIT Emisor": [empresa_a["nit"]],
        "Nombre Emisor": ["Mi propia empresa"],
        "NIT Receptor": ["900444555"],
        "Nombre Receptor": ["Cliente Real SAS"],
        "Fecha": ["2026-07-01"],
        "Total": ["200000"],
        "Grupo": ["Emitido"],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    excel_contenido = buf.getvalue()

    r = client.post(
        f"/empresas/{empresa_a['id']}/documentos/cargar",
        files=[("documentos", ("vacio.zip", _zip_bytes({}), "application/zip")),
               ("excel", ("dian.xlsx", excel_contenido,
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data={
            "mapeo_cufe": "CUFE", "mapeo_numero_factura": "Folio",
            "mapeo_nit_emisor": "NIT Emisor", "mapeo_nombre_emisor": "Nombre Emisor",
            "mapeo_nit_receptor": "NIT Receptor", "mapeo_nombre_receptor": "Nombre Receptor",
            "mapeo_fecha": "Fecha", "mapeo_valor_total": "Total", "mapeo_grupo": "Grupo",
        },
    )
    assert r.status_code == 201, r.text

    facturas = client.get(f"/empresas/{empresa_a['id']}/documentos").json()
    factura = next(f for f in facturas if f["cufe"] == "cufe-receptor-excel-1")
    assert factura["nit_emisor"] == empresa_a["nit"]  # dato crudo conservado
    assert factura["tercero_nit"] == "900444555"  # pero el tercero relevante es el receptor
    assert factura["tercero_nombre"] == "Cliente Real SAS"
