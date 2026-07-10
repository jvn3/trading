"""Auth endpoints (S1.8): register, login, logout, me. Cookie-based sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from alphadash.api.deps import SESSION_COOKIE, get_current_user, get_db, now_utc
from alphadash.db.models import User
from alphadash.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=auth_service.MIN_PASSWORD_LEN)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str
    onboarded: bool = False  # S3.1: false until the guided interview completes


def _set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.app_env == "production",
        max_age=int(auth_service.SESSION_TTL.total_seconds()),
        path="/",
    )


@router.post("/register", response_model=MeResponse, status_code=201)
def register(
    body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> MeResponse:
    try:
        registered = auth_service.register_user(
            db, email=body.email, password=body.password, display_name=body.display_name
        )
        _, token = auth_service.login(db, email=body.email, password=body.password, now=now_utc())
    except auth_service.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    _set_cookie(response, request, token)
    user = registered.user
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        onboarded=user.onboarded_at is not None,
    )


@router.post("/login", response_model=MeResponse)
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> MeResponse:
    try:
        user, token = auth_service.login(
            db, email=body.email, password=body.password, now=now_utc()
        )
    except auth_service.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from None
    _set_cookie(response, request, token)
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        onboarded=user.onboarded_at is not None,
    )


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_service.logout(db, token=token, now=now_utc())
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        onboarded=user.onboarded_at is not None,
    )
