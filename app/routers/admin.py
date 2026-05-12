from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import User, Project, Task, UserRole
from app.auth import get_session_user
from app.config import templates

router = APIRouter(prefix="/admin", tags=["admin"])

# ── Role hierarchy helpers ────────────────────────────────────
ROLE_RANK = {
    UserRole.superadmin.value: 3,
    UserRole.admin.value: 2,
    UserRole.member.value: 1,
}


def can_manage(actor_role: str, target_role: str) -> bool:
    """Return True if actor outranks target (can manage them)."""
    return ROLE_RANK.get(actor_role, 0) > ROLE_RANK.get(target_role, 0)


def is_elevated(role: str) -> bool:
    """True for admin or superadmin — can access admin area."""
    return role in (UserRole.admin.value, UserRole.superadmin.value)


def render_template(request, template_path, context=None):
    return templates.TemplateResponse(
        request=request, name=template_path, context=context or {}
    )


@router.get("/dashboard")
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if not is_elevated(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    total_users_result = await db.execute(select(func.count(User.id)))
    total_users = total_users_result.scalar()

    active_users_result = await db.execute(
        select(func.count(User.id)).where(User.is_active.is_(True))
    )
    active_users = active_users_result.scalar()

    admin_users_result = await db.execute(
        select(func.count(User.id)).where(User.role == UserRole.admin.value)
    )
    admin_users = admin_users_result.scalar()

    member_users_result = await db.execute(
        select(func.count(User.id)).where(User.role == UserRole.member)
    )
    member_users = member_users_result.scalar()

    total_projects_result = await db.execute(select(func.count(Project.id)))
    total_projects = total_projects_result.scalar()

    total_tasks_result = await db.execute(select(func.count(Task.id)))
    total_tasks = total_tasks_result.scalar()

    return render_template(
        request=request,
        template_path="admin/dashboard.html",
        context={
            "user": user,
            "total_users": total_users,
            "active_users": active_users,
            "admin_users": admin_users,
            "member_users": member_users,
            "total_projects": total_projects,
            "total_tasks": total_tasks,
        },
    )


@router.get("/users")
async def admin_users(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if not is_elevated(user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()

    return render_template(
        request=request,
        template_path="admin/users.html",
        context={"request": request, "user": user, "users": users},
    )


@router.post("/users/{user_id}/role")
async def update_user_role(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    current_user = await get_session_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if not is_elevated(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Cannot change own role
    if user_id == current_user.id:
        return RedirectResponse(url="/admin/users", status_code=status.HTTP_302_FOUND)

    target_user = await db.get(User, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Must outrank the target to change their role
    if not can_manage(current_user.role, target_user.role):
        return RedirectResponse(
            url="/admin/users?toast=You+cannot+change+the+role+of+a+higher-ranked+user&toast_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    form_data = await request.form()
    role = form_data.get("role")

    if not isinstance(role, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    # Build allowed roles based on actor's rank
    allowed_roles = [UserRole.member.value, UserRole.admin.value]
    if current_user.role == UserRole.superadmin.value:
        allowed_roles.append(UserRole.superadmin.value)

    if role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    # Cannot promote to a rank >= your own (superadmin can assign any role including superadmin)
    if ROLE_RANK.get(role, 0) >= ROLE_RANK.get(current_user.role, 0) and current_user.role != UserRole.superadmin.value:
        return RedirectResponse(
            url="/admin/users?toast=You+cannot+assign+a+role+equal+to+or+above+your+own&toast_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    target_user.role = role
    await db.commit()


    return RedirectResponse(
        url="/admin/users?toast=Role+updated+successfully&toast_type=success",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(
    request: Request, user_id: int, db: AsyncSession = Depends(get_db)
):
    current_user = await get_session_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if not is_elevated(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if user_id == current_user.id:
        return RedirectResponse(url="/admin/users", status_code=status.HTTP_302_FOUND)

    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not can_manage(current_user.role, target_user.role):
        return RedirectResponse(
            url="/admin/users?toast=You+cannot+modify+a+higher-ranked+user&toast_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    target_user.is_active = not target_user.is_active
    await db.commit()

    return RedirectResponse(url="/admin/users", status_code=status.HTTP_302_FOUND)


@router.post("/users/{user_id}/delete")
async def delete_user(
    request: Request, user_id: int, db: AsyncSession = Depends(get_db)
):
    current_user = await get_session_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if not is_elevated(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if user_id == current_user.id:
        return RedirectResponse(
            url="/admin/users?toast=You+cannot+delete+your+own+account&toast_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Must outrank to delete
    if not can_manage(current_user.role, target_user.role):
        return RedirectResponse(
            url="/admin/users?toast=You+cannot+delete+a+higher-ranked+user&toast_type=error",
            status_code=status.HTTP_302_FOUND,
        )

    # Prevent deleting the last superadmin
    if target_user.role == UserRole.superadmin.value:
        sa_count_result = await db.execute(
            select(func.count(User.id)).where(User.role == UserRole.superadmin.value)
        )
        if sa_count_result.scalar() <= 1:
            return RedirectResponse(
                url="/admin/users?toast=Cannot+delete+the+last+superadmin&toast_type=error",
                status_code=status.HTTP_302_FOUND,
            )

    await db.delete(target_user)
    await db.commit()

    return RedirectResponse(
        url="/admin/users?toast=User+deleted+successfully&toast_type=success",
        status_code=status.HTTP_302_FOUND,
    )
