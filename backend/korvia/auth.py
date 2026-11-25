"""Autenticación con contraseñas cifradas y sesiones revocables.

Las contraseñas se guardan con PBKDF2-HMAC-SHA256 (sal aleatoria). Los tokens
de sesión se guardan como hash: si alguien leyera la base de datos, no podría
reutilizarlos directamente.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from korvia.database import get_session
from korvia.models import Membership, Session as UserSession, User, WRITE_ROLES


PBKDF2_ITERATIONS = 600_000
SESSION_HOURS = int(os.getenv("KORVIA_SESSION_HOURS", "168"))
LOGIN_MAX_FAILURES = int(os.getenv("KORVIA_LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("KORVIA_LOGIN_WINDOW_SECONDS", "900"))
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Solo en memoria: se reinicia al arrancar y no se comparte entre procesos.
_login_failures: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _login_key(email: str, client_host: str | None) -> tuple[str, str]:
    return email, client_host or "desconocido"


def check_login_attempt(email: str, client_host: str | None) -> None:
    """Bloquea temporalmente tras demasiados intentos fallidos."""
    now = time.monotonic()
    attempts = _login_failures[_login_key(email, client_host)]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Espera unos minutos.",
        )


def record_login_failure(email: str, client_host: str | None) -> None:
    _login_failures[_login_key(email, client_host)].append(time.monotonic())


def clear_login_failures(email: str, client_host: str | None) -> None:
    _login_failures.pop(_login_key(email, client_host), None)


def reset_login_failures() -> None:
    """Para pruebas: borra el contador de intentos."""
    _login_failures.clear()

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Necesitas iniciar sesión.",
    headers={"WWW-Authenticate": "Bearer"},
)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str:
    normalized = normalize_email(email)
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Escribe un correo electrónico válido.")
    return normalized


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return token


def revoke_token(db: Session, token: str) -> None:
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    if session is not None:
        db.delete(session)
        db.commit()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED
    token = authorization[7:].strip()
    if not token:
        raise _UNAUTHORIZED

    session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == _hash_token(token),
            UserSession.expires_at > datetime.now(timezone.utc),
        )
    )
    if session is None:
        raise _UNAUTHORIZED

    user = db.get(User, session.user_id)
    if user is None:
        raise _UNAUTHORIZED
    return user


def get_membership(db: Session, user: User, tenant_id: str) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta empresa.",
        )
    return membership


def require_read_access(db: Session, user: User, tenant_id: str) -> Membership:
    return get_membership(db, user, tenant_id)


def require_write_access(db: Session, user: User, tenant_id: str) -> Membership:
    membership = get_membership(db, user, tenant_id)
    if membership.role not in WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu rol solo permite consultar la información.",
        )
    return membership


def require_owner_access(db: Session, user: User, tenant_id: str) -> Membership:
    membership = get_membership(db, user, tenant_id)
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el dueño de la empresa puede gestionar sus usuarios.",
        )
    return membership
