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


def _valor_columna(columna: dict, factura: Factura, movimiento: Movimiento,
                    equivalencias: dict, formato_fecha: str) -> str:
    source = columna.get("source")
    fijo = columna.get("valor_fijo", "")

    if source == "fijo":
        return fijo
    if source == "fecha":
        return factura.fecha_emision.strftime(formato_fecha) if factura.fecha_emision else fijo
    if source == "cuenta":
        codigo = movimiento.cuenta.codigo
        return equivalencias.get(codigo, codigo)
    if source == "nombre_cuenta":
        return movimiento.cuenta.nombre
    if source == "nit":
        return factura.nit_emisor or fijo
    if source == "tercero":
        return factura.nombre_emisor or fijo
    if source == "numero_factura":
        return factura.numero_factura or fijo
    if source == "cufe":
        return factura.cufe or fijo
    if source == "concepto":
        return movimiento.descripcion or f"Factura {factura.numero_factura or ''}"
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
        if not f.nit_emisor:
            errores.append(f"La factura {f.numero_factura or f.id} no tiene NIT de emisor.")

        for m in movimientos:
            filas_por_validar.append({
                "Fecha": f.fecha_emision.strftime(plantilla.formato_fecha) if f.fecha_emision else "",
                "Cuenta": m.cuenta.codigo, "Nit": f.nit_emisor or "", "Tercero": f.nombre_emisor or "",
                "Debito": float(m.valor) if m.tipo == "debito" else 0,
                "Credito": float(m.valor) if m.tipo == "credito" else 0,
            })

    if filas_por_validar:
        errores += adaptador.validar_negocio(filas_por_validar)

    return errores


def generar_archivo(db: Session, plantilla: PlantillaExportacion, facturas: list[Factura]) -> tuple[bytes, int]:
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
                _valor_columna(c, f, m, equivalencias, plantilla.formato_fecha).replace(delimitador, " ")
                for c in columnas
            ]
            lineas.append(delimitador.join(valores))
            total_filas += 1

    contenido = ("\r\n".join(lineas)).encode("utf-8")
    return contenido, total_filas
