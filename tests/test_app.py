import asyncio
from datetime import date
from app.auth import hash_password
from app.models import User, UserRole, Project


def _run_async(coro):
    return asyncio.run(coro)


def create_user(session_factory, username, email, password, role=UserRole.member.value):
    async def _create():
        async with session_factory() as session:
            user = User(
                username=username,
                email=email,
                hashed_password=hash_password(password),
                role=role,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _run_async(_create())


def create_project(session_factory, name, created_by):
    async def _create():
        async with session_factory() as session:
            project = Project(
                name=name, description="Test project", created_by=created_by
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return project

    return _run_async(_create())


def test_home_redirects_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/login"


def test_register_and_dashboard_access(client):
    response = client.post(
        "/register",
        data={
            "username": "tester",
            "email": "tester@example.com",
            "password": "secret123",
            "confirm_password": "secret123",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert "session_id" in response.cookies

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "tester" in dashboard_response.text


def test_create_project_and_task_with_due_date(client):
    register_response = client.post(
        "/register",
        data={
            "username": "project_user",
            "email": "project_user@example.com",
            "password": "secret123",
            "confirm_password": "secret123",
        },
        follow_redirects=False,
    )
    assert register_response.status_code == 302

    project_response = client.post(
        "/projects/create",
        data={"name": "New Project", "description": "A sample project"},
        follow_redirects=False,
    )
    assert project_response.status_code == 302
    assert project_response.headers["location"].startswith("/projects/")

    due_date = date.today().isoformat()
    expected_due_date_text = date.today().strftime("%B %d, %Y")
    task_response = client.post(
        "/projects/1/tasks/create",
        data={
            "title": "Initial Task",
            "description": "Test task description",
            "priority": "high",
            "due_date": due_date,
            "assigned_to": "1",
        },
        follow_redirects=False,
    )
    assert task_response.status_code == 302
    assert task_response.headers["location"].startswith(f"/projects/")
    assert "toast" in task_response.headers["location"]

    task_page = client.get("/tasks/1")
    assert task_page.status_code == 200
    assert "Initial Task" in task_page.text
    assert expected_due_date_text in task_page.text
