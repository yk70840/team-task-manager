from fastapi import APIRouter, Request, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import timedelta
from app.database import get_db
from app.models import User, UserRole
from app.auth import (
    hash_password,
    verify_password,
    get_session_user,
    get_user_by_email,
    get_user_by_username,
)
from app.config import templates

router = APIRouter(prefix="", tags=["auth"])


def render_template(request: Request, template_path: str, context: dict | None = None):
    return templates.TemplateResponse(
        request=request, name=template_path, context=context or {}
    )


@router.get("/login")
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return render_template(request=request, template_path="login.html")


@router.post("/login")
async def login(request: Request, db: AsyncSession = Depends(get_db)):
    form_data = await request.form()
    email = str(form_data.get("email", ""))
    password = str(form_data.get("password", ""))

    if not email or not password:
        return render_template(
            request=request,
            template_path="login.html",
            context={"error": "Email and Password are required"},
        )

    user = await get_user_by_email(db, email)
    if not user or not verify_password(password, user.hashed_password):
        return render_template(
            request=request,
            template_path="login.html",
            context={"error": "Invalid Email or password"},
        )

    if not user.is_active:
        return render_template(
            request=request,
            template_path="login.html",
            context={"error": "User account is inactive"},
        )

    SESSION_NAME = "session_id"
    SESSION_LIFETIME = timedelta(days=1)

    from itsdangerous import URLSafeTimedSerializer

    serializer = URLSafeTimedSerializer(request.app.state.secret_key)
    session_token = serializer.dumps({"user_id": user.id})

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=SESSION_NAME,
        value=session_token,
        httponly=True,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        samesite="lax",
    )
    return response


@router.get("/register")
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return render_template(
        request=request,
        template_path="register.html",
    )


@router.post("/register")
async def register(request: Request, db: AsyncSession = Depends(get_db)):
    form_data = await request.form()
    username = str(form_data.get("username", ""))
    email = str(form_data.get("email", ""))
    password = str(form_data.get("password", ""))
    confirm_password = str(form_data.get("confirm_password", ""))

    if not username or not email or not password:
        return render_template(
            request=request,
            template_path="login.html",
            context={"error": "All fields are required"},
        )

    if password != confirm_password:
        return render_template(
            request=request,
            template_path="register.html",
            context={"error": "Password do not match"},
        )

    if len(password) < 6:
        return render_template(
            request=request,
            template_path="register.html",
            context={"error": "password must be atleast 6 characters long"},
        )

    existing_user = await get_user_by_email(db, email)
    if existing_user:
        return render_template(
            request=request,
            template_path="register.html",
            context={"error": "IEmail already registered"},
        )

    existing_username = await get_user_by_username(db, username)
    if existing_username:
        return render_template(
            request=request,
            template_path="register.html",
            context={"error": "Username already taken"},
        )

    hashed_password = hash_password(password)
    new_user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        role=UserRole.member.value,
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    SESSION_NAME = "session_id"
    SESSION_LIFETIME = timedelta(days=1)

    from itsdangerous import URLSafeTimedSerializer

    serializer = URLSafeTimedSerializer(request.app.state.secret_key)
    session_token = serializer.dumps({"user_id": new_user.id})

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=SESSION_NAME,
        value=session_token,
        httponly=True,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session_id")
    return response
