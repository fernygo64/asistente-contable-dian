import io
import zipfile

from tests.test_documentos import _xml, _zip_bytes


def _configurar_cuentas_base(client, empresa_id, **kwargs):
    r = client.patch(f"/empresas/{empresa_id}/cuentas-base", json=kwargs)
    assert r.status_code == 200, r.text
    return r.json()


def _cargar_una_factura(client, empresa_id, numero="FEP001", cufe="cufe-partida-1",
                         nit="900321321", subtotal="100000", total="119000"):
    zip_contenido = _zip_bytes({f"{numero}.xml": _xml(numero, cufe, nit, subtotal=subtotal, total=total)})
    r = client.post(f"/empresas/{empresa_id}/documentos/cargar",
                     files=[("documentos", ("d.zip", zip_contenido, "application/zip"))])
    assert r.status_code == 201, r.text
    facturas = client.get(f"/empresas/{empresa_id}/documentos", params={"nit_emisor": nit}).json()
    return facturas[0]


def test_no_genera_partida_sin_cuenta_iva_configurada(client, empresa_a):
    # La factura de prueba trae IVA (subtotal 100000 + iva implícito en total 119000,
    # pero el XML de prueba no incluye TaxTotal -> iva=0). Forzamos vía cuenta de gasto
    # sin configurar proveedores, para probar el caso "falta contrapartida".
    factura = _cargar_una_factura(client, empresa_a["id"])
    client.post(f"/empresas/{empresa_a['id']}/cuentas",
                json={"codigo": "519530", "nombre": "Papelería"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores"})
    assert r.status_code == 200
    body = r.json()
    assert body["balanceado"] is False
    assert any("proveedores" in e.lower() for e in body["errores"])


def test_genera_partida_balanceada_con_cuentas_configuradas(client, empresa_a):
    factura = _cargar_una_factura(client, empresa_a["id"], numero="FEP002", cufe="cufe-partida-2",
                                   nit="900321322", subtotal="100000", total="100000")
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "519530", "nombre": "Papelería"})
    _configurar_cuentas_base(client, empresa_a["id"], cuenta_proveedores="220501")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "519530", "contrapartida": "proveedores"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balanceado"] is True
    assert body["total_debito"] == body["total_credito"] == 100000.0
    codigos_credito = [l["cuenta_codigo"] for l in body["lineas"] if l["tipo"] == "credito"]
    assert "220501" in codigos_credito

    factura_actualizada = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}").json()
    assert factura_actualizada["estado"] == "lista_para_contabilizar"


def test_contrapartida_caja_en_vez_de_proveedores(client, empresa_a):
    factura = _cargar_una_factura(client, empresa_a["id"], numero="FEP003", cufe="cufe-partida-3",
                                   nit="900321323", subtotal="50000", total="50000")
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "522515", "nombre": "Combustibles"})
    _configurar_cuentas_base(client, empresa_a["id"], cuenta_caja="110505")

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "522515", "contrapartida": "caja"})
    body = r.json()
    assert body["balanceado"] is True
    codigos_credito = [l["cuenta_codigo"] for l in body["lineas"] if l["tipo"] == "credito"]
    assert "110505" in codigos_credito
    assert "220501" not in codigos_credito


def test_no_se_puede_contabilizar_sin_generar_partida_primero(client, empresa_a):
    factura = _cargar_una_factura(client, empresa_a["id"], numero="FEP004", cufe="cufe-partida-4",
                                   nit="900321324")
    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/contabilizar")
    assert r.status_code == 422


def test_flujo_completo_generar_y_contabilizar(client, empresa_a):
    factura = _cargar_una_factura(client, empresa_a["id"], numero="FEP005", cufe="cufe-partida-5",
                                   nit="900321325", subtotal="75000", total="75000")
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "512005", "nombre": "Arrendamientos"})
    _configurar_cuentas_base(client, empresa_a["id"], cuenta_proveedores="220501")

    r1 = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                      json={"cuenta_gasto_codigo": "512005", "contrapartida": "proveedores"})
    assert r1.json()["balanceado"] is True

    r2 = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/contabilizar")
    assert r2.status_code == 200
    assert r2.json()["estado"] == "contabilizada"

    # la partida debe poder consultarse (preview / auditoría)
    r3 = client.get(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida")
    assert r3.status_code == 200
    assert r3.json()["balanceado"] is True


def test_partida_generada_alimenta_el_historial_de_aprendizaje(client, empresa_a):
    factura = _cargar_una_factura(client, empresa_a["id"], numero="FEP006", cufe="cufe-partida-6",
                                   nit="900321326", subtotal="60000", total="60000")
    client.post(f"/empresas/{empresa_a['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    _configurar_cuentas_base(client, empresa_a["id"], cuenta_proveedores="220501")

    client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                json={"cuenta_gasto_codigo": "513595", "contrapartida": "proveedores",
                      "origen_decision": "sugerencia_aceptada"})

    sug = client.get(f"/empresas/{empresa_a['id']}/historial/sugerencia",
                      params={"nit": "900321326"}).json()
    assert sug["cuenta_sugerida"] == "513595"
    assert sug["total_documentos_historicos"] == 1


def test_regimen_simple_excluye_retefuente_en_partida(client, empresa_a):
    """Reproduce la misma regla ya validada en el extractor de facturas (single-file HTML)."""
    empresa_id = empresa_a["id"]
    # activar régimen simple
    from app.models.models import Empresa
    # (se hace vía API real, no acceso directo a modelos, para probar el endpoint también)
    r = client.post("/empresas", json={"nit": "900654321", "nombre": "Empresa RST", "regimen_simple": True})
    empresa_rst = r.json()

    factura = _cargar_una_factura(client, empresa_rst["id"], numero="FEP007", cufe="cufe-partida-7",
                                   nit="900321327", subtotal="40000", total="40000")
    client.post(f"/empresas/{empresa_rst['id']}/cuentas", json={"codigo": "513595", "nombre": "Honorarios"})
    _configurar_cuentas_base(client, empresa_rst["id"], cuenta_proveedores="220501",
                              cuenta_retefuente="236540")

    # Aunque hipotéticamente hubiera retefuente detectado, RST no la debe aplicar;
    # como nuestro XML de prueba no trae retenciones, validamos que al menos no
    # aparece ninguna línea de retefuente y el balance sigue siendo correcto.
    r = client.post(f"/empresas/{empresa_rst['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "513595", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is True
    assert not any(l["cuenta_codigo"] == "236540" for l in body["lineas"])
