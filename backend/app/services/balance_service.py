"""
Importación de un balance de prueba por tercero SIN pedirle al usuario
que mapee columnas — a diferencia del auxiliar/movimiento contable
(que trae decenas de columnas ambiguas y necesita revisión manual), un
balance por tercero tiene una forma mucho más simple y predecible: NIT,
cuenta (código), nombre de la cuenta y, a veces, nombre del tercero y
un saldo. Se detectan por palabras clave y se importa directo — el
usuario solo sube el archivo (sección pedida explícitamente: "no se
debe hacer nada sino únicamente subir el excel").

Si no logra identificar con confianza NIT y Cuenta, se rechaza con un
mensaje claro en vez de adivinar — nunca se importa con una columna
equivocada.
"""
import re

from app.services.excel_utils import _normalizar

_PATRON_NIT = re.compile(r"\bnit\b|identificacion|c[ée]dula")
_PATRON_CUENTA_CODIGO = re.compile(r"\bcuenta\b|c[oó]digo\s*cuenta|cuenta\s*cont[aá]ble")
_PATRON_NOMBRE_CUENTA = re.compile(r"nombre\s*cuenta|cuenta\s*nombre|descripci[oó]n\s*cuenta|nombre\s*de\s*la\s*cuenta")
_PATRON_NOMBRE_TERCERO = re.compile(r"raz[oó]n\s*social|nombre\s*tercero|tercero\s*nombre")
_PATRON_SALDO = re.compile(r"saldo|valor")


def _coincide(col_normalizada: str, patron: re.Pattern) -> bool:
    return bool(patron.search(col_normalizada))


def detectar_mapeo_balance(columnas_reales: list[str]) -> dict:
    """
    Devuelve {"mapeo": {...}, "faltantes": [...]} — faltantes solo
    incluye 'nit' y/o 'cuenta' si no se pudieron identificar con
    confianza (son las dos únicas obligatorias).
    """
    normalizadas = [(c, _normalizar(c)) for c in columnas_reales]

    def buscar(patron, excluir_patrones=()):
        candidatos = [
            c for c, n in normalizadas
            if _coincide(n, patron) and not any(_coincide(n, ex) for ex in excluir_patrones)
        ]
        return candidatos[0] if len(candidatos) == 1 else None

    # El nombre de cuenta se busca ANTES que la cuenta-código, para
    # poder excluir esa misma columna de la búsqueda de "cuenta".
    nombre_cuenta = buscar(_PATRON_NOMBRE_CUENTA)
    cuenta = buscar(_PATRON_CUENTA_CODIGO, excluir_patrones=(_PATRON_NOMBRE_CUENTA,))
    nit = buscar(_PATRON_NIT)
    nombre_tercero = buscar(_PATRON_NOMBRE_TERCERO)
    saldo = buscar(_PATRON_SALDO)

    mapeo = {}
    if nit:
        mapeo["nit"] = nit
    if cuenta:
        mapeo["cuenta"] = cuenta
    if nombre_cuenta:
        mapeo["nombre_cuenta"] = nombre_cuenta
    if nombre_tercero:
        mapeo["nombre"] = nombre_tercero
    if saldo:
        mapeo["valor"] = saldo

    faltantes = [campo for campo in ("nit", "cuenta") if campo not in mapeo]
    return {"mapeo": mapeo, "faltantes": faltantes}
