"""
Plantillas de mapeo de columnas conocidas para importar historial,
verificadas contra archivos REALES de Siigo Pyme (Movimiento Contable,
1223 filas) y World Office (613 filas) que el usuario compartió.

Respondiendo a la observación del usuario: la empresa ya declara qué
sistema contable usa (Empresa.sistema_contable) — en vez de pedirle que
adivine a mano cuál de ~120 columnas corresponde a cada campo, se usa
esa información para proponer el mapeo automáticamente. El usuario
puede revisarlo y ajustarlo antes de importar; nunca se aplica a ciegas.

Los patrones son expresiones regulares deliberadamente ESPECÍFICAS
(no una simple búsqueda de palabra suelta) porque un archivo real de
Siigo trae más de diez columnas que empiezan por "VALOR..." — una
coincidencia genérica elegiría la equivocada.
"""
import re

# (campo_interno, patrón_regex sobre el nombre de columna normalizado)
PATRONES_SIIGO_PYME = [
    ("nit", re.compile(r"^nit$")),
    ("cuenta", re.compile(r"^cuenta contable\b")),
    ("descripcion", re.compile(r"^descripcion de la secuencia\b")),
    ("numero_documento", re.compile(r"^numero de documento$")),
    ("valor", re.compile(r"^valor de la secuencia\b")),
    ("anio", re.compile(r"^ano del documento$")),
    ("mes", re.compile(r"^mes del documento$")),
    ("dia", re.compile(r"^dia del documento$")),
]

PATRONES_WORLD_OFFICE = [
    ("nit", re.compile(r"detalle con:\s*tercero_?externo")),
    ("cuenta", re.compile(r"detalle con:\s*idcuentacontable")),
    ("descripcion", re.compile(r"detalle con:\s*nota")),
    ("valor_debito", re.compile(r"detalle con:\s*d[ée]bito")),
    ("valor_credito", re.compile(r"detalle con:\s*cr[ée]dito")),
    ("fecha", re.compile(r"encab:\s*fecha")),
    ("numero_documento", re.compile(r"encab:\s*documento n[uú]mero")),
]


def _normalizar(texto: str) -> str:
    import unicodedata
    texto = (texto or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def sugerir_mapeo(sistema_contable: str, columnas_reales: list[str]) -> dict:
    """
    Devuelve {"mapeo": {campo: columna_real_o_None, ...}, "reconocidas": [...]}
    Solo incluye campos para los que SÍ encontró una columna que coincide
    con el patrón conocido de ese sistema — nunca inventa una columna
    que no exista en el archivo real.
    """
    patrones = {
        "siigo_pyme": PATRONES_SIIGO_PYME,
        "world_office": PATRONES_WORLD_OFFICE,
    }.get(sistema_contable, [])

    columnas_normalizadas = {_normalizar(c): c for c in columnas_reales}
    mapeo = {}
    for campo, patron in patrones:
        for col_norm, col_real in columnas_normalizadas.items():
            if patron.search(col_norm):
                mapeo[campo] = col_real
                break

    return {"mapeo": mapeo, "reconocidas": list(mapeo.keys())}
