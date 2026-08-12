"""
Clasificación de documentos a partir de las columnas propias de la DIAN
en su Excel de descarga ("Tipo de documento", "Grupo").

Descubierto al revisar un Excel real de la DIAN (151 filas): la DIAN ya
clasifica cada fila con su propio "Tipo de documento" (Factura
electrónica, Application response, Nomina Individual, Documento
equivalente - X) y su propio "Grupo" (Emitido/Recibido). Usar estas
columnas es MÁS confiable que derivar todo del XML o comparar el NIT
del emisor contra el NIT de la empresa — un solo dígito distinto en el
NIT registrado de la empresa (o un NIT sin normalizar) haría fallar esa
comparación, mientras que la DIAN ya resolvió esa ambigüedad por su
cuenta al generar el Excel.

Cuando el Excel trae esta información, tiene prioridad sobre lo que se
haya inferido del XML.
"""

_TIPOS_DESCARTAR = {"application response"}  # no son documentos contables (sección 3 del usuario)

_TIPOS_NATURALEZA = {
    "factura electronica": "factura",
    "factura electrónica": "factura",
    "nomina individual": "nomina",
    "nómina individual": "nomina",
    "nota credito electronica": "nota_credito",
    "nota crédito electrónica": "nota_credito",
    "nota debito electronica": "nota_debito",
    "nota débito electrónica": "nota_debito",
}

_GRUPOS_DIRECCION = {
    "emitido": "emitida",
    "recibido": "recibida",
}


def _normalizar(texto: str) -> str:
    import unicodedata
    texto = (texto or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def es_tipo_descartable(valor_tipo_documento: str) -> bool:
    """True si la fila del Excel es un tipo de documento que no debe generar factura (ej. acuse de recibo)."""
    return _normalizar(valor_tipo_documento) in _TIPOS_DESCARTAR


def clasificar_desde_excel(valor_tipo_documento: str, valor_grupo: str) -> dict:
    """
    Devuelve {"naturaleza": ..., "direccion": ...} a partir de los
    valores tal como vienen en las columnas del Excel de la DIAN.
    "Documento equivalente - <lo que sea>" (tiquetes aéreos, servicios
    públicos, etc.) siempre cae en "documento_equivalente" — se
    contabiliza igual que una factura recibida normal, pero queda
    identificado como un tipo distinto para reportes/filtros.
    Si el tipo no se reconoce, se asume "factura" por defecto (para no
    perder el registro) pero SIN inventar una dirección si tampoco se
    reconoce el grupo.
    """
    tipo_norm = _normalizar(valor_tipo_documento)
    if tipo_norm.startswith("documento equivalente"):
        naturaleza = "documento_equivalente"
    else:
        naturaleza = _TIPOS_NATURALEZA.get(tipo_norm, "factura")

    direccion = _GRUPOS_DIRECCION.get(_normalizar(valor_grupo), "")

    return {"naturaleza": naturaleza, "direccion": direccion}
