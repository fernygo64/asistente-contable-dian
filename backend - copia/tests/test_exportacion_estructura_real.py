from tests.test_documentos import _xml, _zip_bytes


def _preparar_factura_lista(client, empresa_id, numero, cufe, nit, cuenta_gasto="513595",
                             subtotal="80000", total="80000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    client.post(f"/empresas/{empresa_id}/documentos/cargar",
                files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    factura = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()[0]

    client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": cuenta_gasto, "nombre": "Honorarios"})
    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={"cuenta_proveedores": "220501"})

    r = client.post(f"/empresas/{empresa_id}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": cuenta_gasto, "contrapartida": "proveedores"})
    assert r.json()["balanceado"] is True, r.json()
    return factura


# Estructura real confirmada en "movimientocontable.xlsx" (Movimiento Contable de Siigo Pyme):
# Tipo Comprobante | Código Comprobante | Cuenta Contable | Débito o Crédito (D/C) | Valor | Año | Mes | Día | Nit | Descripción
SIIGO_MOVIMIENTO_CONTABLE_COLUMNAS = [
    {"label": "TIPO DE COMPROBANTE", "source": "fijo", "valor_fijo": "CC"},
    {"label": "CÓDIGO COMPROBANTE", "source": "fijo", "valor_fijo": "1"},
    {"label": "CUENTA CONTABLE", "source": "cuenta", "valor_fijo": ""},
    {"label": "DÉBITO O CRÉDITO", "source": "debito_credito", "valor_fijo": ""},
    {"label": "VALOR DE LA SECUENCIA", "source": "valor", "valor_fijo": ""},
    {"label": "AÑO DEL DOCUMENTO", "source": "anio", "valor_fijo": ""},
    {"label": "MES DEL DOCUMENTO", "source": "mes", "valor_fijo": ""},
    {"label": "DÍA DEL DOCUMENTO", "source": "dia", "valor_fijo": ""},
    {"label": "NIT", "source": "nit", "valor_fijo": ""},
    {"label": "DESCRIPCIÓN DE LA SECUENCIA", "source": "concepto", "valor_fijo": ""},
]

# Estructura real confirmada en "WORLD_OFFICE_JUNIO_2026.xlsx"
WORLD_OFFICE_COLUMNAS_REALES = [
    {"label": "Encab: Tipo Documento", "source": "fijo", "valor_fijo": "CE"},
    {"label": "Encab: Fecha", "source": "fecha", "valor_fijo": ""},
    {"label": "Encab: Tercero Externo", "source": "nit", "valor_fijo": ""},
    {"label": "Encab: Nota", "source": "concepto", "valor_fijo": ""},
    {"label": "Detalle Con: IdCuentaContable", "source": "cuenta", "valor_fijo": ""},
    {"label": "Detalle Con: Tercero_Externo", "source": "nit", "valor_fijo": ""},
    {"label": "Detalle Con: Débito", "source": "debito", "valor_fijo": ""},
    {"label": "Detalle Con: Crédito", "source": "credito", "valor_fijo": ""},
]


def test_plantilla_siigo_con_estructura_real_es_valida(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo Movimiento Contable real", "sistema_contable": "siigo_pyme",
        "delimitador": "|", "columnas": SIIGO_MOVIMIENTO_CONTABLE_COLUMNAS,
    })
    assert r.status_code == 201, r.text

    factura = _preparar_factura_lista(client, empresa_a["id"], "FSR001", "cufe-siigo-real-1", "900712712")
    val = client.post(f"/empresas/{empresa_a['id']}/exportaciones/validar",
                       json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]}).json()
    assert val["valido"] is True, val


def test_exportar_siigo_genera_indicador_debito_credito_correcto(client, empresa_a):
    """El punto clave de la estructura real: una columna D/C, no Debito y Credito separados."""
    factura = _preparar_factura_lista(client, empresa_a["id"], "FSR002", "cufe-siigo-real-2", "900713713",
                                       cuenta_gasto="519530", subtotal="150000", total="150000")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo real export", "sistema_contable": "siigo_pyme",
        "delimitador": "|", "columnas": SIIGO_MOVIMIENTO_CONTABLE_COLUMNAS,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    assert resp.status_code == 200, resp.text
    lineas = resp.content.decode("cp1252").strip().split("\r\n")
    encabezado = lineas[0].split("|")
    idx_dc = encabezado.index("DÉBITO O CRÉDITO")
    idx_valor = encabezado.index("VALOR DE LA SECUENCIA")
    idx_cuenta = encabezado.index("CUENTA CONTABLE")

    filas = [l.split("|") for l in lineas[1:]]
    valores_dc = {f[idx_dc] for f in filas}
    assert valores_dc == {"D", "C"}  # una línea debito, una credito — nunca las dos columnas viejas

    # el gasto (519530) debe quedar como "D" con el valor completo — con
    # 10 dígitos, regla real de Siigo Pyme (rellena con ceros a la derecha)
    fila_gasto = next(f for f in filas if f[idx_cuenta] == "5195300000")
    assert fila_gasto[idx_dc] == "D"
    assert float(fila_gasto[idx_valor]) == 150000.0

    # las sumas de D y C deben cuadrar
    total_d = sum(float(f[idx_valor]) for f in filas if f[idx_dc] == "D")
    total_c = sum(float(f[idx_valor]) for f in filas if f[idx_dc] == "C")
    assert abs(total_d - total_c) < 0.01


def test_exportar_siigo_fecha_partida_en_anio_mes_dia(client, empresa_a):
    factura = _preparar_factura_lista(client, empresa_a["id"], "FSR003", "cufe-siigo-real-3", "900714714")
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Siigo fecha partida", "sistema_contable": "siigo_pyme",
        "delimitador": "|", "columnas": SIIGO_MOVIMIENTO_CONTABLE_COLUMNAS,
    })
    resp = client.post(f"/empresas/{empresa_a['id']}/exportaciones/generar",
                        json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]})
    lineas = resp.content.decode("cp1252").strip().split("\r\n")
    encabezado = lineas[0].split("|")
    idx_anio = encabezado.index("AÑO DEL DOCUMENTO")
    idx_mes = encabezado.index("MES DEL DOCUMENTO")
    idx_dia = encabezado.index("DÍA DEL DOCUMENTO")
    primera_fila = lineas[1].split("|")
    # la factura de prueba usa fecha 2026-08-01 (ver _xml en test_documentos.py)
    assert primera_fila[idx_anio] == "2026"
    assert primera_fila[idx_mes] == "8"
    assert primera_fila[idx_dia] == "1"


def test_plantilla_world_office_con_estructura_real_es_valida(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "World Office real", "sistema_contable": "world_office",
        "columnas": WORLD_OFFICE_COLUMNAS_REALES,
    })
    assert r.status_code == 201, r.text
    factura = _preparar_factura_lista(client, empresa_a["id"], "FWR001", "cufe-wo-real-1", "900715715")
    val = client.post(f"/empresas/{empresa_a['id']}/exportaciones/validar",
                       json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]}).json()
    assert val["valido"] is True, val


def test_plantilla_sin_valor_ni_debito_credito_falla(client, empresa_a):
    """Ni 'debito'+'credito' ni 'debito_credito'+'valor' presentes -> debe fallar."""
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas", json={
        "nombre": "Sin valores", "sistema_contable": "siigo_pyme",
        "columnas": [{"label": "Cuenta", "source": "cuenta", "valor_fijo": ""}],
    })
    factura = _preparar_factura_lista(client, empresa_a["id"], "FSR004", "cufe-siigo-real-4", "900716716")
    val = client.post(f"/empresas/{empresa_a['id']}/exportaciones/validar",
                       json={"plantilla_id": r.json()["id"], "factura_ids": [factura["id"]]}).json()
    assert val["valido"] is False
