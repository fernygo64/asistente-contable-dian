"""Clasificación robusta de documentos desde el Excel de la DIAN.

La DIAN puede expresar la misma naturaleza con texto, variantes singular/plural
o códigos documentales (por ejemplo 91 Nota Crédito y 92 Nota Débito). Esta
capa normaliza esas variantes antes de que el documento llegue al motor contable.
"""
from __future__ import annotations

import re
import unicodedata


# No son documentos contables que deban generar partida.
_TIPOS_DESCARTAR = {
    "application response", "applicationresponse", "acuse de recibo",
    "evento radian", "respuesta de aplicacion",
}


def _normalizar(texto: str) -> str:
    texto = (texto or "").strip().lower()
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _codigo_documental(texto_norm: str) -> str:
    """Extrae un código DIAN corto cuando aparece como 91, 91 - ..., etc."""
    m = re.search(r"(?:^|\b)(91|92)(?:\b|\D)", texto_norm)
    return m.group(1) if m else ""


def es_tipo_descartable(valor_tipo_documento: str) -> bool:
    valor = _normalizar(valor_tipo_documento)
    return any(x in valor for x in _TIPOS_DESCARTAR)


def _naturaleza_desde_tipo(valor_tipo_documento: str) -> str:
    t = _normalizar(valor_tipo_documento)
    codigo = _codigo_documental(t)

    # Códigos DIAN usuales para documentos de ajuste.
    if codigo == "91":
        return "nota_credito"
    if codigo == "92":
        return "nota_debito"

    compacta = re.sub(r"[^a-z0-9]", "", t)
    if "creditnote" in compacta or "nota credito" in t:
        return "nota_credito"
    if "debitnote" in compacta or "nota debito" in t:
        return "nota_debito"
    if "nomina" in t or "payroll" in t:
        return "nomina"
    if "documento equivalente" in t or "documento soporte" in t:
        return "documento_equivalente"
    if "factura" in t or "invoice" in t:
        return "factura"

    # Un tipo vacío/desconocido NO se convierte automáticamente en factura:
    # si existe XML, su raíz estructural decide; si solo existe Excel quedará
    # como documento para revisión en la capa de carga.
    return ""


def _direccion_desde_grupo(valor_grupo: str) -> str:
    g = _normalizar(valor_grupo)
    # Variantes observables en archivos/reportes: "Recibido", "Recibidos",
    # "Documentos recibidos", "Recibida(s)", y equivalentes emitidos.
    if re.search(r"\b(recibid[oa]s?|adquirid[oa]s?|compras?)\b", g):
        return "recibida"
    if re.search(r"\b(emitid[oa]s?|ventas?)\b", g):
        return "emitida"
    return ""


def clasificar_desde_excel(valor_tipo_documento: str, valor_grupo: str) -> dict:
    """Devuelve ``naturaleza`` y ``direccion`` normalizadas.

    El tipo documental y la dirección se mantienen separados: una Nota Crédito
    recibida seguirá siendo ``nota_credito`` + ``recibida`` y por ello usará la
    configuración contable propia de Nota Crédito recibida.
    """
    direccion = _direccion_desde_grupo(valor_grupo) or _direccion_desde_grupo(valor_tipo_documento)
    return {
        "naturaleza": _naturaleza_desde_tipo(valor_tipo_documento),
        "direccion": direccion,
    }
