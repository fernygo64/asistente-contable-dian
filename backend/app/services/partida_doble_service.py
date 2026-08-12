"""
Generación de partida doble (secciones 16-17).

Reglas no negociables:
- Nunca se inventa una cuenta: si la factura tiene IVA/retenciones y la
  empresa no tiene esa cuenta configurada, se devuelve un error
  explicando exactamente qué falta — no se genera un asiento a medias.
- TOTAL DÉBITOS = TOTAL CRÉDITOS siempre, o no se persiste (sección 16).
- Régimen Simple (RST): igual que en el extractor ya construido, si la
  empresa está en Régimen Simple no se practica retefuente ni ReteICA
  — solo ReteIVA si aplica.
"""
import json
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


@dataclass
class ResultadoPartida:
    lineas: list = field(default_factory=list)
    total_debito: float = 0.0
    total_credito: float = 0.0
    balanceado: bool = False
    errores: list = field(default_factory=list)


def generar_partida(db: Session, empresa: Empresa, factura: Factura,
                     cuenta_gasto_id: str, contrapartida: str = "proveedores") -> ResultadoPartida:
    """
    contrapartida: "proveedores" | "caja" | "banco" — igual que en el
    extractor de facturas (Opción A) ya entregado, la contrapartida
    queda abierta a elección del usuario, no fija.
    """
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
        # Misma regla de negocio ya validada en el extractor de facturas:
        # RST no practica retefuente ni ReteICA, solo ReteIVA si aplica.
        retefuente = 0.0
        reteica = 0.0

    lineas = []

    if cuenta_gasto:
        lineas.append(LineaPartida(cuenta_gasto.id, cuenta_gasto.codigo, cuenta_gasto.nombre,
                                    "debito", subtotal, f"Factura {factura.numero_factura or ''}"))

    if iva > 0:
        if empresa.responsable_iva:
            if not empresa.cuenta_iva_descontable_id:
                errores.append("La factura tiene IVA pero la empresa no tiene configurada la "
                                "cuenta de IVA descontable (usa PATCH /empresas/{id}/cuentas-base).")
            else:
                cta = db.get(CuentaContable, empresa.cuenta_iva_descontable_id)
                lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "debito", iva, "IVA descontable"))
        elif lineas:
            # No responsable de IVA: el IVA se lleva como mayor valor del gasto.
            lineas[0].valor += iva

    if inc > 0:
        if not empresa.cuenta_inc_id:
            errores.append("La factura tiene INC pero la empresa no tiene configurada la cuenta de INC.")
        else:
            cta = db.get(CuentaContable, empresa.cuenta_inc_id)
            lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "debito", inc, "INC"))

    if retefuente > 0:
        if not empresa.cuenta_retefuente_id:
            errores.append("La factura tiene retención en la fuente pero la empresa no tiene "
                            "configurada esa cuenta.")
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

    contrapartida_col = {
        "proveedores": empresa.cuenta_proveedores_id,
        "caja": empresa.cuenta_caja_id,
        "banco": empresa.cuenta_banco_id,
    }.get(contrapartida)
    if contrapartida not in ("proveedores", "caja", "banco"):
        errores.append(f"Contrapartida inválida: '{contrapartida}' (debe ser proveedores, caja o banco).")
    elif not contrapartida_col:
        errores.append(f"La empresa no tiene configurada la cuenta de '{contrapartida}'.")

    total_debito = sum(l.valor for l in lineas if l.tipo == "debito")
    total_credito_parcial = sum(l.valor for l in lineas if l.tipo == "credito")
    valor_contrapartida = round(total_debito - total_credito_parcial, 2)

    if not errores and contrapartida_col and valor_contrapartida > 0:
        cta = db.get(CuentaContable, contrapartida_col)
        lineas.append(LineaPartida(cta.id, cta.codigo, cta.nombre, "credito", valor_contrapartida,
                                    f"Contrapartida ({contrapartida})"))

    total_debito = round(sum(l.valor for l in lineas if l.tipo == "debito"), 2)
    total_credito = round(sum(l.valor for l in lineas if l.tipo == "credito"), 2)
    balanceado = abs(total_debito - total_credito) < 0.01 and not errores

    if not errores and not balanceado:
        errores.append(
            f"El comprobante no cuadra: débito {total_debito} vs crédito {total_credito} "
            f"(diferencia {round(total_debito - total_credito, 2)})."
        )

    return ResultadoPartida(lineas=lineas, total_debito=total_debito, total_credito=total_credito,
                             balanceado=balanceado, errores=errores)


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
            tipo=TipoMovimiento(linea.tipo), valor=linea.valor,
            descripcion=linea.descripcion, orden=i,
        )
        db.add(mov)
        movimientos.append(mov)
    db.flush()
    return movimientos
