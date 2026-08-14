"""
Balance de Prueba por Terceros — formato real de Siigo NUBE (distinto
del "Movimiento Contable" de Siigo Pyme, y distinto del balance plano
genérico que ya soporta balance_service.py).

Confirmado contra un archivo real de 974 filas: el código de cuenta NO
viene en una sola columna — se arma progresivamente en 5 columnas
jerárquicas (GRUPO, CUENTA, SUBCUENTA, AUXILIAR, SUBAUXILIAR). Cada fila
de "total de cuenta" solo llena el/los niveles que le corresponden;
las filas de DETALLE POR TERCERO (con NIT) no repiten ningún nivel —
heredan el código más profundo que esté vigente en ese momento del
recorrido de arriba hacia abajo. La columna DESCRIPCION significa cosas
distintas según el tipo de fila: nombre de la CUENTA en una fila de
total, pero nombre del TERCERO en una fila de detalle con NIT.

Ejemplo real verificado:
  GRUPO=13                                    -> código "13"    DEUDORES
  GRUPO=13 CUENTA=05                          -> código "1305"  CLIENTES
  GRUPO=13 CUENTA=05 SUBCUENTA=06              -> código "130506" CLIENTES
  NIT=31398514 (sin GRUPO/CUENTA/SUBCUENTA)   -> hereda "130506", tercero
                                                  "HERNANDEZ OSPINA ESPERANZA"
"""
import pandas as pd


def _es_hoja_valida(nombre_col: str, palabras: list[str]) -> bool:
    n = (nombre_col or "").strip().upper()
    return any(p in n for p in palabras)


def detectar_columnas_balance_terceros(columnas_reales: list[str]) -> dict | None:
    """
    Reconoce las columnas típicas de este formato (GRUPO/CUENTA/
    SUBCUENTA o similar). Devuelve None si el archivo no tiene esta
    forma — quien llama debe entonces probar el detector de balance
    plano genérico en su lugar, nunca forzar este parser sobre un
    archivo que no le corresponde.
    """
    def buscar(palabras):
        for c in columnas_reales:
            if _es_hoja_valida(c, palabras):
                return c
        return None

    grupo = buscar(["GRUPO"])
    cuenta_candidata = buscar(["CUENTA"])
    cuenta = cuenta_candidata if cuenta_candidata != grupo else None
    subcuenta = buscar(["SUBCUENT"])
    auxiliar = None
    for c in columnas_reales:
        cu = c.strip().upper()
        if cu.startswith("AUXILIAR"):
            auxiliar = c
            break
    subauxiliar = buscar(["SUBAUXIL"])
    nit = buscar(["NIT"])
    descripcion = buscar(["DESCRIPCION", "DESCRIPCIÓN"])
    saldo = None
    for c in columnas_reales:
        if "NUEVO SALDO" in c.strip().upper():
            saldo = c
            break
    if not saldo:
        for c in columnas_reales:
            if c.strip().upper().startswith("SALDO"):
                saldo = c
                break

    if not grupo or not nit or not descripcion:
        return None

    return {
        "grupo": grupo, "cuenta": cuenta, "subcuenta": subcuenta,
        "auxiliar": auxiliar, "subauxiliar": subauxiliar,
        "nit": nit, "descripcion": descripcion, "saldo": saldo,
    }


def parsear_balance_terceros_jerarquico(df: pd.DataFrame, columnas: dict) -> list[dict]:
    """
    Devuelve una lista de {"nit", "nombre_tercero", "cuenta_codigo",
    "nombre_cuenta", "valor"} — una por cada línea de detalle con
    tercero real, con el código de cuenta ya reconstruido.
    """
    niveles_cols = [columnas["grupo"], columnas["cuenta"], columnas["subcuenta"],
                     columnas["auxiliar"], columnas["subauxiliar"]]
    niveles_actuales = [None, None, None, None, None]
    nombres_por_codigo: dict[str, str] = {}
    registros = []

    for _, fila in df.iterrows():
        valores_nivel = []
        for col in niveles_cols:
            if col is None:
                valores_nivel.append("")
                continue
            v = fila.get(col)
            valores_nivel.append(str(v).strip() if pd.notna(v) and str(v).strip().lower() != "nan" else "")

        nit_val = fila.get(columnas["nit"])
        nit = str(nit_val).strip() if pd.notna(nit_val) and str(nit_val).strip().lower() != "nan" else ""
        desc_val = fila.get(columnas["descripcion"])
        desc = str(desc_val).strip() if pd.notna(desc_val) else ""

        if any(valores_nivel):
            for i, val in enumerate(valores_nivel):
                if val:
                    niveles_actuales[i] = val
                    for j in range(i + 1, 5):
                        niveles_actuales[j] = None
            codigo = "".join(n for n in niveles_actuales if n)
            if codigo:
                nombres_por_codigo[codigo] = desc
            continue  # fila de total de cuenta, no de detalle por tercero

        if nit:
            codigo = "".join(n for n in niveles_actuales if n)
            if not codigo:
                continue  # NIT sin ninguna cuenta vigente todavía -> se ignora, no se inventa
            valor = None
            if columnas["saldo"]:
                v = fila.get(columnas["saldo"])
                try:
                    valor = float(v)
                except (ValueError, TypeError):
                    valor = None
            registros.append({
                "nit": nit, "nombre_tercero": desc, "cuenta_codigo": codigo,
                "nombre_cuenta": nombres_por_codigo.get(codigo, ""), "valor": valor,
            })

    return registros
