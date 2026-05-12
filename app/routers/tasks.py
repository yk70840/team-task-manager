from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from app.database import get_db
from app.models import User, Project, Task, TaskStatus, TaskPriority, ProjectMember
from app.auth import get_session_user
from app.config import templates

router = APIRouter(tags=["tasks"])

# Role rank hierarchy — mirrors admin.py and projects.py
_ROLE_RANK = {"superadmin": 3, "admin": 2, "member": 1}


async def can_modify_task(actor: User, task: Task, db: AsyncSession) -> bool:
    """
    Actor can act on a task if:
      - they are the task assignee, OR
      - they own the task's project, OR
      - they are elevated AND outrank the project creator.
    """
    if task.assigned_to == actor.id:
        return True
    project = await db.get(Project, task.project_id)
    if project is None:
        return False
    if project.created_by == actor.id:
        return True
    if actor.role not in ("admin", "superadmin"):
        return False
    creator = await db.get(User, project.created_by)
    if creator is None:
        return True  # creator deleted
    return _ROLE_RANK.get(actor.role, 0) > _ROLE_RANK.get(creator.role, 0)


async def can_add_task_to_project(actor: User, project: Project, db: AsyncSession) -> bool:
    """
    Who may create tasks inside a project:
      - The project owner always can.
      - Superadmins can add to any project.
      - Admins can add only if they outrank the project creator
        (i.e. the creator is NOT a superadmin).
      - Regular members cannot add tasks to other people's projects.
    """
    if project.created_by == actor.id:
        return True
    if actor.role == "superadmin":
        return True
    if actor.role == "admin":
        creator = await db.get(User, project.created_by)
        if creator is None:
            return True  # creator deleted — allow
        return _ROLE_RANK.get(actor.role, 0) > _ROLE_RANK.get(creator.role, 0)
    return False


def render_template(request: Request, template_path: str, context: dict | None = None):
    return templates.TemplateResponse(
        request=request, name=template_path, context=context or {}
    )


async def get_assignable_users(db: AsyncSession, project: Project, actor: User) -> list:
    """Return users eligible to be assigned tasks in this project.
    - Elevated roles (admin/superadmin) see all active users.
    - Everyone else only sees project members + the project creator.
    """
    if actor.role in ("admin", "superadmin"):
        result = await db.execute(select(User).where(User.is_active.is_(True)))
        return result.scalars().all()

    # Project creator
    creator_ids = {project.created_by}

    # Project members
    members_result = await db.execute(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project.id, User.is_active.is_(True))
    )
    members = members_result.scalars().all()
    member_ids = {m.id for m in members}

    all_ids = creator_ids | member_ids
    result = await db.execute(
        select(User).where(User.id.in_(all_ids), User.is_active.is_(True))
    )
    return result.scalars().all()


async def ensure_project_member(db: AsyncSession, project_id: int, user_id: int) -> bool:
    """Auto-add user as a project member if not already one.
    Returns True if a new membership was created.
    """
    project = await db.get(Project, project_id)
    if project and project.created_by == user_id:
        return False  # creator is implicitly a member

    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if existing.scalars().first():
        return False  # already a member

    db.add(ProjectMember(project_id=project_id, user_id=user_id))
    return True


@router.get("/projects/{project_id}/tasks/create")
async def task_create_page(
    request: Request, project_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    if not await can_add_task_to_project(user, project, db):
        from app.config import templates as _t
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"code": 403, "title": "Access denied", "detail": "Only the project owner (or a higher-ranked admin) can add tasks to this project.", "user": user},
            status_code=403,
        )

    assignable = await get_assignable_users(db, project, user)
    return render_template(
        request=request,
        template_path="tasks/create.html",
        context={"project": project, "users": assignable, "user": user},
    )


@router.post("/projects/{project_id}/tasks/create")
async def create_task(
    request: Request, project_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    if not await can_add_task_to_project(user, project, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project owner (or a higher-ranked admin) can add tasks to this project.",
        )

    form_data = await request.form()
    title = form_data.get("title")
    description = form_data.get("description", "")
    priority = form_data.get("priority", "medium")
    due_date = form_data.get("due_date")
    assigned_to = form_data.get("assigned_to")

    if not title:
        assignable = await get_assignable_users(db, project, user)
        return render_template(
            request=request,
            template_path="tasks/create.html",
            context={
                "project": project,
                "users": assignable,
                "user": user,
                "error": "Task title is required",
            },
        )

    # Validate assignee is a project member (skip for elevated roles)
    if assigned_to and user.role not in ("admin", "superadmin"):
        assignable = await get_assignable_users(db, project, user)
        assignable_ids = {str(u.id) for u in assignable}
        if str(assigned_to) not in assignable_ids:
            return render_template(
                request=request,
                template_path="tasks/create.html",
                context={
                    "project": project,
                    "users": assignable,
                    "user": user,
                    "error": "Assignee must be a member of this project.",
                },
            )

    task_data = {
        "title": title,
        "description": description,
        "priority": priority,
        "project_id": project_id,
        "status": TaskStatus.todo.value,
    }

    if due_date:
        try:
            task_data["due_date"] = datetime.fromisoformat(str(due_date))
        except ValueError:
            try:
                task_data["due_date"] = datetime.fromisoformat(str(due_date) + "T00:00")
            except ValueError:
                assignable = await get_assignable_users(db, project, user)
                return render_template(
                    request=request,
                    template_path="tasks/create.html",
                    context={
                        "project": project,
                        "users": assignable,
                        "user": user,
                        "error": "Invalid due date format",
                    },
                )

    if assigned_to:
        task_data["assigned_to"] = int(str(assigned_to))

    new_task = Task(**task_data)
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    # Auto-add assignee as project member if they aren't already
    if new_task.assigned_to:
        added = await ensure_project_member(db, project_id, new_task.assigned_to)
        if added:
            await db.commit()

    return RedirectResponse(
        url=f"/projects/{project_id}?toast=Task+created+successfully&toast_type=success",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/tasks/{task_id}")
async def task_detail(
    request: Request, task_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalars().first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    project_result = await db.execute(
        select(Project).where(Project.id == task.project_id)
    )
    project = project_result.scalars().first()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    is_creator = project.created_by == user.id
    is_assignee = task.assigned_to == user.id

    is_member_result = await db.execute(
        select(User)
        .join(ProjectMember)
        .where(
            ProjectMember.project_id == task.project_id,
            ProjectMember.user_id == user.id,
        )
    )
    is_member = is_member_result.scalars().first()

    if not is_creator and not is_assignee and not is_member and not await can_modify_task(user, task, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    assignee = None
    if task.assigned_to:
        assignee_result = await db.execute(
            select(User).where(User.id == task.assigned_to)
        )
        assignee = assignee_result.scalars().first()

    assignable_users = await get_assignable_users(db, project, user)

    return render_template(
        request=request,
        template_path="tasks/detail.html",
        context={
            "task": task,
            "project": project,
            "assignee": assignee,
            "users": assignable_users,
            "user": user,
            "is_creator": is_creator,
            "is_assignee": is_assignee,
        },
    )


@router.post("/tasks/{task_id}/status")
async def update_task_status(
    request: Request, task_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalars().first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    form_data = await request.form()
    status_value = form_data.get("status")

    if not isinstance(status_value, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status"
        )

    if status_value and status_value in [s.value for s in TaskStatus]:
        task.status = status_value
        await db.commit()
        label = status_value.replace("_", " ").title()
        return RedirectResponse(
            url=f"/tasks/{task_id}?toast=Status+updated+to+{label}&toast_type=success",
            status_code=status.HTTP_302_FOUND,
        )

    return RedirectResponse(url=f"/tasks/{task_id}", status_code=status.HTTP_302_FOUND)


@router.post("/tasks/{task_id}/update")
async def update_task(
    request: Request, task_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    if not await can_modify_task(user, task, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    form_data = await request.form()
    title = form_data.get("title")
    description = form_data.get("description", "")
    priority = form_data.get("priority")
    due_date = form_data.get("due_date")
    assigned_to = form_data.get("assigned_to")

    if title:
        task.title = str(title)
    if description is not None:
        task.description = str(description)
    if priority and priority in [p.value for p in TaskPriority]:
        task.priority = str(priority)

    if due_date:
        try:
            task.due_date = datetime.fromisoformat(str(due_date))
        except ValueError:
            try:
                task.due_date = datetime.fromisoformat(str(due_date) + "T00:00")
            except ValueError:
                pass
    elif form_data.get("clear_due_date"):
        task.due_date = None

    if assigned_to:
        new_assignee_id = int(str(assigned_to)) if assigned_to != "unassigned" else None
        task.assigned_to = new_assignee_id

    await db.commit()

    # Auto-add new assignee as project member if they aren't already
    if task.assigned_to:
        added = await ensure_project_member(db, task.project_id, task.assigned_to)
        if added:
            await db.commit()

    return RedirectResponse(url=f"/tasks/{task_id}", status_code=status.HTTP_302_FOUND)


@router.post("/tasks/{task_id}/delete")
async def delete_task(
    request: Request, task_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    project = await db.get(Project, task.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if not await can_modify_task(user, task, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    project_id = task.project_id
    await db.delete(task)
    await db.commit()

    return RedirectResponse(
        url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
    )
