"""Auth dependencies (Fase 1).

`get_current_user` se reusa en cualquier endpoint protegido.
"""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.jwt import decode_token
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

# tokenUrl apunta al endpoint de login para que Swagger muestre el botón "Authorize".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=True)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError as err:
        raise credentials_exc from err
    except jwt.InvalidTokenError as err:
        raise credentials_exc from err

    sub = payload.get("sub")
    if sub is None:
        raise credentials_exc
    try:
        user_id = int(sub)
    except (TypeError, ValueError) as err:
        raise credentials_exc from err

    user = db.get(User, user_id)
    if user is None:
        raise credentials_exc

    # Si en el futuro queremos invalidar tokens viejos, podemos chequear
    # un `token_version` contra `user.token_version`. En Fase 1 no hace falta.
    _ = settings
    return user
