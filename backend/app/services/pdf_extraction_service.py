"""
PDF como fuente SECUNDARIA (sección 6): solo se usa cuando no existe
XML para ese documento. Primero se intenta extraer texto directamente
del PDF; si no hay texto útil, se recurre a OCR. Todo resultado de PDF
(con o sin OCR) queda con confianza < 100% y candidato a
"pendiente_revision" (sección 7) — nunca se contabiliza solo.
"""
import io
import re
import unicodedata
from typing import Optional

import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes

# Campos que buscamos por expresión regular en el texto (directo u OCR).
# Cada patrón encontrado suma al porcentaje de confianza.
_PATRONES = {
    "cufe": re.compile(r"CUFE[:\.\s]*([a-fA-F0-9]{60,100})", re.IGNORECASE),
    "numero_factura": re.compile(r"(?:(?:factura|invoice)\s*(?:electr[oó]nica)?\s*)?(?:n[uú]mero|no\.?|#)\s*[:\.\s]+([A-Z]{0,4}\s?-?\s?\d{2,12})", re.IGNORECASE),
    "nit_emisor": re.compile(r"NIT[:\.\s]*([\d\.]{6,15}-?\d?)", re.IGNORECASE),
    "total": re.compile(r"(?:valor\s+total|total\s+a\s+pagar|total\s+factura)[:\.\s]*\$?\s*([\d\.,]{4,18})", re.IGNORECASE),
    "fecha_emision": re.compile(r"(?:fecha\s+de\s+)?(?:emisi[oó]n|expedici[oó]n)[:\.\s]*(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", re.IGNORECASE),
    "iva": re.compile(r"IVA[:\.\s]*\$?\s*([\d\.,]{2,18})", re.IGNORECASE),
}


def _extraer_texto_directo(contenido: bytes) -> str:
    texto = ""
    try:
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            for pagina in pdf.pages:
                t = pagina.extract_text() or ""
                texto += t + "\n"
    except Exception:
        return ""
    return texto.strip()


def _extraer_texto_ocr(contenido: bytes) -> str:
    try:
        imagenes = convert_from_bytes(contenido, dpi=200)
    except Exception:
        return ""
    texto = ""
    for img in imagenes:
        try:
            texto += pytesseract.image_to_string(img, lang="spa+eng") + "\n"
        except Exception:
            continue
    return texto.strip()


def _normalizar_texto(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)).lower()


def _detectar_naturaleza(texto: str) -> str:
    t = _normalizar_texto(texto)
    if "nota credito" in t or "credit note" in t or re.search(r"\b91\s*[-:]?\s*nota", t):
        return "nota_credito"
    if "nota debito" in t or "debit note" in t or re.search(r"\b92\s*[-:]?\s*nota", t):
        return "nota_debito"
    if "documento equivalente" in t or "documento soporte" in t:
        return "documento_equivalente"
    return "factura"


def _buscar_campos(texto: str) -> dict:
    campos = {}
    for campo, patron in _PATRONES.items():
        m = patron.search(texto)
        if m:
            campos[campo] = m.group(1).strip()
    campos["naturaleza_documento"] = _detectar_naturaleza(texto)
    # En notas crédito/débito el encabezado puede decir "Nota Crédito No."
    # en vez de "Factura No.". Recuperar el número sin alterar el parser
    # histórico de facturas que ya funcionaba.
    if not campos.get("numero_factura") and campos["naturaleza_documento"] in {"nota_credito", "nota_debito"}:
        m = re.search(r"nota\s+(?:cr[eé]dito|d[eé]bito)(?:\s+electr[oó]nica)?\s*(?:n[uú]mero|no\.?|#)?\s*[:.\-]?\s*([A-Z]{1,10}[- ]?\d{1,20})", texto, re.IGNORECASE)
        if m:
            campos["numero_factura"] = m.group(1).strip()
    return campos


def extraer_factura_pdf(contenido: bytes) -> dict:
    """
    Devuelve:
      fuente: "pdf_texto" | "pdf_ocr"
      campos: dict de campos reconocidos (solo los que el regex encontró)
      confianza: 0-100, proporcional a cuántos de los campos clave se
                 reconocieron
      texto_bruto: el texto completo extraído (para revisión manual)
    """
    texto = _extraer_texto_directo(contenido)
    fuente = "pdf_texto"
    if len(texto) < 30:  # texto insuficiente -> probablemente escaneado
        texto = _extraer_texto_ocr(contenido)
        fuente = "pdf_ocr"

    campos = _buscar_campos(texto)
    total_patrones = len(_PATRONES)
    encontrados = sum(1 for campo in _PATRONES if campo in campos)
    confianza = round(encontrados * 100.0 / total_patrones, 1) if total_patrones else 0.0

    # El OCR es intrínsecamente menos confiable que el texto embebido del
    # PDF, incluso con los mismos campos reconocidos (sección 7).
    if fuente == "pdf_ocr":
        confianza = round(confianza * 0.8, 1)

    return {
        "fuente": fuente,
        "campos": campos,
        "confianza": confianza,
        "texto_bruto": texto[:5000],  # tope razonable para no inflar la BD
    }
