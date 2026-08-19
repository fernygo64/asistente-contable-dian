from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ----------------------------------------------------------------- Empresa
class EmpresaCreate(BaseModel):
    nit: str
    nombre: str
    sistema_contable: str = "siigo_pyme"
    responsable_iva: bool = True
    regimen_simple: bool = False


class EmpresaCuentasBase(BaseModel):
    """Códigos de cuenta (se crean si no existen) para los conceptos base de la empresa (sección 38)."""
    cuenta_proveedores: Optional[str] = None
    cuenta_caja: Optional[str] = None
    cuenta_banco: Optional[str] = None
    cuenta_iva_descontable: Optional[str] = None
    cuenta_retefuente: Optional[str] = None
    cuenta_reteica: Optional[str] = None
    cuenta_reteiva: Optional[str] = None
    cuenta_inc: Optional[str] = None
    # Cuentas del lado de venta (facturas EMITIDAS por la propia empresa)
    cuenta_ingresos: Optional[str] = None
    cuenta_clientes: Optional[str] = None
    cuenta_iva_generado: Optional[str] = None
    cuenta_nomina: Optional[str] = None


class EmpresaComprobantesPorTipo(BaseModel):
    """
    Tipo de comprobante contable (texto libre, ej. 'CC', 'P', 'FV') que
    debe usarse al exportar según la clasificación real del documento
    (sección 19-20-21): compras, ventas, notas y nómina normalmente van
    a comprobantes distintos, nunca al mismo.
    """
    comprobante_factura_recibida: Optional[str] = None
    comprobante_factura_emitida: Optional[str] = None
    comprobante_nota_credito: Optional[str] = None
    comprobante_nota_debito: Optional[str] = None
    comprobante_nomina: Optional[str] = None
    comprobante_documento_equivalente: Optional[str] = None


class EmpresaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    nit: str
    nombre: str
    sistema_contable: str
    responsable_iva: bool
    regimen_simple: bool
    modo_contable: str = "mixto"
    activa: bool
    creado_en: datetime


# ------------------------------------------------------------------ Cuenta
class CuentaCreate(BaseModel):
    codigo: str
    nombre: str
    tipo: Optional[str] = None


class CuentaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    empresa_id: str
    codigo: str
    nombre: str
    tipo: Optional[str] = None
    activa: bool


# -------------------------------------------------------------- Proveedor
class ProveedorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    empresa_id: str
    nit: str
    nombre: Optional[str] = None
    direccion: Optional[str] = None


# ---------------------------------------------------------- Centro costo
class CentroCostoCreate(BaseModel):
    codigo: str
    nombre: str
    activo: bool = True


class CentroCostoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    empresa_id: str
    codigo: str
    nombre: str
    activo: bool


# ------------------------------------------------------------------ Regla
class ReglaCreate(BaseModel):
    nombre: str
    criterio: Dict[str, Any]
    cuenta_codigo: str
    activa: bool = True


class ReglaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    empresa_id: str
    nombre: str
    criterio_json: str
    cuenta_id: str
    activa: bool


# ------------------------------------------------------- Historial manual
class HistorialManualCreate(BaseModel):
    proveedor_nit: str
    proveedor_nombre: Optional[str] = None
    cuenta_codigo: str
    fecha_documento: Optional[datetime] = None
    numero_documento: Optional[str] = None
    tipo_documento: Optional[str] = None
    descripcion: Optional[str] = None
    valor: Optional[float] = None
    origen: str = "manual"  # manual | sugerencia_aceptada
    usuario: Optional[str] = None


class MapeoColumnas(BaseModel):
    """
    Relaciona nombres de columna del archivo cargado con los campos
    internos que el sistema entiende. Ej:
      {"nit": "NIT_TERCERO", "cuenta": "CUENTA_PUC", "valor": "VALOR_DEBITO"}
    Solo 'nit' y 'cuenta' son obligatorios para que una fila sea válida.
    """
    nit: str
    cuenta: str
    nombre: Optional[str] = None
    fecha: Optional[str] = None
    numero_documento: Optional[str] = None
    tipo_documento: Optional[str] = None
    descripcion: Optional[str] = None
    valor: Optional[str] = None


class ImportacionResumen(BaseModel):
    id: str
    archivo_nombre: str
    total_registros: int
    registros_validos: int
    registros_rechazados: int
    detalle_rechazos: List[str] = []
    importado_en: datetime


# ------------------------------------------------------------------ Factura
class FacturaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    empresa_id: str
    carga_id: Optional[str] = None
    cufe: Optional[str] = None
    numero_factura: Optional[str] = None
    prefijo: Optional[str] = None
    tipo_comprobante_override: Optional[str] = None
    fecha_emision: Optional[datetime] = None
    nit_emisor: Optional[str] = None
    nombre_emisor: Optional[str] = None
    direccion_emisor: Optional[str] = None
    subtotal: Optional[float] = None
    iva: Optional[float] = None
    inc: Optional[float] = None
    total: Optional[float] = None
    moneda: Optional[str] = None
    forma_pago: Optional[str] = None
    fuente_extraccion: str
    confianza_extraccion: float
    relacionada_con_excel: bool
    metodo_relacion: Optional[str] = None
    motivo_no_relacionada: Optional[str] = None
    es_posible_duplicado: bool
    duplicado_de_id: Optional[str] = None
    naturaleza_documento: str = "factura"
    direccion_documento: str = "recibida"
    tercero_nit: Optional[str] = None
    tercero_nombre: Optional[str] = None
    concepto_resumen: Optional[str] = None
    estado: str
    creado_en: datetime


class CargaResumen(BaseModel):
    id: str
    archivo_excel_nombre: Optional[str] = None
    archivo_zip_nombre: Optional[str] = None
    total_filas_excel: int
    total_archivos_zip: int
    total_relacionados: int
    total_pendientes_revision: int
    total_pendientes_clasificacion: int = 0
    total_descartados: int = 0
    total_duplicados: int
    errores_zip: List[Dict[str, Any]] = []
    avisos_descarte: List[Dict[str, Any]] = []
    desglose_clasificacion: Dict[str, int] = {}
    creado_en: datetime


class CorreccionFactura(BaseModel):
    """Corrección manual sobre una factura ya extraída (sección 6)."""
    numero_factura: Optional[str] = None
    cufe: Optional[str] = None
    nit_emisor: Optional[str] = None
    nombre_emisor: Optional[str] = None
    fecha_emision: Optional[datetime] = None
    subtotal: Optional[float] = None
    iva: Optional[float] = None
    inc: Optional[float] = None
    retenciones: Optional[Dict[str, float]] = None
    total: Optional[float] = None
    nuevo_estado: Optional[str] = None
    usuario: Optional[str] = None


class ResolucionDuplicado(BaseModel):
    es_duplicado: bool   # True: confirmar y descartar; False: no es duplicado, continuar
    usuario: Optional[str] = None


# --------------------------------------------------------------- Partida doble
class GenerarPartidaRequest(BaseModel):
    cuenta_gasto_codigo: str
    contrapartida: Optional[str] = None   # si no se indica, se deriva de la dirección del documento (sección 38)
    origen_decision: str = "manual"      # "manual" | "sugerencia_aceptada"
    centro_costo_codigo: Optional[str] = None
    usuario: Optional[str] = None


class LineaPartidaOut(BaseModel):
    cuenta_codigo: str
    cuenta_nombre: str
    tipo: str
    valor: float
    descripcion: str
    centro_costo_codigo: Optional[str] = None


class PartidaOut(BaseModel):
    factura_id: str
    lineas: List[LineaPartidaOut]
    total_debito: float
    total_credito: float
    balanceado: bool
    errores: List[str] = []


# ---------------------------------------------------- Plantillas de exportación
class ColumnaPlantilla(BaseModel):
    label: str
    source: str   # fecha | cuenta | nombre_cuenta | nit | tercero | numero_factura | cufe | concepto | debito | credito | fijo
    valor_fijo: str = ""


class PlantillaCreate(BaseModel):
    nombre: str = Field(min_length=1, description="No puede quedar vacío — se usa para identificarla en el historial de auditoría")
    sistema_contable: str  # "siigo_pyme" | "world_office"
    delimitador: str = "|"
    extension: str = "txt"
    incluir_encabezado: bool = True
    formato_fecha: str = "%Y-%m-%d"
    columnas: List[ColumnaPlantilla]
    equivalencias_cuentas: Dict[str, str] = {}

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre de la plantilla no puede quedar vacío ni ser solo espacios.")
        return v


class PlantillaOut(BaseModel):
    id: str
    empresa_id: str
    nombre: str
    sistema_contable: str
    delimitador: str
    extension: str
    incluir_encabezado: bool
    formato_fecha: str
    columnas: List[ColumnaPlantilla]
    equivalencias_cuentas: Dict[str, str]
    activa: bool


class GenerarExportacionRequest(BaseModel):
    plantilla_id: str
    factura_ids: List[str]
    usuario: Optional[str] = None


class ExportacionResumen(BaseModel):
    id: str
    sistema_contable: str
    cantidad_registros: int
    estado: str
    errores: List[str] = []
    archivo_nombre: Optional[str] = None
    creado_en: datetime
class OpcionCuenta(BaseModel):
    cuenta_codigo: str
    cuenta_nombre: str
    usos: int
    porcentaje: float


class SugerenciaCuenta(BaseModel):
    proveedor_nit: str
    proveedor_nombre: Optional[str] = None
    total_documentos_historicos: int
    opciones: List[OpcionCuenta]
    cuenta_sugerida: Optional[str] = None
    motivo: str
    fuente: str  # "historial" | "regla" | "sin_informacion"
