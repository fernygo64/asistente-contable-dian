"""Aprendizaje técnico automático de Siigo Pyme a partir del historial real.

La empresa NO parametriza cuenta por cuenta. Al importar un Movimiento
Contable de SIIGO se conservan, fila por fila, los campos técnicos que el
propio archivo demuestra que SIIGO exige. Al exportar movimientos nuevos se
busca la evidencia histórica más específica por cuenta + NIT + tipo/código.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Iterable, Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import HistorialTecnicoSiigo
from app.services.excel_utils import resolver_columna


_CAMPOS_COLUMNAS = {
    "tipo_comprobante": ["TIPO DE COMPROBANTE (OBLIGATORIO)", "TIPO DE COMPROBANTE"],
    "codigo_comprobante": ["CÓDIGO COMPROBANTE  (OBLIGATORIO)", "CÓDIGO COMPROBANTE (OBLIGATORIO)", "CODIGO COMPROBANTE"],
    "numero_documento": ["NÚMERO DE DOCUMENTO", "NUMERO DE DOCUMENTO"],
    "cuenta_codigo": ["CUENTA CONTABLE   (OBLIGATORIO)", "CUENTA CONTABLE (OBLIGATORIO)", "CUENTA CONTABLE"],
    "codigo_vendedor": ["CÓDIGO DEL VENDEDOR", "CODIGO DEL VENDEDOR"],
    "codigo_ciudad": ["CÓDIGO DE LA CIUDAD", "CODIGO DE LA CIUDAD"],
    "codigo_zona": ["CÓDIGO DE LA ZONA", "CODIGO DE LA ZONA"],
    "centro_costo": ["CENTRO DE COSTO"],
    "subcentro_costo": ["SUBCENTRO DE COSTO"],
    "nit": ["NIT"],
    "sucursal": ["SUCURSAL"],
    "anio": ["AÑO DEL DOCUMENTO", "ANO DEL DOCUMENTO"],
    "mes": ["MES DEL DOCUMENTO"],
    "dia": ["DÍA DEL DOCUMENTO", "DIA DEL DOCUMENTO"],
}


def _resolver_primera(columnas: list[str], candidatos: list[str]) -> Optional[str]:
    for candidato in candidatos:
        encontrada = resolver_columna(candidato, columnas)
        if encontrada:
            return encontrada
    return None


def detectar_columnas_tecnicas_siigo(columnas: list[str]) -> dict[str, str]:
    resultado = {}
    for campo, candidatos in _CAMPOS_COLUMNAS.items():
        col = _resolver_primera(columnas, candidatos)
        if col:
            resultado[campo] = col
    # Para considerarlo Movimiento Contable SIIGO exigimos la columna de
    # cuenta, NIT y evidencia de la estructura técnica, no solo un balance.
    tecnicos = {"tipo_comprobante", "codigo_comprobante", "codigo_vendedor", "codigo_ciudad", "codigo_zona", "centro_costo", "subcentro_costo", "sucursal"}
    if "cuenta_codigo" not in resultado or "nit" not in resultado or len(tecnicos.intersection(resultado)) < 2:
        return {}
    return resultado


def _texto(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor)
    if texto.lower() == "nan":
        return ""
    texto = texto.strip()
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    return texto


def _fecha_desde_fila(row, columnas: dict[str, str]) -> Optional[datetime]:
    try:
        if all(k in columnas for k in ("anio", "mes", "dia")):
            a = int(float(_texto(row.get(columnas["anio"]))))
            m = int(float(_texto(row.get(columnas["mes"]))))
            d = int(float(_texto(row.get(columnas["dia"]))))
            return datetime(a, m, d)
    except Exception:
        return None
    return None


def guardar_historial_tecnico_siigo(db: Session, empresa_id: str, importacion_id: str,
                                      df: pd.DataFrame) -> int:
    """Guarda TODAS las filas técnicas, incluso cuentas excluidas del aprendizaje
    contable (caja, bancos, IVA, proveedores). Justamente esas filas son las que
    permiten aprender cómo debe salir cada cuenta en SIIGO.
    """
    columnas = detectar_columnas_tecnicas_siigo(list(df.columns))
    if not columnas:
        return 0

    cantidad = 0
    for i, row in df.iterrows():
        cuenta = _texto(row.get(columnas["cuenta_codigo"]))
        if not cuenta:
            continue
        kwargs = {
            "empresa_id": empresa_id,
            "importacion_id": importacion_id,
            "cuenta_codigo": cuenta,
            "nit": _texto(row.get(columnas["nit"])) or None,
            "tipo_comprobante": _texto(row.get(columnas.get("tipo_comprobante"))) if columnas.get("tipo_comprobante") else None,
            "codigo_comprobante": _texto(row.get(columnas.get("codigo_comprobante"))) if columnas.get("codigo_comprobante") else None,
            "numero_documento": _texto(row.get(columnas.get("numero_documento"))) if columnas.get("numero_documento") else None,
            "codigo_vendedor": _texto(row.get(columnas.get("codigo_vendedor"))) if columnas.get("codigo_vendedor") else None,
            "codigo_ciudad": _texto(row.get(columnas.get("codigo_ciudad"))) if columnas.get("codigo_ciudad") else None,
            "codigo_zona": _texto(row.get(columnas.get("codigo_zona"))) if columnas.get("codigo_zona") else None,
            "centro_costo": _texto(row.get(columnas.get("centro_costo"))) if columnas.get("centro_costo") else None,
            "subcentro_costo": _texto(row.get(columnas.get("subcentro_costo"))) if columnas.get("subcentro_costo") else None,
            "sucursal": _texto(row.get(columnas.get("sucursal"))) if columnas.get("sucursal") else None,
            "fecha_documento": _fecha_desde_fila(row, columnas),
            "fila_origen": int(i) + 2,
        }
        db.add(HistorialTecnicoSiigo(**kwargs))
        cantidad += 1
    return cantidad


def _normalizar_nit(valor: Optional[str]) -> str:
    texto = _texto(valor)
    if not texto:
        return ""
    # Conserva solo dígitos para tolerar puntos/espacios/guiones de formato.
    return re.sub(r"\D", "", texto)


def _normalizar_cuenta(valor: Optional[str]) -> str:
    return _texto(valor)


def _zero_like(valor: Optional[str]) -> bool:
    return _texto(valor) in ("", "0", "00", "000", "0000")


def _modo(rows: Iterable[HistorialTecnicoSiigo], campo: str) -> Optional[str]:
    valores = [_texto(getattr(r, campo, None)) for r in rows]
    valores = [v for v in valores if v != ""]
    if not valores:
        return None
    conteo = Counter(valores)
    maximo = max(conteo.values())
    empatados = {v for v, n in conteo.items() if n == maximo}
    # Si hay empate, prevalece la observación más reciente dentro del grupo.
    # Se compara por timestamp para funcionar igual con datetimes naive (SQLite)
    # y aware (PostgreSQL/Neon).
    def momento(x):
        for v in (x.fecha_documento, x.creado_en):
            if v is not None:
                try:
                    return float(v.timestamp())
                except Exception:
                    pass
        return 0.0
    for r in sorted(rows, key=momento, reverse=True):
        valor = _texto(getattr(r, campo, None))
        if valor in empatados:
            return valor
    return valores[0]


@dataclass
class ParametrosSiigoInferidos:
    maneja_tercero: bool = True
    nit_tecnico_exportacion: Optional[str] = None
    codigo_vendedor: Optional[str] = None
    codigo_ciudad: Optional[str] = None
    codigo_zona: Optional[str] = None
    centro_costo: Optional[str] = None
    subcentro_costo: Optional[str] = None
    sucursal: Optional[str] = None
    fuente: str = "sin_historial"
    coincidencias: int = 0


class IndiceHistorialSiigo:
    def __init__(self, filas: list[HistorialTecnicoSiigo]):
        self.filas = filas
        self.por_cuenta = defaultdict(list)
        self.por_cuenta_nit = defaultdict(list)
        self.por_cuenta_comp = defaultdict(list)
        self.por_cuenta_nit_comp = defaultdict(list)
        self.por_nit = defaultdict(list)
        self.por_nit_comp = defaultdict(list)
        for r in filas:
            c = _normalizar_cuenta(r.cuenta_codigo)
            n = _normalizar_nit(r.nit)
            t = _texto(r.tipo_comprobante)
            k = _texto(r.codigo_comprobante)
            self.por_cuenta[c].append(r)
            self.por_cuenta_nit[(c, n)].append(r)
            self.por_cuenta_comp[(c, t, k)].append(r)
            self.por_cuenta_nit_comp[(c, n, t, k)].append(r)
            if n:
                self.por_nit[n].append(r)
                self.por_nit_comp[(n, t, k)].append(r)


def construir_indice_historial_siigo(db: Session, empresa_id: str) -> IndiceHistorialSiigo:
    filas = db.query(HistorialTecnicoSiigo).filter(
        HistorialTecnicoSiigo.empresa_id == empresa_id
    ).order_by(HistorialTecnicoSiigo.creado_en.asc()).all()
    return IndiceHistorialSiigo(filas)


def _candidatos(indice: IndiceHistorialSiigo, cuenta: str, nit: str, tipo: str, codigo: str):
    grupos = [
        ("cuenta+nit+comprobante", indice.por_cuenta_nit_comp.get((cuenta, nit, tipo, codigo), [])),
        ("cuenta+nit", indice.por_cuenta_nit.get((cuenta, nit), [])),
        ("cuenta+comprobante", indice.por_cuenta_comp.get((cuenta, tipo, codigo), [])),
        ("nit+comprobante", indice.por_nit_comp.get((nit, tipo, codigo), [])),
        ("cuenta", indice.por_cuenta.get(cuenta, [])),
        ("nit", indice.por_nit.get(nit, [])),
    ]
    return [(nombre, filas) for nombre, filas in grupos if filas]


def _inferir_campo(grupos, campo: str) -> tuple[Optional[str], Optional[str], int]:
    for nombre, filas in grupos:
        valor = _modo(filas, campo)
        if valor not in (None, ""):
            return valor, nombre, len(filas)
    return None, None, 0


def inferir_parametros_movimiento(indice: IndiceHistorialSiigo, cuenta_codigo: str,
                                   nit_actual: Optional[str], tipo_comprobante: Optional[str],
                                   codigo_comprobante: Optional[str]) -> ParametrosSiigoInferidos:
    cuenta = _normalizar_cuenta(cuenta_codigo)
    nit = _normalizar_nit(nit_actual)
    tipo = _texto(tipo_comprobante)
    codigo = _texto(codigo_comprobante)
    grupos = _candidatos(indice, cuenta, nit, tipo, codigo)

    resultado = ParametrosSiigoInferidos()
    if not grupos:
        return resultado

    # Manejo de tercero se aprende por CUENTA + comprobante, no copiando el
    # NIT viejo: si históricamente esa cuenta sale en SIIGO con 0, la nueva
    # fila debe volver a salir con 0 aunque el proveedor actual sea otro.
    filas_cuenta_tipo = indice.por_cuenta_comp.get((cuenta, tipo, codigo), []) or indice.por_cuenta.get(cuenta, [])
    if filas_cuenta_tipo:
        nits = [_texto(r.nit) for r in filas_cuenta_tipo]
        ceros = sum(1 for x in nits if _zero_like(x))
        reales = len(nits) - ceros
        if ceros > reales:
            resultado.maneja_tercero = False
            resultado.nit_tecnico_exportacion = _modo([r for r in filas_cuenta_tipo if _zero_like(r.nit)], "nit") or "0"
        else:
            resultado.maneja_tercero = True

    fuentes = []
    max_coincidencias = 0
    for atributo in ("codigo_vendedor", "codigo_ciudad", "codigo_zona", "centro_costo", "subcentro_costo", "sucursal"):
        valor, fuente, coincidencias = _inferir_campo(grupos, atributo)
        setattr(resultado, atributo, valor)
        if fuente:
            fuentes.append(fuente)
            max_coincidencias = max(max_coincidencias, coincidencias)

    resultado.fuente = ",".join(dict.fromkeys(fuentes)) if fuentes else "cuenta"
    resultado.coincidencias = max_coincidencias or len(filas_cuenta_tipo)
    return resultado
