from fastapi import APIRouter, Request, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models import User, Project, Task
from app.auth import get_session_user, hash_password, verify_password
from app.config import templates

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def profile_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Stats
    task_count_result = await db.execute(
        select(func.count(Task.id)).where(Task.assigned_to == user.id)
    )
    task_count = task_count_result.scalar()

    done_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assigned_to == user.id, Task.status == "completed"
        )
    )
    done_count = done_count_result.scalar()

    project_count_result = await db.execute(
        select(func.count(Project.id)).where(Project.created_by == user.id)
    )
    project_count = project_count_result.scalar()

    return templates.TemplateResponse(
        request=request,
        name="profile/index.html",
        context={
            "user": user,
            "task_count": task_count,
            "done_count": done_count,
            "project_count": project_count,
            "error": None,
            "success": None,
        },
    )


@router.post("/update")
async def update_profile(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    form = await request.form()
    new_username = (form.get("username") or "").strip()
    new_email    = (form.get("email") or "").strip()

    errors = []

    if not new_username or len(new_username) < 3:
        errors.append("Username must be at least 3 characters.")

    if not new_email or "@" not in new_email:
        errors.append("A valid email address is required.")

    # Check uniqueness only if changed
    if new_username != user.username:
        clash_result = await db.execute(
            select(User).where(User.username == new_username)
        )
        if clash_result.scalars().first():
            errors.append("That username is already taken.")

    if new_email != user.email:
        clash_result = await db.execute(
            select(User).where(User.email == new_email)
        )
        if clash_result.scalars().first():
            errors.append("That email is already in use.")

    if not errors:
        user.username = new_username
        user.email    = new_email
        await db.commit()
        return RedirectResponse(
            url="/profile?toast=Profile+updated+successfully&toast_type=success",
            status_code=status.HTTP_302_FOUND,
        )

    # Re-fetch stats for error render
    task_count_result = await db.execute(
        select(func.count(Task.id)).where(Task.assigned_to == user.id)
    )
    done_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assigned_to == user.id, Task.status == "completed"
        )
    )
    project_count_result = await db.execute(
        select(func.count(Project.id)).where(Project.created_by == user.id)
    )

    return templates.TemplateResponse(
        request=request,
        name="profile/index.html",
        status_code=400,
        context={
            "user": user,
            "task_count": task_count_result.scalar(),
            "done_count": done_count_result.scalar(),
            "project_count": project_count_result.scalar(),
            "error": " ".join(errors),
            "success": None,
        },
    )


@router.post("/change-password")
async def change_password(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    form = await request.form()
    current_pw  = form.get("current_password", "")
    new_pw      = form.get("new_password", "")
    confirm_pw  = form.get("confirm_password", "")

    error = None
    if not verify_password(current_pw, user.hashed_password):
        error = "Current password is incorrect."
    elif len(new_pw) < 8:
        error = "New password must be at least 8 characters."
    elif new_pw != confirm_pw:
        error = "New passwords do not match."

    if error:
        # Re-fetch stats
        task_count_result = await db.execute(
            select(func.count(Task.id)).where(Task.assigned_to == user.id)
        )
        done_count_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.assigned_to == user.id, Task.status == "completed"
            )
        )
        project_count_result = await db.execute(
            select(func.count(Project.id)).where(Project.created_by == user.id)
        )
        return templates.TemplateResponse(
            request=request,
            name="profile/index.html",
            status_code=400,
            context={
                "user": user,
                "task_count": task_count_result.scalar(),
                "done_count": done_count_result.scalar(),
                "project_count": project_count_result.scalar(),
                "error": error,
                "success": None,
                "pw_error": True,  # scroll to password section
            },
        )

    user.hashed_password = hash_password(new_pw)
    await db.commit()
    return RedirectResponse(
        url="/profile?toast=Password+changed+successfully&toast_type=success",
        status_code=status.HTTP_302_FOUND,
    )
