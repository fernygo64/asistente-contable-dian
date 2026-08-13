"""
Importación de historial contable ya existente en la empresa (sección 8-9-12).

No asume orden fijo de columnas: recibe un mapeo explícito
{campo_interno: nombre_columna_en_el_archivo} y lo aplica. Registra
auditoría completa de la importación (cuántos registros, cuántos
rechazados y por qué) y NUNCA modifica ni borra importaciones previas.
"""
import io
import json
import re
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import ImportacionHistorico, OrigenDecision
from app.services.historial_service import get_or_create_proveedor, get_or_create_cuenta, registrar_decision
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.excel_utils import resolver_columna, leer_dataframe_excel


def _leer_dataframe(contenido: bytes, nombre_archivo: str) -> pd.DataFrame:
    return leer_dataframe_excel(contenido, nombre_archivo)


_PATRON_FECHA_ISO = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")


def _parse_fecha(v) -> Optional[datetime]:
    if not v or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        v_str = str(v)
        if _PATRON_FECHA_ISO.match(v_str):
            return pd.to_datetime(v_str, dayfirst=False).to_pydatetime()
        return pd.to_datetime(v_str, dayfirst=True).to_pydatetime()
    except Exception:
        return None


def _parse_valor(v) -> Optional[float]:
    if v in (None, "", "nan"):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def importar_historico(db: Session, empresa_id: str, contenido: bytes, nombre_archivo: str,
                        mapeo: dict, usuario: Optional[str],
                        cuentas_excluir: Optional[list[str]] = None) -> ImportacionHistorico:
    """
    cuentas_excluir: lista de códigos o prefijos de cuenta a ignorar del
    aprendizaje (ej. ["2205", "1105", "2408"] para proveedores, caja/
    bancos, IVA). Un archivo de "Movimiento Contable" trae TODAS las
    líneas del comprobante — la cuenta de gasto/ingreso real, pero
    también la contrapartida, el IVA y las retenciones. Sin excluir
    esas cuentas de control, el sistema aprendería, por ejemplo, que
    "proveedores" es una cuenta típica de gasto de ese NIT, lo cual es
    ruido, no una decisión de clasificación real.
    """
    df = _leer_dataframe(contenido, nombre_archivo)
    columnas_reales = list(df.columns)

    mapeo_resuelto = {}
    no_encontradas = []
    for campo, valor in mapeo.items():
        if not valor:
            continue
        columna_real = resolver_columna(valor, columnas_reales)
        if not columna_real:
            no_encontradas.append(f"'{valor}' (campo '{campo}')")
        else:
            mapeo_resuelto[campo] = columna_real

    if no_encontradas:
        raise ValueError(
            f"No se encontraron estas columnas en el archivo: {', '.join(no_encontradas)}. "
            f"Columnas disponibles: {columnas_reales}"
        )
    if not mapeo_resuelto.get("nit") or not mapeo_resuelto.get("cuenta"):
        raise ValueError("El mapeo debe incluir al menos las columnas para 'nit' y 'cuenta'.")
    columna_nit = mapeo_resuelto["nit"]
    columna_cuenta = mapeo_resuelto["cuenta"]

    prefijos_excluir = [p.strip() for p in (cuentas_excluir or []) if p.strip()]

    total = len(df)
    validos = 0
    excluidos_por_cuenta = 0
    rechazos: list[str] = []

    importacion = ImportacionHistorico(
        empresa_id=empresa_id,
        archivo_nombre=nombre_archivo,
        mapeo_columnas_json=json.dumps(mapeo, ensure_ascii=False),
        total_registros=total,
        registros_validos=0,
        registros_rechazados=0,
        usuario=usuario,
    )
    db.add(importacion)
    db.flush()  # obtiene importacion.id

    for i, row in df.iterrows():
        nit = str(row.get(columna_nit, "")).strip()
        cuenta_codigo = str(row.get(columna_cuenta, "")).strip()
        if not nit or not cuenta_codigo:
            rechazos.append(f"Fila {i + 2}: falta NIT o cuenta.")
            continue

        if any(cuenta_codigo.startswith(p) for p in prefijos_excluir):
            excluidos_por_cuenta += 1
            continue

        nombre_col = mapeo_resuelto.get("nombre")
        nombre_proveedor = str(row.get(nombre_col, "")).strip() if nombre_col else None

        proveedor = get_or_create_proveedor(db, empresa_id, nit, nombre_proveedor or None)
        cuenta = get_or_create_cuenta(db, empresa_id, cuenta_codigo)

        fecha_col = mapeo_resuelto.get("fecha")
        numero_col = mapeo_resuelto.get("numero_documento")
        tipo_col = mapeo_resuelto.get("tipo_documento")
        desc_col = mapeo_resuelto.get("descripcion")
        valor_col = mapeo_resuelto.get("valor")

        registrar_decision(
            db, empresa_id, proveedor.id, cuenta.id,
            origen=OrigenDecision.importado,
            fecha_documento=_parse_fecha(row.get(fecha_col)) if fecha_col else None,
            numero_documento=str(row.get(numero_col, "")).strip() if numero_col else None,
            tipo_documento=str(row.get(tipo_col, "")).strip() if tipo_col else None,
            descripcion=str(row.get(desc_col, "")).strip() if desc_col else None,
            valor=_parse_valor(row.get(valor_col)) if valor_col else None,
            importacion_id=importacion.id,
        )
        validos += 1

    importacion.registros_validos = validos
    importacion.registros_rechazados = total - validos - excluidos_por_cuenta
    if excluidos_por_cuenta:
        rechazos.insert(0, f"{excluidos_por_cuenta} fila(s) omitidas por pertenecer a una cuenta excluida "
                           f"(contrapartida/impuestos, no se cuentan como rechazo ni como aprendizaje).")
    importacion.detalle_rechazos_json = json.dumps(rechazos[:200], ensure_ascii=False)  # tope razonable

    auditoria_registrar(
        db, empresa_id, entidad="ImportacionHistorico", entidad_id=importacion.id,
        accion="importacion_historico",
        detalle={"archivo": nombre_archivo, "validos": validos, "excluidos_por_cuenta": excluidos_por_cuenta,
                 "rechazados": total - validos - excluidos_por_cuenta},
        usuario=usuario,
    )

    return importacion
