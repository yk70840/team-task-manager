from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import User, Project, Task, ProjectMember, UserRole
from app.auth import get_session_user
from app.config import templates
from app.routers.tasks import can_add_task_to_project

router = APIRouter(prefix="/projects", tags=["projects"])

# Role ranks — mirrors admin.py
_ROLE_RANK = {"superadmin": 3, "admin": 2, "member": 1}


async def can_modify_project(actor: User, project: Project, db: AsyncSession) -> bool:
    """
    An actor can modify a project if:
      - they own it, OR
      - they are elevated (admin/superadmin) AND outrank the project creator.
    """
    if project.created_by == actor.id:
        return True
    if actor.role not in ("admin", "superadmin"):
        return False
    # Fetch creator role to compare ranks
    creator = await db.get(User, project.created_by)
    if creator is None:
        return True  # creator deleted — allow
    return _ROLE_RANK.get(actor.role, 0) > _ROLE_RANK.get(creator.role, 0)


def render_template(request: Request, template_path: str, context: dict | None = None):
    return templates.TemplateResponse(
        request=request, name=template_path, context=context or {}
    )


async def get_user_projects(db: AsyncSession, user_id: int):
    # Created projects
    created_result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks), selectinload(Project.creator))
        .where(Project.created_by == user_id)
    )
    created = created_result.scalars().all()

    # Member projects
    member_result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks), selectinload(Project.creator))
        .join(ProjectMember)
        .where(ProjectMember.user_id == user_id)
    )
    member = member_result.scalars().all()

    return list({p.id: p for p in list(created) + list(member)}.values())


@router.get("/")
async def projects_list(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    if user.role == UserRole.superadmin:
        # Superadmin sees every project in the system
        result = await db.execute(
            select(Project).options(
                selectinload(Project.tasks),
                selectinload(Project.creator),
            )
        )
        projects = result.scalars().all()
    elif user.role == UserRole.admin:
        # Admin sees all non-superadmin projects PLUS any superadmin
        # projects they have been explicitly added to as a member.
        result = await db.execute(
            select(Project)
            .join(User, Project.created_by == User.id)
            .options(
                selectinload(Project.tasks),
                selectinload(Project.creator),
            )
            .where(
                or_(
                    User.role != UserRole.superadmin,
                    Project.id.in_(
                        select(ProjectMember.project_id).where(
                            ProjectMember.user_id == user.id
                        )
                    ),
                )
            )
        )
        projects = result.scalars().all()
    else:
        projects = await get_user_projects(db, user.id)

    return render_template(
        request=request,
        template_path="projects/list.html",
        context={"projects": projects, "user": user},
    )


@router.get("/create")
async def project_create_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return render_template(
        request=request, template_path="projects/create.html", context={"user": user}
    )


@router.post("/create")
async def create_project(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    form_data = await request.form()
    name = form_data.get("name")
    description = form_data.get("description", "")

    if not name:
        return render_template(
            request=request,
            template_path="projects/create.html",
            context={"user": user, "error": "Project name is required"},
        )

    new_project = Project(name=name, description=description, created_by=user.id)
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)

    member = ProjectMember(user_id=user.id, project_id=new_project.id)
    db.add(member)
    await db.commit()

    return RedirectResponse(
        url=f"/projects/{new_project.id}", status_code=status.HTTP_302_FOUND
    )


@router.get("/{project_id}")
async def project_detail(
    request: Request, project_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(
        select(Project)
        .options(
            selectinload(Project.tasks).selectinload(Task.assignee),
            selectinload(Project.creator),
        )
        .where(Project.id == project_id)
    )
    project = project_result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    is_member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    )
    is_member = is_member_result.scalars().first()

    # Members and owners can always view — hierarchy only restricts non-members.
    if not is_member and project.created_by != user.id:
        if user.role == UserRole.admin and project.creator.role == UserRole.superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot access superadmin-owned projects",
            )
        if user.role not in (UserRole.admin, UserRole.superadmin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )

    tasks_result = await db.execute(select(Task).where(Task.project_id == project_id))
    tasks = tasks_result.scalars().all()

    members_result = await db.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
    )
    members = members_result.scalars().all()

    member_users = []
    for m in members:
        u_result = await db.execute(select(User).where(User.id == m.user_id))
        u = u_result.scalars().first()
        if u:
            member_users.append(u)

    is_creator = project.created_by == user.id
    can_add_task = await can_add_task_to_project(user, project, db)

    return render_template(
        request=request,
        template_path="projects/detail.html",
        context={
            "project": project,
            "tasks": tasks,
            "members": member_users,
            "user": user,
            "is_member": bool(is_member),
            "is_creator": is_creator,
            "can_add_task": can_add_task,
        },
    )


@router.get("/{project_id}/edit")
async def project_edit_page(
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

    if not await can_modify_project(user, project, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return render_template(
        request=request,
        template_path="projects/edit.html",
        context={"project": project, "user": user},
    )


@router.post("/{project_id}/edit")
async def update_project(
    request: Request,
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    user = await get_session_user(request, db)

    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalars().first()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if not await can_modify_project(user, project, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    form_data = await request.form()

    name = form_data.get("name")
    description = form_data.get("description", "")

    if not isinstance(name, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project name",
        )

    if not isinstance(description, str):
        description = ""

    project.name = name
    project.description = description

    await db.commit()
    await db.refresh(project)

    return RedirectResponse(
        url=f"/projects/{project_id}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/{project_id}/delete")
async def delete_project(
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

    if not await can_modify_project(user, project, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await db.delete(project)
    await db.commit()

    return RedirectResponse(url="/projects", status_code=status.HTTP_302_FOUND)


@router.post("/{project_id}/members/add")
async def add_member(
    request: Request, project_id: int, db: AsyncSession = Depends(get_db)
):
    user = await get_session_user(request, db)
    if not user:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
        )

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    if project.created_by != user.id and user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    form_data = await request.form()
    email = form_data.get("email")

    if not email:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
        )

    new_member_result = await db.execute(select(User).where(User.email == email))
    new_member = new_member_result.scalars().first()
    if not new_member:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
        )

    existing_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == new_member.id,
        )
    )
    existing = existing_result.scalars().first()

    if existing:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
        )

    member = ProjectMember(user_id=new_member.id, project_id=project_id)
    db.add(member)
    await db.commit()

    return RedirectResponse(
        url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
    )


@router.post("/{project_id}/members/{member_id}/remove")
async def remove_member(
    request: Request,
    project_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db),
):
    current_user = await get_session_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )

    if not await can_modify_project(current_user, project, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if member_id == project.created_by:
        return RedirectResponse(
            url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
        )

    membership_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == member_id
        )
    )
    membership = membership_result.scalars().first()

    if membership:
        await db.delete(membership)
        await db.commit()

    return RedirectResponse(
        url=f"/projects/{project_id}", status_code=status.HTTP_302_FOUND
    )
