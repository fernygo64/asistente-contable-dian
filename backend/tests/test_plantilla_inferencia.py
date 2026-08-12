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
    contenido = b"Tipo Comprobante|Fecha|Cuenta"
    r = detectar_estructura_archivo_plano(contenido)
    origenes = {c["label"]: c["source"] for c in r["columnas"]}
    assert origenes["Tipo Comprobante"] == "fijo"  # no se inventa a qué campo corresponde


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
