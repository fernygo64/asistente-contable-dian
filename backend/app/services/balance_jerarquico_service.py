"""
Balance de Prueba por Terceros — formatos jerárquicos de Siigo.

Siigo Pyme/Siigo puede presentar el código repartido en hasta cinco columnas
jerárquicas (grupo/cuenta/subcuenta/auxiliar/subauxiliar). En archivos reales
cada tramo suele ser de dos dígitos. Las filas con NIT heredan la cuenta más
profunda vigente y la columna DESCRIPCIÓN sirve tanto para el nombre de la
cuenta (filas jerárquicas) como para el nombre del tercero (filas con NIT).
"""
import re
import pandas as pd


def _es_hoja_valida(nombre_col: str, palabras: list[str]) -> bool:
    n = (nombre_col or "").strip().upper()
    return any(p in n for p in palabras)


def _segmento(v, primer_nivel: bool = False) -> str:
    """Normaliza un tramo jerárquico. La clase raíz (1-9) conserva un dígito; los demás tramos usan dos."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    txt = str(v).strip()
    if not txt or txt.lower() == "nan":
        return ""
    # Excel/pandas puede entregar 5.0 aun cuando visualmente la celda sea 05.
    try:
        n = int(float(txt.replace(",", ".")))
        if 0 <= n <= 99:
            if primer_nivel and n < 10:
                return str(n)
            return str(n).zfill(2)
    except (ValueError, TypeError):
        pass
    digitos = re.sub(r"\D", "", txt)
    if not digitos:
        return ""
    if primer_nivel and len(digitos) == 1:
        return digitos
    return digitos.zfill(2) if len(digitos) <= 2 else digitos


def detectar_columnas_balance_terceros(columnas_reales: list[str]) -> dict | None:
    def buscar(palabras):
        for c in columnas_reales:
            if _es_hoja_valida(c, palabras):
                return c
        return None

    grupo = buscar(["GRUPO"])
    cuenta_candidata = buscar(["CUENTA"])
    cuenta = cuenta_candidata if cuenta_candidata != grupo else None
    subcuenta = buscar(["SUBCUENT"])
    auxiliar = next((c for c in columnas_reales if c.strip().upper().startswith("AUXILIAR")), None)
    subauxiliar = buscar(["SUBAUXIL"])
    nit = buscar(["NIT", "IDENTIFICACION", "IDENTIFICACIÓN"])
    descripcion = buscar(["DESCRIPCION", "DESCRIPCIÓN"])
    saldo = next((c for c in columnas_reales if "NUEVO SALDO" in c.strip().upper()), None)
    if not saldo:
        saldo = next((c for c in columnas_reales if c.strip().upper().startswith("SALDO")), None)

    # Formato real esperado: al menos nivel principal + NIT + descripción.
    if not grupo or not nit or not descripcion:
        return None
    return {
        "grupo": grupo, "cuenta": cuenta, "subcuenta": subcuenta,
        "auxiliar": auxiliar, "subauxiliar": subauxiliar,
        "nit": nit, "descripcion": descripcion, "saldo": saldo,
    }


def _recorrer(df: pd.DataFrame, columnas: dict):
    niveles_cols = [columnas["grupo"], columnas["cuenta"], columnas["subcuenta"], columnas["auxiliar"], columnas["subauxiliar"]]
    niveles_actuales = [None] * 5
    nombres_por_codigo: dict[str, str] = {}
    catalogo: dict[str, str] = {}
    detalles = []

    for _, fila in df.iterrows():
        valores_nivel = [_segmento(fila.get(c), primer_nivel=(i == 0)) if c else "" for i, c in enumerate(niveles_cols)]
        nit_raw = fila.get(columnas["nit"])
        nit = str(nit_raw).strip() if pd.notna(nit_raw) and str(nit_raw).strip().lower() != "nan" else ""
        desc_raw = fila.get(columnas["descripcion"])
        desc = str(desc_raw).strip() if pd.notna(desc_raw) else ""

        if any(valores_nivel):
            for i, val in enumerate(valores_nivel):
                if val:
                    niveles_actuales[i] = val
                    for j in range(i + 1, 5):
                        niveles_actuales[j] = None
            codigo = "".join(n for n in niveles_actuales if n)
            if codigo:
                if desc:
                    nombres_por_codigo[codigo] = desc
                    catalogo[codigo] = desc
            continue

        if nit:
            codigo = "".join(n for n in niveles_actuales if n)
            if not codigo:
                continue
            valor = None
            if columnas.get("saldo"):
                v = fila.get(columnas["saldo"])
                try:
                    valor = float(str(v).replace(",", ""))
                except (ValueError, TypeError):
                    valor = None
            detalles.append({
                "nit": nit, "nombre_tercero": desc, "cuenta_codigo": codigo,
                "nombre_cuenta": nombres_por_codigo.get(codigo, ""), "valor": valor,
            })
    return detalles, [{"codigo": c, "nombre": n} for c, n in catalogo.items()]


def parsear_balance_terceros_jerarquico(df: pd.DataFrame, columnas: dict) -> list[dict]:
    return _recorrer(df, columnas)[0]


def extraer_catalogo_cuentas_jerarquico(df: pd.DataFrame, columnas: dict) -> list[dict]:
    """Devuelve todas las cuentas/nombres visibles en las filas jerárquicas, incluso sin NIT."""
    return _recorrer(df, columnas)[1]
