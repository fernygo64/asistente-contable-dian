"""Autenticación real, aislamiento multiempresa y autorización por rol/permisos."""
from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import AUTH_REQUIRED
from app.database import get_db
from app.models.models import Empresa, Usuario, UsuarioEmpresa
from app.services.auth_service import decode_token, permisos_asignacion


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    ac_session: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Usuario | None:
    """Devuelve el usuario autenticado. AUTH_REQUIRED=0 existe solo para regresión/local."""
    if not AUTH_REQUIRED:
        return None
    token = ac_session
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
    payload = decode_token(db, token)
    if not payload:
        raise HTTPException(status_code=401, detail="La sesión venció o no es válida. Inicia sesión nuevamente.")
    user = db.query(Usuario).filter(Usuario.id == payload.get("sub")).first()
    if not user or not user.activo:
        raise HTTPException(status_code=401, detail="Usuario inactivo o inexistente.")
    if int(user.token_version or 1) != int(payload.get("ver", 0)):
        raise HTTPException(status_code=401, detail="La sesión fue revocada. Inicia sesión nuevamente.")
    return user


def require_authenticated(user: Usuario | None = Depends(get_current_user)) -> Usuario | None:
    return user


def usuario_actual(
    user: Usuario | None = Depends(get_current_user),
    x_user: str = Header(default="usuario_sin_identificar"),
) -> str:
    return user.email if user else x_user


def _permiso_para_request(request: Request) -> str:
    path = request.url.path.lower()
    method = request.method.upper()

    if "/usuarios" in path:
        return "usuarios_gestionar"
    if "/auditoria" in path:
        return "auditoria_ver"
    if "/historial" in path:
        return "historial_ver" if method == "GET" else "historial_gestionar"
    if "/documentos" in path:
        if method == "GET":
            return "documentos_ver"
        if method == "DELETE" or "eliminar" in path:
            return "documentos_eliminar"
        if "/cargar" in path or "/excel-" in path:
            return "documentos_cargar"
        return "facturas_operar"
    if "/exportaciones" in path or "/plantillas" in path:
        return "exportaciones_ver" if method == "GET" else "exportaciones_generar"
    if "/empleados" in path:
        return "empresa_ver" if method == "GET" else "empleados_gestionar"
    if "/siigo" in path or "/cuentas" in path or "/centros-costo" in path or "/reglas" in path:
        return "empresa_ver" if method == "GET" else "empresa_configurar"
    if method == "GET":
        return "empresa_ver"
    if any(x in path for x in ("/desactivar", "/reactivar")) or method == "DELETE":
        return "empresa_administrar"
    return "empresa_configurar"


def get_asignacion_empresa(db: Session, user: Usuario, empresa_id: str) -> UsuarioEmpresa | None:
    return db.query(UsuarioEmpresa).filter(
        UsuarioEmpresa.usuario_id == user.id,
        UsuarioEmpresa.empresa_id == empresa_id,
        UsuarioEmpresa.activo.is_(True),
    ).first()


def verificar_permiso_empresa(db: Session, user: Usuario | None, empresa_id: str, permiso: str) -> UsuarioEmpresa | None:
    if user is None:  # AUTH_REQUIRED=0
        return None
    if user.es_superadmin:
        return None
    asignacion = get_asignacion_empresa(db, user, empresa_id)
    if not asignacion:
        # 404 evita revelar la existencia de empresas ajenas.
        raise HTTPException(status_code=404, detail="Empresa no encontrada.")
    if permiso not in permisos_asignacion(asignacion):
        raise HTTPException(status_code=403, detail=f"No tienes permiso para esta acción ({permiso}).")
    return asignacion


def get_empresa_activa(
    empresa_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario | None = Depends(get_current_user),
) -> Empresa:
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail=f"Empresa {empresa_id} no existe.")
    verificar_permiso_empresa(db, user, empresa_id, _permiso_para_request(request))
    if not empresa.activa:
        raise HTTPException(status_code=403, detail=f"Empresa {empresa_id} está inactiva.")
    return empresa


def require_superadmin(user: Usuario | None = Depends(get_current_user)) -> Usuario | None:
    if user is None:
        return None
    if not user.es_superadmin:
        raise HTTPException(status_code=403, detail="Esta acción requiere un administrador general.")
    return user
