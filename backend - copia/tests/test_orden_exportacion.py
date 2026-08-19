from datetime import datetime

from app.services.export_service import agrupar_y_ordenar_facturas
from app.models.models import Factura


def _f(direccion, naturaleza, fecha=None, prefijo=None, numero=None, nombre=None, nit=None):
    return Factura(
        id=f"{direccion}-{naturaleza}-{numero}-{prefijo}", empresa_id="e1",
        direccion_documento=direccion, naturaleza_documento=naturaleza,
        fecha_emision=datetime(*fecha) if fecha else None,
        prefijo=prefijo, numero_factura=numero, nombre_emisor=nombre, nit_emisor=nit,
    )


def test_agrupa_recibidas_antes_que_emitidas_y_estas_antes_que_nomina():
    facturas = [
        _f("no_aplica", "nomina", numero="N1"),
        _f("emitida", "factura", numero="E1"),
        _f("recibida", "factura", numero="R1"),
    ]
    ordenadas = agrupar_y_ordenar_facturas(facturas)
    tipos = [(f.direccion_documento, f.naturaleza_documento) for f in ordenadas]
    assert tipos == [("recibida", "factura"), ("emitida", "factura"), ("no_aplica", "nomina")]


def test_recibidas_van_antes_que_sus_propias_notas_credito():
    facturas = [
        _f("recibida", "nota_credito", numero="NC1"),
        _f("recibida", "factura", numero="R1"),
    ]
    ordenadas = agrupar_y_ordenar_facturas(facturas)
    tipos = [f.naturaleza_documento for f in ordenadas]
    assert tipos == ["factura", "nota_credito"]


def test_orden_dentro_del_grupo_por_fecha_descendente():
    facturas = [
        _f("recibida", "factura", fecha=(2026, 7, 1), numero="R1"),
        _f("recibida", "factura", fecha=(2026, 7, 15), numero="R2"),
        _f("recibida", "factura", fecha=(2026, 7, 10), numero="R3"),
    ]
    ordenadas = agrupar_y_ordenar_facturas(facturas)
    fechas = [f.fecha_emision.day for f in ordenadas]
    assert fechas == [15, 10, 1]


def test_orden_por_prefijo_folio_nombre_nit_descendente_cuando_fecha_es_igual():
    facturas = [
        _f("recibida", "factura", fecha=(2026, 7, 1), prefijo="A", numero="100", nombre="Zeta SAS", nit="900"),
        _f("recibida", "factura", fecha=(2026, 7, 1), prefijo="B", numero="050", nombre="Alfa SAS", nit="100"),
    ]
    ordenadas = agrupar_y_ordenar_facturas(facturas)
    assert [f.prefijo for f in ordenadas] == ["B", "A"]


def test_valores_vacios_quedan_al_final_del_grupo_no_al_principio():
    facturas = [
        _f("recibida", "factura", numero="R1"),
        _f("recibida", "factura", fecha=(2026, 7, 1), prefijo="A", numero="R2"),
    ]
    ordenadas = agrupar_y_ordenar_facturas(facturas)
    assert ordenadas[0].numero_factura == "R2"
    assert ordenadas[1].numero_factura == "R1"
