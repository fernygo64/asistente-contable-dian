"""
Motor de historial contable y sugerencia explicable (secciones 8-15).

Principios que este módulo garantiza:
- El historial es una bitácora de DECISIONES, nunca una tabla de "cuenta
  fija por proveedor". Cada llamado a registrar_decision() INSERTA una
  fila nueva; nunca actualiza ni borra una fila anterior.
- Toda sugerencia se calcula en tiempo de consulta a partir de las filas
  existentes — así el aprendizaje "evoluciona" automáticamente sin
  ningún job de recálculo.
- Toda sugerencia trae su explicación en lenguaje natural y sus cifras
  (sección 15) — nunca se sugiere una cuenta sin decir por qué.
- Si no hay historial ni reglas aplicables, se dice explícitamente que
  no hay información suficiente (sección 13, sección 37) — nunca se
  inventa una cuenta.
"""
import json
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Proveedor, CuentaContable, HistorialContable, ReglaContable, OrigenDecision
)


def get_or_create_proveedor(db: Session, empresa_id: str, nit: str, nombre: Optional[str] = None,
                             direccion: Optional[str] = None) -> Proveedor:
    nit = nit.strip()
    prov = db.query(Proveedor).filter(
        Proveedor.empresa_id == empresa_id, Proveedor.nit == nit
    ).first()
    if prov:
        if nombre and not prov.nombre:
            prov.nombre = nombre
        if direccion and not prov.direccion:
            prov.direccion = direccion
        return prov
    prov = Proveedor(empresa_id=empresa_id, nit=nit, nombre=nombre, direccion=direccion)
    db.add(prov)
    db.flush()
    return prov


def get_or_create_cuenta(db: Session, empresa_id: str, codigo: str,
                          nombre: Optional[str] = None) -> CuentaContable:
    codigo = codigo.strip()
    cta = db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa_id, CuentaContable.codigo == codigo
    ).first()
    if cta:
        return cta
    cta = CuentaContable(empresa_id=empresa_id, codigo=codigo, nombre=nombre or codigo)
    db.add(cta)
    db.flush()
    return cta


def registrar_decision(db: Session, empresa_id: str, proveedor_id: str, cuenta_id: str,
                        origen: OrigenDecision, fecha_documento=None, numero_documento=None,
                        tipo_documento=None, descripcion=None, valor=None,
                        importacion_id=None) -> HistorialContable:
    """
    Inserta SIEMPRE una fila nueva. Nunca modifica una decisión previa —
    así el historial conserva la trazabilidad completa (secciones 11-12).
    """
    fila = HistorialContable(
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        cuenta_id=cuenta_id,
        fecha_documento=fecha_documento,
        numero_documento=numero_documento,
        tipo_documento=tipo_documento,
        descripcion=descripcion,
        valor=valor,
        origen=origen,
        importacion_id=importacion_id,
    )
    db.add(fila)
    db.flush()
    return fila


def _buscar_regla_aplicable(db: Session, empresa_id: str, nit: str,
                             descripcion: Optional[str] = None) -> Optional[ReglaContable]:
    reglas = db.query(ReglaContable).filter(
        ReglaContable.empresa_id == empresa_id, ReglaContable.activa == True  # noqa: E712
    ).all()
    for r in reglas:
        try:
            criterio = json.loads(r.criterio_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if criterio.get("nit") and criterio["nit"].strip() == nit.strip():
            return r
        if criterio.get("palabra_clave") and descripcion:
            if criterio["palabra_clave"].lower() in descripcion.lower():
                return r
    return None


def sugerir_cuenta(db: Session, empresa_id: str, nit: str,
                    descripcion: Optional[str] = None) -> dict:
    """
    Devuelve un dict serializable con la sugerencia y su explicación,
    siguiendo el orden de prioridad de la sección 37:
    historial de la empresa → reglas de la empresa → sin información.
    """
    nit = nit.strip()
    proveedor = db.query(Proveedor).filter(
        Proveedor.empresa_id == empresa_id, Proveedor.nit == nit
    ).first()

    if proveedor:
        filas = (
            db.query(HistorialContable.cuenta_id, func.count(HistorialContable.id).label("usos"))
            .filter(HistorialContable.empresa_id == empresa_id,
                    HistorialContable.proveedor_id == proveedor.id)
            .group_by(HistorialContable.cuenta_id)
            .all()
        )
        if filas:
            total = sum(f.usos for f in filas)
            opciones = []
            for cuenta_id, usos in filas:
                cta = db.get(CuentaContable, cuenta_id)
                opciones.append({
                    "cuenta_codigo": cta.codigo,
                    "cuenta_nombre": cta.nombre,
                    "usos": usos,
                    "porcentaje": round(usos * 100.0 / total, 1),
                })
            # Empate en frecuencia -> desempate determinístico por código de
            # cuenta ascendente, para que la sugerencia nunca dependa del
            # orden interno (no documentado) de la base de datos.
            opciones.sort(key=lambda o: (-o["usos"], o["cuenta_codigo"]))
            principal = opciones[0]
            motivo = (
                f"Este proveedor (NIT {nit}) tiene {total} documento(s) histórico(s) en esta empresa. "
                f"La cuenta {principal['cuenta_codigo']} ({principal['cuenta_nombre']}) se usó "
                f"{principal['usos']} vez/veces, el {principal['porcentaje']}% del historial."
            )
            return {
                "proveedor_nit": nit,
                "proveedor_nombre": proveedor.nombre,
                "total_documentos_historicos": total,
                "opciones": opciones,
                "cuenta_sugerida": principal["cuenta_codigo"],
                "motivo": motivo,
                "fuente": "historial",
            }

    # Sin historial (o proveedor nuevo): buscar regla explícita de la empresa
    regla = _buscar_regla_aplicable(db, empresa_id, nit, descripcion)
    if regla:
        cta = db.get(CuentaContable, regla.cuenta_id)
        return {
            "proveedor_nit": nit,
            "proveedor_nombre": proveedor.nombre if proveedor else None,
            "total_documentos_historicos": 0,
            "opciones": [],
            "cuenta_sugerida": cta.codigo,
            "motivo": f'Regla de empresa "{regla.nombre}" aplicada (sin historial previo de este proveedor).',
            "fuente": "regla",
        }

    # Ni historial ni regla: NO se inventa una cuenta (sección 13, 37)
    return {
        "proveedor_nit": nit,
        "proveedor_nombre": proveedor.nombre if proveedor else None,
        "total_documentos_historicos": 0,
        "opciones": [],
        "cuenta_sugerida": None,
        "motivo": "Sin historial suficiente para sugerir una cuenta. Selecciona la cuenta manualmente.",
        "fuente": "sin_informacion",
    }
