"""Configuración técnica y numeración persistente para exportaciones Siigo Pyme."""
from __future__ import annotations

from collections import defaultdict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.models import (
    Empresa, Factura, ConfiguracionComprobanteSiigo, ConsecutivoSiigo,
    ParametrizacionCuentaSiigo, ExportacionFactura, SistemaContable,
)

TIPOS_DOCUMENTO = (
    "factura_recibida", "factura_emitida", "nota_credito", "nota_debito",
    "nomina", "documento_equivalente",
)

_EMPRESA_TIPO_ATTR = {
    "factura_recibida": "comprobante_factura_recibida",
    "factura_emitida": "comprobante_factura_emitida",
    "nota_credito": "comprobante_nota_credito",
    "nota_debito": "comprobante_nota_debito",
    "nomina": "comprobante_nomina",
    "documento_equivalente": "comprobante_documento_equivalente",
}


def tipo_documento_clave(factura: Factura) -> str:
    if factura.naturaleza_documento == "nota_credito":
        return "nota_credito"
    if factura.naturaleza_documento == "nota_debito":
        return "nota_debito"
    if factura.naturaleza_documento == "nomina":
        return "nomina"
    if factura.naturaleza_documento == "documento_equivalente":
        return "documento_equivalente"
    return "factura_emitida" if factura.direccion_documento == "emitida" else "factura_recibida"


def configuraciones_empresa(db: Session, empresa: Empresa) -> dict[str, dict]:
    filas = db.query(ConfiguracionComprobanteSiigo).filter(
        ConfiguracionComprobanteSiigo.empresa_id == empresa.id
    ).all()
    por_tipo = {x.tipo_documento: x for x in filas}
    resultado = {}
    for clave in TIPOS_DOCUMENTO:
        fila = por_tipo.get(clave)
        tipo_legacy = getattr(empresa, _EMPRESA_TIPO_ATTR[clave], None)
        resultado[clave] = {
            "id": fila.id if fila else None,
            "tipo_documento": clave,
            "tipo_comprobante": (fila.tipo_comprobante if fila and fila.tipo_comprobante is not None else tipo_legacy) or "",
            # '1' es SOLO compatibilidad con el comportamiento histórico; la UI permite cambiarlo por empresa/tipo.
            "codigo_comprobante": (fila.codigo_comprobante if fila and fila.codigo_comprobante is not None else "1"),
            "codigo_vendedor_default": fila.codigo_vendedor_default if fila else "1",
            "codigo_ciudad_default": fila.codigo_ciudad_default if fila else None,
            "codigo_zona_default": fila.codigo_zona_default if fila else "0",
            "centro_costo_default": fila.centro_costo_default if fila else "0",
            "subcentro_costo_default": fila.subcentro_costo_default if fila else "0",
            "sucursal_default": fila.sucursal_default if fila else "0",
        }
    return resultado


def configuracion_factura(db: Session, empresa: Empresa, factura: Factura) -> dict:
    return configuraciones_empresa(db, empresa)[tipo_documento_clave(factura)]


def parametros_cuentas_empresa(db: Session, empresa_id: str) -> dict[str, ParametrizacionCuentaSiigo]:
    filas = db.query(ParametrizacionCuentaSiigo).filter(
        ParametrizacionCuentaSiigo.empresa_id == empresa_id,
        ParametrizacionCuentaSiigo.activa.is_(True),
    ).all()
    return {x.cuenta_id: x for x in filas}


def _numero_ya_asignado(db: Session, empresa_id: str, factura_id: str, tipo: str, codigo: str):
    return db.query(ExportacionFactura).filter(
        ExportacionFactura.empresa_id == empresa_id,
        ExportacionFactura.factura_id == factura_id,
        ExportacionFactura.sistema_contable == SistemaContable.siigo_pyme,
        ExportacionFactura.tipo_comprobante == tipo,
        ExportacionFactura.codigo_comprobante == codigo,
        ExportacionFactura.numero_documento.isnot(None),
    ).order_by(ExportacionFactura.creado_en.asc()).first()


def _bloquear_clave_postgres(db: Session, empresa_id: str, tipo: str, codigo: str) -> None:
    """Evita que dos exportaciones concurrentes reserven el mismo número en PostgreSQL."""
    dialecto = getattr(getattr(db, "bind", None), "dialect", None)
    if dialecto and dialecto.name == "postgresql":
        llave = f"siigo:{empresa_id}:{tipo}:{codigo}"
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": llave})


def _obtener_consecutivo_bloqueado(db: Session, empresa_id: str, tipo: str, codigo: str) -> ConsecutivoSiigo:
    _bloquear_clave_postgres(db, empresa_id, tipo, codigo)
    q = db.query(ConsecutivoSiigo).filter(
        ConsecutivoSiigo.empresa_id == empresa_id,
        ConsecutivoSiigo.tipo_comprobante == tipo,
        ConsecutivoSiigo.codigo_comprobante == codigo,
    )
    if getattr(getattr(db, "bind", None), "dialect", None) and db.bind.dialect.name == "postgresql":
        q = q.with_for_update()
    fila = q.first()
    if not fila:
        fila = ConsecutivoSiigo(
            empresa_id=empresa_id, tipo_comprobante=tipo, codigo_comprobante=codigo,
            ultimo_consecutivo_usado=0,
        )
        db.add(fila)
        db.flush()
    return fila


def proyectar_numeros(db: Session, empresa: Empresa, facturas_ordenadas: list[Factura]) -> dict[str, str]:
    """Vista previa: NO consume números. Reutiliza números históricos cuando existen."""
    cfgs = configuraciones_empresa(db, empresa)
    bases: dict[tuple[str, str], int] = {}
    usados: dict[tuple[str, str], int] = defaultdict(int)
    resultado: dict[str, str] = {}
    for f in facturas_ordenadas:
        clave_doc = tipo_documento_clave(f)
        cfg = dict(cfgs[clave_doc])
        if f.tipo_comprobante_override:
            cfg["tipo_comprobante"] = f.tipo_comprobante_override
        tipo, codigo = cfg["tipo_comprobante"], cfg["codigo_comprobante"]
        es_venta_real = f.direccion_documento == "emitida" and f.naturaleza_documento != "nomina"
        if es_venta_real:
            resultado[f.id] = f.numero_factura or ""
            continue
        previo = _numero_ya_asignado(db, empresa.id, f.id, tipo, codigo)
        if previo:
            resultado[f.id] = previo.numero_documento
            continue
        key = (tipo, codigo)
        if key not in bases:
            fila = db.query(ConsecutivoSiigo).filter(
                ConsecutivoSiigo.empresa_id == empresa.id,
                ConsecutivoSiigo.tipo_comprobante == tipo,
                ConsecutivoSiigo.codigo_comprobante == codigo,
            ).first()
            bases[key] = int(fila.ultimo_consecutivo_usado if fila else 0)
        usados[key] += 1
        resultado[f.id] = str(bases[key] + usados[key])
    return resultado


def asignar_numeros(db: Session, empresa: Empresa, facturas_ordenadas: list[Factura]) -> tuple[dict[str, str], dict[str, dict]]:
    """Reserva números dentro de la transacción activa. El caller hace commit/rollback."""
    cfgs = configuraciones_empresa(db, empresa)
    resultado: dict[str, str] = {}
    cfg_por_factura: dict[str, dict] = {}
    for f in facturas_ordenadas:
        cfg = dict(cfgs[tipo_documento_clave(f)])
        if f.tipo_comprobante_override:
            cfg["tipo_comprobante"] = f.tipo_comprobante_override
        tipo, codigo = cfg["tipo_comprobante"], cfg["codigo_comprobante"]
        cfg_por_factura[f.id] = cfg
        es_venta_real = f.direccion_documento == "emitida" and f.naturaleza_documento != "nomina"
        if es_venta_real:
            resultado[f.id] = f.numero_factura or ""
            continue
        previo = _numero_ya_asignado(db, empresa.id, f.id, tipo, codigo)
        if previo:
            resultado[f.id] = previo.numero_documento
            continue
        consecutivo = _obtener_consecutivo_bloqueado(db, empresa.id, tipo, codigo)
        consecutivo.ultimo_consecutivo_usado = int(consecutivo.ultimo_consecutivo_usado or 0) + 1
        db.flush()
        resultado[f.id] = str(consecutivo.ultimo_consecutivo_usado)
    return resultado, cfg_por_factura
