from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.config import AUTH_TOKEN_HOURS
from app.core.security import get_current_user, get_empresa_activa, require_superadmin
from app.models.models import Empresa, Usuario, UsuarioEmpresa
from app.schemas.schemas import (
    AuthBootstrapIn, AuthLoginIn, CambioPasswordIn,
    UsuarioEmpresaAsignacionIn, UsuarioEmpresaUpdateIn,
)
from app.services.auditoria_service import registrar as auditoria_registrar
from app.services.auth_service import (
    PERMISOS, ROLES, ROLE_PERMISSIONS, create_token, hash_password,
    normalizar_email, permisos_asignacion, serializar_asignacion,
    validar_password, verify_password,
)

router = APIRouter(prefix="/auth", tags=["autenticacion"])
usuarios_router = APIRouter(prefix="/empresas/{empresa_id}/usuarios", tags=["usuarios"])


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key="ac_session", value=token, httponly=True, secure=request.url.scheme == "https",
        samesite="strict", max_age=AUTH_TOKEN_HOURS * 3600, path="/",
    )


def _user_publico(db: Session, user: Usuario):
    if user.es_superadmin:
        empresas = db.query(Empresa).order_by(Empresa.nombre).all()
        asignaciones = [{
            "empresa_id": e.id, "empresa_nombre": e.nombre, "rol": "superadmin",
            "permisos": list(PERMISOS), "permisos_personalizados": {}, "activo": True,
        } for e in empresas]
    else:
        rows = db.query(UsuarioEmpresa, Empresa).join(
            Empresa, Empresa.id == UsuarioEmpresa.empresa_id
        ).filter(
            UsuarioEmpresa.usuario_id == user.id,
            UsuarioEmpresa.activo.is_(True),
        ).order_by(Empresa.nombre).all()
        asignaciones = []
        for asig, emp in rows:
            d = serializar_asignacion(asig)
            d["empresa_nombre"] = emp.nombre
            asignaciones.append(d)
    return {
        "id": user.id,
        "email": user.email,
        "nombre": user.nombre,
        "activo": user.activo,
        "es_superadmin": user.es_superadmin,
        "asignaciones": asignaciones,
    }


@router.get("/estado")
def estado_auth(db: Session = Depends(get_db)):
    return {"requiere_bootstrap": db.query(Usuario.id).first() is None}


@router.post("/bootstrap", status_code=201)
def bootstrap(payload: AuthBootstrapIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if db.query(Usuario.id).first() is not None:
        raise HTTPException(status_code=409, detail="El administrador inicial ya fue creado.")
    try:
        email = normalizar_email(payload.email)
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    user = Usuario(
        email=email, nombre=payload.nombre.strip(), password_hash=password_hash,
        activo=True, es_superadmin=True,
    )
    db.add(user)
    db.flush()
    # El primer administrador queda ligado también a las empresas existentes,
    # aunque el atributo superadmin ya le da acceso global. Esto conserva
    # trazabilidad si luego se le retira el privilegio global.
    for empresa in db.query(Empresa).all():
        db.add(UsuarioEmpresa(usuario_id=user.id, empresa_id=empresa.id, rol="contador", permisos_json="{}"))
    db.commit()
    db.refresh(user)
    token = create_token(db, user)
    _set_session_cookie(response, request, token)
    return {"token": token, "usuario": _user_publico(db, user)}


@router.post("/login")
def login(payload: AuthLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        email = normalizar_email(payload.email)
    except ValueError:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")
    user = db.query(Usuario).filter(Usuario.email == email).first()
    now = datetime.now(timezone.utc)
    if user and user.bloqueado_hasta:
        bloqueado = user.bloqueado_hasta
        if bloqueado.tzinfo is None:
            bloqueado = bloqueado.replace(tzinfo=timezone.utc)
        if bloqueado > now:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Intenta nuevamente en unos minutos.")
        user.bloqueado_hasta = None
        user.intentos_fallidos = 0
    if not user or not user.activo or not verify_password(payload.password, user.password_hash):
        if user and user.activo:
            user.intentos_fallidos = int(user.intentos_fallidos or 0) + 1
            if user.intentos_fallidos >= 5:
                from datetime import timedelta
                user.bloqueado_hasta = now + timedelta(minutes=15)
                user.intentos_fallidos = 0
            db.commit()
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")
    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    user.ultimo_acceso = now
    db.commit()
    token = create_token(db, user)
    _set_session_cookie(response, request, token)
    return {"token": token, "usuario": _user_publico(db, user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("ac_session", path="/")
    return {"ok": True}


@router.get("/me")
def me(user: Usuario | None = Depends(get_current_user), db: Session = Depends(get_db)):
    if user is None:
        return {"id": "test", "email": "test@local", "nombre": "Pruebas", "es_superadmin": True, "asignaciones": []}
    return _user_publico(db, user)


@router.get("/matriz-permisos")
def matriz_permisos(user: Usuario | None = Depends(get_current_user)):
    # Compatibilidad con clientes anteriores. Ya no existe una matriz editable.
    return {"roles": ["contador"], "permisos": [], "matriz": {}}


@router.post("/cambiar-password")
def cambiar_password(payload: CambioPasswordIn, user: Usuario | None = Depends(get_current_user), db: Session = Depends(get_db)):
    if user is None:
        return {"ok": True}
    if not verify_password(payload.password_actual, user.password_hash):
        raise HTTPException(status_code=422, detail="La contraseña actual no es correcta.")
    try:
        validar_password(payload.password_nueva)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    user.password_hash = hash_password(payload.password_nueva)
    user.token_version = int(user.token_version or 1) + 1
    db.commit()
    return {"ok": True, "sesion_revocada": True}


@router.get("/admin/usuarios")
def listar_todos_usuarios(_admin: Usuario | None = Depends(require_superadmin), db: Session = Depends(get_db)):
    return [_user_publico(db, u) for u in db.query(Usuario).order_by(Usuario.nombre).all()]


def _actualizar_empresas_usuario(db: Session, user: Usuario, empresa_ids: list[str]) -> None:
    validas = {e.id for e in db.query(Empresa).filter(Empresa.id.in_(empresa_ids or [])).all()} if empresa_ids else set()
    existentes = {a.empresa_id: a for a in db.query(UsuarioEmpresa).filter(UsuarioEmpresa.usuario_id == user.id).all()}
    for empresa_id, asig in existentes.items():
        if empresa_id not in validas:
            db.delete(asig)
    for empresa_id in validas:
        asig = existentes.get(empresa_id)
        if not asig:
            asig = UsuarioEmpresa(usuario_id=user.id, empresa_id=empresa_id)
            db.add(asig)
        asig.rol = "contador"
        asig.permisos_json = "{}"
        asig.activo = True


@router.post("/admin/usuarios", status_code=201)
def crear_usuario_global(payload: dict, _admin: Usuario | None = Depends(require_superadmin), db: Session = Depends(get_db)):
    try:
        email = normalizar_email(str(payload.get("email") or ""))
        password_hash = hash_password(str(payload.get("password") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if db.query(Usuario).filter(Usuario.email == email).first():
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese correo.")
    user = Usuario(email=email, nombre=str(payload.get("nombre") or email).strip(), password_hash=password_hash, activo=True, es_superadmin=False)
    db.add(user); db.flush()
    _actualizar_empresas_usuario(db, user, list(payload.get("empresa_ids") or []))
    db.commit(); db.refresh(user)
    return _user_publico(db, user)


@router.patch("/admin/usuarios/{usuario_id}")
def administrar_usuario(usuario_id: str, payload: dict, admin: Usuario | None = Depends(require_superadmin), db: Session = Depends(get_db)):
    user = db.get(Usuario, usuario_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if user.es_superadmin and admin and user.id != admin.id:
        raise HTTPException(status_code=422, detail="El Administrador General no se administra desde esta ficha.")
    if "nombre" in payload and payload["nombre"]:
        user.nombre = str(payload["nombre"]).strip()
    if "email" in payload and payload["email"]:
        try: nuevo = normalizar_email(str(payload["email"]))
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc))
        otro = db.query(Usuario).filter(Usuario.email == nuevo, Usuario.id != user.id).first()
        if otro: raise HTTPException(status_code=409, detail="Ese correo ya pertenece a otro usuario.")
        user.email = nuevo
    if "activo" in payload and not user.es_superadmin:
        user.activo = bool(payload["activo"]); user.token_version = int(user.token_version or 1) + 1
    if payload.get("password_nueva"):
        try:
            user.password_hash = hash_password(str(payload["password_nueva"])); user.token_version = int(user.token_version or 1) + 1
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    if "empresa_ids" in payload and not user.es_superadmin:
        _actualizar_empresas_usuario(db, user, list(payload.get("empresa_ids") or []))
        user.token_version = int(user.token_version or 1) + 1
    db.commit(); db.refresh(user)
    return _user_publico(db, user)


@router.delete("/admin/usuarios/{usuario_id}")
def eliminar_usuario_global(usuario_id: str, admin: Usuario | None = Depends(require_superadmin), db: Session = Depends(get_db)):
    user = db.get(Usuario, usuario_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if user.es_superadmin or (admin and user.id == admin.id):
        raise HTTPException(status_code=422, detail="No puedes eliminar al Administrador General.")
    db.query(UsuarioEmpresa).filter(UsuarioEmpresa.usuario_id == user.id).delete(synchronize_session=False)
    db.delete(user); db.commit()
    return {"eliminado": True, "usuario_id": usuario_id}


def _serializar_usuario_empresa(db: Session, user: Usuario, asig: UsuarioEmpresa | None = None):
    if asig:
        d = serializar_asignacion(asig)
    else:
        d = {"rol": "superadmin", "permisos": list(PERMISOS), "permisos_personalizados": {}, "activo": True}
    return {
        "id": user.id, "email": user.email, "nombre": user.nombre,
        "activo": user.activo, "es_superadmin": user.es_superadmin, **d,
    }


@usuarios_router.get("")
def listar_usuarios_empresa(
    empresa_id: str, db: Session = Depends(get_db), empresa: Empresa = Depends(get_empresa_activa)
):
    rows = db.query(UsuarioEmpresa, Usuario).join(
        Usuario, Usuario.id == UsuarioEmpresa.usuario_id
    ).filter(UsuarioEmpresa.empresa_id == empresa_id).order_by(Usuario.nombre).all()
    return [_serializar_usuario_empresa(db, user, asig) for asig, user in rows]


@usuarios_router.post("", status_code=201)
def asignar_usuario_empresa(
    empresa_id: str, payload: UsuarioEmpresaAsignacionIn, db: Session = Depends(get_db),
    empresa: Empresa = Depends(get_empresa_activa), actor: Usuario | None = Depends(get_current_user),
):
    
    desconocidos = set(payload.permisos) - set(PERMISOS)
    if desconocidos:
        raise HTTPException(status_code=422, detail=f"Permisos desconocidos: {', '.join(sorted(desconocidos))}")
    try:
        email = normalizar_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    user = db.query(Usuario).filter(Usuario.email == email).first()
    if not user:
        if not payload.password:
            raise HTTPException(status_code=422, detail="Para un usuario nuevo debes definir una contraseña inicial.")
        try:
            ph = hash_password(payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        user = Usuario(email=email, nombre=(payload.nombre or email).strip(), password_hash=ph, activo=True)
        db.add(user); db.flush()

    asig = db.query(UsuarioEmpresa).filter(
        UsuarioEmpresa.usuario_id == user.id, UsuarioEmpresa.empresa_id == empresa_id
    ).first()
    if not asig:
        asig = UsuarioEmpresa(usuario_id=user.id, empresa_id=empresa_id)
        db.add(asig)
    asig.rol = "contador"
    asig.permisos_json = "{}"
    asig.activo = True
    auditoria_registrar(db, empresa_id, "UsuarioEmpresa", user.id, "usuario_asignado",
                        {"email": user.email, "rol": asig.rol, "permisos": payload.permisos or {}}, actor.email if actor else "test")
    db.commit(); db.refresh(asig); db.refresh(user)
    return _serializar_usuario_empresa(db, user, asig)


@usuarios_router.patch("/{usuario_id}")
def actualizar_usuario_empresa(
    empresa_id: str, usuario_id: str, payload: UsuarioEmpresaUpdateIn, db: Session = Depends(get_db),
    empresa: Empresa = Depends(get_empresa_activa), actor: Usuario | None = Depends(get_current_user),
):
    asig = db.query(UsuarioEmpresa).filter(
        UsuarioEmpresa.empresa_id == empresa_id, UsuarioEmpresa.usuario_id == usuario_id
    ).first()
    if not asig:
        raise HTTPException(status_code=404, detail="Usuario no asignado a esta empresa.")
    if payload.rol is not None:
        if payload.rol not in ROLES:
            raise HTTPException(status_code=422, detail="Rol inválido.")
        asig.rol = "contador"
    if payload.permisos is not None:
        desconocidos = set(payload.permisos) - set(PERMISOS)
        if desconocidos:
            raise HTTPException(status_code=422, detail="Hay permisos desconocidos.")
        asig.permisos_json = json.dumps(payload.permisos, ensure_ascii=False)
    if payload.activo is not None:
        asig.activo = payload.activo
    auditoria_registrar(db, empresa_id, "UsuarioEmpresa", usuario_id, "usuario_permiso_actualizado",
                        {"rol": asig.rol, "activo": asig.activo, "permisos": json.loads(asig.permisos_json or "{}")}, actor.email if actor else "test")
    db.commit(); db.refresh(asig)
    user = db.get(Usuario, usuario_id)
    return _serializar_usuario_empresa(db, user, asig)


@usuarios_router.delete("/{usuario_id}")
def quitar_usuario_empresa(
    empresa_id: str, usuario_id: str, db: Session = Depends(get_db),
    empresa: Empresa = Depends(get_empresa_activa), actor: Usuario | None = Depends(get_current_user),
):
    asig = db.query(UsuarioEmpresa).filter(
        UsuarioEmpresa.empresa_id == empresa_id, UsuarioEmpresa.usuario_id == usuario_id
    ).first()
    if not asig:
        raise HTTPException(status_code=404, detail="Usuario no asignado a esta empresa.")
    db.delete(asig)
    auditoria_registrar(db, empresa_id, "UsuarioEmpresa", usuario_id, "usuario_acceso_retirado", {}, actor.email if actor else "test")
    db.commit()
    return {"eliminado": True, "usuario_id": usuario_id}
