"""
Importación de historial contable ya existente en la empresa (sección 8-9-12).

No asume orden fijo de columnas: recibe un mapeo explícito
{campo_interno: nombre_columna_en_el_archivo} y lo aplica. Registra
auditoría completa de la importación (cuántos registros, cuántos
rechazados y por qué) y NUNCA modifica ni borra importaciones previas.
"""
import io
import json
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import ImportacionHistorico, OrigenDecision
from app.services.historial_service import get_or_create_proveedor, get_or_create_cuenta, registrar_decision
from app.services.auditoria_service import registrar as auditoria_registrar


def _leer_dataframe(contenido: bytes, nombre_archivo: str) -> pd.DataFrame:
    if nombre_archivo.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(contenido), dtype=str, keep_default_na=False)
    return pd.read_excel(io.BytesIO(contenido), dtype=str, keep_default_na=False, na_filter=False)


def _parse_fecha(v) -> Optional[datetime]:
    if not v or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.to_datetime(v).to_pydatetime()
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
                        mapeo: dict, usuario: Optional[str]) -> ImportacionHistorico:
    df = _leer_dataframe(contenido, nombre_archivo)

    columna_nit = mapeo.get("nit")
    columna_cuenta = mapeo.get("cuenta")
    if not columna_nit or not columna_cuenta:
        raise ValueError("El mapeo debe incluir al menos las columnas para 'nit' y 'cuenta'.")
    faltantes = [c for c in (columna_nit, columna_cuenta) if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Las columnas mapeadas {faltantes} no existen en el archivo. "
            f"Columnas disponibles: {list(df.columns)}"
        )

    total = len(df)
    validos = 0
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

        nombre_col = mapeo.get("nombre")
        nombre_proveedor = str(row.get(nombre_col, "")).strip() if nombre_col else None

        proveedor = get_or_create_proveedor(db, empresa_id, nit, nombre_proveedor or None)
        cuenta = get_or_create_cuenta(db, empresa_id, cuenta_codigo)

        fecha_col = mapeo.get("fecha")
        numero_col = mapeo.get("numero_documento")
        tipo_col = mapeo.get("tipo_documento")
        desc_col = mapeo.get("descripcion")
        valor_col = mapeo.get("valor")

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
    importacion.registros_rechazados = total - validos
    importacion.detalle_rechazos_json = json.dumps(rechazos[:200], ensure_ascii=False)  # tope razonable

    auditoria_registrar(
        db, empresa_id, entidad="ImportacionHistorico", entidad_id=importacion.id,
        accion="importacion_historico",
        detalle={"archivo": nombre_archivo, "validos": validos, "rechazados": total - validos},
        usuario=usuario,
    )

    return importacion
