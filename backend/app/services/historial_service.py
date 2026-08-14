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


def _normalizar_texto(t: str) -> str:
    import unicodedata
    t = (t or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def _palabras_clave(t: str, largo_minimo: int = 4) -> set:
    return {p for p in _normalizar_texto(t).split() if len(p) >= largo_minimo}


def sugerir_cuenta(db: Session, empresa_id: str, nit: str,
                    descripcion: Optional[str] = None) -> dict:
    """
    Devuelve un dict serializable con la sugerencia y su explicación,
    siguiendo el orden de prioridad de la sección 37:
    historial de la empresa (afinado por NIT+concepto cuando es posible)
    → reglas de la empresa → catálogo PUC como candidatos (nunca una
    decisión, solo opciones para elegir) → sin información.
    """
    nit = nit.strip()
    proveedor = db.query(Proveedor).filter(
        Proveedor.empresa_id == empresa_id, Proveedor.nit == nit
    ).first()

    if proveedor:
        registros = (
            db.query(HistorialContable)
            .filter(HistorialContable.empresa_id == empresa_id, HistorialContable.proveedor_id == proveedor.id)
            .all()
        )
        if registros:
            total = len(registros)
            fuente = "historial"
            registros_para_contar = registros
            claves_concepto = _palabras_clave(descripcion) if descripcion else set()

            if claves_concepto:
                coincidentes = [
                    r for r in registros
                    if r.descripcion and (_palabras_clave(r.descripcion) & claves_concepto)
                ]
                if coincidentes:
                    registros_para_contar = coincidentes
                    fuente = "historial_nit_concepto"

            conteo: dict[str, int] = {}
            for r in registros_para_contar:
                conteo[r.cuenta_id] = conteo.get(r.cuenta_id, 0) + 1
            total_considerado = sum(conteo.values())

            opciones = []
            for cuenta_id, usos in conteo.items():
                cta = db.get(CuentaContable, cuenta_id)
                opciones.append({
                    "cuenta_codigo": cta.codigo,
                    "cuenta_nombre": cta.nombre,
                    "usos": usos,
                    "porcentaje": round(usos * 100.0 / total_considerado, 1),
                })
            # Empate en frecuencia -> desempate determinístico por código de
            # cuenta ascendente, para que la sugerencia nunca dependa del
            # orden interno (no documentado) de la base de datos.
            opciones.sort(key=lambda o: (-o["usos"], o["cuenta_codigo"]))
            principal = opciones[0]

            if fuente == "historial_nit_concepto":
                motivo = (
                    f"De los {total} documento(s) histórico(s) de este proveedor (NIT {nit}), "
                    f"{total_considerado} tienen un concepto similar al de esta factura. "
                    f"La cuenta {principal['cuenta_codigo']} ({principal['cuenta_nombre']}) se usó en "
                    f"{principal['usos']} de esos ({principal['porcentaje']}%)."
                )
            else:
                aviso_concepto = (
                    " No se encontró en el historial ningún documento con un concepto similar al de esta "
                    "factura, así que se usa la frecuencia general de este proveedor (confianza menor)."
                    if claves_concepto else ""
                )
                motivo = (
                    f"Este proveedor (NIT {nit}) tiene {total} documento(s) histórico(s) en esta empresa. "
                    f"La cuenta {principal['cuenta_codigo']} ({principal['cuenta_nombre']}) se usó "
                    f"{principal['usos']} vez/veces, el {principal['porcentaje']}% del historial."
                    f"{aviso_concepto}"
                )

            return {
                "proveedor_nit": nit,
                "proveedor_nombre": proveedor.nombre,
                "total_documentos_historicos": total,
                "opciones": opciones,
                "cuenta_sugerida": principal["cuenta_codigo"],
                "motivo": motivo,
                "fuente": fuente,
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

    # Ni historial ni regla: buscar candidatos primero en las CUENTAS
    # PROPIAS de la empresa (si ya tienen un nombre real, ej. cargado
    # desde un balance por tercero — "IVA Compras 19%", "Servicios
    # Prestados") — son más precisas que el catálogo PUC genérico porque
    # son el plan de cuentas real de ESTA contabilidad específica, con
    # sus propios códigos y su propio criterio de nombrar cada cuenta
    # (ej. distinguir IVA al 19% del 5%, o servicio de compra, por el
    # nombre). Si no hay coincidencia ahí, se cae al catálogo PUC.
    if descripcion:
        claves = _palabras_clave(descripcion)
        if claves:
            cuentas_propias = (
                db.query(CuentaContable)
                .filter(CuentaContable.empresa_id == empresa_id, CuentaContable.nombre != CuentaContable.codigo)
                .all()
            )
            candidatos_propios = [c for c in cuentas_propias if _palabras_clave(c.nombre) & claves]
            if candidatos_propios:
                return {
                    "proveedor_nit": nit,
                    "proveedor_nombre": proveedor.nombre if proveedor else None,
                    "total_documentos_historicos": 0,
                    "opciones": [
                        {"cuenta_codigo": c.codigo, "cuenta_nombre": c.nombre, "usos": 0, "porcentaje": 0.0}
                        for c in candidatos_propios[:8]
                    ],
                    "cuenta_sugerida": None,
                    "motivo": "Sin historial ni regla para este proveedor. Estas son cuentas de TU propio plan "
                              "de cuentas cuyo nombre coincide con el concepto de la factura — revísalas y "
                              "elige manualmente, no son una decisión automática.",
                    "fuente": "cuentas_propias",
                }

    # Ni historial, ni regla, ni cuenta propia con nombre reconocible:
    # buscar candidatos en el catálogo PUC según el concepto — son solo
    # OPCIONES para que el usuario elija, nunca una decisión automática
    # (sección 13, 37: nunca se inventa una cuenta).
    if descripcion:
        from app.models.models import PucCuenta
        claves = _palabras_clave(descripcion)
        if claves:
            candidatos = []
            for cta in db.query(PucCuenta).all():
                claves_cuenta = _palabras_clave(cta.nombre)
                if claves_cuenta & claves:
                    candidatos.append(cta)
            if candidatos:
                return {
                    "proveedor_nit": nit,
                    "proveedor_nombre": proveedor.nombre if proveedor else None,
                    "total_documentos_historicos": 0,
                    "opciones": [
                        {"cuenta_codigo": c.codigo, "cuenta_nombre": c.nombre, "usos": 0, "porcentaje": 0.0}
                        for c in candidatos[:8]
                    ],
                    "cuenta_sugerida": None,
                    "motivo": "Sin historial ni regla para este proveedor. Estas son cuentas del catálogo PUC "
                              "cuyo nombre coincide con el concepto de la factura — revísalas y elige "
                              "manualmente, no son una decisión automática.",
                    "fuente": "puc_catalogo",
                }

    # Ni historial, ni regla, ni coincidencia en el PUC: NO se inventa nada
    return {
        "proveedor_nit": nit,
        "proveedor_nombre": proveedor.nombre if proveedor else None,
        "total_documentos_historicos": 0,
        "opciones": [],
        "cuenta_sugerida": None,
        "motivo": "Sin historial suficiente para sugerir una cuenta. Selecciona la cuenta manualmente.",
        "fuente": "sin_informacion",
    }
