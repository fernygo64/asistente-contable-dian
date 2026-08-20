import io
import zipfile

XML_ANGELA_REAL = '''<?xml version="1.0" encoding="utf-8"?>
<NominaIndividual xmlns="dian:gov:co:facturaelectronica:NominaIndividual">
  <Periodo FechaIngreso="2022-03-01" FechaLiquidacionInicio="2026-05-01" FechaLiquidacionFin="2026-05-30" TiempoLaborado="1552" FechaGen="2026-06-03"/>
  <NumeroSecuenciaXML Prefijo="DNE" Consecutivo="108" Numero="DNE108"/>
  <InformacionGeneral Version="V1.0" CUNE="43c8e51534653c3d435dc4dc984f11c5f686c2161bc4500d42acc70a965893d78526e1f59be4367f2056a0ee0ab4a057" FechaGen="2026-06-03" PeriodoNomina="5" TipoMoneda="COP"/>
  <Empleador RazonSocial="RAL ENERGY SAS" NIT="901499176" DV="8" Pais="CO"/>
  <Trabajador TipoTrabajador="01" SubTipoTrabajador="00" AltoRiesgoPension="false" TipoDocumento="13" NumeroDocumento="1093216007" PrimerApellido="ALVAREZ" SegundoApellido="GIRALDO" PrimerNombre="ANGELA ROSA" SalarioIntegral="false" TipoContrato="2" Sueldo="5000000"/>
  <Pago Forma="1" Metodo="46"/>
  <FechasPagos><FechaPago>2026-06-03</FechaPago></FechasPagos>
  <Devengados>
    <Basico DiasTrabajados="30" SueldoTrabajado="5000000"/>
  </Devengados>
  <Deducciones>
    <Salud Porcentaje="4.00" Deduccion="200000"/>
    <FondoPension Porcentaje="4.00" Deduccion="200000"/>
  </Deducciones>
  <DevengadosTotal>5000000</DevengadosTotal>
  <DeduccionesTotal>400000</DeduccionesTotal>
  <ComprobanteTotal>4600000</ComprobanteTotal>
</NominaIndividual>'''.encode('utf-8')

XML_ZORAIDA_CON_TRANSPORTE = '''<?xml version="1.0" encoding="utf-8"?>
<NominaIndividual xmlns="dian:gov:co:facturaelectronica:NominaIndividual">
  <Periodo FechaIngreso="2025-10-15" FechaLiquidacionInicio="2026-05-01" FechaLiquidacionFin="2026-05-30" TiempoLaborado="228" FechaGen="2026-06-03"/>
  <NumeroSecuenciaXML Prefijo="DNE" Consecutivo="109" Numero="DNE109"/>
  <InformacionGeneral Version="V1.0" CUNE="6c7aa1a981e3772bf100c58b72c34d2ba813fd40b8ced354a11fd00b171b051e513dcb16f624cda6dfb45d5af6da866b" FechaGen="2026-06-03" PeriodoNomina="5" TipoMoneda="COP"/>
  <Empleador RazonSocial="RAL ENERGY SAS" NIT="901499176" DV="8" Pais="CO"/>
  <Trabajador TipoTrabajador="01" SubTipoTrabajador="00" AltoRiesgoPension="false" TipoDocumento="13" NumeroDocumento="30334248" PrimerApellido="MUÑOZ" SegundoApellido="CARMONA" PrimerNombre="ZORAIDA" SalarioIntegral="false" TipoContrato="2" Sueldo="1750905"/>
  <Pago Forma="1" Metodo="10"/>
  <FechasPagos><FechaPago>2026-06-03</FechaPago></FechasPagos>
  <Devengados>
    <Basico DiasTrabajados="30" SueldoTrabajado="1750905"/>
    <Transporte AuxilioTransporte="249095"/>
  </Devengados>
  <Deducciones>
    <Salud Porcentaje="4.00" Deduccion="70100"/>
    <FondoPension Porcentaje="4.00" Deduccion="70100"/>
  </Deducciones>
  <DevengadosTotal>2000000</DevengadosTotal>
  <DeduccionesTotal>140200</DeduccionesTotal>
  <ComprobanteTotal>1859800</ComprobanteTotal>
</NominaIndividual>'''.encode('utf-8')


def _zip_con(nombre, contenido):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(nombre, contenido)
    return buf.getvalue()


def _configurar_cuentas_nomina(client, empresa_id):
    for codigo, nombre in [
        ("5105060000", "Sueldos"), ("2505050000", "Nomina por pagar"),
        ("5105270000", "Auxilio transporte"),
        ("2370050000", "Salud por pagar"), ("2380300000", "Pension por pagar"),
        ("5105300000", "Cesantias"), ("2610050000", "Cesantias por pagar"),
        ("5105330000", "Intereses cesantias"), ("2610100000", "Intereses cesantias por pagar"),
        ("5105360000", "Prima"), ("2610200000", "Prima por pagar"),
        ("5105390000", "Vacaciones"), ("2610150000", "Vacaciones por pagar"),
    ]:
        client.post(f"/empresas/{empresa_id}/cuentas", json={"codigo": codigo, "nombre": nombre})

    client.patch(f"/empresas/{empresa_id}/cuentas-base", json={
        "cuenta_salario": "5105060000", "cuenta_auxilio_transporte": "5105270000",
        "cuenta_nomina_por_pagar": "2505050000",
        "cuenta_salud_por_pagar": "2370050000", "cuenta_pension_por_pagar": "2380300000",
        "cuenta_cesantias": "5105300000", "cuenta_cesantias_por_pagar": "2610050000",
        "cuenta_intereses_cesantias": "5105330000", "cuenta_intereses_cesantias_por_pagar": "2610100000",
        "cuenta_prima": "5105360000", "cuenta_prima_por_pagar": "2610200000",
        "cuenta_vacaciones": "5105390000", "cuenta_vacaciones_por_pagar": "2610150000",
    })


def test_nomina_multilinea_completa_con_xml_real(client, empresa_a):
    _configurar_cuentas_nomina(client, empresa_a["id"])
    client.post(f"/empresas/{empresa_a['id']}/empleados", json={
        "nit": "1093216007", "nombre": "ANGELA ROSA ALVAREZ GIRALDO",
        "eps_nit": "860066942", "eps_nombre": "EPS SURA",
        "afp_nit": "800229739", "afp_nombre": "PORVENIR",
    })

    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", _zip_con("nomina.xml", XML_ANGELA_REAL), "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nomina"}).json()[0]
    assert factura["nit_emisor"] == "1093216007"

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar", json={})
    body = r.json()
    assert body["balanceado"] is True, body
    assert body["errores"] == []

    lineas = {(l["cuenta_codigo"], l["tipo"]): l["valor"] for l in body["lineas"]}
    assert lineas[("5105060000", "debito")] == 5000000.0
    assert lineas[("2370050000", "credito")] == 200000.0
    assert lineas[("2380300000", "credito")] == 200000.0
    assert lineas[("2505050000", "credito")] == 4600000.0

    assert abs(lineas[("5105300000", "debito")] - 416666.5) < 1
    assert abs(lineas[("5105330000", "debito")] - 49999.98) < 1
    assert abs(lineas[("5105360000", "debito")] - 416666.5) < 1
    assert abs(lineas[("5105390000", "debito")] - 208333.5) < 1


def test_nomina_con_auxilio_transporte(client, empresa_a):
    _configurar_cuentas_nomina(client, empresa_a["id"])
    client.post(f"/empresas/{empresa_a['id']}/empleados", json={
        "nit": "30334248", "nombre": "ZORAIDA MUÑOZ CARMONA",
        "eps_nit": "900156264", "eps_nombre": "NUEVA EPS",
        "afp_nit": "900336004", "afp_nombre": "COLPENSIONES",
    })
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", _zip_con("nomina.xml", XML_ZORAIDA_CON_TRANSPORTE), "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nomina"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar", json={})
    body = r.json()
    assert body["balanceado"] is True, body
    lineas = {(l["cuenta_codigo"], l["tipo"]): l["valor"] for l in body["lineas"]}
    assert lineas[("5105060000", "debito")] == 1750905.0
    assert lineas[("5105270000", "debito")] == 249095.0
    assert lineas[("2505050000", "credito")] == 1859800.0


def test_nomina_sin_ficha_de_empleado_cae_al_registro_manual(client, empresa_a):
    _configurar_cuentas_nomina(client, empresa_a["id"])
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", _zip_con("nomina.xml", XML_ANGELA_REAL), "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nomina"}).json()[0]
    client.patch(f"/empresas/{empresa_a['id']}/cuentas-base", json={"cuenta_proveedores": "220501"})

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar",
                     json={"cuenta_gasto_codigo": "5105060000", "contrapartida": "proveedores"})
    body = r.json()
    assert body["balanceado"] is True, body
    assert len(body["lineas"]) == 2


def test_nomina_sin_afiliaciones_del_empleado_da_error_claro(client, empresa_a):
    _configurar_cuentas_nomina(client, empresa_a["id"])
    client.post(f"/empresas/{empresa_a['id']}/empleados", json={"nit": "1093216007", "nombre": "Angela"})
    client.post(f"/empresas/{empresa_a['id']}/documentos/cargar",
                files=[("documentos", ("d.zip", _zip_con("nomina.xml", XML_ANGELA_REAL), "application/zip"))])
    factura = client.get(f"/empresas/{empresa_a['id']}/documentos", params={"naturaleza": "nomina"}).json()[0]

    r = client.post(f"/empresas/{empresa_a['id']}/documentos/{factura['id']}/partida/generar", json={})
    body = r.json()
    assert body["balanceado"] is False
    assert any("EPS" in e for e in body["errores"])
