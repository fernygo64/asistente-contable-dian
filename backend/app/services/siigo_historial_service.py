"""Aprendizaje técnico automático de Siigo Pyme a partir del historial real.

El historial de Movimiento Contable de SIIGO funciona como el manual técnico
real de cada empresa. Al importarlo se conserva la huella completa de las 123
columnas de cada fila, además de los campos de búsqueda principales
(tipo/código de comprobante + cuenta + NIT).

Al exportar movimientos nuevos no se parametriza cuenta por cuenta a mano:
se busca evidencia histórica compatible y solo se reutilizan valores técnicos
cuando son estables. Para campos relacionales (por ejemplo número de documento
cruce) se aprende la relación, no se copia literalmente el número viejo.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
import unicodedata
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
    "debito_credito": ["DÉBITO O CRÉDITO (OBLIGATORIO)", "DEBITO O CREDITO (OBLIGATORIO)"],
    "codigo_vendedor": ["CÓDIGO DEL VENDEDOR", "CODIGO DEL VENDEDOR"],
    "codigo_ciudad": ["CÓDIGO DE LA CIUDAD", "CODIGO DE LA CIUDAD"],
    "codigo_zona": ["CÓDIGO DE LA ZONA", "CODIGO DE LA ZONA"],
    "centro_costo": ["CENTRO DE COSTO"],
    "subcentro_costo": ["SUBCENTRO DE COSTO"],
    "nit": ["NIT"],
    "sucursal": ["SUCURSAL"],
    "descripcion": ["DESCRIPCIÓN DE LA SECUENCIA", "DESCRIPCION DE LA SECUENCIA"],
    "anio": ["AÑO DEL DOCUMENTO", "ANO DEL DOCUMENTO"],
    "mes": ["MES DEL DOCUMENTO"],
    "dia": ["DÍA DEL DOCUMENTO", "DIA DEL DOCUMENTO"],
}

# Columnas cuya información pertenece al movimiento NUEVO y no se debe copiar
# literalmente de un comprobante histórico.
_DINAMICAS_BASE = {
    "TIPO DE COMPROBANTE (OBLIGATORIO)",
    "CÓDIGO COMPROBANTE (OBLIGATORIO)",
    "NÚMERO DE DOCUMENTO",
    "CUENTA CONTABLE (OBLIGATORIO)",
    "DÉBITO O CRÉDITO (OBLIGATORIO)",
    "VALOR DE LA SECUENCIA (OBLIGATORIO)",
    "AÑO DEL DOCUMENTO", "MES DEL DOCUMENTO", "DÍA DEL DOCUMENTO",
    "SECUENCIA", "NIT", "DESCRIPCIÓN DE LA SECUENCIA",
    "FECHA ACTUALIZACIÓN DEL DOCUMENTO", "HORA DE ACTUALIZACIÓN DEL DOCUMENTO",
}

# Campos técnicos donde una constante histórica por cuenta/comprobante sí es
# evidencia útil. Incluye explícitamente producto/bodega, que SIIGO exige para
# determinadas cuentas (confirmado con el historial real SATSANGA).
_APRENDIBLES_ESTATICOS = {
    "CÓDIGO DEL VENDEDOR", "CÓDIGO DE LA CIUDAD", "CÓDIGO DE LA ZONA",
    "CENTRO DE COSTO", "SUBCENTRO DE COSTO", "SUCURSAL",
    "NÚMERO DE CHEQUE", "COMPROBANTE ANULADO", "CÓDIGO DEL MOTIVO DE DEVOLUCIÓN",
    "FORMA DE PAGO", "INGRESOS PARA TERCEROS", "SECUENCIA GRAVADA O EXCENTA",
    "IVA COMO MAYOR VALOR DE LA COMPRA",
    "LÍNEA PRODUCTO", "GRUPO PRODUCTO", "CÓDIGO PRODUCTO", "CANTIDAD", "CANTIDAD DOS",
    "CÓDIGO DE LA BODEGA", "CÓDIGO DE LA UBICACIÓN",
    "CANTIDAD DE FACTOR DE CONVERSIÓN", "OPERADOR DE FACTOR DE CONVERSIÓN",
    "VALOR DEL FACTOR DE CONVERSIÓN",
    "GRUPO ACTIVOS", "CÓDIGO ACTIVO", "ADICIÓN O MEJORA",
    "VECES ADICIONALES A DEPRECIAR POR ADICIÓN O MEJORA", "VECES A DEPRECIAR NIIF",
    "TIPO DOCUMENTO DE PEDIDO", "CÓDIGO COMPROBANTE DE PEDIDO", "SECUENCIA DE PEDIDO",
    "TIPO DE MONEDA ELABORACIÓN", "NÚMERO DE VENCIMIENTO",
    "NÚMERO DE CAJA ASOCIADA AL COMPROBANTE", "INCONTERM", "MEDIO DE TRANSPORTE",
    "PAÍS DE ORIGEN", "CIUDAD DE ORIGEN", "PAIS DESTINO", "CIUDAD DESTINO",
    "UNIDAD DE MEDIDA NETO", "UNIDAD DE MEDIDA BRUTO", "CONCEPTO FACTURACION EN BLOQUE",
    "DATOS ESTABLEC. (L=LOCAL O=OFICINA)", "NÚMERO ESTABLECIMIENTO",
}

# Campos donde no se copia un literal viejo, sino que se detecta si el historial
# muestra una relación 1:1 con el número/fecha del comprobante histórico.
_RELACIONALES = {
    "TIPO Y COMPROBANTE CRUCE": "tipo_codigo_comprobante",
    "NÚMERO DE DOCUMENTO CRUCE": "numero_documento",
    "AÑO VENCIMIENTO DE DOCUMENTO CRUCE": "anio",
    "MES VENCIMIENTO DE DOCUMENTO CRUCE": "mes",
    "DÍA VENCIMIENTO DE DOCUMENTO CRUCE": "dia",
}


def _norm_label(valor: str) -> str:
    texto = " ".join(str(valor or "").strip().upper().split())
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return texto


_DINAMICAS_BASE_N = {_norm_label(x) for x in _DINAMICAS_BASE}
_APRENDIBLES_ESTATICOS_N = {_norm_label(x) for x in _APRENDIBLES_ESTATICOS}
_RELACIONALES_N = {_norm_label(k): v for k, v in _RELACIONALES.items()}


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


def _valor_exacto(valor) -> str:
    """Conserva espacios técnicos; pandas ya entrega strings en este camino."""
    if valor is None:
        return ""
    texto = str(valor)
    if texto.lower() == "nan":
        return ""
    if re.fullmatch(r"\d+\.0", texto.strip()):
        return texto.strip()[:-2]
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
    """Guarda todas las filas técnicas, incluidas cuentas excluidas del aprendizaje contable.

    Además de los campos índice se conserva el mapa completo de las 123 columnas
    con sus valores EXACTOS (incluidos espacios). Así una nueva exigencia de SIIGO
    no obliga a volver a diseñar el modelo de datos.
    """
    columnas = detectar_columnas_tecnicas_siigo(list(df.columns))
    if not columnas:
        return 0

    cantidad = 0
    nombres_columnas = [str(c) for c in df.columns]
    for i, row in df.iterrows():
        cuenta = _texto(row.get(columnas["cuenta_codigo"]))
        if not cuenta:
            continue
        valores_completos = {c: _valor_exacto(row.get(c)) for c in nombres_columnas}
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
            "descripcion_secuencia": _texto(row.get(columnas.get("descripcion"))) if columnas.get("descripcion") else None,
            "valores_columnas_json": json.dumps(valores_completos, ensure_ascii=False),
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
    valores_tecnicos: dict[str, str] = field(default_factory=dict)
    relaciones_tecnicas: dict[str, str] = field(default_factory=dict)
    ambiguos: list[str] = field(default_factory=list)
    fuente: str = "sin_historial"
    coincidencias: int = 0

    def valor_tecnico(self, label: str) -> Optional[str]:
        return self.valores_tecnicos.get(_norm_label(label))

    def relacion_tecnica(self, label: str) -> Optional[str]:
        return self.relaciones_tecnicas.get(_norm_label(label))


class IndiceHistorialSiigo:
    def __init__(self, filas: list[HistorialTecnicoSiigo]):
        self.filas = filas
        self.por_cuenta = defaultdict(list)
        self.por_cuenta_nit = defaultdict(list)
        self.por_cuenta_comp = defaultdict(list)
        self.por_cuenta_nit_comp = defaultdict(list)
        self.por_cuenta_tipo = defaultdict(list)
        self.por_cuenta_nit_tipo = defaultdict(list)
        self.por_nit = defaultdict(list)
        self.por_nit_comp = defaultdict(list)
        self.valores_por_id: dict[str, dict[str, str]] = {}
        self.labels: dict[str, str] = {}
        for r in filas:
            c = _normalizar_cuenta(r.cuenta_codigo)
            n = _normalizar_nit(r.nit)
            t = _texto(r.tipo_comprobante)
            k = _texto(r.codigo_comprobante)
            self.por_cuenta[c].append(r)
            self.por_cuenta_nit[(c, n)].append(r)
            self.por_cuenta_comp[(c, t, k)].append(r)
            self.por_cuenta_nit_comp[(c, n, t, k)].append(r)
            self.por_cuenta_tipo[(c, t)].append(r)
            self.por_cuenta_nit_tipo[(c, n, t)].append(r)
            if n:
                self.por_nit[n].append(r)
                self.por_nit_comp[(n, t, k)].append(r)
            try:
                raw = json.loads(r.valores_columnas_json or "{}")
            except Exception:
                raw = {}
            normalizados = {}
            for label, valor in raw.items():
                key = _norm_label(label)
                self.labels.setdefault(key, label)
                normalizados[key] = "" if valor is None else str(valor)
            self.valores_por_id[r.id] = normalizados

    def valor(self, fila: HistorialTecnicoSiigo, label_norm: str) -> Optional[str]:
        if label_norm in self.valores_por_id.get(fila.id, {}):
            return self.valores_por_id[fila.id][label_norm]
        # Compatibilidad con filas históricas importadas por la V3 antes de que
        # existiera el JSON de 123 columnas.
        legacy = {
            _norm_label("CÓDIGO DEL VENDEDOR"): fila.codigo_vendedor,
            _norm_label("CÓDIGO DE LA CIUDAD"): fila.codigo_ciudad,
            _norm_label("CÓDIGO DE LA ZONA"): fila.codigo_zona,
            _norm_label("CENTRO DE COSTO"): fila.centro_costo,
            _norm_label("SUBCENTRO DE COSTO"): fila.subcentro_costo,
            _norm_label("SUCURSAL"): fila.sucursal,
        }
        valor = legacy.get(label_norm)
        return None if valor is None else str(valor)


def construir_indice_historial_siigo(db: Session, empresa_id: str) -> IndiceHistorialSiigo:
    filas = db.query(HistorialTecnicoSiigo).filter(
        HistorialTecnicoSiigo.empresa_id == empresa_id
    ).order_by(HistorialTecnicoSiigo.creado_en.asc()).all()
    return IndiceHistorialSiigo(filas)


def _candidatos(indice: IndiceHistorialSiigo, cuenta: str, nit: str, tipo: str, codigo: str):
    grupos = [
        ("cuenta+nit+comprobante", indice.por_cuenta_nit_comp.get((cuenta, nit, tipo, codigo), [])),
        # El código puede cambiar entre empresas (p.ej. F-2 histórico y F-1 actual),
        # pero el TIPO F conserva el comportamiento técnico de la cuenta.
        ("cuenta+nit+tipo", indice.por_cuenta_nit_tipo.get((cuenta, nit, tipo), [])),
        ("cuenta+comprobante", indice.por_cuenta_comp.get((cuenta, tipo, codigo), [])),
        ("cuenta+tipo", indice.por_cuenta_tipo.get((cuenta, tipo), [])),
        ("cuenta+nit", indice.por_cuenta_nit.get((cuenta, nit), [])),
        ("nit+comprobante", indice.por_nit_comp.get((nit, tipo, codigo), [])),
        ("cuenta", indice.por_cuenta.get(cuenta, [])),
        ("nit", indice.por_nit.get(nit, [])),
    ]
    return [(nombre, filas) for nombre, filas in grupos if filas]


def _valor_estable(indice: IndiceHistorialSiigo, filas: list[HistorialTecnicoSiigo], label_norm: str) -> Optional[str]:
    valores = [indice.valor(r, label_norm) for r in filas]
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    primero = valores[0]
    if all(v == primero for v in valores):
        return primero
    return None


def _relacion_estable(indice: IndiceHistorialSiigo, filas: list[HistorialTecnicoSiigo], label_norm: str) -> Optional[str]:
    relacion = _RELACIONALES_N.get(label_norm)
    if not relacion or not filas:
        return None
    for r in filas:
        valor = indice.valor(r, label_norm)
        if valor is None:
            return None
        if relacion == "tipo_codigo_comprobante":
            tipo = _texto(r.tipo_comprobante)
            codigo = _texto(r.codigo_comprobante)
            try:
                codigo_fmt = f"{int(codigo):03d}"
            except Exception:
                codigo_fmt = codigo.zfill(3)
            esperado = f"{tipo}-{codigo_fmt}" if tipo and codigo else ""
        elif relacion == "numero_documento":
            esperado = _texto(r.numero_documento)
        elif relacion == "anio":
            esperado = str(r.fecha_documento.year) if r.fecha_documento else ""
        elif relacion == "mes":
            esperado = str(r.fecha_documento.month) if r.fecha_documento else ""
        elif relacion == "dia":
            esperado = str(r.fecha_documento.day) if r.fecha_documento else ""
        else:
            return None
        if _texto(valor) != _texto(esperado):
            return None
    return relacion


def _inferir_tecnicos(indice: IndiceHistorialSiigo, grupos) -> tuple[dict[str, str], dict[str, str], list[str], list[str]]:
    valores: dict[str, str] = {}
    relaciones: dict[str, str] = {}
    ambiguos: list[str] = []
    fuentes: list[str] = []

    labels = set(indice.labels.keys()) | _APRENDIBLES_ESTATICOS_N | set(_RELACIONALES_N.keys())
    for label_norm in labels:
        if label_norm in _DINAMICAS_BASE_N:
            continue
        es_estatico = label_norm in _APRENDIBLES_ESTATICOS_N
        es_relacional = label_norm in _RELACIONALES_N
        if not es_estatico and not es_relacional:
            continue
        encontrado = False
        hubo_datos = False
        for nombre, filas in grupos:
            presentes = [indice.valor(r, label_norm) for r in filas]
            presentes = [v for v in presentes if v is not None]
            if not presentes:
                continue
            hubo_datos = True
            if es_relacional:
                rel = _relacion_estable(indice, filas, label_norm)
                if rel:
                    relaciones[label_norm] = rel
                    fuentes.append(nombre)
                    encontrado = True
                    break
            if es_estatico:
                estable = _valor_estable(indice, filas, label_norm)
                if estable is not None:
                    valores[label_norm] = estable
                    fuentes.append(nombre)
                    encontrado = True
                    break
        if hubo_datos and not encontrado:
            ambiguos.append(indice.labels.get(label_norm, label_norm))
    return valores, relaciones, ambiguos, fuentes


def inferir_parametros_movimiento(indice: IndiceHistorialSiigo, cuenta_codigo: str,
                                   nit_actual: Optional[str], tipo_comprobante: Optional[str],
                                   codigo_comprobante: Optional[str],
                                   descripcion_actual: Optional[str] = None) -> ParametrosSiigoInferidos:
    cuenta = _normalizar_cuenta(cuenta_codigo)
    nit = _normalizar_nit(nit_actual)
    tipo = _texto(tipo_comprobante)
    codigo = _texto(codigo_comprobante)
    grupos = _candidatos(indice, cuenta, nit, tipo, codigo)

    resultado = ParametrosSiigoInferidos()
    if not grupos:
        return resultado

    # Manejo de tercero se aprende por CUENTA + tipo/código. Una cuenta que
    # históricamente sale con NIT 0 debe volver a salir con 0 aunque el tercero
    # actual sea distinto.
    filas_cuenta_tipo = (indice.por_cuenta_comp.get((cuenta, tipo, codigo), [])
                         or indice.por_cuenta_tipo.get((cuenta, tipo), [])
                         or indice.por_cuenta.get(cuenta, []))
    if filas_cuenta_tipo:
        nits = [_texto(r.nit) for r in filas_cuenta_tipo]
        ceros = sum(1 for x in nits if _zero_like(x))
        reales = len(nits) - ceros
        if ceros > reales:
            resultado.maneja_tercero = False
            resultado.nit_tecnico_exportacion = _modo([r for r in filas_cuenta_tipo if _zero_like(r.nit)], "nit") or "0"

    valores, relaciones, ambiguos, fuentes = _inferir_tecnicos(indice, grupos)
    resultado.valores_tecnicos = valores
    resultado.relaciones_tecnicas = relaciones
    resultado.ambiguos = ambiguos

    # Compatibilidad con los campos J:Q que ya consumía export_service.py.
    resultado.codigo_vendedor = valores.get(_norm_label("CÓDIGO DEL VENDEDOR"))
    resultado.codigo_ciudad = valores.get(_norm_label("CÓDIGO DE LA CIUDAD"))
    resultado.codigo_zona = valores.get(_norm_label("CÓDIGO DE LA ZONA"))
    resultado.centro_costo = valores.get(_norm_label("CENTRO DE COSTO"))
    resultado.subcentro_costo = valores.get(_norm_label("SUBCENTRO DE COSTO"))
    resultado.sucursal = valores.get(_norm_label("SUCURSAL"))

    resultado.fuente = ",".join(dict.fromkeys(fuentes)) if fuentes else grupos[0][0]
    resultado.coincidencias = len(grupos[0][1])
    return resultado
