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


def _cuenta_equivalente_empresa(db: Session, empresa_id: str, codigo: str) -> Optional[CuentaContable]:
    """Busca la cuenta canónica sin duplicar la versión SIIGO de 10 dígitos.

    Ej.: 519525 y 5195250000 representan la misma cuenta. Se prefiere
    la cuenta natural más específica del plan real de la empresa.
    """
    codigo = str(codigo or "").strip()
    if not codigo:
        return None
    cuentas = db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa_id, CuentaContable.activa.is_(True)
    ).all()
    if codigo.isdigit() and len(codigo) <= 10:
        objetivo = codigo.ljust(10, "0")
        equivalentes = [
            c for c in cuentas
            if str(c.codigo or "").isdigit() and len(str(c.codigo)) <= 10
            and str(c.codigo).ljust(10, "0") == objetivo
        ]
        if equivalentes:
            equivalentes.sort(key=lambda c: (
                0 if len(str(c.codigo)) < 10 else 1,
                -len(str(c.codigo)),
                0 if (c.nombre and c.nombre != c.codigo) else 1,
                str(c.codigo),
            ))
            return equivalentes[0]
    return next((c for c in cuentas if str(c.codigo) == codigo), None)


def get_or_create_cuenta(db: Session, empresa_id: str, codigo: str,
                          nombre: Optional[str] = None) -> CuentaContable:
    codigo = str(codigo or "").strip()
    cta = _cuenta_equivalente_empresa(db, empresa_id, codigo)
    if cta:
        if nombre and (not cta.nombre or cta.nombre == cta.codigo):
            cta.nombre = nombre
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


def _es_cuenta_de_resultado(codigo: str, clases_permitidas: tuple[str, ...] = ("4", "5", "6", "7")) -> bool:
    """
    Solo cuentas de INGRESO (clase 4), GASTO (clase 5), COSTO DE VENTAS
    (clase 6) o COSTO DE PRODUCCIÓN (clase 7) del PUC colombiano pueden
    sugerirse como "cuenta de gasto/ingreso" de una factura — nunca una
    cuenta de balance (activo 1, pasivo 2, patrimonio 3), donde caen
    IVA, retenciones, proveedores, clientes, caja y bancos. Esas se
    resuelven aparte (automáticamente, o como contrapartida explícita),
    nunca deberían aparecer como opción para "la cuenta del gasto" —
    pedido explícito del usuario tras ver "RETEFUENTE" e IVA como
    candidatos ahí, lo cual no tiene sentido contable.

    Además, cuando se conoce la DIRECCIÓN del documento, se restringe
    más: una factura RECIBIDA (compra) solo debe sugerir cuentas de
    GASTO/COSTO (5/6/7), nunca de INGRESO (4) — y viceversa para una
    EMITIDA (venta) — evita repetir el error real donde una venta usó
    por error su propia cuenta de ingreso como "cuenta de gasto".
    """
    return bool(codigo) and codigo[0] in clases_permitidas


def sugerir_cuenta(db: Session, empresa_id: str, nit: str,
                    descripcion: Optional[str] = None, direccion: Optional[str] = None) -> dict:
    """
    Devuelve un dict serializable con la sugerencia y su explicación,
    siguiendo el orden de prioridad de la sección 37:
    historial de la empresa (afinado por NIT+concepto cuando es posible)
    → reglas de la empresa → catálogo PUC como candidatos (nunca una
    decisión, solo opciones para elegir) → sin información.

    direccion ("recibida" | "emitida"), cuando se conoce, restringe los
    candidatos a la clase de cuenta correcta (gasto/costo para recibida,
    ingreso para emitida) — si no se indica, se permiten ambas.
    """
    if direccion == "emitida":
        clases_permitidas = ("4",)
    elif direccion == "recibida":
        clases_permitidas = ("5", "6", "7")
    else:
        clases_permitidas = ("4", "5", "6", "7")

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
        # Solo cuentas de resultado (ingreso/gasto/costo) pueden salir
        # como sugerencia de "cuenta de gasto" — un historial importado
        # de un movimiento contable completo trae TODAS las líneas del
        # comprobante (incluida la contrapartida, el IVA, las
        # retenciones), y esas nunca deben aparecer aquí como opción.
        registros = [r for r in registros if _es_cuenta_de_resultado(db.get(CuentaContable, r.cuenta_id).codigo, clases_permitidas)]
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

            # Agrupar por cuenta CANÓNICA para no mostrar duplicada la misma
            # cuenta como 519510 y 5195100000.
            conteo: dict[str, int] = {}
            canonicas: dict[str, CuentaContable] = {}
            for r in registros_para_contar:
                original = db.get(CuentaContable, r.cuenta_id)
                if not original:
                    continue
                cta = _cuenta_equivalente_empresa(db, empresa_id, original.codigo) or original
                canonicas[cta.id] = cta
                conteo[cta.id] = conteo.get(cta.id, 0) + 1
            total_considerado = sum(conteo.values())

            opciones = []
            for cuenta_id, usos in conteo.items():
                cta = canonicas[cuenta_id]
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
            candidatos_propios = [
                c for c in cuentas_propias
                if (_palabras_clave(c.nombre) & claves) and _es_cuenta_de_resultado(c.codigo, clases_permitidas)
            ]
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

    # Sin historial, regla o coincidencia en el PLAN REAL de la empresa:
    # no se consulta el PUC global. La corrección manual solo ofrece cuentas
    # observadas en Balance/Movimiento Contable de esta empresa.
    # Sin evidencia suficiente: NO se inventa nada.
    return {
        "proveedor_nit": nit,
        "proveedor_nombre": proveedor.nombre if proveedor else None,
        "total_documentos_historicos": 0,
        "opciones": [],
        "cuenta_sugerida": None,
        "motivo": "Sin historial suficiente para sugerir una cuenta. Selecciona la cuenta manualmente.",
        "fuente": "sin_informacion",
    }


def sugerir_cuentas_masivo(db: Session, empresa_id: str, facturas: list) -> dict[str, dict]:
    """Sugerencias en lote sin N+1 y sin recalcular equivalencias por factura.

    Precarga proveedores, historial y cuentas una sola vez. Esto evita que la
    clasificación masiva se vuelva lenta cuando el usuario selecciona decenas o
    cientos de documentos y, además, mantiene una única cuenta canónica cuando
    el historial trae la misma cuenta en versión natural y SIIGO de 10 dígitos.
    """
    from collections import defaultdict

    resultado: dict[str, dict] = {}
    validas = [
        f for f in facturas
        if getattr(f, "tercero_nit", None)
        and getattr(f, "naturaleza_documento", None) != "nomina"
    ]
    if not validas:
        return resultado

    nits = {str(f.tercero_nit).strip() for f in validas if str(f.tercero_nit or "").strip()}
    proveedores = db.query(Proveedor).filter(
        Proveedor.empresa_id == empresa_id,
        Proveedor.nit.in_(list(nits)),
    ).all()
    prov_por_nit = {p.nit: p for p in proveedores}
    prov_ids = [p.id for p in proveedores]

    cuentas = db.query(CuentaContable).filter(CuentaContable.empresa_id == empresa_id).all()
    cuenta_por_id = {c.id: c for c in cuentas}

    # Canonicalización una sola vez para todo el lote. 519525 y 5195250000
    # pertenecen a la misma cuenta; se prefiere el código natural y el nombre
    # real aprendido de la contabilidad.
    por_equivalencia: dict[str, list[CuentaContable]] = defaultdict(list)
    for c in cuentas:
        cod = str(c.codigo or "").strip()
        eq = cod.ljust(10, "0") if cod.isdigit() and len(cod) <= 10 else cod
        por_equivalencia[eq].append(c)
    canonica_por_id: dict[str, CuentaContable] = {}
    for grupo in por_equivalencia.values():
        grupo.sort(key=lambda c: (
            0 if len(str(c.codigo or "")) < 10 else 1,
            -len(str(c.codigo or "")),
            0 if (c.nombre and c.nombre != c.codigo) else 1,
            str(c.codigo or ""),
        ))
        canon = grupo[0]
        # Si el código natural solo tiene como nombre el propio código pero una
        # cuenta equivalente sí trae el nombre real, úsalo para mostrar/aprender.
        nombre_real = next((x.nombre for x in grupo if x.nombre and x.nombre != x.codigo), None)
        if nombre_real and (not canon.nombre or canon.nombre == canon.codigo):
            canon.nombre = nombre_real
        for c in grupo:
            canonica_por_id[c.id] = canon

    hist_por_prov: dict[str, list[HistorialContable]] = defaultdict(list)
    if prov_ids:
        historiales = db.query(HistorialContable).filter(
            HistorialContable.empresa_id == empresa_id,
            HistorialContable.proveedor_id.in_(prov_ids),
        ).all()
        for h in historiales:
            hist_por_prov[h.proveedor_id].append(h)

    for f in validas:
        nit = str(f.tercero_nit or "").strip()
        prov = prov_por_nit.get(nit)
        if not prov:
            continue
        clases = ("4",) if f.direccion_documento == "emitida" else ("5", "6", "7")
        registros = [
            r for r in hist_por_prov.get(prov.id, [])
            if r.cuenta_id in cuenta_por_id
            and _es_cuenta_de_resultado(cuenta_por_id[r.cuenta_id].codigo, clases)
        ]
        if not registros:
            continue

        claves = _palabras_clave(getattr(f, "concepto_resumen", None) or "")
        usados, fuente = registros, "historial"
        if claves:
            coinc = [
                r for r in registros
                if r.descripcion and (_palabras_clave(r.descripcion) & claves)
            ]
            if coinc:
                usados, fuente = coinc, "historial_nit_concepto"

        conteo: dict[str, int] = {}
        canonicas: dict[str, CuentaContable] = {}
        for r in usados:
            original = cuenta_por_id.get(r.cuenta_id)
            if not original:
                continue
            cta_canon = canonica_por_id.get(original.id, original)
            canonicas[cta_canon.id] = cta_canon
            conteo[cta_canon.id] = conteo.get(cta_canon.id, 0) + 1
        if not conteo:
            continue

        orden = sorted(conteo.items(), key=lambda kv: (-kv[1], canonicas[kv[0]].codigo))
        cuenta_id, usos = orden[0]
        cta = canonicas[cuenta_id]
        total = sum(conteo.values())
        resultado[f.id] = {
            "cuenta_sugerida": cta.codigo,
            "cuenta_nombre": cta.nombre,
            "fuente": fuente,
            "usos": usos,
            "total": total,
            "porcentaje": round(usos * 100.0 / total, 1) if total else 0.0,
        }
    return resultado
