from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import engine, Base, get_db
from app.seed import seed_database
from app.routers import auth, dashboard, projects, tasks, admin, users, profile
from app.config import SECRET_KEY, templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()

    import os as _os
    port = _os.getenv("PORT", "8765")
    print(f"\n  ✅  Team Task Manager is running → http://localhost:{port}\n")

    yield


app = FastAPI(
    title="Team Task Manager",
    description="A team task management application",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.secret_key = SECRET_KEY

app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ── No-cache middleware ───────────────────────────────────────
# Prevents the browser from serving stale cached HTML on back-navigation.
# Static assets are excluded so CSS/JS/images are still cached normally.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

class NoCacheHTMLMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheHTMLMiddleware)



app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(profile.router)


# ── Custom error pages ────────────────────────────────────────
_ERROR_META = {
    403: ("Access Denied",  "You don't have permission to view this page."),
    404: ("Page Not Found", "The page you're looking for doesn't exist or has been moved."),
    500: ("Server Error",   "Something went wrong on our end. Please try again later."),
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    from app.auth import get_session_user
    from app.database import get_db as _get_db

    code = exc.status_code
    title, default_detail = _ERROR_META.get(code, ("Error", str(exc.detail)))

    # Try to get the current user so the navbar renders
    try:
        async for db in _get_db():
            user = await get_session_user(request, db)
            break
    except Exception:
        user = None

    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=code,
        context={
            "user": user,
            "code": code,
            "title": title,
            "detail": str(exc.detail) if exc.detail else default_detail,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles path/query param type errors (e.g. /projects/hello where int expected)."""
    from app.auth import get_session_user
    from app.database import get_db as _get_db

    try:
        async for db in _get_db():
            user = await get_session_user(request, db)
            break
    except Exception:
        user = None

    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=404,
        context={
            "user": user,
            "code": 404,
            "title": "Page Not Found",
            "detail": "The page you're looking for doesn't exist or has an invalid address.",
        },
    )


@app.get("/")
async def root(request: Request, db: AsyncSession = Depends(get_db)):
    from app.auth import get_session_user

    user = await get_session_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


if __name__ == "__main__":
    import os
    import uvicorn

    # PORT is the standard variable used by Railway and Docker Compose.
    port = int(os.getenv("PORT") or 8765)
    print(f"Going to use port: {port}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
