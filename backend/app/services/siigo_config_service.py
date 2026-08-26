"""Configuración técnica y numeración para exportaciones Siigo Pyme."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.models import (
    Empresa, Factura, ConfiguracionComprobanteSiigo, ConsecutivoSiigo,
    ParametrizacionCuentaSiigo, ExportacionFactura, SistemaContable,
)

# Cada naturaleza que puede ser recibida/emitida tiene configuración separada.
TIPOS_DOCUMENTO = (
    "factura_recibida", "factura_emitida",
    "nota_credito_recibida", "nota_credito_emitida",
    "nota_debito_recibida", "nota_debito_emitida",
    "documento_equivalente_recibido", "documento_equivalente_emitido",
    "nomina",
)

# Compatibilidad con campos históricos de Empresa. Para notas/documento
# equivalente el campo legacy era único, por eso ambas direcciones lo usan
# solo como respaldo cuando todavía no existe una fila nueva específica.
_EMPRESA_TIPO_ATTR = {
    "factura_recibida": "comprobante_factura_recibida",
    "factura_emitida": "comprobante_factura_emitida",
    "nota_credito_recibida": "comprobante_nota_credito",
    "nota_credito_emitida": "comprobante_nota_credito",
    "nota_debito_recibida": "comprobante_nota_debito",
    "nota_debito_emitida": "comprobante_nota_debito",
    "documento_equivalente_recibido": "comprobante_documento_equivalente",
    "documento_equivalente_emitido": "comprobante_documento_equivalente",
    "nomina": "comprobante_nomina",
}

# Filas antiguas creadas antes de separar recibido/emitido.
_LEGACY_ROW_KEY = {
    "nota_credito_recibida": "nota_credito",
    "nota_credito_emitida": "nota_credito",
    "nota_debito_recibida": "nota_debito",
    "nota_debito_emitida": "nota_debito",
    "documento_equivalente_recibido": "documento_equivalente",
    "documento_equivalente_emitido": "documento_equivalente",
}


def tipo_documento_clave(factura: Factura) -> str:
    direccion = "emitida" if factura.direccion_documento == "emitida" else "recibida"
    if factura.naturaleza_documento == "nota_credito":
        return f"nota_credito_{direccion}"
    if factura.naturaleza_documento == "nota_debito":
        return f"nota_debito_{direccion}"
    if factura.naturaleza_documento == "nomina":
        return "nomina"
    if factura.naturaleza_documento == "documento_equivalente":
        return f"documento_equivalente_{'emitido' if direccion == 'emitida' else 'recibido'}"
    return f"factura_{direccion}"


def configuraciones_empresa(db: Session, empresa: Empresa) -> dict[str, dict]:
    filas = db.query(ConfiguracionComprobanteSiigo).filter(
        ConfiguracionComprobanteSiigo.empresa_id == empresa.id
    ).all()
    por_tipo = {x.tipo_documento: x for x in filas}
    resultado = {}
    for clave in TIPOS_DOCUMENTO:
        fila = por_tipo.get(clave) or por_tipo.get(_LEGACY_ROW_KEY.get(clave, ""))
        tipo_legacy = getattr(empresa, _EMPRESA_TIPO_ATTR[clave], None)
        resultado[clave] = {
            "id": fila.id if fila and fila.tipo_documento == clave else None,
            "tipo_documento": clave,
            "tipo_comprobante": (fila.tipo_comprobante if fila and fila.tipo_comprobante is not None else tipo_legacy) or "",
            "codigo_comprobante": (fila.codigo_comprobante if fila and fila.codigo_comprobante is not None else "1"),
            "codigo_vendedor_default": fila.codigo_vendedor_default if fila else "1",
            "codigo_ciudad_default": fila.codigo_ciudad_default if fila else None,
            "codigo_zona_default": fila.codigo_zona_default if fila else "0",
            "centro_costo_default": fila.centro_costo_default if fila else "0",
            "subcentro_costo_default": fila.subcentro_costo_default if fila else "0",
            "sucursal_default": fila.sucursal_default if fila else "0",
            # Compatibilidad: históricamente las facturas emitidas usaban el folio/numero DIAN.
            # Una fila explícita de configuración siempre prevalece y permite elegir cualquiera de los dos modos.
            "modo_numeracion": ((getattr(fila, "modo_numeracion", None) if fila else None)
                                 or ("folio_dian" if clave == "factura_emitida" else "interna")),
        }
    return resultado


def configuracion_factura(db: Session, empresa: Empresa, factura: Factura) -> dict:
    return configuraciones_empresa(db, empresa)[tipo_documento_clave(factura)]


def parametros_cuentas_empresa(db: Session, empresa_id: str) -> dict[str, ParametrizacionCuentaSiigo]:
    # Conservado solo por compatibilidad. La V5 prioriza aprendizaje automático
    # del Historial SIIGO y ya no expone parametrización manual en interfaz.
    filas = db.query(ParametrizacionCuentaSiigo).filter(
        ParametrizacionCuentaSiigo.empresa_id == empresa_id,
        ParametrizacionCuentaSiigo.activa.is_(True),
    ).all()
    return {x.cuenta_id: x for x in filas}


def _normalizar_clave(texto: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def folio_dian_factura(factura: Factura) -> str:
    """Folio DIAN sin letras ni caracteres especiales; conserva ceros iniciales."""
    candidatos = []
    try:
        fila = json.loads(factura.excel_fila_json or "{}")
        if isinstance(fila, dict):
            for k, v in fila.items():
                nk = _normalizar_clave(k)
                if nk == "folio" or nk.endswith(" folio") or nk.startswith("folio "):
                    candidatos.append(v)
            # Algunos reportes DIAN lo nombran "Número/Folio".
            for k, v in fila.items():
                nk = _normalizar_clave(k)
                if "folio" in nk and v not in candidatos:
                    candidatos.append(v)
    except Exception:
        pass
    candidatos.extend([factura.numero_factura])
    for valor in candidatos:
        if valor is None:
            continue
        digitos = re.sub(r"\D", "", str(valor))
        if digitos:
            return digitos
    return ""


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
    """Vista previa: no consume consecutivos internos."""
    cfgs = configuraciones_empresa(db, empresa)
    bases: dict[tuple[str, str], int] = {}
    usados: dict[tuple[str, str], int] = defaultdict(int)
    resultado: dict[str, str] = {}
    for f in facturas_ordenadas:
        cfg = dict(cfgs[tipo_documento_clave(f)])
        if f.tipo_comprobante_override:
            cfg["tipo_comprobante"] = f.tipo_comprobante_override
        tipo, codigo = cfg.get("tipo_comprobante") or "", cfg.get("codigo_comprobante") or ""
        if cfg.get("modo_numeracion") == "folio_dian":
            resultado[f.id] = folio_dian_factura(f)
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
    """Reserva consecutivos internos dentro de la transacción activa."""
    cfgs = configuraciones_empresa(db, empresa)
    resultado: dict[str, str] = {}
    cfg_por_factura: dict[str, dict] = {}
    for f in facturas_ordenadas:
        cfg = dict(cfgs[tipo_documento_clave(f)])
        if f.tipo_comprobante_override:
            cfg["tipo_comprobante"] = f.tipo_comprobante_override
        tipo, codigo = cfg.get("tipo_comprobante") or "", cfg.get("codigo_comprobante") or ""
        cfg_por_factura[f.id] = cfg
        if cfg.get("modo_numeracion") == "folio_dian":
            resultado[f.id] = folio_dian_factura(f)
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
