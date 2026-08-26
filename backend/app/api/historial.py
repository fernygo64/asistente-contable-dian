import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_empresa_activa, usuario_actual
from app.models.models import Empresa, OrigenDecision, ImportacionHistorico, HistorialContable, HistorialTecnicoSiigo, Proveedor, CuentaContable, Empleado
from app.schemas.schemas import SugerenciaCuenta, ImportacionResumen, HistorialManualCreate
from app.services import historial_service, importacion_service
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.excel_utils import leer_columnas_excel
from app.services.excel_utils import leer_columnas_excel, leer_dataframe_excel
from app.services.mapeo_conocido_service import sugerir_mapeo
from app.services.balance_service import detectar_mapeo_balance
from app.services.balance_jerarquico_service import detectar_columnas_balance_terceros, parsear_balance_terceros_jerarquico

router = APIRouter(prefix="/empresas/{empresa_id}/historial", tags=["historial"])


@router.post("/importar-balance", response_model=ImportacionResumen, status_code=201)
async def importar_balance_automatico(
    empresa_id: str, archivo: UploadFile = File(...),
    db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa),
    usuario: str = Depends(usuario_actual),
):
    """
    Balance de prueba por tercero — el usuario NO mapea nada, solo sube
    el archivo. Prueba dos formas automáticamente:
    1) El "Balance de Prueba por Terceros" real de Siigo Nube (código de
       cuenta jerárquico en columnas GRUPO/CUENTA/SUBCUENTA/AUXILIAR,
       detalle por NIT heredando el código más profundo vigente).
    2) Un balance plano genérico (NIT y cuenta en la misma fila).
    Si ninguna de las dos formas se reconoce con confianza, se rechaza
    con un mensaje claro en vez de adivinar.
    """
    contenido = await archivo.read()
    try:
        df = leer_dataframe_excel(contenido, archivo.filename or "balance.xlsx")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"No se pudo leer el archivo: {e}")
    columnas = list(df.columns)

    columnas_jerarquicas = detectar_columnas_balance_terceros(columnas)
    if columnas_jerarquicas:
        registros_crudos = parsear_balance_terceros_jerarquico(df, columnas_jerarquicas)
        if not registros_crudos:
            raise HTTPException(
                status_code=422,
                detail="Se reconoció la forma de 'Balance de Prueba por Terceros' de Siigo Nube, pero no se "
                       "encontró ninguna fila de detalle con NIT y cuenta. Revisa que el archivo tenga datos.",
            )
        registros = [
            {"nit": r["nit"], "cuenta_codigo": r["cuenta_codigo"], "nombre": r["nombre_tercero"],
             "nombre_cuenta": r["nombre_cuenta"], "fecha": None, "numero": None, "tipo": None,
             "desc": None, "valor": r["valor"]}
            for r in registros_crudos
        ]
        importacion = importacion_service.importar_registros_historico(
            db, empresa_id, archivo.filename, registros,
            {"formato": "balance_terceros_siigo_nube", **columnas_jerarquicas}, usuario, len(registros),
        )
        db.commit()
        return ImportacionResumen(
            id=importacion.id, archivo_nombre=importacion.archivo_nombre,
            total_registros=importacion.total_registros, registros_validos=importacion.registros_validos,
            registros_rechazados=importacion.registros_rechazados,
            detalle_rechazos=json.loads(importacion.detalle_rechazos_json or "[]"),
            filas_tecnicas_siigo=getattr(importacion, "filas_tecnicas_siigo", 0),
            importado_en=importacion.importado_en,
        )

    deteccion = detectar_mapeo_balance(columnas)
    if deteccion["faltantes"]:
        raise HTTPException(
            status_code=422,
            detail=f"No se pudieron identificar automáticamente las columnas: {', '.join(deteccion['faltantes'])}. "
                   f"Este archivo no tiene la forma esperada de un balance por tercero (ni el formato jerárquico "
                   f"de Siigo Nube, ni uno plano simple) — usa la sección 'Auxiliar / Movimiento contable' de más "
                   f"abajo, donde sí puedes mapear las columnas a mano. Columnas detectadas: {columnas}",
        )

    try:
        importacion = importacion_service.importar_historico(
            db, empresa_id, contenido, archivo.filename, deteccion["mapeo"], usuario, cuentas_excluir=None
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))

    if importacion.registros_validos == 0 and importacion.total_registros > 0:
        # Las columnas SE reconocieron por nombre, pero ninguna fila tenía
        # NIT y cuenta en la misma fila a la vez — típico de un archivo con
        # estructura jerárquica que el detector plano no supo leer (nunca
        # se debe reportar como "éxito" si no aprendió nada realmente).
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Se reconocieron columnas con nombre de NIT y de cuenta, pero ninguna fila del archivo tenía "
                   "ambos datos juntos — esto pasa cuando el código de cuenta viene repartido en varias columnas "
                   "(jerárquico) en vez de en una sola. Prueba con la sección 'Auxiliar / Movimiento contable' de "
                   "más abajo, donde puedes mapear las columnas a mano.",
        )
    db.commit()
    return ImportacionResumen(
        id=importacion.id,
        archivo_nombre=importacion.archivo_nombre,
        total_registros=importacion.total_registros,
        registros_validos=importacion.registros_validos,
        registros_rechazados=importacion.registros_rechazados,
        detalle_rechazos=json.loads(importacion.detalle_rechazos_json or "[]"),
        filas_tecnicas_siigo=getattr(importacion, "filas_tecnicas_siigo", 0),
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
        filas_tecnicas_siigo=getattr(importacion, "filas_tecnicas_siigo", 0),
        importado_en=importacion.importado_en,
    )


@router.get("/importaciones")
def listar_importaciones(empresa_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa)):
    """Historial de cargas ya hechas (sección 12) — el sistema nunca las borra ni modifica
    por su cuenta; el usuario sí puede borrar una explícitamente con DELETE .../{id}."""
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


@router.delete("/importaciones/{importacion_id}")
def eliminar_importacion(empresa_id: str, importacion_id: str, db: Session = Depends(get_db),
                          empresa: Empresa = Depends(get_empresa_activa), usuario: str = Depends(usuario_actual)):
    """
    Borra una carga de historial que se hizo por error (archivo
    equivocado, empresa equivocada, etc.) — junto con TODAS las
    decisiones de aprendizaje que trajo esa carga en particular (las
    filas de HistorialContable con ese importacion_id). Nunca borra los
    proveedores ni las cuentas contables en sí: pueden seguir usándose
    por otras importaciones o por partidas ya generadas — solo se
    olvida el "esto se usó para ese NIT" que trajo esta carga.
    """
    importacion = db.query(ImportacionHistorico).filter(
        ImportacionHistorico.empresa_id == empresa_id, ImportacionHistorico.id == importacion_id
    ).first()
    if not importacion:
        raise HTTPException(status_code=404, detail="Importación no encontrada en esta empresa.")

    from app.models.models import HistorialContable
    decisiones_borradas = db.query(HistorialContable).filter(
        HistorialContable.empresa_id == empresa_id, HistorialContable.importacion_id == importacion_id
    ).delete()
    tecnicas_borradas = db.query(HistorialTecnicoSiigo).filter(
        HistorialTecnicoSiigo.empresa_id == empresa_id, HistorialTecnicoSiigo.importacion_id == importacion_id
    ).delete()

    nombre_archivo = importacion.archivo_nombre
    db.delete(importacion)
    auditoria_registrar(db, empresa_id, "ImportacionHistorico", importacion_id, "importacion_eliminada",
                         {"archivo": nombre_archivo, "decisiones_borradas": decisiones_borradas, "filas_tecnicas_siigo_borradas": tecnicas_borradas}, usuario)
    db.commit()
    return {"eliminada": True, "id": importacion_id, "decisiones_borradas": decisiones_borradas, "filas_tecnicas_siigo_borradas": tecnicas_borradas}


@router.get("/resumen-aprendizaje")
def resumen_aprendizaje(empresa_id: str, db: Session = Depends(get_db),
                        empresa: Empresa = Depends(get_empresa_activa)):
    """Resumen compacto de lo aprendido; no exige parametrización manual."""
    decisiones = db.query(HistorialContable).filter(HistorialContable.empresa_id == empresa_id).count()
    tecnicas_q = db.query(HistorialTecnicoSiigo).filter(HistorialTecnicoSiigo.empresa_id == empresa_id)
    tecnicas = tecnicas_q.count()
    cuentas = {x[0] for x in tecnicas_q.with_entities(HistorialTecnicoSiigo.cuenta_codigo).all() if x[0]}
    terceros = {x[0] for x in tecnicas_q.with_entities(HistorialTecnicoSiigo.nit).all() if x[0]}
    comprobantes = {
        (x[0] or "", x[1] or "")
        for x in tecnicas_q.with_entities(
            HistorialTecnicoSiigo.tipo_comprobante, HistorialTecnicoSiigo.codigo_comprobante
        ).all() if x[0] or x[1]
    }
    importaciones = db.query(ImportacionHistorico).filter(ImportacionHistorico.empresa_id == empresa_id).count()
    return {
        "importaciones": importaciones,
        "decisiones_contables": decisiones,
        "filas_tecnicas": tecnicas,
        "cuentas": len(cuentas),
        "terceros": len(terceros),
        "comprobantes": len(comprobantes),
        "campos_siigo": 123 if tecnicas else 0,
    }


@router.get("/sugerencia", response_model=SugerenciaCuenta)
def sugerir(empresa_id: str, nit: str, descripcion: str | None = None, direccion: str | None = None,
            db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa)):
    resultado = historial_service.sugerir_cuenta(db, empresa_id, nit, descripcion, direccion)
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


@router.get("/detectar-empleados")
def detectar_empleados_desde_historial(empresa_id: str, db: Session = Depends(get_db),
                                        empresa: Empresa = Depends(get_empresa_activa)):
    """
    Busca en el historial YA CARGADO (Auxiliar/Movimiento contable)
    comprobantes de nómina completos: agrupa las líneas por su mismo
    "número de documento" y, cuando encuentra que ese comprobante usó
    la cuenta de "nómina por pagar" configurada en Empresas → Cuentas
    de nómina, el NIT de esa línea es el candidato a EMPLEADO — y si en
    el MISMO comprobante también aparecen las cuentas de salud/pensión/
    ARL/caja de compensación por pagar, sus NIT son las afiliaciones
    reales de ese empleado (nunca se inventa una afiliación: solo se
    reporta lo que de verdad coincidió en el mismo comprobante real).

    Nunca crea nada solo — devuelve candidatos para que el usuario
    confirme cuáles quiere dar de alta en "Empleados".
    """
    cuentas_nomina = {
        "eps": empresa.cuenta_salud_por_pagar_id, "afp": empresa.cuenta_pension_por_pagar_id,
        "arl": empresa.cuenta_arl_por_pagar_id, "caja": empresa.cuenta_caja_compensacion_por_pagar_id,
    }
    if not empresa.cuenta_nomina_por_pagar_id:
        return {"candidatos": [],
                "aviso": "Configura primero la cuenta de 'Nómina por pagar' en Empresas → Cuentas de nómina "
                         "para poder detectar empleados desde el historial."}

    filas = (
        db.query(HistorialContable)
        .filter(HistorialContable.empresa_id == empresa_id, HistorialContable.numero_documento.isnot(None))
        .all()
    )
    if not filas:
        return {"candidatos": [], "aviso": "Todavía no hay historial cargado (Auxiliar/Movimiento contable)."}

    por_documento: dict[str, list[HistorialContable]] = {}
    for f in filas:
        por_documento.setdefault(f.numero_documento, []).append(f)

    proveedores_ids = {f.proveedor_id for lista in por_documento.values() for f in lista}
    proveedores = {p.id: p for p in db.query(Proveedor).filter(Proveedor.id.in_(proveedores_ids)).all()}

    candidatos_por_nit: dict[str, dict] = {}
    for numero_documento, lineas in por_documento.items():
        linea_empleado = next((l for l in lineas if l.cuenta_id == empresa.cuenta_nomina_por_pagar_id), None)
        if not linea_empleado:
            continue
        prov_empleado = proveedores.get(linea_empleado.proveedor_id)
        if not prov_empleado:
            continue

        candidato = candidatos_por_nit.setdefault(prov_empleado.nit, {
            "nit": prov_empleado.nit, "nombre": prov_empleado.nombre,
            "eps_nit": None, "eps_nombre": None, "afp_nit": None, "afp_nombre": None,
            "arl_nit": None, "arl_nombre": None, "caja_compensacion_nit": None, "caja_compensacion_nombre": None,
            "comprobantes_detectados": 0,
        })
        candidato["comprobantes_detectados"] += 1

        for clave, campo_cuenta_id in cuentas_nomina.items():
            if not campo_cuenta_id:
                continue
            linea_afiliacion = next((l for l in lineas if l.cuenta_id == campo_cuenta_id), None)
            if not linea_afiliacion:
                continue
            prov_afiliacion = proveedores.get(linea_afiliacion.proveedor_id)
            if not prov_afiliacion:
                continue
            campo_nit = {"eps": "eps_nit", "afp": "afp_nit", "arl": "arl_nit", "caja": "caja_compensacion_nit"}[clave]
            campo_nombre = {"eps": "eps_nombre", "afp": "afp_nombre", "arl": "arl_nombre", "caja": "caja_compensacion_nombre"}[clave]
            candidato[campo_nit] = prov_afiliacion.nit
            candidato[campo_nombre] = prov_afiliacion.nombre

    ya_existentes = {e.nit for e in db.query(Empleado).filter_by(empresa_id=empresa_id).all()}
    candidatos = [c for c in candidatos_por_nit.values() if c["nit"] not in ya_existentes]
    return {"candidatos": candidatos, "aviso": None}


_PALABRAS_CLAVE_CUENTA_NOMINA = {
    "cuenta_salario": ["salario", "sueldo"],
    "cuenta_auxilio_transporte": ["auxilio de transporte", "auxilio transporte"],
    "cuenta_nomina_por_pagar": ["nomina por pagar", "nómina por pagar", "salarios por pagar"],
    "cuenta_salud_por_pagar": ["salud por pagar", "eps por pagar"],
    "cuenta_pension_por_pagar": ["pension por pagar", "pensión por pagar", "fondo de pension", "afp por pagar"],
    "cuenta_cesantias": ["cesantias", "cesantías"],
    "cuenta_cesantias_por_pagar": ["cesantias por pagar", "cesantías por pagar"],
    "cuenta_intereses_cesantias": ["intereses sobre cesantias", "intereses cesantias", "intereses sobre cesantías"],
    "cuenta_intereses_cesantias_por_pagar": ["intereses cesantias por pagar", "intereses sobre cesantias por pagar"],
    "cuenta_prima": ["prima de servicios", "prima"],
    "cuenta_prima_por_pagar": ["prima por pagar", "prima de servicios por pagar"],
    "cuenta_vacaciones": ["vacaciones"],
    "cuenta_vacaciones_por_pagar": ["vacaciones por pagar"],
    "cuenta_arl": ["arl", "riesgos laborales"],
    "cuenta_arl_por_pagar": ["arl por pagar"],
    "cuenta_caja_compensacion": ["caja de compensacion", "caja de compensación"],
    "cuenta_caja_compensacion_por_pagar": ["caja de compensacion por pagar", "caja de compensación por pagar"],
}


@router.get("/sugerir-cuentas-nomina")
def sugerir_cuentas_nomina(empresa_id: str, db: Session = Depends(get_db),
                            empresa: Empresa = Depends(get_empresa_activa)):
    """
    Busca en las cuentas propias de la empresa (típicamente con nombres
    reales ya traídos del historial cargado) coincidencias por palabra
    clave para cada uno de los 16 conceptos de "Cuentas de nómina" —
    solo SUGIERE, nunca guarda nada solo; si hay ambigüedad (2+
    coincidencias para el mismo concepto) no arriesga, deja ese
    concepto sin sugerencia para que el usuario decida.
    """
    from app.services.historial_service import _normalizar_texto

    cuentas = db.query(CuentaContable).filter(
        CuentaContable.empresa_id == empresa_id, CuentaContable.activa.is_(True)
    ).all()

    sugerencias = {}
    for campo, palabras in _PALABRAS_CLAVE_CUENTA_NOMINA.items():
        coincidencias = [
            c for c in cuentas
            if any(p in _normalizar_texto(c.nombre) for p in [_normalizar_texto(pal) for pal in palabras])
        ]
        if len(coincidencias) == 1:
            c = coincidencias[0]
            sugerencias[campo] = {"codigo": c.codigo, "nombre": c.nombre}
    return {"sugerencias": sugerencias}
