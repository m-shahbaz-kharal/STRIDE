from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .db import get_db
from .models import User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
auth_scheme = HTTPBearer()


def _load_jwt_secret() -> str:
    """Resolve the JWT signing secret.

    Production deployments MUST set ``JWT_SECRET`` to a strong value. In
    dev/test the secret is derived from a side-channel file so tokens
    survive restarts but are still unique per machine — never the literal
    ``"change-me"`` that the previous default leaked into the world.
    """
    explicit = os.getenv("JWT_SECRET")
    if explicit:
        return explicit
    if os.getenv("STRIDE_PRODUCTION") == "1":
        raise RuntimeError("JWT_SECRET must be set when STRIDE_PRODUCTION=1")
    state_dir = os.path.join(os.path.expanduser("~"), ".stride")
    secret_path = os.path.join(state_dir, "jwt_secret")
    try:
        with open(secret_path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        os.makedirs(state_dir, exist_ok=True)
        token = secrets.token_urlsafe(64)
        with open(secret_path, "w", encoding="utf-8") as fh:
            fh.write(token)
        try:
            os.chmod(secret_path, 0o600)
        except Exception:
            pass
        return token


JWT_SECRET = _load_jwt_secret()
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        subject = payload.get("sub")
        if not subject:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return subject
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def _coerce_user_id(raw: str) -> uuid.UUID:
    """Convert a JWT ``sub`` claim into a ``UUID`` or raise ``HTTPException``."""
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(auth_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user_id = _coerce_user_id(decode_access_token(credentials.credentials))
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def resolve_user_for_token(token: Optional[str], db: Session) -> Optional[User]:
    """Best-effort user lookup for non-HTTP contexts (e.g. WebSocket).

    Returns ``None`` if the token is missing, malformed, expired, or
    points to a deleted user. WebSocket handlers should close with
    code 4001 in that case.
    """
    if not token:
        return None
    try:
        subject = decode_access_token(token)
    except HTTPException:
        return None
    try:
        user_uuid = uuid.UUID(subject)
    except (ValueError, TypeError):
        return None
    user = db.get(User, user_uuid)
    return user
