"""
Generación del archivo de exportación (secciones 22-23, 39).

Flujo: CONTABILIZACIÓN INTERNA -> PLANTILLA DE LA EMPRESA -> ARCHIVO.
La lógica contable (movimientos, cuentas, valores) nunca depende de
las columnas de Siigo o World Office — eso se resuelve aquí, en la
capa de exportación, aplicando la plantilla configurada.
"""
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import Empresa, Factura, Movimiento, PlantillaExportacion, EstadoFactura
from app.services.export_adapters import obtener_adaptador


def _tipo_comprobante_para_factura(empresa: Empresa, factura: Factura) -> str:
    """
    Resuelve el tipo de comprobante configurado en la empresa según la
    clasificación real del documento — nunca el mismo para compras,
    ventas, notas y nómina (sección 19-21, confirmado con archivos
    reales de Siigo/World Office que usan comprobantes distintos).
    """
    if factura.naturaleza_documento == "nota_credito":
        return empresa.comprobante_nota_credito or ""
    if factura.naturaleza_documento == "nota_debito":
        return empresa.comprobante_nota_debito or ""
    if factura.naturaleza_documento == "nomina":
        return empresa.comprobante_nomina or ""
    if factura.naturaleza_documento == "documento_equivalente":
        return empresa.comprobante_documento_equivalente or ""
    if factura.direccion_documento == "emitida":
        return empresa.comprobante_factura_emitida or ""
    return empresa.comprobante_factura_recibida or ""


def _valor_columna(columna: dict, factura: Factura, movimiento: Movimiento,
                    equivalencias: dict, formato_fecha: str, empresa: Optional[Empresa] = None) -> str:
    source = columna.get("source")
    fijo = columna.get("valor_fijo", "")

    if source == "fijo":
        return fijo
    if source == "tipo_comprobante":
        valor = _tipo_comprobante_para_factura(empresa, factura) if empresa else ""
        return valor or fijo
    if source == "fecha":
        return factura.fecha_emision.strftime(formato_fecha) if factura.fecha_emision else fijo
    if source == "anio":
        return str(factura.fecha_emision.year) if factura.fecha_emision else fijo
    if source == "mes":
        return str(factura.fecha_emision.month) if factura.fecha_emision else fijo
    if source == "dia":
        return str(factura.fecha_emision.day) if factura.fecha_emision else fijo
    if source == "cuenta":
        codigo = movimiento.cuenta.codigo
        return equivalencias.get(codigo, codigo)
    if source == "nombre_cuenta":
        return movimiento.cuenta.nombre
    if source == "nit":
        return factura.tercero_nit or fijo
    if source == "tercero":
        return factura.tercero_nombre or fijo
    if source == "numero_factura":
        return factura.numero_factura or fijo
    if source == "cufe":
        return factura.cufe or fijo
    if source == "concepto":
        return movimiento.descripcion or f"Factura {factura.numero_factura or ''}"
    if source == "debito_credito":
        # Estructura real de Siigo Pyme (Movimiento Contable): una sola
        # columna con "D" o "C" en vez de dos columnas separadas.
        return "D" if movimiento.tipo == "debito" else "C"
    if source == "valor":
        # El valor del movimiento sin importar si es débito o crédito —
        # se usa junto con "debito_credito" (columna aparte indica el lado).
        return f"{float(movimiento.valor):.2f}"
    if source == "debito":
        return f"{float(movimiento.valor):.2f}" if movimiento.tipo == "debito" else ""
    if source == "credito":
        return f"{float(movimiento.valor):.2f}" if movimiento.tipo == "credito" else ""
    return fijo


def validar_exportacion(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                         facturas: list[Factura]) -> list[str]:
    """Sección 23: nunca se genera el archivo como válido si hay errores."""
    errores = []
    adaptador = obtener_adaptador(plantilla.sistema_contable.value if hasattr(plantilla.sistema_contable, "value")
                                   else plantilla.sistema_contable)
    columnas = json.loads(plantilla.columnas_json)

    errores += adaptador.validar_plantilla(columnas)
    if not columnas:
        errores.append("La plantilla no tiene columnas configuradas.")

    filas_por_validar = []
    for f in facturas:
        if f.estado not in (EstadoFactura.lista_para_contabilizar, EstadoFactura.contabilizada):
            errores.append(
                f"La factura {f.numero_factura or f.id} está en estado '{f.estado.value}' — "
                f"debe generar y aprobar su partida doble antes de exportarla."
            )
            continue
        movimientos = db.query(Movimiento).filter(Movimiento.factura_id == f.id).order_by(Movimiento.orden).all()
        if not movimientos:
            errores.append(f"La factura {f.numero_factura or f.id} no tiene movimientos contables generados.")
            continue
        total_d = sum(float(m.valor) for m in movimientos if m.tipo == "debito")
        total_c = sum(float(m.valor) for m in movimientos if m.tipo == "credito")
        if abs(total_d - total_c) >= 0.01:
            errores.append(f"La factura {f.numero_factura or f.id} no está balanceada (débito {total_d} "
                            f"vs crédito {total_c}).")
        if not f.fecha_emision:
            errores.append(f"La factura {f.numero_factura or f.id} no tiene fecha de emisión válida.")
        if not f.tercero_nit:
            errores.append(f"La factura {f.numero_factura or f.id} no tiene NIT de tercero "
                            f"({'receptor' if f.direccion_documento == 'emitida' else 'emisor'}).")

        for m in movimientos:
            filas_por_validar.append({
                "Fecha": f.fecha_emision.strftime(plantilla.formato_fecha) if f.fecha_emision else "",
                "Cuenta": m.cuenta.codigo, "Nit": f.tercero_nit or "", "Tercero": f.tercero_nombre or "",
                "Debito": float(m.valor) if m.tipo == "debito" else 0,
                "Credito": float(m.valor) if m.tipo == "credito" else 0,
            })

    if filas_por_validar:
        errores += adaptador.validar_negocio(filas_por_validar)

    return errores


def generar_archivo(db: Session, empresa: Empresa, plantilla: PlantillaExportacion,
                     facturas: list[Factura]) -> tuple[bytes, int]:
    """Devuelve (contenido_bytes, cantidad_de_filas). Se asume ya validado."""
    columnas = json.loads(plantilla.columnas_json)
    equivalencias = json.loads(plantilla.equivalencias_cuentas_json or "{}")
    delimitador = "\t" if plantilla.delimitador == "\\t" else plantilla.delimitador

    lineas = []
    if plantilla.incluir_encabezado:
        lineas.append(delimitador.join(c["label"] for c in columnas))

    total_filas = 0
    for f in facturas:
        movimientos = db.query(Movimiento).filter(Movimiento.factura_id == f.id).order_by(Movimiento.orden).all()
        for m in movimientos:
            valores = [
                _valor_columna(c, f, m, equivalencias, plantilla.formato_fecha, empresa).replace(delimitador, " ")
                for c in columnas
            ]
            lineas.append(delimitador.join(valores))
            total_filas += 1

    contenido = ("\r\n".join(lineas)).encode("utf-8")
    return contenido, total_filas
