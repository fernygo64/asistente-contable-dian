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
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import Empresa, Factura, Movimiento, TipoMovimiento, CuentaContable


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


def _seleccionar_cuenta_iva_por_tasa(db: Session, empresa: Empresa, subtotal: float, iva: float,
                                      concepto: Optional[str] = None) -> Optional[CuentaContable]:
    """
    En vez de usar siempre LA MISMA cuenta de IVA configurada en
    "Cuentas base" (que solo admite una), busca entre las cuentas
    PROPIAS de la empresa con código que empieza por "2408" (grupo de
    IVA en el PUC) una cuyo NOMBRE mencione la tasa real de esta
    factura (19% o 5%, calculada del propio documento) — esto requiere
    haber cargado un balance por tercero con los nombres reales de esas
    cuentas (sección pedida por el usuario). Si no encuentra una
    coincidencia específica, devuelve None y quien llama usa la cuenta
    de IVA descontable única configurada, como antes.

    Un plan de cuentas real puede tener VARIAS cuentas para la misma
    tasa (ej. "IVA Descontable Compras 19%" y "IVA Descontable
    Servicios 19%" a la vez — confirmado con un balance real) — cuando
    pasa eso, se usa el concepto de la factura para desempatar entre
    "servicio" y "compra"; si sigue sin ser claro, no se arriesga.
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


def _generar_partida_compra(db: Session, empresa: Empresa, factura: Factura,
                             cuenta_gasto_id: str, contrapartida: str,
                             centro_costo=None) -> ResultadoPartida:
    """Factura RECIBIDA de un tercero: gasto/costo + IVA descontable, contrapartida Proveedores/Caja/Banco."""
    errores = []
    cuenta_gasto = db.get(CuentaContable, cuenta_gasto_id) if cuenta_gasto_id else None
    if not cuenta_gasto:
        errores.append("No se indicó (o no existe) la cuenta de gasto/costo para esta factura.")

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
    if cuenta_gasto:
        # El centro de costo se aplica a la línea de gasto/costo (donde
        # tiene sentido contable de verdad) — no a IVA, retenciones ni a
        # la contrapartida, que no pertenecen a un centro de costo.
        lineas.append(LineaPartida(cuenta_gasto.id, cuenta_gasto.codigo, cuenta_gasto.nombre,
                                    "debito", subtotal, f"Factura {factura.numero_factura or ''}",
                                    centro_costo_id=centro_costo.id if centro_costo else None,
                                    centro_costo_codigo=centro_costo.codigo if centro_costo else None))

    if iva > 0:
        if empresa.responsable_iva:
            cta_por_tasa = _seleccionar_cuenta_iva_por_tasa(db, empresa, subtotal, iva, factura.concepto_resumen)
            if cta_por_tasa:
                tasa_detectada = round(iva / subtotal * 100) if subtotal > 0 else None
                lineas.append(LineaPartida(cta_por_tasa.id, cta_por_tasa.codigo, cta_por_tasa.nombre,
                                            "debito", iva, f"IVA descontable {tasa_detectada}% (detectado automáticamente)"))
            elif not empresa.cuenta_iva_descontable_id:
                errores.append("La factura tiene IVA pero la empresa no tiene configurada la "
                                "cuenta de IVA descontable (ni una cuenta 2408 propia que mencione la tasa).")
            else:
                cta = db.get(CuentaContable, empresa.cuenta_iva_descontable_id)
                lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "debito", iva, "IVA descontable"))
        elif lineas:
            lineas[0].valor += iva

    if inc > 0:
        if not empresa.cuenta_inc_id:
            errores.append("La factura tiene INC pero la empresa no tiene configurada la cuenta de INC.")
        else:
            cta = db.get(CuentaContable, empresa.cuenta_inc_id)
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "debito", inc, "INC"))

    if retefuente > 0:
        if not empresa.cuenta_retefuente_id:
            errores.append("La factura tiene retención en la fuente pero la empresa no tiene configurada esa cuenta.")
        else:
            cta = db.get(CuentaContable, empresa.cuenta_retefuente_id)
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", retefuente, "Retefuente"))

    if reteica > 0:
        if not empresa.cuenta_reteica_id:
            errores.append("La factura tiene ReteICA pero la empresa no tiene configurada esa cuenta.")
        else:
            cta = db.get(CuentaContable, empresa.cuenta_reteica_id)
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", reteica, "ReteICA"))

    if reteiva > 0:
        if not empresa.cuenta_reteiva_id:
            errores.append("La factura tiene ReteIVA pero la empresa no tiene configurada esa cuenta.")
        else:
            cta = db.get(CuentaContable, empresa.cuenta_reteiva_id)
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", reteiva, "ReteIVA"))

    cuenta_contra, errores_contra = _resolver_contrapartida(db, empresa, contrapartida,
                                                              ("proveedores", "caja", "banco"))
    errores += errores_contra

    total_debito, total_credito_parcial = _totales(lineas)
    valor_contrapartida = round(total_debito - total_credito_parcial, 2)
    if not errores and cuenta_contra and valor_contrapartida > 0:
        lineas.append(LineaPartida(cuenta_contra.id, cuenta_contra.codigo, cuenta_contra.nombre,
                                    "credito", valor_contrapartida, f"Contrapartida ({contrapartida})"))

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

    subtotal = float(factura.subtotal or 0)
    iva = float(factura.iva or 0)
    inc = float(factura.inc or 0)

    lineas = []
    if cuenta_ingreso:
        lineas.append(LineaPartida(cuenta_ingreso.id, cuenta_ingreso.codigo, cuenta_ingreso.nombre,
                                    "credito", subtotal, f"Venta — Factura {factura.numero_factura or ''}",
                                    centro_costo_id=centro_costo.id if centro_costo else None,
                                    centro_costo_codigo=centro_costo.codigo if centro_costo else None))

    if iva > 0:
        if empresa.responsable_iva:
            if not empresa.cuenta_iva_generado_id:
                errores.append("La factura tiene IVA pero la empresa no tiene configurada la "
                                "cuenta de IVA generado.")
            else:
                cta = db.get(CuentaContable, empresa.cuenta_iva_generado_id)
                lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", iva, "IVA generado"))
        elif lineas:
            lineas[0].valor += iva

    if inc > 0:
        if not empresa.cuenta_inc_id:
            errores.append("La factura tiene INC pero la empresa no tiene configurada la cuenta de INC.")
        else:
            cta = db.get(CuentaContable, empresa.cuenta_inc_id)
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", inc, "INC"))

    cuenta_contra, errores_contra = _resolver_contrapartida(db, empresa, contrapartida,
                                                              ("clientes", "caja", "banco"))
    errores += errores_contra

    total_debito_parcial, total_credito = _totales(lineas)
    valor_contrapartida = round(total_credito - total_debito_parcial, 2)
    if not errores and cuenta_contra and valor_contrapartida > 0:
        lineas.append(LineaPartida(cuenta_contra.id, cuenta_contra.codigo, cuenta_contra.nombre,
                                    "debito", valor_contrapartida, f"Contrapartida ({contrapartida})"))

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
        # No hay extracción automática de conceptos de nómina (esquema
        # XML distinto) — pero SÍ se permite que el usuario la registre
        # manualmente, eligiendo su propia cuenta y contrapartida, igual
        # que cualquier otro gasto. Nunca se sugiere sola ni entra en el
        # "usar sugerencia" masivo (eso sigue excluyendo nómina aparte).
        resultado = _generar_partida_compra(db, empresa, factura, cuenta_gasto_id, contrapartida, centro_costo)
        total_debito, total_credito = _totales(resultado.lineas)
        return ResultadoPartida(lineas=resultado.lineas, total_debito=total_debito,
                                 total_credito=total_credito, balanceado=resultado.balanceado,
                                 errores=resultado.errores)

    # En modo "solo_gastos" (persona natural que solo lleva sus propios
    # gastos), TODO se contabiliza por el lado de gasto sin importar lo
    # que diga la clasificación Emitido/Recibido de la DIAN — evita
    # exigir cuentas de ingresos/clientes que esta empresa no necesita.
    if empresa.modo_contable == "solo_gastos":
        contrapartida_efectiva = contrapartida
        if contrapartida == "clientes":
            # "Clientes" no aplica en este modo — se usa lo que la
            # empresa SÍ tenga configurado (proveedores, si no caja, si
            # no banco), nunca se asume "proveedores" a ciegas.
            contrapartida_efectiva = _elegir_contrapartida_configurada(
                empresa, ("proveedores", "caja", "banco")) or "proveedores"
        resultado = _generar_partida_compra(db, empresa, factura, cuenta_gasto_id, contrapartida_efectiva, centro_costo)
    elif factura.direccion_documento == "emitida":
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
        )
        db.add(mov)
        movimientos.append(mov)
    db.flush()
    return movimientos
