"""Auth router (Fase 1): register, login, me."""
from __future__ import annotations

import json

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.jwt import create_access_token
from app.db.models import User, UserProfile
from app.db.session import get_db
from app.schemas.auth import Token, UserLogin, UserRegister
from app.schemas.user import MeResponse, UserOut, UserProfileOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _profile_to_out(profile: UserProfile) -> UserProfileOut:
    try:
        prefs = json.loads(profile.preferences_json or "{}")
    except json.JSONDecodeError:
        prefs = {}
    return UserProfileOut(
        user_id=profile.user_id,
        career=profile.career,
        current_year=profile.current_year,
        preferences=prefs,
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def register(payload: UserRegister, db: Session = Depends(get_db)) -> User:
    email = payload.email.lower().strip()

    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya está registrado",
        )

    user = User(
        email=email,
        password_hash=_hash_password(payload.password),
        name=payload.name.strip(),
    )
    db.add(user)
    db.flush()  # para tener user.id

    profile = UserProfile(user_id=user.id)
    db.add(profile)

    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    email = payload.email.lower().strip()

    user = db.query(User).filter(User.email == email).first()
    if user is None or not _verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )

    token = create_access_token(user.id)
    return Token(access_token=token)


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if profile is None:
        # No debería pasar (se crea junto al user), pero defendemos igual.
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return MeResponse(
        user=UserOut.model_validate(current_user),
        profile=_profile_to_out(profile),
    )
