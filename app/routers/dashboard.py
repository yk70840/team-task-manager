from fastapi import APIRouter, Request, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from datetime import datetime
from app.database import get_db
from app.models import Project, Task, TaskStatus
from app.auth import get_session_user
from app.config import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Total tasks
    total_tasks_result = await db.execute(
        select(func.count(Task.id)).where(Task.assigned_to == user.id)
    )
    total_tasks = total_tasks_result.scalar()

    # Completed tasks
    completed_tasks_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assigned_to == user.id, Task.status == TaskStatus.completed.value
        )
    )
    completed_tasks = completed_tasks_result.scalar()

    # Pending tasks
    pending_tasks_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assigned_to == user.id, Task.status != TaskStatus.completed.value
        )
    )
    pending_tasks = pending_tasks_result.scalar()

    # Overdue tasks
    overdue_tasks_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assigned_to == user.id,
            Task.due_date < datetime.now(),
            Task.due_date.is_not(None),
            Task.status != TaskStatus.completed.value,
        )
    )
    overdue_tasks = overdue_tasks_result.scalar()

    # Created projects
    created_projects_result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.created_by == user.id)
    )
    created_projects = created_projects_result.scalars().all()

    # Recent tasks
    user_tasks_result = await db.execute(
        select(Task)
        .options(selectinload(Task.project))
        .where(Task.assigned_to == user.id)
        .order_by(Task.created_at.desc())
        .limit(5)
    )
    user_tasks = user_tasks_result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "user": user,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": pending_tasks,
            "overdue_tasks": overdue_tasks,
            "projects": created_projects[:5],
            "recent_tasks": user_tasks,
        },
    )
