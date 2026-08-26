"""
Generación de partida doble (secciones 16-17).

Reglas no negociables:
- Nunca se inventa una cuenta: si la factura tiene IVA/retenciones y la
  empresa no tiene esa cuenta configurada, se devuelve un error
  explicando exactamente qué falta — no se genera un asiento a medias.
- TOTAL DÉBITOS = TOTAL CRÉDITOS siempre, o no se persiste (sección 16).
- Régimen Simple (RST): si la empresa está en Régimen Simple no se
  practica retefuente ni ReteICA — solo ReteIVA si aplica.
- Una factura EMITIDA por la propia empresa es una VENTA (ingreso), no
  una compra — usa cuentas de ingreso/clientes/IVA generado, nunca las
  de gasto/proveedores/IVA descontable. Mezclar esto produciría estados
  financieros incorrectos, así que están completamente separadas.
- Una nota crédito usa las mismas cuentas que tendría la factura que
  corrige, pero con débito y crédito invertidos (reduce lo que esa
  factura había generado).
- Un documento de nómina electrónica NO se contabiliza automáticamente
  en esta etapa (esquema XML distinto, sin extracción de conceptos) —
  se niega explícitamente en vez de arriesgar un asiento inventado.
"""
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import (
    Empresa, Factura, Movimiento, TipoMovimiento, CuentaContable, Empleado,
    HistorialTecnicoSiigo,
)


@dataclass
class LineaPartida:
    cuenta_id: str
    cuenta_codigo: str
    cuenta_nombre: str
    tipo: str  # "debito" | "credito"
    valor: float
    descripcion: str = ""
    centro_costo_id: Optional[str] = None
    centro_costo_codigo: Optional[str] = None
    tercero_nit_override: Optional[str] = None      # solo cuando el tercero de ESTA línea es distinto al de la factura (nómina: EPS/AFP)
    tercero_nombre_override: Optional[str] = None


@dataclass
class ResultadoPartida:
    lineas: list = field(default_factory=list)
    total_debito: float = 0.0
    total_credito: float = 0.0
    balanceado: bool = False
    errores: list = field(default_factory=list)


def _totales(lineas: list[LineaPartida]) -> tuple[float, float]:
    debito = round(sum(l.valor for l in lineas if l.tipo == "debito"), 2)
    credito = round(sum(l.valor for l in lineas if l.tipo == "credito"), 2)
    return debito, credito



def _hist_valores(row: HistorialTecnicoSiigo) -> dict:
    try:
        return json.loads(row.valores_columnas_json or "{}")
    except Exception:
        return {}


def _hist_dc(row: HistorialTecnicoSiigo) -> str:
    valores = _hist_valores(row)
    for k, v in valores.items():
        nk = " ".join(str(k or "").upper().split())
        if "DÉBITO O CRÉDITO" in nk or "DEBITO O CREDITO" in nk:
            return str(v or "").strip().upper()[:1]
    return ""


def _hist_valor(row: HistorialTecnicoSiigo) -> float:
    valores = _hist_valores(row)
    for k, v in valores.items():
        nk = " ".join(str(k or "").upper().split())
        if "VALOR DE LA SECUENCIA" in nk:
            try:
                return abs(float(str(v).replace(",", ".")))
            except Exception:
                return 0.0
    return 0.0


def _cuenta_por_codigo(db: Session, empresa_id: str, codigo: str | None) -> Optional[CuentaContable]:
    if not codigo:
        return None
    return db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa_id, CuentaContable.codigo == str(codigo)
    ).first()


def _inferir_control_historial(db: Session, empresa: Empresa, factura: Factura,
                               cuenta_principal: Optional[CuentaContable], rol: str) -> Optional[CuentaContable]:
    """Aprende cuentas de control de comprobantes históricos reales.

    No usa una cuenta base universal. Busca comprobantes históricos que contienen
    la misma cuenta principal y, cuando es posible, el mismo tercero. Solo devuelve
    una cuenta si el patrón observado es estable; de lo contrario deja que el flujo
    pida revisión en vez de inventar una cuenta.
    """
    if not cuenta_principal:
        return None
    filas = db.query(HistorialTecnicoSiigo).filter(
        HistorialTecnicoSiigo.empresa_id == empresa.id
    ).all()
    if not filas:
        return None

    nit_obj = re.sub(r"\D", "", str(factura.tercero_nit or ""))
    grupos: dict[tuple[str, str, str], list[HistorialTecnicoSiigo]] = defaultdict(list)
    for r in filas:
        if not r.numero_documento:
            continue
        grupos[(str(r.tipo_comprobante or ""), str(r.codigo_comprobante or ""), str(r.numero_documento))].append(r)

    grupos_coincidentes = []
    for g in grupos.values():
        principales = [r for r in g if str(r.cuenta_codigo or "") == str(cuenta_principal.codigo)]
        if not principales:
            continue
        if nit_obj:
            exactas = [r for r in principales if re.sub(r"\D", "", str(r.nit or "")) == nit_obj]
            if exactas:
                grupos_coincidentes.append((2, g))
                continue
        grupos_coincidentes.append((1, g))
    if not grupos_coincidentes:
        return None
    mejor_nivel = max(n for n, _ in grupos_coincidentes)
    grupos_coincidentes = [g for n, g in grupos_coincidentes if n == mejor_nivel]

    candidatos = []
    compra = factura.direccion_documento != "emitida"
    for g in grupos_coincidentes:
        posibles = []
        for r in g:
            codigo = str(r.cuenta_codigo or "")
            dc = _hist_dc(r)
            if codigo == str(cuenta_principal.codigo):
                continue
            if rol == "iva_descontable" and codigo.startswith("2408") and dc == "D":
                posibles.append(r)
            elif rol == "iva_generado" and codigo.startswith("2408") and dc == "C":
                posibles.append(r)
            elif rol == "retefuente" and codigo.startswith("2365") and dc == "C":
                posibles.append(r)
            elif rol == "reteica" and codigo.startswith("2368") and dc == "C":
                posibles.append(r)
            elif rol == "reteiva" and codigo.startswith("2367") and dc == "C":
                posibles.append(r)
            elif rol == "inc" and codigo.startswith("24") and not codigo.startswith("2408"):
                posibles.append(r)
            elif rol == "contrapartida_compra" and compra and dc == "C" and (codigo.startswith("11") or codigo.startswith("22") or codigo.startswith("23")) and not codigo.startswith(("2365","2367","2368","2408")):
                posibles.append(r)
            elif rol == "contrapartida_venta" and (not compra) and dc == "D" and (codigo.startswith("11") or codigo.startswith("13")):
                posibles.append(r)
        if rol.startswith("contrapartida") and posibles:
            # La contrapartida principal suele ser la línea de mayor valor dentro
            # del comprobante; evita confundirla con pequeños ajustes/control.
            posibles = sorted(posibles, key=_hist_valor, reverse=True)[:1]
        candidatos.extend(str(r.cuenta_codigo) for r in posibles if r.cuenta_codigo)

    if not candidatos:
        return None
    conteo = Counter(candidatos)
    codigo, usos = conteo.most_common(1)[0]
    # Con evidencia exacta por NIT una observación ya es útil; sin ella pedimos
    # mayoría clara para no convertir una casualidad en regla general.
    total = sum(conteo.values())
    if mejor_nivel < 2 and (usos < 2 or usos / total < 0.70):
        return None
    return _cuenta_por_codigo(db, empresa.id, codigo)


def _resolver_contrapartida_inteligente(db: Session, empresa: Empresa, factura: Factura,
                                         cuenta_principal: Optional[CuentaContable], contrapartida: str,
                                         opciones_validas: tuple[str, ...], rol_historial: str):
    # Si el usuario eligió explícitamente una opción y existe, se respeta.
    mapa = {
        "proveedores": empresa.cuenta_proveedores_id, "caja": empresa.cuenta_caja_id,
        "banco": empresa.cuenta_banco_id, "clientes": empresa.cuenta_clientes_id,
    }
    if contrapartida in opciones_validas and mapa.get(contrapartida):
        return db.get(CuentaContable, mapa[contrapartida]), []
    # Compatibilidad con empresas antiguas que usaban "solo_gastos":
    # ese control ya no se muestra en la interfaz V5, pero conservamos el
    # comportamiento histórico para no romper datos existentes. Si llega una
    # contrapartida no válida para una compra (p. ej. "clientes"), usamos
    # primero la cuenta realmente configurada entre las opciones permitidas.
    if getattr(empresa, "modo_contable", None) == "solo_gastos" and contrapartida not in opciones_validas:
        elegida = _elegir_contrapartida_configurada(empresa, opciones_validas)
        if elegida and mapa.get(elegida):
            return db.get(CuentaContable, mapa[elegida]), []
    aprendida = _inferir_control_historial(db, empresa, factura, cuenta_principal, rol_historial)
    if aprendida:
        return aprendida, []
    # Si no hubo evidencia histórica, recién ahí se usa una cuenta base ya
    # existente como respaldo. Esto mantiene compatibilidad sin convertir las
    # cuentas base en la regla principal de todas las compras/ventas.
    if not contrapartida:
        elegida = _elegir_contrapartida_configurada(empresa, opciones_validas)
        if elegida and mapa.get(elegida):
            return db.get(CuentaContable, mapa[elegida]), []
        return None, [
            "El historial no permite determinar la contrapartida y la empresa no tiene una cuenta de respaldo configurada."
        ]
    return _resolver_contrapartida(db, empresa, contrapartida, opciones_validas)


def _resolver_contrapartida(db: Session, empresa: Empresa, contrapartida: str,
                             opciones_validas: tuple[str, ...]) -> tuple[Optional[CuentaContable], list[str]]:
    errores = []
    mapa = {
        "proveedores": empresa.cuenta_proveedores_id,
        "caja": empresa.cuenta_caja_id,
        "banco": empresa.cuenta_banco_id,
        "clientes": empresa.cuenta_clientes_id,
    }
    if contrapartida not in opciones_validas:
        errores.append(f"Contrapartida inválida: '{contrapartida}' (debe ser una de: {', '.join(opciones_validas)}).")
        return None, errores
    cuenta_id = mapa.get(contrapartida)
    if not cuenta_id:
        errores.append(f"La empresa no tiene configurada la cuenta de '{contrapartida}' "
                        f"(usa PATCH /empresas/{{id}}/cuentas-base).")
        return None, errores
    return db.get(CuentaContable, cuenta_id), errores


_PALABRAS_SERVICIO = re.compile(
    r"servicio|honorario|asesor|consultor|mantenimiento|arrendamiento|transporte|"
    r"vigilancia|aseo|publicidad|capacitaci[oó]n|reparaci[oó]n", re.IGNORECASE)
_PALABRAS_COMPRA = re.compile(
    r"compra|mercanc[ií]a|art[ií]culo|producto|materia\s*prima|insumo|repuesto|"
    r"equipo|inventario|suministro", re.IGNORECASE)
_PALABRA_GENERADO = re.compile(r"generad[oa]", re.IGNORECASE)
_PALABRA_DESCONTABLE = re.compile(r"descontable", re.IGNORECASE)


def _seleccionar_cuenta_iva_por_tasa(db: Session, empresa: Empresa, subtotal: float, iva: float,
                                      concepto: Optional[str] = None,
                                      tipo_iva: str = "descontable") -> Optional[CuentaContable]:
    """
    En vez de usar siempre LA MISMA cuenta de IVA configurada en
    "Cuentas base" (que solo admite una), busca entre las cuentas
    PROPIAS de la empresa con código que empieza por "2408" (grupo de
    IVA en el PUC) una cuyo NOMBRE mencione la tasa real de esta
    factura (19% o 5%, calculada del propio documento) — esto requiere
    haber cargado un balance por tercero con los nombres reales de esas
    cuentas (sección pedida por el usuario). Si no encuentra una
    coincidencia específica, devuelve None y quien llama usa la cuenta
    única configurada, como antes.

    tipo_iva ("descontable" para compras, "generado" para ventas): con
    varias cuentas 2408 a la vez (compras y ventas, o distintas tasas),
    primero se filtra por esta polaridad — nunca se debe usar una
    cuenta de "IVA Descontable" para una VENTA ni viceversa, error real
    encontrado (una venta terminó usando "IVA Descontable Compras 19%").
    Si sigue habiendo más de una coincidencia, se usa el concepto de la
    factura para desempatar entre "servicio" y "compra"; si continúa
    sin ser claro, no se arriesga.
    """
    if subtotal <= 0 or iva <= 0:
        return None
    tasa = round(iva / subtotal * 100)
    if tasa not in (19, 5):
        # Tasas no estándar (redondeos raros, IVA a otro % por un
        # descuento, etc.) — no se arriesga una coincidencia falsa.
        return None

    candidatas = db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa.id, CuentaContable.codigo.like("2408%")
    ).all()
    patron = re.compile(rf"\b{tasa}\b")
    coincidencias = [c for c in candidatas if patron.search(c.nombre)]

    if len(coincidencias) > 1:
        patron_polaridad = _PALABRA_GENERADO if tipo_iva == "generado" else _PALABRA_DESCONTABLE
        con_polaridad = [c for c in coincidencias if patron_polaridad.search(c.nombre)]
        if con_polaridad:
            coincidencias = con_polaridad

    if len(coincidencias) == 1:
        return coincidencias[0]

    if len(coincidencias) > 1 and concepto:
        es_servicio = bool(_PALABRAS_SERVICIO.search(concepto))
        es_compra = bool(_PALABRAS_COMPRA.search(concepto))
        if es_servicio and not es_compra:
            candidatas_servicio = [c for c in coincidencias if re.search(r"servicio", c.nombre, re.IGNORECASE)]
            if len(candidatas_servicio) == 1:
                return candidatas_servicio[0]
        elif es_compra and not es_servicio:
            candidatas_compra = [c for c in coincidencias if re.search(r"compra", c.nombre, re.IGNORECASE)]
            if len(candidatas_compra) == 1:
                return candidatas_compra[0]

    # Sigue ambiguo -> no se arriesga a elegir mal.
    return None


def _descripcion_comprobante(factura: Factura) -> str:
    """
    Descripción corta y consistente para TODAS las líneas de un mismo
    comprobante — confirmado por el usuario: "Prefijo" + "-" + "Folio"
    (los títulos reales del propio Excel de la DIAN, ya guardados como
    factura.prefijo/factura.numero_factura) más una descripción corta
    de lo que trae la factura. Antes cada línea del mismo comprobante
    (gasto, IVA, contrapartida) llevaba un texto distinto y genérico
    ("Factura X", "IVA descontable", "Contrapartida (...)") — ahora
    todas comparten esta misma descripción real.
    """
    partes_doc = [p for p in [factura.prefijo, factura.numero_factura] if p]
    doc = "-".join(partes_doc)

    descripcion_corta = ""
    if factura.conceptos_json:
        try:
            items = json.loads(factura.conceptos_json)
            descripciones = [
                i.get("descripcion", "").strip() for i in items
                if i.get("descripcion", "").strip() and i.get("descripcion") != "(sin descripción)"
            ]
            descripcion_corta = "; ".join(dict.fromkeys(descripciones))[:200]  # sin duplicados, orden preservado
        except (ValueError, TypeError):
            descripcion_corta = ""

    if doc and descripcion_corta:
        return f"{doc} {descripcion_corta}"
    if doc:
        return doc
    if descripcion_corta:
        return descripcion_corta
    return f"Factura {factura.numero_factura or ''}".strip()


def _generar_partida_compra(db: Session, empresa: Empresa, factura: Factura,
                             cuenta_gasto_id: str, contrapartida: str,
                             centro_costo=None) -> ResultadoPartida:
    """Factura RECIBIDA de un tercero: gasto/costo + IVA descontable, contrapartida Proveedores/Caja/Banco."""
    errores = []
    cuenta_gasto = db.get(CuentaContable, cuenta_gasto_id) if cuenta_gasto_id else None
    if not cuenta_gasto:
        errores.append("No se indicó (o no existe) la cuenta de gasto/costo para esta factura.")
    elif cuenta_gasto.codigo and cuenta_gasto.codigo[0] == "4":
        # Caso real detectado: una venta terminó procesándose por este
        # camino (compra) usando su propia cuenta de INGRESO como si
        # fuera de gasto — quedó debitada en vez de acreditada. Nunca
        # se genera una partida así; se avisa con el motivo exacto.
        errores.append(
            f"La cuenta {cuenta_gasto.codigo} ({cuenta_gasto.nombre}) es una cuenta de INGRESO (empieza por 4), "
            f"no de gasto — no se puede usar aquí. Si esta factura es una VENTA, revisa su dirección "
            f"(emitida/recibida) antes de generar la partida."
        )

    subtotal = float(factura.subtotal or 0)
    iva = float(factura.iva or 0)
    inc = float(factura.inc or 0)
    retenciones = json.loads(factura.retenciones_json) if factura.retenciones_json else {}
    retefuente = float(retenciones.get("retefuente", 0) or 0)
    reteica = float(retenciones.get("reteica", 0) or 0)
    reteiva = float(retenciones.get("reteiva", 0) or 0)

    if empresa.regimen_simple:
        retefuente = 0.0
        reteica = 0.0

    lineas = []
    descripcion = _descripcion_comprobante(factura)
    if cuenta_gasto:
        # El centro de costo se aplica a la línea de gasto/costo (donde
        # tiene sentido contable de verdad) — no a IVA, retenciones ni a
        # la contrapartida, que no pertenecen a un centro de costo.
        lineas.append(LineaPartida(cuenta_gasto.id, cuenta_gasto.codigo, cuenta_gasto.nombre,
                                    "debito", subtotal, descripcion,
                                    centro_costo_id=centro_costo.id if centro_costo else None,
                                    centro_costo_codigo=centro_costo.codigo if centro_costo else None))

    if iva > 0:
        if empresa.responsable_iva:
            cta_por_tasa = _seleccionar_cuenta_iva_por_tasa(db, empresa, subtotal, iva, factura.concepto_resumen,
                                                              tipo_iva="descontable")
            if cta_por_tasa:
                lineas.append(LineaPartida(cta_por_tasa.id, cta_por_tasa.codigo, cta_por_tasa.nombre,
                                            "debito", iva, descripcion))
            else:
                cta = _inferir_control_historial(db, empresa, factura, cuenta_gasto, "iva_descontable")
                if not cta and empresa.cuenta_iva_descontable_id:
                    cta = db.get(CuentaContable, empresa.cuenta_iva_descontable_id)
                if not cta:
                    errores.append("La factura tiene IVA y el historial no permite determinar con certeza la cuenta de IVA descontable.")
                else:
                    lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "debito", iva, descripcion))
        elif lineas:
            lineas[0].valor += iva

    if inc > 0:
        cta = _inferir_control_historial(db, empresa, factura, cuenta_gasto, "inc")
        if not cta and empresa.cuenta_inc_id:
            cta = db.get(CuentaContable, empresa.cuenta_inc_id)
        if not cta:
            errores.append("La factura tiene INC y el historial no permite determinar con certeza la cuenta correspondiente.")
        else:
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "debito", inc, descripcion))

    if retefuente > 0:
        cta = _inferir_control_historial(db, empresa, factura, cuenta_gasto, "retefuente")
        if not cta and empresa.cuenta_retefuente_id:
            cta = db.get(CuentaContable, empresa.cuenta_retefuente_id)
        if not cta:
            errores.append("La factura tiene retención en la fuente y el historial no permite determinar con certeza la cuenta correspondiente.")
        else:
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", retefuente, descripcion))

    if reteica > 0:
        cta = _inferir_control_historial(db, empresa, factura, cuenta_gasto, "reteica")
        if not cta and empresa.cuenta_reteica_id:
            cta = db.get(CuentaContable, empresa.cuenta_reteica_id)
        if not cta:
            errores.append("La factura tiene ReteICA y el historial no permite determinar con certeza la cuenta correspondiente.")
        else:
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", reteica, descripcion))

    if reteiva > 0:
        cta = _inferir_control_historial(db, empresa, factura, cuenta_gasto, "reteiva")
        if not cta and empresa.cuenta_reteiva_id:
            cta = db.get(CuentaContable, empresa.cuenta_reteiva_id)
        if not cta:
            errores.append("La factura tiene ReteIVA y el historial no permite determinar con certeza la cuenta correspondiente.")
        else:
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", reteiva, descripcion))

    cuenta_contra, errores_contra = _resolver_contrapartida_inteligente(
        db, empresa, factura, cuenta_gasto, contrapartida, ("proveedores", "caja", "banco"), "contrapartida_compra"
    )
    errores += errores_contra

    total_debito, total_credito_parcial = _totales(lineas)
    valor_contrapartida = round(total_debito - total_credito_parcial, 2)
    if not errores and cuenta_contra and valor_contrapartida > 0:
        lineas.append(LineaPartida(cuenta_contra.id, cuenta_contra.codigo, cuenta_contra.nombre,
                                    "credito", valor_contrapartida, descripcion))

    total_debito, total_credito = _totales(lineas)
    balanceado = abs(total_debito - total_credito) < 0.01 and not errores
    if not errores and not balanceado:
        errores.append(f"El comprobante no cuadra: débito {total_debito} vs crédito {total_credito} "
                        f"(diferencia {round(total_debito - total_credito, 2)}).")

    return ResultadoPartida(lineas=lineas, total_debito=total_debito, total_credito=total_credito,
                             balanceado=balanceado, errores=errores)


def _generar_partida_venta(db: Session, empresa: Empresa, factura: Factura,
                            cuenta_ingreso_id: str, contrapartida: str,
                            centro_costo=None) -> ResultadoPartida:
    """
    Factura EMITIDA por la propia empresa: es un ingreso, no un gasto.
    Ingreso + IVA generado (créditos) contra Clientes/Caja/Banco (débito).
    Nota: las retenciones que un cliente practica sobre una venta se
    tratan como un derecho a favor (anticipo de impuestos), cuenta que
    no está modelada todavía — si la factura trae retenciones, el
    comprobante puede no cuadrar y quedará marcado con el error exacto
    en vez de contabilizarse de forma incompleta o incorrecta.
    """
    errores = []
    cuenta_ingreso = db.get(CuentaContable, cuenta_ingreso_id) if cuenta_ingreso_id else None
    if not cuenta_ingreso:
        errores.append("No se indicó (o no existe) la cuenta de ingreso para esta factura emitida.")
    elif cuenta_ingreso.codigo and cuenta_ingreso.codigo[0] in ("5", "6", "7"):
        errores.append(
            f"La cuenta {cuenta_ingreso.codigo} ({cuenta_ingreso.nombre}) es una cuenta de GASTO/COSTO "
            f"(empieza por {cuenta_ingreso.codigo[0]}), no de ingreso — no se puede usar aquí para una venta."
        )

    subtotal = float(factura.subtotal or 0)
    iva = float(factura.iva or 0)
    inc = float(factura.inc or 0)

    lineas = []
    descripcion = _descripcion_comprobante(factura)
    if cuenta_ingreso:
        lineas.append(LineaPartida(cuenta_ingreso.id, cuenta_ingreso.codigo, cuenta_ingreso.nombre,
                                    "credito", subtotal, descripcion,
                                    centro_costo_id=centro_costo.id if centro_costo else None,
                                    centro_costo_codigo=centro_costo.codigo if centro_costo else None))

    if iva > 0:
        if empresa.responsable_iva:
            cta_por_tasa = _seleccionar_cuenta_iva_por_tasa(db, empresa, subtotal, iva,
                                                              factura.concepto_resumen, tipo_iva="generado")
            if cta_por_tasa:
                lineas.append(LineaPartida(cta_por_tasa.id, cta_por_tasa.codigo, cta_por_tasa.nombre,
                                            "credito", iva, descripcion))
            else:
                cta = _inferir_control_historial(db, empresa, factura, cuenta_ingreso, "iva_generado")
                if not cta and empresa.cuenta_iva_generado_id:
                    cta = db.get(CuentaContable, empresa.cuenta_iva_generado_id)
                if not cta:
                    errores.append("La factura tiene IVA y el historial no permite determinar con certeza la cuenta de IVA generado.")
                else:
                    lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", iva, descripcion))
        elif lineas:
            lineas[0].valor += iva

    if inc > 0:
        cta = _inferir_control_historial(db, empresa, factura, cuenta_ingreso, "inc")
        if not cta and empresa.cuenta_inc_id:
            cta = db.get(CuentaContable, empresa.cuenta_inc_id)
        if not cta:
            errores.append("La factura tiene INC y el historial no permite determinar con certeza la cuenta correspondiente.")
        else:
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", inc, descripcion))

    cuenta_contra, errores_contra = _resolver_contrapartida_inteligente(
        db, empresa, factura, cuenta_ingreso, contrapartida, ("clientes", "caja", "banco"), "contrapartida_venta"
    )
    errores += errores_contra

    total_debito_parcial, total_credito = _totales(lineas)
    valor_contrapartida = round(total_credito - total_debito_parcial, 2)
    if not errores and cuenta_contra and valor_contrapartida > 0:
        lineas.append(LineaPartida(cuenta_contra.id, cuenta_contra.codigo, cuenta_contra.nombre,
                                    "debito", valor_contrapartida, descripcion))

    total_debito, total_credito = _totales(lineas)
    balanceado = abs(total_debito - total_credito) < 0.01 and not errores
    if not errores and not balanceado:
        retenciones = json.loads(factura.retenciones_json) if factura.retenciones_json else {}
        tiene_retenciones = any(float(v or 0) > 0 for v in retenciones.values())
        extra = (" La factura trae retenciones practicadas por el cliente, que todavía no se "
                 "modelan automáticamente en el lado de venta — regístralas manualmente."
                 if tiene_retenciones else "")
        errores.append(f"El comprobante no cuadra: débito {total_debito} vs crédito {total_credito} "
                        f"(diferencia {round(total_debito - total_credito, 2)}).{extra}")

    return ResultadoPartida(lineas=lineas, total_debito=total_debito, total_credito=total_credito,
                             balanceado=balanceado, errores=errores)


def _elegir_contrapartida_configurada(empresa: Empresa, orden: tuple[str, ...]) -> Optional[str]:
    """
    Devuelve la primera opción de `orden` que la empresa realmente tiene
    configurada en "Cuentas base" — nunca asume ciegamente "proveedores"
    (una empresa en modo "solo_gastos" puede no manejar proveedores en
    absoluto y usar solo caja/banco, caso real reportado). Si ninguna
    está configurada, devuelve None y quien llama deja la contrapartida
    tal cual venía, para que el error de "cuenta no configurada" sea
    claro sobre cuál falta.
    """
    mapa = {
        "proveedores": empresa.cuenta_proveedores_id, "caja": empresa.cuenta_caja_id,
        "banco": empresa.cuenta_banco_id, "clientes": empresa.cuenta_clientes_id,
    }
    for opcion in orden:
        if mapa.get(opcion):
            return opcion
    return None


def _generar_partida_nomina_multilinea(db: Session, empresa: Empresa, factura: Factura,
                                        centro_costo_id: Optional[str]) -> Optional[ResultadoPartida]:
    """
    Asiento multilínea real de nómina, verificado contra un comprobante
    real de Siigo (pedido explícito del usuario, con dos XML reales de
    nómina electrónica de la DIAN aportados como referencia):

    - Salario (+ auxilio de transporte si aplica) se debita completo a
      la cuenta de gasto, y se acredita repartido entre: la EPS del
      empleado (deducción de salud), su fondo de pensión (deducción de
      pensión), y la cuenta de nómina por pagar por el NETO restante —
      exactamente como en el comprobante real (una sola línea de gasto,
      tres créditos que suman lo mismo).
    - Cesantías, intereses sobre cesantías, prima de servicios y
      vacaciones se provisionan aparte, con las fórmulas legales fijas
      colombianas sobre el salario devengado (8.3333%, 12% anual sobre
      las cesantías, 8.3333% y 4.1667% respectivamente) — verificadas
      al peso contra el comprobante real del usuario. Cada una es
      opcional: si la empresa no configuró esa cuenta, simplemente no
      se genera esa línea (nunca bloquea el resto).
    - ARL y caja de compensación NO se calculan automáticamente (varían
      por empresa/clase de riesgo, no hay un porcentaje único de ley) —
      quedan para que el usuario las registre aparte si las necesita.

    Devuelve None si faltan los prerrequisitos mínimos (sin desglose
    real extraído del XML, sin ficha de empleado con NIT, o sin las
    cuentas base de salario/nómina por pagar configuradas) — en ese
    caso quien llama cae al camino simple de un solo gasto+contrapartida
    elegido a mano, como antes.
    """
    if not factura.nomina_detalle_json or not factura.tercero_nit:
        return None
    try:
        detalle = json.loads(factura.nomina_detalle_json)
    except (ValueError, TypeError):
        return None

    empleado = db.query(Empleado).filter(
        Empleado.empresa_id == empresa.id, Empleado.nit == factura.tercero_nit
    ).first()
    if not empleado or not empresa.cuenta_salario_id or not empresa.cuenta_nomina_por_pagar_id:
        return None

    def cta(cuenta_id):
        return db.get(CuentaContable, cuenta_id) if cuenta_id else None

    salario = float(detalle.get("devengado_basico") or 0)
    transporte = float(detalle.get("devengado_transporte") or 0)
    salud = float(detalle.get("deduccion_salud") or 0)
    pension = float(detalle.get("deduccion_pension") or 0)
    neto_a_pagar = round((salario + transporte) - (salud + pension), 2)
    nombre_empleado = empleado.nombre or empleado.nit

    errores: list[str] = []
    lineas: list[LineaPartida] = []

    cta_salario = cta(empresa.cuenta_salario_id)
    if salario > 0:
        if cta_salario:
            lineas.append(LineaPartida(cta_salario.id, cta_salario.codigo, cta_salario.nombre, "debito", salario,
                                        f"Nómina {factura.numero_factura or ''} — salario — {nombre_empleado}".strip(),
                                        centro_costo_id))
        else:
            errores.append("Falta configurar la cuenta de Salario en Empresas → Cuentas de nómina.")

    if transporte > 0:
        cta_transporte = cta(empresa.cuenta_auxilio_transporte_id)
        if cta_transporte:
            lineas.append(LineaPartida(cta_transporte.id, cta_transporte.codigo, cta_transporte.nombre, "debito",
                                        transporte, f"Nómina {factura.numero_factura or ''} — auxilio de transporte — {nombre_empleado}".strip(),
                                        centro_costo_id))
        else:
            errores.append("Falta configurar la cuenta de Auxilio de transporte en Empresas → Cuentas de nómina.")

    if salud > 0:
        cta_salud = cta(empresa.cuenta_salud_por_pagar_id)
        if not cta_salud:
            errores.append("Falta configurar la cuenta de Salud por pagar en Empresas → Cuentas de nómina.")
        elif not empleado.eps_nit:
            errores.append(f"Falta el NIT de la EPS en la ficha del empleado {nombre_empleado} (módulo Empleados).")
        else:
            lineas.append(LineaPartida(cta_salud.id, cta_salud.codigo, cta_salud.nombre, "credito", salud,
                                        f"Salud por pagar — {empleado.eps_nombre or empleado.eps_nit}",
                                        tercero_nit_override=empleado.eps_nit, tercero_nombre_override=empleado.eps_nombre))

    if pension > 0:
        cta_pension = cta(empresa.cuenta_pension_por_pagar_id)
        if not cta_pension:
            errores.append("Falta configurar la cuenta de Pensión por pagar en Empresas → Cuentas de nómina.")
        elif not empleado.afp_nit:
            errores.append(f"Falta el NIT del fondo de pensión en la ficha del empleado {nombre_empleado} (módulo Empleados).")
        else:
            lineas.append(LineaPartida(cta_pension.id, cta_pension.codigo, cta_pension.nombre, "credito", pension,
                                        f"Pensión por pagar — {empleado.afp_nombre or empleado.afp_nit}",
                                        tercero_nit_override=empleado.afp_nit, tercero_nombre_override=empleado.afp_nombre))

    if neto_a_pagar > 0:
        cta_nomina_pagar = cta(empresa.cuenta_nomina_por_pagar_id)
        if cta_nomina_pagar:
            lineas.append(LineaPartida(cta_nomina_pagar.id, cta_nomina_pagar.codigo, cta_nomina_pagar.nombre,
                                        "credito", neto_a_pagar, f"Nómina por pagar — {nombre_empleado}"))
        else:
            errores.append("Falta configurar la cuenta de Nómina por pagar en Empresas → Cuentas de nómina.")

    def _provision(valor: float, cuenta_gasto_id, cuenta_pagar_id, nombre_concepto: str):
        if valor <= 0:
            return
        cg, cp = cta(cuenta_gasto_id), cta(cuenta_pagar_id)
        if not cg or not cp:
            return  # provisión opcional: si no está configurada, no se genera (no bloquea el resto)
        lineas.append(LineaPartida(cg.id, cg.codigo, cg.nombre, "debito", valor,
                                    f"{nombre_concepto} — {nombre_empleado}", centro_costo_id))
        lineas.append(LineaPartida(cp.id, cp.codigo, cp.nombre, "credito", valor,
                                    f"{nombre_concepto} por pagar — {nombre_empleado}"))

    cesantias = round(salario * 0.0833333, 2)
    intereses_cesantias = round(cesantias * 0.12, 2)
    prima = round(salario * 0.0833333, 2)
    vacaciones = round(salario * 0.0416667, 2)

    _provision(cesantias, empresa.cuenta_cesantias_id, empresa.cuenta_cesantias_por_pagar_id, "Cesantías")
    _provision(intereses_cesantias, empresa.cuenta_intereses_cesantias_id,
               empresa.cuenta_intereses_cesantias_por_pagar_id, "Intereses sobre cesantías")
    _provision(prima, empresa.cuenta_prima_id, empresa.cuenta_prima_por_pagar_id, "Prima de servicios")
    _provision(vacaciones, empresa.cuenta_vacaciones_id, empresa.cuenta_vacaciones_por_pagar_id, "Vacaciones")

    total_debito, total_credito = _totales(lineas)
    balanceado = abs(total_debito - total_credito) < 0.01 and not errores
    return ResultadoPartida(lineas=lineas, total_debito=total_debito, total_credito=total_credito,
                             balanceado=balanceado, errores=errores)


def generar_partida(db: Session, empresa: Empresa, factura: Factura,
                     cuenta_gasto_id: str, contrapartida: str = "proveedores",
                     centro_costo=None) -> ResultadoPartida:
    """
    Punto de entrada único. Enruta según la clasificación real del
    documento (sección reportada por el usuario: la descarga de la DIAN
    mezcla facturas emitidas/recibidas, notas crédito/débito y nómina —
    cada una necesita un tratamiento contable distinto, nunca el mismo).
    centro_costo es opcional: si se indica, se aplica a la línea de
    gasto/ingreso (nunca a IVA, retenciones ni contrapartida).
    """
    if factura.naturaleza_documento == "nomina":
        resultado_multilinea = _generar_partida_nomina_multilinea(db, empresa, factura, centro_costo)
        if resultado_multilinea is not None:
            return resultado_multilinea
        # Sin los prerrequisitos del asiento multilínea (falta ficha de
        # empleado, cuentas de nómina configuradas, o desglose real del
        # XML) — se sigue permitiendo el registro manual simple de
        # siempre, con la cuenta y contrapartida que el usuario elija.
        resultado = _generar_partida_compra(db, empresa, factura, cuenta_gasto_id, contrapartida, centro_costo)
        total_debito, total_credito = _totales(resultado.lineas)
        return ResultadoPartida(lineas=resultado.lineas, total_debito=total_debito,
                                 total_credito=total_credito, balanceado=resultado.balanceado,
                                 errores=resultado.errores)

    # Una factura EMITIDA real (no nómina, ya se descartó arriba) SIEMPRE
    # va por el camino de venta — sin importar el modo contable. El
    # módulo "Facturas Emitidas" ya garantiza que solo llegan ventas
    # genuinas aquí (nunca nómina, eso se maneja aparte arriba); forzar
    # esto por "solo_gastos" invertía una venta real (bug real reportado:
    # una cuenta de INGRESO terminaba debitada en vez de acreditada).
    if factura.direccion_documento == "emitida":
        resultado = _generar_partida_venta(db, empresa, factura, cuenta_gasto_id, contrapartida, centro_costo)
    else:
        resultado = _generar_partida_compra(db, empresa, factura, cuenta_gasto_id, contrapartida, centro_costo)

    if factura.naturaleza_documento == "nota_credito" and resultado.lineas:
        # Misma cuenta, débito y crédito invertidos: una nota crédito
        # reduce lo que la factura original había generado.
        for linea in resultado.lineas:
            linea.tipo = "credito" if linea.tipo == "debito" else "debito"
            linea.descripcion = f"Nota crédito — {linea.descripcion}"
        resultado.total_debito, resultado.total_credito = resultado.total_credito, resultado.total_debito

    return resultado


def persistir_partida(db: Session, empresa_id: str, factura: Factura,
                       resultado: ResultadoPartida) -> list[Movimiento]:
    """
    Solo se llama si resultado.balanceado es True (sección 16: nunca se
    contabiliza un comprobante descuadrado). Si la factura ya tenía
    movimientos de un intento anterior, se reemplazan.
    """
    if not resultado.balanceado:
        raise ValueError("No se puede persistir una partida descuadrada o con errores.")

    db.query(Movimiento).filter(Movimiento.factura_id == factura.id).delete()

    movimientos = []
    for i, linea in enumerate(resultado.lineas):
        mov = Movimiento(
            empresa_id=empresa_id, factura_id=factura.id, cuenta_id=linea.cuenta_id,
            centro_costo_id=linea.centro_costo_id,
            tipo=TipoMovimiento(linea.tipo), valor=linea.valor,
            descripcion=linea.descripcion, orden=i,
            tercero_nit_override=linea.tercero_nit_override,
            tercero_nombre_override=linea.tercero_nombre_override,
        )
        db.add(mov)
        movimientos.append(mov)
    db.flush()
    return movimientos
