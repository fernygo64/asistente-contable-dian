"""
Detección automática de estructura a partir de un archivo plano de
ejemplo ya exportado por el software contable del usuario (sección 20:
"el usuario podrá cargar un archivo de ejemplo proporcionado por su
Siigo Pyme"). En vez de que el usuario escriba a mano el nombre de cada
columna, se detecta el delimitador y los encabezados reales, y se
propone automáticamente a qué campo interno corresponde cada uno según
palabras clave — el usuario solo confirma o ajusta.
"""
import re

_DELIMITADORES_CANDIDATOS = ["|", ";", "\t", ","]

_PALABRAS_CLAVE_ORIGEN = [
    (re.compile(r"fecha", re.IGNORECASE), "fecha"),
    (re.compile(r"cuenta", re.IGNORECASE), "cuenta"),
    (re.compile(r"nit|identificaci[oó]n|documento.*tercero", re.IGNORECASE), "nit"),
    (re.compile(r"tercero|nombre|raz[oó]n", re.IGNORECASE), "tercero"),
    (re.compile(r"d[eé]bito|debe", re.IGNORECASE), "debito"),
    (re.compile(r"cr[eé]dito|haber", re.IGNORECASE), "credito"),
    (re.compile(r"concepto|detalle|descripci[oó]n|glosa", re.IGNORECASE), "concepto"),
    (re.compile(r"factura|documento", re.IGNORECASE), "numero_factura"),
    (re.compile(r"cufe|cude", re.IGNORECASE), "cufe"),
]


def _detectar_delimitador(primera_linea: str) -> str:
    conteos = {d: primera_linea.count(d) for d in _DELIMITADORES_CANDIDATOS}
    mejor = max(conteos, key=conteos.get)
    return mejor if conteos[mejor] > 0 else "|"


def _sugerir_origen(nombre_columna: str) -> str:
    for patron, origen in _PALABRAS_CLAVE_ORIGEN:
        if patron.search(nombre_columna):
            return origen
    return "fijo"


def detectar_estructura_archivo_plano(contenido: bytes) -> dict:
    """
    Devuelve {"delimitador": ..., "columnas": [{"label":..., "source":...}]}
    a partir de la primera línea (encabezado) del archivo de ejemplo.
    Si el archivo no trae encabezado real (algunos sistemas exportan solo
    datos), igual se detecta el delimitador y se numeran las columnas
    genéricamente, dejando "source" en "fijo" para que el usuario las
    ajuste — nunca se inventa a qué campo corresponde cada una.
    """
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
