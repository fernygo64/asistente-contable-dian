from app.services.siigo_pyme_extendido import DEFAULTS_SIIGO_PYME_EXTENDIDO
from tests.test_exportacion import _preparar_factura_lista

HEADERS_AR = [
    "TIPO DE COMPROBANTE (OBLIGATORIO)", "CÓDIGO COMPROBANTE  (OBLIGATORIO)",
    "NÚMERO DE DOCUMENTO", "CUENTA CONTABLE   (OBLIGATORIO)",
    "DÉBITO O CRÉDITO (OBLIGATORIO)", "VALOR DE LA SECUENCIA   (OBLIGATORIO)",
    "AÑO DEL DOCUMENTO", "MES DEL DOCUMENTO", "DÍA DEL DOCUMENTO", "CÓDIGO DEL VENDEDOR",
    "CÓDIGO DE LA CIUDAD", "CÓDIGO DE LA ZONA", "SECUENCIA", "CENTRO DE COSTO",
    "SUBCENTRO DE COSTO", "NIT", "SUCURSAL", "DESCRIPCIÓN DE LA SECUENCIA",
]


def test_modelo_general_123_columnas_y_s_ds_completo(client, empresa_a):
    empresa_id=empresa_a['id']
    f=_preparar_factura_lista(client, empresa_id, 'MG001', 'cufe-mg-1', '900222501')
    # Config comprobante G-1, arrancando desde 80.
    client.put(f'/empresas/{empresa_id}/siigo/comprobantes', json={'configuraciones':[{
        'tipo_documento':'factura_recibida','tipo_comprobante':'G','codigo_comprobante':'1',
        'ultimo_consecutivo_usado':80,'codigo_vendedor_default':'1','codigo_zona_default':'0',
        'centro_costo_default':'0','subcentro_costo_default':'0','sucursal_default':'0'
    }]})
    cuentas=client.get(f'/empresas/{empresa_id}/siigo/cuentas').json()
    por={x['cuenta_codigo']:x for x in cuentas}
    client.put(f"/empresas/{empresa_id}/siigo/cuentas/{por['513595']['cuenta_id']}", json={
        'maneja_tercero':True,'codigo_vendedor':'1','codigo_ciudad':'1','codigo_zona':'0','subcentro_costo':'0','sucursal':'0'
    })
    client.put(f"/empresas/{empresa_id}/siigo/cuentas/{por['220501']['cuenta_id']}", json={
        'maneja_tercero':False,'nit_tecnico_exportacion':'0','codigo_vendedor':'1','codigo_ciudad':'0','codigo_zona':'0','subcentro_costo':'0','sucursal':'0'
    })
    headers=HEADERS_AR+list(DEFAULTS_SIIGO_PYME_EXTENDIDO.keys())
    assert len(headers)==123
    cols=[{'label':h,'source':'fijo','valor_fijo':''} for h in headers]
    r=client.post(f'/empresas/{empresa_id}/plantillas',json={
        'nombre':'Modelo General v2','sistema_contable':'siigo_pyme','delimitador':';','extension':'csv','columnas':cols
    })
    assert r.status_code==201,r.text
    assert r.json()['version_formato']==2
    resp=client.post(f'/empresas/{empresa_id}/exportaciones/generar',json={'plantilla_id':r.json()['id'],'factura_ids':[f['id']]})
    assert resp.status_code==200,resp.text
    filas=resp.content.decode('cp1252').split('\r\n')
    assert filas[0].split(';')==headers
    datos=[x.split(';') for x in filas[1:] if x]
    assert len(datos)==2
    assert all(len(x)==123 for x in datos)
    assert all(all(v!='' for v in x[18:]) for x in datos)
    # G, código 1, consecutivo 81 compartido por ambas secuencias.
    assert {(x[0],x[1],x[2]) for x in datos}=={('G','1','81')}
    # Gasto lleva proveedor; contrapartida configurada sin tercero lleva 0.
    por_cuenta={(x[3],x[15]) for x in datos}
    assert ('5135950000','900222501') in por_cuenta
    assert ('2205010000','0') in por_cuenta
