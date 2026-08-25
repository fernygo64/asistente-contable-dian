"""
Modelo de dominio.

REGLA NO NEGOCIABLE (sección 32 de la especificación): toda tabla que
contenga información contable, de proveedores, historial, reglas,
centros de costo, comprobantes, importaciones o auditoría DEBE tener
una columna empresa_id no nula, con índice y clave foránea a
Empresa.id. Ninguna consulta de estas tablas puede omitir el filtro
por empresa_id — eso se refuerza en la capa de servicios/API
(app/core/security.py + dependencias por request), no solo aquí.
"""
import enum
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, DateTime, Text,
    UniqueConstraint, Index, Enum as SAEnum, Numeric
)
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class SistemaContable(str, enum.Enum):
    siigo_pyme = "siigo_pyme"
    world_office = "world_office"


class OrigenDecision(str, enum.Enum):
    importado = "importado"      # vino de un histórico cargado por el usuario
    manual = "manual"            # el usuario clasificó una factura a mano
    regla = "regla"              # una regla contable la asignó
    sugerencia_aceptada = "sugerencia_aceptada"  # el usuario aceptó la sugerencia del sistema


class FuenteExtraccion(str, enum.Enum):
    xml = "xml"
    pdf_texto = "pdf_texto"
    pdf_ocr = "pdf_ocr"
    excel_dian = "excel_dian"    # solo el registro del Excel, aún sin XML/PDF relacionado


class EstadoFactura(str, enum.Enum):
    pendiente_extraccion = "pendiente_extraccion"
    extraida = "extraida"
    pendiente_revision = "pendiente_revision"       # baja confianza o relación dudosa
    pendiente_clasificacion = "pendiente_clasificacion"
    clasificada = "clasificada"
    lista_para_contabilizar = "lista_para_contabilizar"
    contabilizada = "contabilizada"
    exportada = "exportada"
    error = "error"
    duplicada = "duplicada"


# ---------------------------------------------------------------- Empresa --
class Empresa(Base):
    """
    Raíz de aislamiento multiempresa. Toda la demás información cuelga de aquí.
    """
    __tablename__ = "empresas"

    id = Column(String(36), primary_key=True, default=_uuid)
    nit = Column(String(30), nullable=False, index=True)
    nombre = Column(String(200), nullable=False)
    sistema_contable = Column(SAEnum(SistemaContable), nullable=False, default=SistemaContable.siigo_pyme)
    responsable_iva = Column(Boolean, nullable=False, default=True)
    regimen_simple = Column(Boolean, nullable=False, default=False)

    # Cuentas base configurables — nunca hardcodeadas en lógica (sección 38)
    cuenta_proveedores_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_proveedores"), nullable=True)
    cuenta_caja_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_caja"), nullable=True)
    cuenta_banco_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_banco"), nullable=True)
    cuenta_iva_descontable_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_iva"), nullable=True)
    cuenta_retefuente_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_retefuente"), nullable=True)
    cuenta_reteica_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_reteica"), nullable=True)
    cuenta_reteiva_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_reteiva"), nullable=True)
    cuenta_inc_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_inc"), nullable=True)

    # Cuentas del lado de VENTA (facturas emitidas por la propia empresa) —
    # distintas de las del lado de compra: nunca se debe usar cuenta de
    # gasto/proveedores para una factura que la empresa emitió (sección
    # reportada por el usuario: "las emitidas son ingresos... van en otras cuentas").
    cuenta_ingresos_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_ingresos"), nullable=True)
    cuenta_clientes_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_clientes"), nullable=True)
    cuenta_iva_generado_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_iva_generado"), nullable=True)
    cuenta_nomina_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_nomina"), nullable=True)

    # Cuentas de nómina y provisiones (asiento multilínea, verificado
    # contra comprobante real de Siigo). Cada empresa configura las
    # suyas — nunca se asume un código fijo. Cada concepto tiene su
    # cuenta de GASTO y, cuando aplica, su cuenta de PASIVO por pagar
    # (a quien corresponda: al propio empleado, a la EPS, al fondo de
    # pensión/cesantías, a la ARL o a la caja de compensación — el
    # tercero exacto de cada línea lo determina el empleado, no la
    # cuenta).
    cuenta_salario_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_salario"), nullable=True)
    cuenta_auxilio_transporte_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_auxtte"), nullable=True)
    cuenta_nomina_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_nom_pagar"), nullable=True)
    cuenta_salud_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_salud_pagar"), nullable=True)
    cuenta_pension_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_pension_pagar"), nullable=True)
    cuenta_cesantias_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_cesantias"), nullable=True)
    cuenta_cesantias_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_cesantias_pagar"), nullable=True)
    cuenta_intereses_cesantias_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_intcesantias"), nullable=True)
    cuenta_intereses_cesantias_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_intcesantias_pagar"), nullable=True)
    cuenta_prima_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_prima"), nullable=True)
    cuenta_prima_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_prima_pagar"), nullable=True)
    cuenta_vacaciones_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_vacaciones"), nullable=True)
    cuenta_vacaciones_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_vacaciones_pagar"), nullable=True)
    cuenta_arl_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_arl"), nullable=True)
    cuenta_arl_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_arl_pagar"), nullable=True)
    cuenta_caja_compensacion_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_caja"), nullable=True)
    cuenta_caja_compensacion_por_pagar_id = Column(String(36), ForeignKey("cuentas_contables.id", use_alter=True, name="fk_empresa_cuenta_caja_pagar"), nullable=True)

    # Modo contable (reportado por el usuario): una empresa "mixta" (la
    # mayoría de personas jurídicas) contabiliza sus facturas RECIBIDAS
    # como gasto y las EMITIDAS como ingreso, cada una con sus propias
    # cuentas. Pero una persona natural que solo usa este sistema para
    # llevar SUS PROPIOS gastos (aunque la DIAN marque algún documento
    # como "Emitido" por razones ajenas a una venta real) puede no tener
    # ni necesitar cuentas de ingreso/clientes configuradas — en ese caso
    # "solo_gastos" hace que TODO se contabilice por el lado de gasto,
    # sin exigir cuenta de ingresos ni bloquear el flujo.
    modo_contable = Column(String(20), nullable=False, default="mixto")  # "mixto" | "solo_gastos"

    # Tipo de comprobante contable por tipo de documento DIAN (sección 19):
    # en Siigo/World Office, compras, ventas, notas crédito/débito y nómina
    # normalmente van a comprobantes DISTINTOS — nunca al mismo. Son textos
    # libres (ej. "CC", "P", "FV") porque cada empresa parametriza los suyos
    # propios en su software; nunca se asume un valor por defecto.
    comprobante_factura_recibida = Column(String(20), nullable=True)
    comprobante_factura_emitida = Column(String(20), nullable=True)
    comprobante_nota_credito = Column(String(20), nullable=True)
    comprobante_nota_debito = Column(String(20), nullable=True)
    comprobante_nomina = Column(String(20), nullable=True)
    comprobante_documento_equivalente = Column(String(20), nullable=True)

    activa = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    cuentas = relationship("CuentaContable", back_populates="empresa", foreign_keys="CuentaContable.empresa_id")
    proveedores = relationship("Proveedor", back_populates="empresa")
    centros_costo = relationship("CentroCosto", back_populates="empresa")
    reglas = relationship("ReglaContable", back_populates="empresa")

    __table_args__ = (
        UniqueConstraint("nit", name="uq_empresa_nit"),
    )


# ---------------------------------------------------- Catálogo PUC (global) --
class PucCuenta(Base):
    """
    Catálogo de referencia del Plan Único de Cuentas colombiano (Decreto
    2650 de 1993) — es el mismo para todas las empresas, por eso NO lleva
    empresa_id. Se usa únicamente como ayuda de búsqueda al configurar las
    cuentas base de una empresa o al clasificar una factura sin historial
    (nunca se aplica solo, siempre requiere que el usuario elija).

    No pretende tener las ~2.460 cuentas completas del PUC oficial — trae
    un subconjunto verificado de las cuentas de uso más común en una pyme
    (activos y pasivos corrientes, proveedores, clientes, impuestos,
    retenciones, y los grupos principales de ingresos/gastos/costos). Cada
    empresa puede seguir creando cualquier cuenta propia con
    POST /empresas/{id}/cuentas aunque no esté en este catálogo.
    """
    __tablename__ = "puc_cuentas"

    codigo = Column(String(20), primary_key=True)
    nombre = Column(String(200), nullable=False)
    clase = Column(String(60), nullable=False)   # ej. "Gastos", "Activo"
    naturaleza = Column(String(10), nullable=False)  # "debito" | "credito"

    __table_args__ = (
        Index("ix_puc_nombre", "nombre"),
    )


# ------------------------------------------------------------ Plan cuentas --
class CuentaContable(Base):
    __tablename__ = "cuentas_contables"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    nombre = Column(String(200), nullable=False)
    tipo = Column(String(30), nullable=True)  # Gasto/Costo/Activo/Pasivo/Inventario...
    activa = Column(Boolean, nullable=False, default=True)

    empresa = relationship("Empresa", back_populates="cuentas", foreign_keys=[empresa_id])

    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_cuenta_empresa_codigo"),
        Index("ix_cuenta_empresa_codigo", "empresa_id", "codigo"),
    )


# ------------------------------------------------------------- Proveedores --
class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    nit = Column(String(30), nullable=False)
    nombre = Column(String(200), nullable=True)
    direccion = Column(String(300), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    empresa = relationship("Empresa", back_populates="proveedores")

    __table_args__ = (
        UniqueConstraint("empresa_id", "nit", name="uq_proveedor_empresa_nit"),
        Index("ix_proveedor_empresa_nit", "empresa_id", "nit"),
    )


# --------------------------------------------------------------- Empleados --
class Empleado(Base):
    """
    Empleado de una empresa, con sus afiliaciones (EPS, fondo de pensión/
    cesantías, ARL, caja de compensación) — cada una con su propio NIT.
    Esto es lo que permite armar el asiento multilínea real de nómina
    (verificado contra un comprobante real de Siigo): las cuentas de
    gasto/pasivo se configuran una sola vez por empresa en "Cuentas de
    nómina", pero el TERCERO de cada línea de pasivo varía por empleado
    — ahí es donde entra esta ficha. Ningún dato aquí es fijo ni supuesto
    por el sistema: si un campo de afiliación queda vacío, esa línea del
    asiento simplemente no se genera (nunca se inventa un NIT).
    """
    __tablename__ = "empleados"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    nit = Column(String(30), nullable=False)
    nombre = Column(String(200), nullable=True)
    eps_nit = Column(String(30), nullable=True)
    eps_nombre = Column(String(200), nullable=True)
    afp_nit = Column(String(30), nullable=True)
    afp_nombre = Column(String(200), nullable=True)
    arl_nit = Column(String(30), nullable=True)
    arl_nombre = Column(String(200), nullable=True)
    caja_compensacion_nit = Column(String(30), nullable=True)
    caja_compensacion_nombre = Column(String(200), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    empresa = relationship("Empresa")

    __table_args__ = (
        UniqueConstraint("empresa_id", "nit", name="uq_empleado_empresa_nit"),
        Index("ix_empleado_empresa_nit", "empresa_id", "nit"),
    )


# ----------------------------------------------------------- Centro costo --
class CentroCosto(Base):
    __tablename__ = "centros_costo"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    codigo = Column(String(30), nullable=False)
    nombre = Column(String(200), nullable=False)
    activo = Column(Boolean, nullable=False, default=True)

    empresa = relationship("Empresa", back_populates="centros_costo")

    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_centrocosto_empresa_codigo"),
    )


# ---------------------------------------------------------- Reglas cont. --
class ReglaContable(Base):
    """
    Regla explícita configurada por el usuario para una empresa.
    criterio_json describe condiciones simples, ej:
      {"nit": "900123456"} o {"palabra_clave": "transporte"} o
      {"tipo_documento": "factura_venta"}
    Nunca se comparte ni se evalúa entre empresas distintas.
    """
    __tablename__ = "reglas_contables"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    nombre = Column(String(200), nullable=False)
    criterio_json = Column(Text, nullable=False)  # JSON serializado
    cuenta_id = Column(String(36), ForeignKey("cuentas_contables.id"), nullable=False)
    activa = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    empresa = relationship("Empresa", back_populates="reglas")
    cuenta = relationship("CuentaContable")


# -------------------------------------------------- Importación histórico --
class ImportacionHistorico(Base):
    """
    Registro de auditoría de cada archivo histórico cargado (sección 12).
    NUNCA se borra ni se modifica automáticamente.
    """
    __tablename__ = "importaciones_historico"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    archivo_nombre = Column(String(300), nullable=False)
    mapeo_columnas_json = Column(Text, nullable=False)  # {"NIT": "columna_A", ...}
    total_registros = Column(Integer, nullable=False, default=0)
    registros_validos = Column(Integer, nullable=False, default=0)
    registros_rechazados = Column(Integer, nullable=False, default=0)
    detalle_rechazos_json = Column(Text, nullable=True)
    usuario = Column(String(120), nullable=True)
    importado_en = Column(DateTime(timezone=True), default=_now, nullable=False)


# ------------------------------------------------------- Historial cont. --
class HistorialContable(Base):
    """
    Historial de DECISIONES, no una tabla de "cuenta fija por proveedor".
    Cada fila es una decisión puntual (importada o generada por el uso del
    sistema). El motor de sugerencia calcula frecuencias sobre estas filas
    en tiempo de consulta — nunca se sobreescribe ni se borra una decisión
    anterior cuando llega una nueva (sección 11).
    """
    __tablename__ = "historial_contable"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    proveedor_id = Column(String(36), ForeignKey("proveedores.id"), nullable=False, index=True)
    cuenta_id = Column(String(36), ForeignKey("cuentas_contables.id"), nullable=False, index=True)

    fecha_documento = Column(DateTime(timezone=True), nullable=True)
    numero_documento = Column(String(60), nullable=True)
    tipo_documento = Column(String(60), nullable=True)
    descripcion = Column(String(500), nullable=True)
    valor = Column(Numeric(18, 2), nullable=True)

    origen = Column(SAEnum(OrigenDecision), nullable=False)
    importacion_id = Column(String(36), ForeignKey("importaciones_historico.id"), nullable=True)

    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    empresa = relationship("Empresa")
    proveedor = relationship("Proveedor")
    cuenta = relationship("CuentaContable")

    __table_args__ = (
        Index("ix_historial_empresa_proveedor", "empresa_id", "proveedor_id"),
    )


# --------------------------------------------------- Documentos DIAN (Etapa 2)
class CargaDocumentosDian(Base):
    """
    Una "sesión" de carga manual: el Excel de la DIAN + el ZIP de XML/PDF
    correspondiente (sección 3). Se conserva como registro de auditoría
    de la carga completa, igual que ImportacionHistorico para el histórico.
    """
    __tablename__ = "cargas_documentos_dian"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    archivo_excel_nombre = Column(String(300), nullable=True)
    archivo_zip_nombre = Column(String(300), nullable=True)
    total_filas_excel = Column(Integer, nullable=False, default=0)
    total_archivos_zip = Column(Integer, nullable=False, default=0)
    total_relacionados = Column(Integer, nullable=False, default=0)
    total_pendientes_revision = Column(Integer, nullable=False, default=0)
    total_pendientes_clasificacion = Column(Integer, nullable=False, default=0)
    total_descartados = Column(Integer, nullable=False, default=0)
    total_duplicados = Column(Integer, nullable=False, default=0)
    usuario = Column(String(120), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_carga_empresa_creado", "empresa_id", "creado_en"),
    )


class Factura(Base):
    """
    Documento/factura de un tercero. Puede provenir de XML, PDF (con o sin
    OCR), o únicamente del Excel de la DIAN mientras no se relacione con
    su archivo. El XML SIEMPRE tiene prioridad sobre el PDF cuando ambos
    existen (sección 5) — eso se resuelve en documentos_service, no aquí.
    """
    __tablename__ = "facturas"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    carga_id = Column(String(36), ForeignKey("cargas_documentos_dian.id"), nullable=True, index=True)

    # Identificadores usados para relacionar/deduplicar (sección 4, 26)
    cufe = Column(String(120), nullable=True, index=True)
    numero_factura = Column(String(60), nullable=True, index=True)
    prefijo = Column(String(20), nullable=True)
    tipo_comprobante_override = Column(String(20), nullable=True)  # forzado manualmente en bloque (sección pedida: elegir masivamente, no factura por factura)
    fecha_emision = Column(DateTime(timezone=True), nullable=True)
    hora_emision = Column(String(20), nullable=True)

    nit_emisor = Column(String(30), nullable=True, index=True)
    nombre_emisor = Column(String(200), nullable=True)
    direccion_emisor = Column(String(300), nullable=True)
    nit_receptor = Column(String(30), nullable=True)
    nombre_receptor = Column(String(200), nullable=True)

    subtotal = Column(Numeric(18, 2), nullable=True)
    base_gravable = Column(Numeric(18, 2), nullable=True)
    iva = Column(Numeric(18, 2), nullable=True)
    inc = Column(Numeric(18, 2), nullable=True)
    retenciones_json = Column(Text, nullable=True)      # {"retefuente": .., "reteica": .., "reteiva": ..}
    otros_impuestos_json = Column(Text, nullable=True)
    total = Column(Numeric(18, 2), nullable=True)
    moneda = Column(String(10), nullable=True)
    forma_pago = Column(String(60), nullable=True)
    medio_pago = Column(String(60), nullable=True)
    conceptos_json = Column(Text, nullable=True)         # lista de líneas (código, descripción, cantidad, valor)
    nomina_detalle_json = Column(Text, nullable=True)     # devengados/deducciones reales extraídos del XML de nómina (asiento multilínea)

    # Trazabilidad de archivos originales (sección 27) — rutas dentro de
    # storage/<empresa_id>/..., nunca mezcladas entre empresas.
    archivo_xml_path = Column(String(500), nullable=True)
    archivo_pdf_path = Column(String(500), nullable=True)
    excel_fila_json = Column(Text, nullable=True)         # datos crudos de la fila del Excel DIAN, si existió

    fuente_extraccion = Column(SAEnum(FuenteExtraccion), nullable=False)
    confianza_extraccion = Column(Numeric(5, 2), nullable=False, default=0)  # 0-100, ver sección 7
    campos_extraidos_json = Column(Text, nullable=True)   # qué campos se lograron extraer (para el % de confianza)

    relacionada_con_excel = Column(Boolean, nullable=False, default=False)
    metodo_relacion = Column(String(30), nullable=True)   # "cufe" | "numero_nit_fecha" | "nit_fecha_total" | None
    motivo_no_relacionada = Column(Text, nullable=True)

    es_posible_duplicado = Column(Boolean, nullable=False, default=False)
    duplicado_de_id = Column(String(36), ForeignKey("facturas.id"), nullable=True)

    estado = Column(SAEnum(EstadoFactura), nullable=False, default=EstadoFactura.pendiente_extraccion)

    # Clasificación del documento (reportado por el usuario: la descarga de
    # la DIAN mezcla facturas, notas crédito/débito, nómina y acuses de
    # recibo; una factura puede ser emitida por la propia empresa -venta-
    # o recibida de un tercero -compra-, y cada caso usa cuentas distintas).
    naturaleza_documento = Column(String(30), nullable=False, default="factura")  # factura | nota_credito | nota_debito | nomina | documento_equivalente
    direccion_documento = Column(String(20), nullable=False, default="recibida")  # emitida | recibida | no_aplica

    datos_originales_json = Column(Text, nullable=True)   # snapshot de la extracción, nunca se modifica
    datos_corregidos_json = Column(Text, nullable=True)   # correcciones manuales del usuario, sección 6

    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)
    actualizado_en = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        Index("ix_factura_empresa_cufe", "empresa_id", "cufe"),
        Index("ix_factura_empresa_numero_nit", "empresa_id", "numero_factura", "nit_emisor"),
        Index("ix_factura_empresa_estado", "empresa_id", "estado"),
    )

    @property
    def tercero_nit(self) -> str | None:
        """
        NIT del TERCERO relevante para efectos de historial/sugerencia
        contable — el emisor si la factura es recibida (nuestro
        proveedor), pero el RECEPTOR si la factura es emitida (nuestro
        cliente), nunca la propia empresa. Corrige un error real: antes
        el sistema siempre usaba el emisor, que para una venta somos
        nosotros mismos.
        """
        if self.direccion_documento == "emitida":
            return self.nit_receptor or self.nit_emisor
        return self.nit_emisor

    @property
    def tercero_nombre(self) -> str | None:
        if self.direccion_documento == "emitida":
            return self.nombre_receptor or self.nombre_emisor
        return self.nombre_emisor

    @property
    def concepto_resumen(self) -> str | None:
        """
        Breve descripción de qué se compró/vendió — sección pedida por
        el usuario: cuando el sistema no tiene sugerencia (ni historial
        ni regla), el contador necesita ver de un vistazo de qué se
        trata la factura para decidir manualmente qué cuenta usar, sin
        tener que abrir el detalle completo. Se arma a partir de los
        conceptos/ítems ya extraídos del XML, recortado a un tamaño
        legible en la lista.
        """
        if not self.conceptos_json:
            return None
        try:
            items = json.loads(self.conceptos_json)
        except (ValueError, TypeError):
            return None
        descripciones = [i.get("descripcion", "") for i in items if i.get("descripcion")]
        if not descripciones:
            return None
        texto = "; ".join(descripciones)
        return texto[:150] + ("…" if len(texto) > 150 else "")


class TipoMovimiento(str, enum.Enum):
    debito = "debito"
    credito = "credito"


class EstadoExportacion(str, enum.Enum):
    generada = "generada"
    error = "error"


# --------------------------------------------------------- Partida doble --
class Movimiento(Base):
    """
    Línea de la partida doble de una factura (sección 16). Cada factura
    contabilizada tiene N movimientos; la suma de débitos debe ser
    igual a la suma de créditos — se valida en partida_doble_service
    antes de persistir, nunca se guarda un comprobante descuadrado.
    """
    __tablename__ = "movimientos"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    factura_id = Column(String(36), ForeignKey("facturas.id"), nullable=False, index=True)
    cuenta_id = Column(String(36), ForeignKey("cuentas_contables.id"), nullable=False)
    centro_costo_id = Column(String(36), ForeignKey("centros_costo.id"), nullable=True)
    tipo = Column(SAEnum(TipoMovimiento), nullable=False)
    valor = Column(Numeric(18, 2), nullable=False)
    descripcion = Column(String(300), nullable=True)
    orden = Column(Integer, nullable=False, default=0)
    tercero_nit_override = Column(String(30), nullable=True)      # solo cuando el tercero de ESTA línea es distinto al de la factura (ej. nómina: EPS/AFP en vez del empleado)
    tercero_nombre_override = Column(String(200), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    cuenta = relationship("CuentaContable")
    centro_costo = relationship("CentroCosto")

    __table_args__ = (
        Index("ix_movimiento_empresa_factura", "empresa_id", "factura_id"),
    )


# -------------------------------------------------- Plantillas de export. --
class PlantillaExportacion(Base):
    """
    Plantilla de archivo plano por empresa y sistema contable
    (secciones 20-22). Nunca hardcodeada: columnas, delimitador,
    formato de fecha/numérico y equivalencia de cuentas se configuran
    aquí y el adaptador correspondiente solo las aplica.
    """
    __tablename__ = "plantillas_exportacion"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    nombre = Column(String(200), nullable=False)
    sistema_contable = Column(SAEnum(SistemaContable), nullable=False)
    delimitador = Column(String(5), nullable=False, default="|")
    extension = Column(String(10), nullable=False, default="txt")
    incluir_encabezado = Column(Boolean, nullable=False, default=True)
    formato_fecha = Column(String(20), nullable=False, default="%Y-%m-%d")
    columnas_json = Column(Text, nullable=False)             # [{label, source, valor_fijo}]
    equivalencias_cuentas_json = Column(Text, nullable=False, default="{}")  # {codigo_interno: codigo_software}
    # Versionado técnico del formato. Las plantillas históricas quedan en v1;
    # al reprocesar SIIGO se crea una nueva versión v2 conservando la anterior.
    version_formato = Column(Integer, nullable=False, default=1)
    plantilla_origen_id = Column(String(36), ForeignKey("plantillas_exportacion.id"), nullable=True)
    activa = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)
    actualizado_en = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("empresa_id", "nombre", name="uq_plantilla_empresa_nombre"),
    )


# ------------------------------------------- Configuración técnica Siigo --
class ConfiguracionComprobanteSiigo(Base):
    """Tipo+código y defaults técnicos por empresa y clase documental."""
    __tablename__ = "configuraciones_comprobante_siigo"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    tipo_documento = Column(String(40), nullable=False)  # factura_recibida, factura_emitida, nota_credito, ...
    tipo_comprobante = Column(String(20), nullable=True)
    codigo_comprobante = Column(String(20), nullable=True)
    codigo_vendedor_default = Column(String(20), nullable=True)
    codigo_ciudad_default = Column(String(20), nullable=True)
    codigo_zona_default = Column(String(20), nullable=True)
    centro_costo_default = Column(String(30), nullable=True)
    subcentro_costo_default = Column(String(30), nullable=True)
    sucursal_default = Column(String(20), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)
    actualizado_en = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("empresa_id", "tipo_documento", name="uq_cfg_siigo_empresa_tipo_doc"),
        Index("ix_cfg_siigo_empresa_tipo_doc", "empresa_id", "tipo_documento"),
    )


class ConsecutivoSiigo(Base):
    """Último consecutivo usado por empresa + tipo + código SIIGO."""
    __tablename__ = "consecutivos_siigo"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    tipo_comprobante = Column(String(20), nullable=False)
    codigo_comprobante = Column(String(20), nullable=False)
    ultimo_consecutivo_usado = Column(Integer, nullable=False, default=0)
    actualizado_en = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("empresa_id", "tipo_comprobante", "codigo_comprobante", name="uq_consecutivo_siigo"),
        Index("ix_consecutivo_siigo_clave", "empresa_id", "tipo_comprobante", "codigo_comprobante"),
    )


class ParametrizacionCuentaSiigo(Base):
    """Comportamiento técnico de una cuenta al exportar a SIIGO; no contamina CuentaContable."""
    __tablename__ = "parametrizaciones_cuenta_siigo"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    cuenta_id = Column(String(36), ForeignKey("cuentas_contables.id"), nullable=False, index=True)
    maneja_tercero = Column(Boolean, nullable=False, default=True)
    nit_tecnico_exportacion = Column(String(30), nullable=True, default="0")
    codigo_vendedor = Column(String(20), nullable=True)
    codigo_ciudad = Column(String(20), nullable=True)
    codigo_zona = Column(String(20), nullable=True)
    centro_costo = Column(String(30), nullable=True)
    subcentro_costo = Column(String(30), nullable=True)
    sucursal = Column(String(20), nullable=True)
    activa = Column(Boolean, nullable=False, default=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)
    actualizado_en = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    cuenta = relationship("CuentaContable")

    __table_args__ = (
        UniqueConstraint("empresa_id", "cuenta_id", name="uq_param_cuenta_siigo"),
        Index("ix_param_cuenta_siigo_empresa", "empresa_id", "cuenta_id"),
    )


class ExportacionFactura(Base):
    """Relación por destino: una factura puede exportarse a SIIGO y World Office independientemente."""
    __tablename__ = "exportaciones_facturas"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    exportacion_id = Column(String(36), ForeignKey("exportaciones.id"), nullable=True, index=True)
    factura_id = Column(String(36), ForeignKey("facturas.id"), nullable=False, index=True)
    sistema_contable = Column(String(20), nullable=False)
    tipo_comprobante = Column(String(20), nullable=True)
    codigo_comprobante = Column(String(20), nullable=True)
    numero_documento = Column(String(60), nullable=True)
    usuario = Column(String(120), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("exportacion_id", "factura_id", name="uq_exportacion_factura"),
        Index("ix_exp_factura_destino", "empresa_id", "factura_id", "sistema_contable"),
    )


class Exportacion(Base):
    """Registro de auditoría de cada exportación generada (sección 39)."""
    __tablename__ = "exportaciones"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    plantilla_id = Column(String(36), ForeignKey("plantillas_exportacion.id"), nullable=False)
    sistema_contable = Column(SAEnum(SistemaContable), nullable=False)
    usuario = Column(String(120), nullable=True)
    cantidad_registros = Column(Integer, nullable=False, default=0)
    facturas_incluidas_json = Column(Text, nullable=True)   # lista de factura_id
    estado = Column(SAEnum(EstadoExportacion), nullable=False)
    errores_json = Column(Text, nullable=True)
    archivo_nombre = Column(String(300), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_exportacion_empresa_creado", "empresa_id", "creado_en"),
    )


# ----------------------------------------------------------------- Audit --
class Auditoria(Base):
    __tablename__ = "auditoria"

    id = Column(String(36), primary_key=True, default=_uuid)
    empresa_id = Column(String(36), ForeignKey("empresas.id"), nullable=False, index=True)
    entidad = Column(String(60), nullable=False)       # ej: "HistorialContable", "Factura"
    entidad_id = Column(String(36), nullable=True)
    accion = Column(String(60), nullable=False)        # ej: "importacion_historico", "correccion_manual"
    detalle_json = Column(Text, nullable=True)
    usuario = Column(String(120), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        Index("ix_auditoria_empresa_creado", "empresa_id", "creado_en"),
    )
