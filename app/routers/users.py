from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import User, Project, Task
from app.schemas import UserResponse, ProjectResponse, TaskResponse
from typing import List

router = APIRouter(prefix="/api", tags=["api"])


# Auth APIs
@router.post("/auth/register")
async def api_register(db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to register"}


@router.post("/auth/login")
async def api_login():
    return {"message": "Use the web interface to login"}


@router.post("/auth/logout")
async def api_logout():
    return {"message": "Use the web interface to logout"}


# Project APIs
@router.get("/projects", response_model=List[ProjectResponse])
async def api_list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project))
    projects = result.scalars().all()
    return projects


@router.post("/projects", response_model=ProjectResponse)
async def api_create_project(db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to create projects"}


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def api_get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return project


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def api_update_project(project_id: int, db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to update projects"}


@router.delete("/projects/{project_id}")
async def api_delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to delete projects"}


# Task APIs
@router.get("/tasks", response_model=List[TaskResponse])
async def api_list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task))
    tasks = result.scalars().all()
    return tasks


@router.post("/tasks", response_model=TaskResponse)
async def api_create_task(db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to create tasks"}


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def api_get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalars().first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return task


@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def api_update_task(task_id: int, db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to update tasks"}


@router.delete("/tasks/{task_id}")
async def api_delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to delete tasks"}


# Admin APIs
@router.get("/admin/users", response_model=List[UserResponse])
async def api_list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return users


@router.put("/admin/users/{user_id}/role")
async def api_update_user_role(user_id: int, db: AsyncSession = Depends(get_db)):
    return {"message": "Use the web interface to update user roles"}
