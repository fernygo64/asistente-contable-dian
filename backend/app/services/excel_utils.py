"""
Resolución tolerante de nombres de columna.

El usuario no debería tener que escribir el nombre de una columna
letra por letra e igual de mayúsculas/minúsculas que el archivo — eso
es frágil y genera errores como 'FOLIO' vs 'Folio'. Esta utilidad
compara ignorando mayúsculas/minúsculas y espacios sobrantes, y
devuelve el nombre REAL de la columna tal como aparece en el archivo
(para que las lecturas posteriores usen el nombre correcto).
"""
import io
import unicodedata
import pandas as pd


def _normalizar(texto: str) -> str:
    texto = texto.strip().lower()
    # quita tildes para que "Emisión" y "Emision" también se reconozcan como la misma columna
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return texto


def resolver_columna(valor_mapeado: str, columnas_reales: list[str]) -> str | None:
    """Devuelve el nombre real de la columna que coincide (sin importar
    mayúsculas/minúsculas, espacios o tildes), o None si no hay ninguna igual."""
    if not valor_mapeado:
        return None
    objetivo = _normalizar(valor_mapeado)
    for col in columnas_reales:
        if _normalizar(col) == objetivo:
            return col
    return None


def leer_columnas_excel(contenido: bytes, nombre_archivo: str) -> list[str]:
    if nombre_archivo.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(contenido), dtype=str, keep_default_na=False, nrows=0)
    else:
        df = pd.read_excel(io.BytesIO(contenido), dtype=str, keep_default_na=False, na_filter=False, nrows=0)
    return list(df.columns)
