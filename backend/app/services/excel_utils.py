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


def _fila_encabezado_mas_probable_desde_filas(filas_crudas: list) -> int:
    """
    Muchos exportadores contables (confirmado con un archivo real de
    Siigo Pyme: trae el nombre de la empresa en la fila 0, un título en
    la fila 1, un rango de fechas en la fila 2, una fila vacía, y RECIÉN
    en la fila 4 el encabezado real) no ponen el encabezado en la
    primera fila. Se escanean las primeras filas y se elige la que
    tenga más celdas de texto cortas y distintas — una fila de título
    ocupa una sola celda con texto largo; un encabezado real tiene
    muchas celdas con palabras cortas.
    """
    mejor_fila, mejor_puntaje = 0, -1
    for i, fila in enumerate(filas_crudas):
        celdas_texto = [str(v).strip() for v in fila if isinstance(v, str) and str(v).strip()]
        if not celdas_texto:
            continue
        celdas_cortas = [c for c in celdas_texto if 0 < len(c) <= 60]
        puntaje = len(celdas_cortas)
        if puntaje > mejor_puntaje:
            mejor_puntaje = puntaje
            mejor_fila = i
    return mejor_fila


def _detectar_fila_encabezado(contenido: bytes) -> int:
    """
    Encuentra la fila de encabezado real "espiando" solo las primeras
    ~40 filas con openpyxl en modo read_only — NUNCA carga el archivo
    completo en memoria dos veces. Con un archivo real de más de mil
    filas y cien columnas, leerlo completo dos veces (antes: una vez
    con pandas para detectar el encabezado, otra para los datos) casi
    duplicaba el uso de memoria y el tiempo de proceso — suficiente,
    en un servidor con memoria limitada, para agotar los recursos si
    coincide con otra carga pesada en curso.
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    try:
        hoja = wb.active
        filas_crudas = []
        for i, fila in enumerate(hoja.iter_rows(max_row=40, values_only=True)):
            filas_crudas.append(fila)
        return _fila_encabezado_mas_probable_desde_filas(filas_crudas)
    finally:
        wb.close()


def leer_dataframe_excel(contenido: bytes, nombre_archivo: str) -> pd.DataFrame:
    """
    Lee el archivo completo usando la fila de encabezado REAL (nunca
    asume que es la primera fila) — tanto para previsualizar columnas
    como para leer los datos de verdad, de modo que ambos pasos sean
    siempre consistentes entre sí. Solo hace UNA lectura completa del
    archivo con pandas (la detección del encabezado usa openpyxl en
    modo liviano aparte, ver _detectar_fila_encabezado).
    """
    if nombre_archivo.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(contenido), dtype=str, keep_default_na=False)

    fila_encabezado = _detectar_fila_encabezado(contenido)
    return pd.read_excel(io.BytesIO(contenido), header=fila_encabezado, dtype=str,
                          keep_default_na=False, na_filter=False)


def leer_columnas_excel(contenido: bytes, nombre_archivo: str) -> list[str]:
    df = leer_dataframe_excel(contenido, nombre_archivo)
    return list(df.columns)
