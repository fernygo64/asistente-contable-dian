"""Formato y orden canónico de documentos DIAN.

Regla operativa acordada para documentos recibidos y para el archivo contable:
- El orden usa la FECHA DE EMISIÓN completa, de la más antigua a la más reciente.
- Dentro de la misma fecha: Prefijo, Folio y Nombre Emisor, ascendente.
- La combinación ``DD PREFIJO-FOLIO NOMBRE EMISOR`` es únicamente una referencia
  técnica disponible para diagnóstico; NO se usa como descripción contable.
- "DESCRIPCIÓN DE LA SECUENCIA" se construye aparte como
  ``PREFIJO-FOLIO + concepto breve de la compra``.

La fecha completa se conserva para ordenar y asignar consecutivos.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def _texto(valor: Any) -> str:
    return " ".join(str(valor or "").strip().split())


def prefijo_folio(prefijo: Any, folio: Any) -> str:
    """Une prefijo y folio con UN solo guion, sin duplicar el prefijo.

    Ejemplos:
    - ``ABC`` + ``12345`` -> ``ABC-12345``
    - ``ABC`` + ``ABC12345`` -> ``ABC-12345``
    - ``ABC`` + ``ABC-12345`` -> ``ABC-12345``
    - sin prefijo + ``ABC-12345`` -> ``ABC-12345`` (no se inventa un prefijo).
    """
    p = _texto(prefijo)
    f = _texto(folio)
    if not p:
        return f
    if not f:
        return p

    # Si Folio ya incluye el prefijo, quitarlo solo del inicio. Se toleran
    # guion, slash, guion bajo o espacios entre ambos para no generar ABC-ABC-12345.
    patron = re.compile(rf"^{re.escape(p)}(?:\s*[-_/]\s*|\s*)", re.IGNORECASE)
    resto = patron.sub("", f, count=1).strip(" -_/")
    if not resto:
        resto = f.strip(" -_/")
    return f"{p}-{resto}" if resto else p



def folio_sin_prefijo(prefijo: Any, folio: Any) -> str:
    """Devuelve el Folio separado cuando el valor original ya incluía el Prefijo."""
    p = _texto(prefijo)
    f = _texto(folio)
    if not p or not f:
        return f
    patron = re.compile(rf"^{re.escape(p)}(?:\s*[-_/]\s*|\s*)", re.IGNORECASE)
    resto = patron.sub("", f, count=1).strip(" -_/")
    return resto or f

def referencia_documento(fecha_emision: datetime | date | None, prefijo: Any, folio: Any,
                         nombre_emisor: Any) -> str:
    """Devuelve ``DD PREFIJO-FOLIO NOMBRE EMISOR`` en una sola línea."""
    partes: list[str] = []
    if fecha_emision:
        try:
            partes.append(f"{int(fecha_emision.day):02d}")
        except Exception:
            pass
    doc = prefijo_folio(prefijo, folio)
    if doc:
        partes.append(doc)
    nombre = _texto(nombre_emisor)
    if nombre:
        partes.append(nombre)
    return " ".join(partes).strip()


def _natural(texto: Any) -> tuple:
    """Clave alfanumérica estable: AR2 queda antes que AR10."""
    s = _texto(texto).casefold()
    partes = re.split(r"(\d+)", s)
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in partes if p != "")


def clave_orden_documento(documento: Any) -> tuple:
    """Fecha completa ascendente -> Prefijo -> Folio -> Nombre Emisor.

    Los valores vacíos siempre quedan al final. No agrupa por naturaleza documental:
    una nota crédito conserva su clasificación/comprobante, pero ocupa el lugar que
    cronológicamente le corresponde dentro del lote.
    """
    fecha = getattr(documento, "fecha_emision", None)
    if isinstance(fecha, datetime):
        fecha_key = (fecha.year, fecha.month, fecha.day, fecha.hour, fecha.minute, fecha.second, fecha.microsecond)
    elif isinstance(fecha, date):
        fecha_key = (fecha.year, fecha.month, fecha.day, 0, 0, 0, 0)
    else:
        fecha_key = (9999, 12, 31, 23, 59, 59, 999999)

    prefijo = _texto(getattr(documento, "prefijo", None))
    folio = _texto(getattr(documento, "numero_factura", None))
    nombre = _texto(getattr(documento, "nombre_emisor", None))
    return (
        fecha is None, fecha_key,
        not bool(prefijo), _natural(prefijo),
        not bool(folio), _natural(folio),
        not bool(nombre), _natural(nombre),
    )


def ordenar_documentos(documentos: list[Any]) -> list[Any]:
    return sorted(documentos, key=clave_orden_documento)
