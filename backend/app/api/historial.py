import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import Empresa, OrigenDecision, ImportacionHistorico
from app.schemas.schemas import SugerenciaCuenta, ImportacionResumen, HistorialManualCreate
from app.services import historial_service, importacion_service
from app.services.excel_utils import leer_columnas_excel
from app.services.mapeo_conocido_service import sugerir_mapeo
from app.services.balance_service import detectar_mapeo_balance

router = APIRouter(prefix="/empresas/{empresa_id}/historial", tags=["historial"])


@router.post("/importar-balance", response_model=ImportacionResumen, status_code=201)
async def importar_balance_automatico(
    empresa_id: str, archivo: UploadFile = File(...),
    db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa),
    usuario: str = Depends(usuario_actual),
):
    """
    Balance de prueba por tercero — el usuario NO mapea nada, solo sube
    el archivo. Se detectan las columnas (NIT, cuenta, nombre de cuenta)
    por palabras clave, y si se identifican con confianza, se importa
    directo. Un balance por tercero no trae contrapartida/control
    mezclada como un auxiliar completo, así que no requiere excluir
    cuentas — cada fila ya es una asociación NIT↔cuenta útil de aprender.
    """
    contenido = await archivo.read()
    try:
        columnas = leer_columnas_excel(contenido, archivo.filename or "balance.xlsx")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"No se pudo leer el archivo: {e}")

    deteccion = detectar_mapeo_balance(columnas)
    if deteccion["faltantes"]:
        raise HTTPException(
            status_code=422,
            detail=f"No se pudieron identificar automáticamente las columnas: {', '.join(deteccion['faltantes'])}. "
                   f"Este archivo no tiene la forma esperada de un balance por tercero simple — usa la sección "
                   f"'Auxiliar / Movimiento contable' de más abajo, donde sí puedes mapear las columnas a mano. "
                   f"Columnas detectadas en tu archivo: {columnas}",
        )

    try:
        importacion = importacion_service.importar_historico(
            db, empresa_id, contenido, archivo.filename, deteccion["mapeo"], usuario, cuentas_excluir=None
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    return ImportacionResumen(
        id=importacion.id,
        archivo_nombre=importacion.archivo_nombre,
        total_registros=importacion.total_registros,
        registros_validos=importacion.registros_validos,
        registros_rechazados=importacion.registros_rechazados,
        detalle_rechazos=json.loads(importacion.detalle_rechazos_json or "[]"),
        importado_en=importacion.importado_en,
    )


@router.post("/sugerir-mapeo")
async def sugerir_mapeo_historico(empresa_id: str, archivo: UploadFile = File(...),
                                   db: Session = Depends(get_db),
                                   empresa: Empresa = Depends(get_empresa_activa)):
    """
    Propone el mapeo de columnas automáticamente según el sistema
    contable declarado por la empresa (Siigo Pyme / World Office),
    verificado contra archivos reales de ambos. Solo sugiere columnas
    que SÍ existen en el archivo subido — el usuario revisa y ajusta
    antes de importar, nunca se aplica a ciegas.
    """
    contenido = await archivo.read()
    try:
        columnas = leer_columnas_excel(contenido, archivo.filename or "archivo.xlsx")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"No se pudo leer el archivo: {e}")
    sistema = empresa.sistema_contable.value if hasattr(empresa.sistema_contable, "value") else empresa.sistema_contable
    resultado = sugerir_mapeo(sistema, columnas)

    # Cuentas de control ya configuradas en "Cuentas base" — se sugieren
    # como candidatas a excluir del aprendizaje (proveedores, IVA,
    # retenciones no son la cuenta de gasto/ingreso real).
    from app.models.models import CuentaContable
    ids_control = [
        empresa.cuenta_proveedores_id, empresa.cuenta_caja_id, empresa.cuenta_banco_id,
        empresa.cuenta_iva_descontable_id, empresa.cuenta_retefuente_id,
        empresa.cuenta_reteica_id, empresa.cuenta_reteiva_id, empresa.cuenta_inc_id,
    ]
    codigos_excluir_sugeridos = []
    for cuenta_id in ids_control:
        if not cuenta_id:
            continue
        cta = db.get(CuentaContable, cuenta_id)
        if cta:
            codigos_excluir_sugeridos.append(cta.codigo)

    return {"sistema_contable": sistema, "columnas": columnas,
            "cuentas_excluir_sugeridas": codigos_excluir_sugeridos, **resultado}


@router.post("/importar", response_model=ImportacionResumen, status_code=201)
async def importar_historico(
    empresa_id: str,
    archivo: UploadFile = File(...),
    mapeo_nit: str = Form(...),
    mapeo_cuenta: str = Form(...),
    mapeo_nombre: str | None = Form(default=None),
    mapeo_nombre_cuenta: str | None = Form(default=None, description="Columna con el NOMBRE de la cuenta (ej. 'IVA Compras 19%') — permite luego reconocer por texto si una cuenta es de IVA al 19%, al 5%, de servicios o de compras, usando el nombre real de TU plan de cuentas"),
    mapeo_fecha: str | None = Form(default=None),
    mapeo_anio: str | None = Form(default=None),
    mapeo_mes: str | None = Form(default=None),
    mapeo_dia: str | None = Form(default=None),
    mapeo_numero_documento: str | None = Form(default=None),
    mapeo_tipo_documento: str | None = Form(default=None),
    mapeo_descripcion: str | None = Form(default=None),
    mapeo_valor: str | None = Form(default=None),
    mapeo_valor_debito: str | None = Form(default=None),
    mapeo_valor_credito: str | None = Form(default=None),
    cuentas_excluir: str | None = Form(default=None, description="Códigos/prefijos separados por coma a ignorar del aprendizaje (ej. proveedores, bancos, IVA)"),
    db: Session = Depends(get_db),
    empresa: Empresa = Depends(get_empresa_activa),
    usuario: str = Depends(usuario_actual),
):
    mapeo = {
        "nit": mapeo_nit, "cuenta": mapeo_cuenta, "nombre": mapeo_nombre,
        "nombre_cuenta": mapeo_nombre_cuenta,
        "fecha": mapeo_fecha, "anio": mapeo_anio, "mes": mapeo_mes, "dia": mapeo_dia,
        "numero_documento": mapeo_numero_documento,
        "tipo_documento": mapeo_tipo_documento, "descripcion": mapeo_descripcion,
        "valor": mapeo_valor, "valor_debito": mapeo_valor_debito, "valor_credito": mapeo_valor_credito,
    }
    lista_excluir = [c.strip() for c in (cuentas_excluir or "").split(",") if c.strip()]
    contenido = await archivo.read()
    try:
        importacion = importacion_service.importar_historico(
            db, empresa_id, contenido, archivo.filename, mapeo, usuario, cuentas_excluir=lista_excluir
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    import json
    return ImportacionResumen(
        id=importacion.id,
        archivo_nombre=importacion.archivo_nombre,
        total_registros=importacion.total_registros,
        registros_validos=importacion.registros_validos,
        registros_rechazados=importacion.registros_rechazados,
        detalle_rechazos=json.loads(importacion.detalle_rechazos_json or "[]"),
        importado_en=importacion.importado_en,
    )


@router.get("/importaciones")
def listar_importaciones(empresa_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa)):
    """Historial de cargas ya hechas (sección 12) — nunca se borran ni se modifican."""
    filas = (
        db.query(ImportacionHistorico)
        .filter(ImportacionHistorico.empresa_id == empresa_id)
        .order_by(ImportacionHistorico.importado_en.desc())
        .all()
    )
    return [
        {
            "id": f.id, "archivo_nombre": f.archivo_nombre, "total_registros": f.total_registros,
            "registros_validos": f.registros_validos, "registros_rechazados": f.registros_rechazados,
            "usuario": f.usuario, "importado_en": f.importado_en,
        }
        for f in filas
    ]


@router.get("/sugerencia", response_model=SugerenciaCuenta)
def sugerir(empresa_id: str, nit: str, descripcion: str | None = None,
            db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa)):
    resultado = historial_service.sugerir_cuenta(db, empresa_id, nit, descripcion)
    return SugerenciaCuenta(**resultado)


@router.post("/decision", status_code=201)
def registrar_decision_manual(empresa_id: str, payload: HistorialManualCreate,
                               db: Session = Depends(get_db),
                               empresa: Empresa = Depends(get_empresa_activa),
                               usuario: str = Depends(usuario_actual)):
    """
    Registra una decisión de contabilización (manual o sugerencia aceptada).
    Nunca modifica el historial anterior — siempre agrega una fila nueva,
    para que el aprendizaje evolucione conservando la trazabilidad
    (secciones 11 y 41).
    """
    if payload.origen not in ("manual", "sugerencia_aceptada"):
        raise HTTPException(status_code=422, detail="origen debe ser 'manual' o 'sugerencia_aceptada'.")

    proveedor = historial_service.get_or_create_proveedor(
        db, empresa_id, payload.proveedor_nit, payload.proveedor_nombre
    )
    cuenta = historial_service.get_or_create_cuenta(db, empresa_id, payload.cuenta_codigo)

    fila = historial_service.registrar_decision(
        db, empresa_id, proveedor.id, cuenta.id,
        origen=OrigenDecision(payload.origen),
        fecha_documento=payload.fecha_documento,
        numero_documento=payload.numero_documento,
        tipo_documento=payload.tipo_documento,
        descripcion=payload.descripcion,
        valor=payload.valor,
    )
    db.commit()
    return {
        "id": fila.id,
        "proveedor_id": proveedor.id,
        "cuenta_id": cuenta.id,
        "mensaje": "Decisión registrada. El historial se actualizó sin borrar decisiones anteriores.",
    }
