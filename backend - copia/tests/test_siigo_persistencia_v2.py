import json

from app.models.models import PlantillaExportacion, SistemaContable
from app.services.siigo_pyme_extendido import DEFAULTS_SIIGO_PYME_EXTENDIDO
from tests.test_exportacion import _preparar_factura_lista

BASE = [
    {"label": "Tipo", "source": "tipo_comprobante", "valor_fijo": ""},
    {"label": "Codigo", "source": "codigo_comprobante_siigo", "valor_fijo": ""},
    {"label": "Numero", "source": "numero_documento", "valor_fijo": ""},
    {"label": "Cuenta", "source": "cuenta", "valor_fijo": ""},
    {"label": "Nit", "source": "nit", "valor_fijo": ""},
    {"label": "Debito", "source": "debito", "valor_fijo": ""},
    {"label": "Credito", "source": "credito", "valor_fijo": ""},
]


def _config_siigo(client, empresa_id, tipo="G", codigo="1", ultimo=80):
    payload = {"configuraciones": [{
        "tipo_documento": "factura_recibida", "tipo_comprobante": tipo,
        "codigo_comprobante": codigo, "codigo_vendedor_default": "1",
        "codigo_zona_default": "0", "subcentro_costo_default": "0",
        "sucursal_default": "0", "ultimo_consecutivo_usado": ultimo,
    }]}
    r = client.put(f"/empresas/{empresa_id}/siigo/comprobantes", json=payload)
    assert r.status_code == 200, r.text


def _plantilla(client, empresa_id, nombre="Persistencia"):
    r = client.post(f"/empresas/{empresa_id}/plantillas", json={
        "nombre": nombre, "sistema_contable": "siigo_pyme", "columnas": BASE,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _numero(resp):
    lineas = resp.content.decode("cp1252").strip().split("\r\n")
    return lineas[1].split("|")[2]


def test_consecutivo_persiste_entre_exportaciones_y_reexportacion(client, empresa_a):
    empresa_id = empresa_a["id"]
    _config_siigo(client, empresa_id, ultimo=80)
    f1 = _preparar_factura_lista(client, empresa_id, "PER001", "cufe-per-1", "900111201")
    f2 = _preparar_factura_lista(client, empresa_id, "PER002", "cufe-per-2", "900111202")
    p = _plantilla(client, empresa_id)

    r1 = client.post(f"/empresas/{empresa_id}/exportaciones/generar", json={"plantilla_id": p, "factura_ids": [f1["id"]]})
    r2 = client.post(f"/empresas/{empresa_id}/exportaciones/generar", json={"plantilla_id": p, "factura_ids": [f2["id"]]})
    r1b = client.post(f"/empresas/{empresa_id}/exportaciones/generar", json={"plantilla_id": p, "factura_ids": [f1["id"]]})
    assert _numero(r1) == "81"
    assert _numero(r2) == "82"
    assert _numero(r1b) == "81"


def test_exportacion_pendiente_es_independiente_por_sistema(client, empresa_a):
    empresa_id = empresa_a["id"]
    _config_siigo(client, empresa_id, ultimo=0)
    f = _preparar_factura_lista(client, empresa_id, "DST001", "cufe-dst-1", "900111301")
    p_siigo = _plantilla(client, empresa_id, "Destino SIIGO")
    r = client.post(f"/empresas/{empresa_id}/plantillas", json={
        "nombre": "Destino WO", "sistema_contable": "world_office",
        "columnas": [
            {"label":"Cuenta","source":"cuenta","valor_fijo":""},
            {"label":"Nit","source":"nit","valor_fijo":""},
            {"label":"Debito","source":"debito","valor_fijo":""},
            {"label":"Credito","source":"credito","valor_fijo":""},
        ]})
    p_wo = r.json()["id"]
    client.post(f"/empresas/{empresa_id}/exportaciones/generar", json={"plantilla_id":p_siigo,"factura_ids":[f["id"]]})
    pend_siigo = client.get(f"/empresas/{empresa_id}/exportaciones/pendientes/{p_siigo}").json()
    pend_wo = client.get(f"/empresas/{empresa_id}/exportaciones/pendientes/{p_wo}").json()
    assert f["id"] not in {x["id"] for x in pend_siigo}
    assert f["id"] in {x["id"] for x in pend_wo}


def test_nit_depende_de_parametrizacion_de_cuenta(client, empresa_a):
    empresa_id = empresa_a["id"]
    _config_siigo(client, empresa_id, ultimo=0)
    f = _preparar_factura_lista(client, empresa_id, "NIT001", "cufe-nit-v2", "900111401")
    cuentas = client.get(f"/empresas/{empresa_id}/siigo/cuentas").json()
    por_codigo = {x["cuenta_codigo"]: x for x in cuentas}
    assert "513595" in por_codigo and "220501" in por_codigo
    client.put(f"/empresas/{empresa_id}/siigo/cuentas/{por_codigo['513595']['cuenta_id']}", json={"maneja_tercero": True})
    client.put(f"/empresas/{empresa_id}/siigo/cuentas/{por_codigo['220501']['cuenta_id']}", json={"maneja_tercero": False, "nit_tecnico_exportacion":"0"})
    p = _plantilla(client, empresa_id, "NIT por cuenta")
    resp = client.post(f"/empresas/{empresa_id}/exportaciones/generar", json={"plantilla_id":p,"factura_ids":[f["id"]]})
    filas = [x.split("|") for x in resp.content.decode("cp1252").strip().split("\r\n")[1:]]
    cuenta_nit = {(r[3], r[4]) for r in filas}
    assert ("5135950000", "900111401") in cuenta_nit
    assert ("2205010000", "0") in cuenta_nit


def test_reprocesar_plantilla_preserva_encabezados_y_crea_version_nueva(client, db_session, empresa_a):
    empresa_id = empresa_a["id"]
    encabezados = [
        "TIPO DE COMPROBANTE (OBLIGATORIO)", "CÓDIGO COMPROBANTE  (OBLIGATORIO)",
        "NÚMERO DE DOCUMENTO", "CUENTA CONTABLE   (OBLIGATORIO)",
        "DÉBITO O CRÉDITO (OBLIGATORIO)", "VALOR DE LA SECUENCIA   (OBLIGATORIO)",
        "AÑO DEL DOCUMENTO", "MES DEL DOCUMENTO", "DÍA DEL DOCUMENTO", "CÓDIGO DEL VENDEDOR",
        "CÓDIGO DE LA CIUDAD", "CÓDIGO DE LA ZONA", "SECUENCIA", "CENTRO DE COSTO",
        "SUBCENTRO DE COSTO", "NIT", "SUCURSAL", "DESCRIPCIÓN DE LA SECUENCIA",
    ] + list(DEFAULTS_SIIGO_PYME_EXTENDIDO.keys())
    assert len(encabezados) == 123
    vieja = PlantillaExportacion(
        empresa_id=empresa_id, nombre="Vieja SIIGO", sistema_contable=SistemaContable.siigo_pyme,
        delimitador=";", extension="csv", incluir_encabezado=True, formato_fecha="%Y-%m-%d",
        columnas_json=json.dumps([{"label":h,"source":"fijo","valor_fijo":""} for h in encabezados], ensure_ascii=False),
        version_formato=1,
    )
    db_session.add(vieja); db_session.commit(); db_session.refresh(vieja)
    r = client.post(f"/empresas/{empresa_id}/plantillas/{vieja.id}/reprocesar-siigo")
    assert r.status_code == 201, r.text
    nueva = r.json()
    assert nueva["version_formato"] == 2
    assert nueva["plantilla_origen_id"] == vieja.id
    assert [c["label"] for c in nueva["columnas"]] == encabezados
    assert nueva["columnas"][1]["source"] == "codigo_comprobante_siigo"
    assert nueva["columnas"][17]["source"] == "concepto_siigo"


def test_no_permite_reducir_consecutivo_siigo(client, empresa_a):
    empresa_id = empresa_a["id"]
    _config_siigo(client, empresa_id, ultimo=80)
    r = client.put(f"/empresas/{empresa_id}/siigo/comprobantes", json={"configuraciones":[{
        "tipo_documento":"factura_recibida", "tipo_comprobante":"G", "codigo_comprobante":"1",
        "ultimo_consecutivo_usado":79,
    }]})
    assert r.status_code == 409
    assert "no se puede reducir" in r.json()["detail"]
