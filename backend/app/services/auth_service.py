"""Autenticación, contraseñas, sesiones y matriz de permisos multiempresa."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import AUTH_TOKEN_HOURS
from app.models.models import ConfiguracionAplicacion, Usuario, UsuarioEmpresa

PBKDF2_ITERATIONS = 310_000
ROLES = ("contador",)

PERMISOS = (
    "empresa_ver",
    "empresa_configurar",
    "empresa_administrar",
    "usuarios_gestionar",
    "historial_ver",
    "historial_gestionar",
    "documentos_ver",
    "documentos_cargar",
    "documentos_eliminar",
    "facturas_operar",
    "empleados_gestionar",
    "exportaciones_ver",
    "exportaciones_generar",
    "auditoria_ver",
)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    # Todos los usuarios no administradores son Contadores con acceso
    # operativo completo a las empresas asignadas. La única facultad
    # reservada al Administrador General es crear/editar/eliminar usuarios.
    "contador": set(PERMISOS) - {"usuarios_gestionar"},
}



def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + pad)


def hash_password(password: str) -> str:
    validar_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _b64d(salt), int(iterations))
        return hmac.compare_digest(_b64e(digest), expected)
    except Exception:
        return False


def validar_password(password: str) -> None:
    if len(password or "") < 10:
        raise ValueError("La contraseña debe tener al menos 10 caracteres.")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise ValueError("La contraseña debe incluir letras y números.")


def normalizar_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Correo electrónico inválido.")
    return email


def _get_secret(db: Session) -> str:
    env_secret = os.environ.get("AUTH_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret
    row = db.get(ConfiguracionAplicacion, "auth_secret_key")
    if row:
        return row.valor
    secret = secrets.token_urlsafe(48)
    row = ConfiguracionAplicacion(clave="auth_secret_key", valor=secret)
    db.add(row)
    try:
        db.commit()
        return secret
    except IntegrityError:
        db.rollback()
        row = db.get(ConfiguracionAplicacion, "auth_secret_key")
        if not row:
            raise
        return row.valor


def create_token(db: Session, user: Usuario, hours: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "email": user.email,
        "ver": int(user.token_version or 1),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours or AUTH_TOKEN_HOURS)).timestamp()),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = _b64e(hmac.new(_get_secret(db).encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(db: Session, token: str) -> dict[str, Any] | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64e(hmac.new(_get_secret(db).encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body).decode("utf-8"))
        if int(payload.get("exp", 0)) <= int(datetime.now(timezone.utc).timestamp()):
            return None
        return payload
    except Exception:
        return None


def permisos_asignacion(asignacion: UsuarioEmpresa) -> set[str]:
    # El modelo se simplificó: cualquier usuario asignado a una empresa es
    # Contador y dispone de todas las funciones operativas, excepto usuarios.
    return set(ROLE_PERMISSIONS["contador"])


def serializar_asignacion(asignacion: UsuarioEmpresa) -> dict[str, Any]:
    return {
        "empresa_id": asignacion.empresa_id,
        "rol": "contador",
        "permisos": sorted(permisos_asignacion(asignacion)),
        "permisos_personalizados": {},
        "activo": asignacion.activo,
    }
