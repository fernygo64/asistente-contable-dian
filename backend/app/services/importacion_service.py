"""
Importación de historial contable ya existente en la empresa (sección 8-9-12).

No asume orden fijo de columnas: recibe un mapeo explícito
{campo_interno: nombre_columna_en_el_archivo} y lo aplica. Registra
auditoría completa de la importación (cuántos registros, cuántos
rechazados y por qué) y NUNCA modifica ni borra importaciones previas.

Rendimiento: un archivo real de "Movimiento Contable" puede traer miles
de filas. Consultar/crear el proveedor y la cuenta por cada fila (una
ida y vuelta a la base de datos por fila) es lo bastante lento contra
una base remota (ej. Neon) como para agotar el tiempo de espera del
navegador — se comprobó con un archivo real de 1223 filas. Por eso se
resuelven todos los proveedores/cuentas en un par de consultas en lote
antes del bucle, no una por una dentro de él.
"""
import io
import json
import re
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import ImportacionHistorico, OrigenDecision, Proveedor, CuentaContable, HistorialContable
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.excel_utils import resolver_columna, leer_dataframe_excel
from app.services.siigo_historial_service import guardar_historial_tecnico_siigo


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


def _fecha_desde_partes(anio, mes, dia) -> Optional[datetime]:
    """Reconstruye la fecha cuando el archivo la trae partida en Año/Mes/Día
    (confirmado en el archivo real de Siigo Pyme: 'Movimiento Contable')."""
    try:
        return datetime(int(float(anio)), int(float(mes)), int(float(dia)))
    except (ValueError, TypeError):
        return None


def importar_registros_historico(db: Session, empresa_id: str, nombre_archivo: str,
                                  registros: list[dict], mapeo_descripcion: dict,
                                  usuario: Optional[str], total_filas_original: int,
                                  filas_excluidas: int = 0) -> ImportacionHistorico:
    """
    Núcleo compartido de guardado en lote — recibe una lista YA
    NORMALIZADA de registros {"nit", "cuenta_codigo", "nombre" (tercero,
    opcional), "nombre_cuenta" (opcional), "fecha" (opcional), "numero"
    (opcional), "tipo" (opcional), "desc" (opcional), "valor" (opcional)}.
    Tanto el mapeo por columnas (auxiliar/movimiento contable, balance
    plano) como el parser jerárquico de Siigo Nube ("Balance de Prueba
    por Terceros") terminan aquí — evita duplicar la lógica de
    resolución en lote de proveedores/cuentas entre los dos caminos.
    """
    nits_distintos = {r["nit"] for r in registros}
    codigos_distintos = {r["cuenta_codigo"] for r in registros}

    proveedores_existentes = {
        p.nit: p for p in db.query(Proveedor).filter(
            Proveedor.empresa_id == empresa_id, Proveedor.nit.in_(nits_distintos)
        ).all()
    } if nits_distintos else {}
    cuentas_existentes = {
        c.codigo: c for c in db.query(CuentaContable).filter(
            CuentaContable.empresa_id == empresa_id, CuentaContable.codigo.in_(codigos_distintos)
        ).all()
    } if codigos_distintos else {}

    nuevos_proveedores = {}
    for r in registros:
        nit = r["nit"]
        if nit in proveedores_existentes or nit in nuevos_proveedores:
            continue
        p = Proveedor(id=str(uuid.uuid4()), empresa_id=empresa_id, nit=nit, nombre=r.get("nombre") or None)
        nuevos_proveedores[nit] = p
        db.add(p)

    nuevas_cuentas = {}
    for r in registros:
        codigo = r["cuenta_codigo"]
        nombre_cuenta = r.get("nombre_cuenta")
        if codigo in cuentas_existentes:
            # Si la cuenta ya existía pero solo tenía el código como
            # nombre provisional, y este archivo SÍ trae un nombre real
            # (ej. "IVA Descontable Compras 19%"), se actualiza — ese
            # nombre es justamente lo que permite luego reconocer por
            # texto si una cuenta es de IVA al 19%, al 5%, de servicios
            # o de compras.
            cta = cuentas_existentes[codigo]
            if nombre_cuenta and cta.nombre == cta.codigo:
                cta.nombre = nombre_cuenta
            continue
        if codigo in nuevas_cuentas:
            continue
        c = CuentaContable(id=str(uuid.uuid4()), empresa_id=empresa_id, codigo=codigo,
                            nombre=nombre_cuenta or codigo)
        nuevas_cuentas[codigo] = c
        db.add(c)

    mapa_proveedores = {**proveedores_existentes, **nuevos_proveedores}
    mapa_cuentas = {**cuentas_existentes, **nuevas_cuentas}

    importacion = ImportacionHistorico(
        empresa_id=empresa_id,
        archivo_nombre=nombre_archivo,
        mapeo_columnas_json=json.dumps(mapeo_descripcion, ensure_ascii=False),
        total_registros=total_filas_original,
        registros_validos=0,
        registros_rechazados=0,
        usuario=usuario,
    )
    db.add(importacion)
    db.flush()  # una sola ida a la base para obtener los IDs generados arriba y el de la importación

    for r in registros:
        proveedor = mapa_proveedores[r["nit"]]
        cuenta = mapa_cuentas[r["cuenta_codigo"]]
        if r.get("nombre") and not proveedor.nombre:
            proveedor.nombre = r["nombre"]
        db.add(HistorialContable(
            empresa_id=empresa_id, proveedor_id=proveedor.id, cuenta_id=cuenta.id,
            fecha_documento=r.get("fecha"), numero_documento=r.get("numero") or None,
            tipo_documento=r.get("tipo") or None, descripcion=r.get("desc") or None, valor=r.get("valor"),
            origen=OrigenDecision.importado, importacion_id=importacion.id,
        ))

    validos = len(registros)
    importacion.registros_validos = validos
    importacion.registros_rechazados = total_filas_original - validos - filas_excluidas
    rechazos = []
    if filas_excluidas:
        rechazos.append(f"{filas_excluidas} fila(s) omitidas por pertenecer a una cuenta excluida "
                         f"(contrapartida/impuestos, no se cuentan como rechazo ni como aprendizaje).")
    importacion.detalle_rechazos_json = json.dumps(rechazos[:200], ensure_ascii=False)

    auditoria_registrar(
        db, empresa_id, entidad="ImportacionHistorico", entidad_id=importacion.id,
        accion="importacion_historico",
        detalle={"archivo": nombre_archivo, "validos": validos, "excluidos_por_cuenta": filas_excluidas,
                 "rechazados": total_filas_original - validos - filas_excluidas},
        usuario=usuario,
    )

    return importacion


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

    mapeo puede traer "valor" (una sola columna con el monto, ej. Siigo
    Pyme con su "Débito o Crédito" aparte) o, alternativamente,
    "valor_debito" + "valor_credito" (columnas separadas, ej. World
    Office) — se usa lo que venga poblado por fila, el que esté en 0/vacío
    se ignora.
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
    columna_nombre = mapeo_resuelto.get("nombre")
    columna_nombre_cuenta = mapeo_resuelto.get("nombre_cuenta")
    columna_fecha = mapeo_resuelto.get("fecha")
    columna_anio = mapeo_resuelto.get("anio")
    columna_mes = mapeo_resuelto.get("mes")
    columna_dia = mapeo_resuelto.get("dia")
    columna_numero = mapeo_resuelto.get("numero_documento")
    columna_tipo = mapeo_resuelto.get("tipo_documento")
    columna_desc = mapeo_resuelto.get("descripcion")
    columna_valor = mapeo_resuelto.get("valor")
    columna_valor_debito = mapeo_resuelto.get("valor_debito")
    columna_valor_credito = mapeo_resuelto.get("valor_credito")

    prefijos_excluir = [p.strip() for p in (cuentas_excluir or []) if p.strip()]

    total = len(df)
    rechazos: list[str] = []

    # ---- filtrar filas válidas (sin tocar la base de datos todavía) ----
    registros = []
    excluidos_por_cuenta = 0
    for i, row in df.iterrows():
        nit = str(row.get(columna_nit, "")).strip()
        cuenta_codigo = str(row.get(columna_cuenta, "")).strip()
        if not nit or not cuenta_codigo:
            rechazos.append(f"Fila {i + 2}: falta NIT o cuenta.")
            continue
        if any(cuenta_codigo.startswith(p) for p in prefijos_excluir):
            excluidos_por_cuenta += 1
            continue

        if columna_valor:
            valor = _parse_valor(row.get(columna_valor))
        else:
            v_deb = _parse_valor(row.get(columna_valor_debito)) if columna_valor_debito else None
            v_cred = _parse_valor(row.get(columna_valor_credito)) if columna_valor_credito else None
            valor = v_deb if (v_deb not in (None, 0)) else v_cred

        if columna_fecha:
            fecha = _parse_fecha(row.get(columna_fecha))
        elif columna_anio and columna_mes and columna_dia:
            fecha = _fecha_desde_partes(row.get(columna_anio), row.get(columna_mes), row.get(columna_dia))
        else:
            fecha = None

        registros.append({
            "nit": nit, "cuenta_codigo": cuenta_codigo,
            "nombre": str(row.get(columna_nombre, "")).strip() if columna_nombre else None,
            "nombre_cuenta": str(row.get(columna_nombre_cuenta, "")).strip() if columna_nombre_cuenta else None,
            "fecha": fecha,
            "numero": str(row.get(columna_numero, "")).strip() if columna_numero else None,
            "tipo": str(row.get(columna_tipo, "")).strip() if columna_tipo else None,
            "desc": str(row.get(columna_desc, "")).strip() if columna_desc else None,
            "valor": valor,
        })

    if excluidos_por_cuenta:
        rechazos.insert(0, f"{excluidos_por_cuenta} fila(s) omitidas por pertenecer a una cuenta excluida "
                           f"(contrapartida/impuestos, no se cuentan como rechazo ni como aprendizaje).")

    importacion = importar_registros_historico(
        db, empresa_id, nombre_archivo, registros, mapeo, usuario, total, excluidos_por_cuenta
    )

    # Aprendizaje técnico SIIGO AUTOMÁTICO: se inspecciona el archivo
    # completo fila por fila y se guardan vendedor/ciudad/zona/centro/
    # subcentro/sucursal y el patrón real de NIT por cuenta. Esto ocurre
    # incluso para cuentas excluidas del aprendizaje de clasificación
    # (caja, bancos, IVA, proveedores), porque justamente esas líneas
    # muestran cómo SIIGO exige exportar cada cuenta.
    tecnicos_siigo = guardar_historial_tecnico_siigo(db, empresa_id, importacion.id, df)
    importacion.filas_tecnicas_siigo = tecnicos_siigo
    if tecnicos_siigo:
        auditoria_registrar(
            db, empresa_id, entidad="ImportacionHistorico", entidad_id=importacion.id,
            accion="aprendizaje_tecnico_siigo_automatico",
            detalle={"archivo": nombre_archivo, "filas_tecnicas_aprendidas": tecnicos_siigo},
            usuario=usuario,
        )
    # Los rechazos por fila sin NIT/cuenta son propios de este camino
    # (mapeo por columnas) — se agregan encima de los que ya puso la
    # función compartida (exclusión por cuenta).
    detalle_previo = json.loads(importacion.detalle_rechazos_json or "[]")
    todos_los_rechazos = rechazos[:200] if not detalle_previo else (detalle_previo + [
        r for r in rechazos if r not in detalle_previo
    ])[:200]
    importacion.detalle_rechazos_json = json.dumps(todos_los_rechazos, ensure_ascii=False)
    return importacion
