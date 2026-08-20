from app.services.plantilla_inferencia_service import detectar_estructura_archivo_plano


def test_detecta_delimitador_pipe():
    contenido = b"Fecha|Cuenta|Nit|Debito|Credito\n2026-01-01|513595|900123456|1000|0"
    r = detectar_estructura_archivo_plano(contenido)
    assert r["delimitador"] == "|"
    assert len(r["columnas"]) == 5


def test_detecta_delimitador_punto_y_coma():
    contenido = b"Fecha;Cuenta;Nit;Debito;Credito\n2026-01-01;513595;900123456;1000;0"
    r = detectar_estructura_archivo_plano(contenido)
    assert r["delimitador"] == ";"


def test_detecta_desde_excel_con_filas_de_titulo_antes_del_encabezado():
    """
    Reproduce la estructura real del archivo de ejemplo de Siigo Pyme
    (movimientocontable.xlsx): 3 filas de título/instrucciones antes del
    encabezado real. Debe encontrar el encabezado real, no la primera fila.
    """
    import io
    import pandas as pd

    filas = [
        ["MODELO PARA LA IMPORTACION DE MOVIMIENTO CONTABLE"] + [None] * 5,
        ["De: ENE 1/2026 A: JUL 31/2026"] + [None] * 5,
        [None] * 6,
        ["TIPO DE COMPROBANTE (OBLIGATORIO)", "CUENTA CONTABLE (OBLIGATORIO)",
         "DÉBITO O CRÉDITO (OBLIGATORIO)", "VALOR DE LA SECUENCIA (OBLIGATORIO)", "NIT", "DESCRIPCIÓN"],
        ["P", "5120950000", "D", "1669130", "900608161", "Honorarios"],
    ]
    df = pd.DataFrame(filas)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=False)
    contenido = buf.getvalue()

    r = detectar_estructura_archivo_plano(contenido)
    labels = [c["label"] for c in r["columnas"]]
    assert "CUENTA CONTABLE (OBLIGATORIO)" in labels
    assert "MODELO PARA LA IMPORTACION DE MOVIMIENTO CONTABLE" not in labels  # no confundir el título con encabezado

    origenes = {c["label"]: c["source"] for c in r["columnas"]}
    assert origenes["CUENTA CONTABLE (OBLIGATORIO)"] == "cuenta"
    assert origenes["DÉBITO O CRÉDITO (OBLIGATORIO)"] == "debito_credito"
    assert origenes["VALOR DE LA SECUENCIA (OBLIGATORIO)"] == "valor"
    assert origenes["NIT"] == "nit"


def test_detecta_desde_excel_estructura_world_office():
    """Reproduce la estructura real de World Office: Encab:/Detalle Con: en fila 1 (sin preámbulo)."""
    import io
    import pandas as pd

    df = pd.DataFrame([{
        "Encab: Tipo Documento": "CE", "Encab: Fecha": "30-06-2026", "Encab: Tercero Externo": "808000516",
        "Detalle Con: IdCuentaContable": "11050501", "Detalle Con: Débito": 129920, "Detalle Con: Crédito": 0,
    }])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    contenido = buf.getvalue()

    r = detectar_estructura_archivo_plano(contenido)
    origenes = {c["label"]: c["source"] for c in r["columnas"]}
    assert origenes["Detalle Con: IdCuentaContable"] == "cuenta"
    assert origenes["Detalle Con: Débito"] == "debito"
    assert origenes["Detalle Con: Crédito"] == "credito"
    assert origenes["Encab: Fecha"] == "fecha"


def test_sugiere_origen_por_palabra_clave():
    contenido = b"Fecha|Cuenta Contable|NIT Tercero|Nombre Tercero|Debito|Credito|Concepto"
    r = detectar_estructura_archivo_plano(contenido)
    origenes = {c["label"]: c["source"] for c in r["columnas"]}
    assert origenes["Fecha"] == "fecha"
    assert origenes["Cuenta Contable"] == "cuenta"
    assert origenes["NIT Tercero"] == "nit"
    assert origenes["Nombre Tercero"] == "tercero"
    assert origenes["Debito"] == "debito"
    assert origenes["Credito"] == "credito"
    assert origenes["Concepto"] == "concepto"


def test_columna_no_reconocida_queda_como_fijo():
    contenido = b"Sucursal Origen|Fecha|Cuenta"
    r = detectar_estructura_archivo_plano(contenido)
    origenes = {c["label"]: c["source"] for c in r["columnas"]}
    assert origenes["Sucursal Origen"] == "fijo"  # no se inventa a qué campo corresponde


def test_columna_tipo_de_comprobante_se_reconoce():
    """
    Bug real reportado: el detector automático de plantillas nunca
    reconocía "TIPO DE COMPROBANTE (OBLIGATORIO)" (columna real de
    Siigo Pyme) — la dejaba como "fijo" (vacía), así que el CSV
    exportado nunca traía ese dato aunque estuviera bien configurado.
    """
    contenido = b"TIPO DE COMPROBANTE (OBLIGATORIO)|CODIGO COMPROBANTE  (OBLIGATORIO)|CUENTA CONTABLE   (OBLIGATORIO)|Fecha"
    r = detectar_estructura_archivo_plano(contenido)
    origenes = {c["label"]: c["source"] for c in r["columnas"]}
    assert origenes["TIPO DE COMPROBANTE (OBLIGATORIO)"] == "tipo_comprobante"
    assert origenes["CODIGO COMPROBANTE  (OBLIGATORIO)"] == "fijo"  # campo distinto, no se confunde
    assert origenes["CUENTA CONTABLE   (OBLIGATORIO)"] == "cuenta"


def test_columna_numero_de_documento_no_se_confunde_con_numero_de_factura():
    """
    Segundo bug real encontrado con un archivo de ejemplo real de
    Siigo: "NÚMERO DE DOCUMENTO" es un consecutivo interno (no el
    número real de la factura), mientras que "NÚMERO DE FACTURA
    ELECTRÓNICA..." sí es el número real — son cosas distintas y antes
    ambas se detectaban igual (numero_factura), lo cual estaba mal.
    """
    contenido = b"NUMERO DE DOCUMENTO|NUMERO DE FACTURA ELECTRONICA A DEBITAR/ACREDITAR|Cuenta"
    r = detectar_estructura_archivo_plano(contenido)
    origenes = {c["label"]: c["source"] for c in r["columnas"]}
    assert origenes["NUMERO DE DOCUMENTO"] == "numero_documento"
    assert origenes["NUMERO DE FACTURA ELECTRONICA A DEBITAR/ACREDITAR"] == "numero_factura"


def test_endpoint_inferir_plantilla(client, empresa_a):
    contenido = b"Fecha|Cuenta|Nit|Tercero|Debito|Credito\n2026-01-01|513595|900123456|Prov X|500000|0"
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas/inferir-desde-ejemplo",
                     files={"archivo": ("ejemplo.txt", contenido, "text/plain")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delimitador"] == "|"
    assert len(body["columnas"]) == 6
    assert body["columnas"][0] == {"label": "Fecha", "source": "fecha"}


def test_endpoint_inferir_plantilla_archivo_vacio(client, empresa_a):
    r = client.post(f"/empresas/{empresa_a['id']}/plantillas/inferir-desde-ejemplo",
                     files={"archivo": ("vacio.txt", b"", "text/plain")})
    assert r.status_code == 422
