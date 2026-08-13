"""
Detección automática de estructura a partir de un archivo plano de
ejemplo ya exportado por el software contable del usuario (sección 20:
"el usuario podrá cargar un archivo de ejemplo proporcionado por su
Siigo Pyme"). En vez de que el usuario escriba a mano el nombre de cada
columna, se detecta el delimitador y los encabezados reales, y se
propone automáticamente a qué campo interno corresponde cada uno según
palabras clave — el usuario solo confirma o ajusta.

Confirmado con archivos reales: tanto el de Siigo Pyme (Movimiento
Contable) como el de World Office pueden venir como .xlsx en vez de
texto delimitado, y el de Siigo trae varias filas de título/instrucciones
ANTES del encabezado real — por eso se escanean varias filas en vez de
asumir que la primera siempre es el encabezado.
"""
import io
import re

import pandas as pd

_DELIMITADORES_CANDIDATOS = ["|", ";", "\t", ","]

_PALABRAS_CLAVE_ORIGEN = [
    (re.compile(r"a[ñn]o", re.IGNORECASE), "anio"),
    (re.compile(r"\bmes\b", re.IGNORECASE), "mes"),
    (re.compile(r"\bd[ií]a\b", re.IGNORECASE), "dia"),
    (re.compile(r"d[eé]bito.*cr[eé]dito|cr[eé]dito.*d[eé]bito", re.IGNORECASE), "debito_credito"),
    (re.compile(r"fecha", re.IGNORECASE), "fecha"),
    (re.compile(r"cuenta", re.IGNORECASE), "cuenta"),
    (re.compile(r"nit|identificaci[oó]n|documento.*tercero", re.IGNORECASE), "nit"),
    (re.compile(r"tercero|nombre|raz[oó]n", re.IGNORECASE), "tercero"),
    (re.compile(r"d[eé]bito|debe", re.IGNORECASE), "debito"),
    (re.compile(r"cr[eé]dito|haber", re.IGNORECASE), "credito"),
    (re.compile(r"valor", re.IGNORECASE), "valor"),
    (re.compile(r"concepto|detalle|descripci[oó]n|glosa|nota", re.IGNORECASE), "concepto"),
    (re.compile(r"factura|n[uú]mero.*documento|documento.*n[uú]mero", re.IGNORECASE), "numero_factura"),
    (re.compile(r"cufe|cude", re.IGNORECASE), "cufe"),
]


def _es_xlsx(contenido: bytes) -> bool:
    return contenido[:2] == b"PK"  # los .xlsx son en realidad archivos ZIP


def _detectar_delimitador(primera_linea: str) -> str:
    conteos = {d: primera_linea.count(d) for d in _DELIMITADORES_CANDIDATOS}
    mejor = max(conteos, key=conteos.get)
    return mejor if conteos[mejor] > 0 else "|"


def _sugerir_origen(nombre_columna: str) -> str:
    for patron, origen in _PALABRAS_CLAVE_ORIGEN:
        if patron.search(nombre_columna):
            return origen
    return "fijo"


def _fila_encabezado_mas_probable(df_crudo: pd.DataFrame) -> int:
    """
    Algunos archivos de ejemplo (confirmado con el de Siigo Pyme) traen
    varias filas de título/instrucciones antes del encabezado real. Se
    escanean las primeras filas y se elige la que tenga más celdas de
    texto distintas y cortas — un título ocupa una sola celda con texto
    largo; un encabezado real tiene muchas celdas con palabras cortas.
    """
    mejor_fila, mejor_puntaje = 0, -1
    limite = min(15, len(df_crudo))
    for i in range(limite):
        fila = df_crudo.iloc[i]
        celdas_texto = [str(v).strip() for v in fila if isinstance(v, str) and str(v).strip()]
        if not celdas_texto:
            continue
        celdas_cortas = [c for c in celdas_texto if 0 < len(c) <= 60]
        puntaje = len(celdas_cortas)
        if puntaje > mejor_puntaje:
            mejor_puntaje = puntaje
            mejor_fila = i
    return mejor_fila


def _detectar_desde_excel(contenido: bytes) -> dict:
    df_crudo = pd.read_excel(io.BytesIO(contenido), header=None, dtype=str)
    fila_encabezado = _fila_encabezado_mas_probable(df_crudo)
    encabezados = df_crudo.iloc[fila_encabezado].tolist()

    columnas = []
    for i, valor in enumerate(encabezados):
        label = str(valor).strip() if valor is not None and str(valor).strip() and str(valor) != "nan" else f"Columna {i + 1}"
        columnas.append({"label": label, "source": _sugerir_origen(label)})
    return {"delimitador": "|", "columnas": columnas}


def detectar_estructura_archivo_plano(contenido: bytes) -> dict:
    """
    Devuelve {"delimitador": ..., "columnas": [{"label":..., "source":...}]}
    a partir del archivo de ejemplo — soporta tanto texto delimitado
    (.txt/.csv) como Excel (.xlsx/.xls), detectando automáticamente cuál
    de los dos es. Si el archivo no trae encabezado real (algunos
    sistemas exportan solo datos), igual se detecta el delimitador y se
    numeran las columnas genéricamente, dejando "source" en "fijo" para
    que el usuario las ajuste — nunca se inventa a qué campo corresponde
    cada una.
    """
    if _es_xlsx(contenido):
        return _detectar_desde_excel(contenido)

    texto = contenido.decode("utf-8", errors="replace")
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        return {"delimitador": "|", "columnas": []}

    primera_linea = lineas[0]
    delimitador = _detectar_delimitador(primera_linea)
    partes = [p.strip() for p in primera_linea.split(delimitador)]

    columnas = []
    for i, parte in enumerate(partes):
        label = parte if parte else f"Columna {i + 1}"
        columnas.append({"label": label, "source": _sugerir_origen(label)})

    return {"delimitador": delimitador, "columnas": columnas}
