# Team Task Manager

A full-stack team task management application built with **FastAPI**, featuring a three-tier role hierarchy, project-scoped permissions, and a modern dark-mode UI.

---

## Features

- **Authentication** — Session-based login/register with bcrypt password hashing
- **Three-tier Role System** — `superadmin > admin > member` with enforced hierarchy
- **Project Management** — Create, edit, delete projects; filter by ownership
- **Task Management** — Create tasks, assign to members, set priority & due dates, update status inline
- **Permission Enforcement** — Only project owners (and outranking admins) can add tasks; admins cannot act on superadmin-owned projects
- **Admin Panel** — Manage users, toggle active status, promote/demote roles within your rank
- **Dashboard** — Live stats: tasks by status, project progress, recent activity
- **Docker + PostgreSQL** — One-command deployment via Docker Compose
- **Railway-ready** — `PORT` and `DATABASE_URL` auto-detected for Railway deployment

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy 2 (async), Pydantic |
| Database | PostgreSQL (Docker/production), SQLite (local dev) |
| Async driver | `asyncpg` (Postgres), `aiosqlite` (SQLite) |
| Frontend | Jinja2 templates, Vanilla CSS (custom design system) |
| Auth | Session cookies, bcrypt |
| Package manager | uv |
| Containerisation | Docker, Docker Compose |

---

## Project Structure

```
├── app/
│   ├── main.py           # App entry point, lifespan, error handlers
│   ├── database.py       # Async engine, session factory
│   ├── models.py         # SQLAlchemy ORM models
│   ├── schemas.py        # Pydantic schemas
│   ├── auth.py           # Session helpers, password hashing
│   ├── seed.py           # Default user seeding
│   ├── config.py         # Settings, Jinja2 templates
│   ├── routers/
│   │   ├── auth.py       # Login / register / logout
│   │   ├── dashboard.py  # Dashboard stats
│   │   ├── projects.py   # Project CRUD + members
│   │   ├── tasks.py      # Task CRUD + status update
│   │   ├── admin.py      # Admin user management
│   │   ├── users.py      # Public user lookup
│   │   └── profile.py    # Profile management
│   ├── templates/        # Jinja2 HTML templates
│   └── static/           # CSS, JS, assets
├── tests/
│   ├── conftest.py       # Test DB fixtures
│   ├── test_app.py       # Smoke tests
│   └── test_projects.py  # Permission & feature tests
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

---

## Quick Start

### Option A — Local dev (SQLite, no Docker)

```bash
# 1. Install dependencies
uv sync

# 2. Copy and configure environment
cp .env.example .env

# 3. Run the app
python app/main.py
# or: uv run uvicorn app.main:app --reload
```

App runs at **`http://localhost:8765`** (or `8000` if `APP_PORT` not set).

---

### Option B — Docker Compose (PostgreSQL)

```bash
# First run — builds image and starts Postgres
docker compose up --build

# Background
docker compose up -d

# Rebuild after code changes
docker compose up --build

# Full reset (wipe database)
docker compose down -v && docker compose up --build
```

App runs at **`http://localhost:8765`**.

---

## Environment Variables

Copy `.env.example` to `.env` and edit as needed:

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Session signing secret — **change in production** | weak placeholder |
| `PORT` | Host port Docker exposes | `8765` |
| `DB_PASSWORD` | PostgreSQL user password | `ttm_password` |
| `DATABASE_URL` | Full DB connection string (local dev) | SQLite file |
| `DB_ECHO` | Set to `1` to log SQL queries | `0` |

> In Docker, `DATABASE_URL` is set automatically by Compose and does not need to be in `.env`.

---

## Default Seed Accounts

Created automatically on first startup:

| Role | Email | Password |
|---|---|---|
| Superadmin | `superadmin@example.com` | `superadmin123` |
| Admin | `admin@example.com` | `admin123` |
| Member | `member@example.com` | `member123` |

## Demo Data

On a **fresh database** (no existing projects), the seeder also creates 3 demo projects with 10 tasks to give the dashboard and project views realistic data immediately.

| Project | Owner | Tasks | Overdue |
|---|---|---|---|
| Website Redesign | admin | 4 | 2 |
| Mobile App — v2.0 | admin | 3 | 1 |
| Internal Tooling | member | 3 | 1 |

Each project has a mix of **completed**, **in-progress**, and **todo** tasks. Overdue tasks have a `due_date` set in the past so dashboard indicators fire on first launch.

> Demo data is **skipped** if any project already exists — safe to run `seed_database()` on an existing database without duplicating data.

To get a fresh seed (wipe everything and start over):

```bash
# Local
rm -f team_task_manager.db && python app/main.py

# Docker
docker compose down -v && docker compose up --build
```

---

## Role Hierarchy

```
superadmin  →  full access, can manage everyone
   admin    →  can manage members, can act on member-owned projects
  member    →  can manage their own projects and tasks
```

**Task creation rules:**
- Project owner → always can add tasks
- Superadmin → can add tasks to any project
- Admin → can add tasks to member-owned projects, **blocked on superadmin-owned projects**
- Member → cannot add tasks to other users' projects

---

## Running Tests

```bash
# Run all tests
uv run pytest

# Verbose output
uv run pytest -v

# Specific file
uv run pytest tests/test_projects.py -v
```

---

## Deploying to Railway

1. Push to GitHub
2. Create a new Railway project → **Deploy from GitHub repo**
3. Add a **PostgreSQL** plugin — Railway sets `DATABASE_URL` automatically
4. Add `SECRET_KEY` in **Variables** tab
5. Railway handles `PORT`, HTTPS, and restarts

No other changes needed — the app auto-detects Railway's `PORT` and upgrades the Postgres URL dialect.

---

## API Routes

### Auth
| Method | Path | Description |
|---|---|---|
| `GET` | `/login` | Login page |
| `POST` | `/login` | Submit login |
| `GET` | `/register` | Register page |
| `POST` | `/register` | Submit registration |
| `GET` | `/logout` | Logout |

### Projects
| Method | Path | Description |
|---|---|---|
| `GET` | `/projects/` | List projects |
| `POST` | `/projects/create` | Create project |
| `GET` | `/projects/{id}` | Project detail |
| `POST` | `/projects/{id}/edit` | Update project |
| `POST` | `/projects/{id}/delete` | Delete project |
| `POST` | `/projects/{id}/members/add` | Add member |
| `POST` | `/projects/{id}/members/{uid}/remove` | Remove member |

### Tasks
| Method | Path | Description |
|---|---|---|
| `GET` | `/projects/{id}/tasks/create` | Create task page |
| `POST` | `/projects/{id}/tasks/create` | Submit task |
| `GET` | `/tasks/{id}` | Task detail |
| `POST` | `/tasks/{id}/status` | Update status |
| `POST` | `/tasks/{id}/update` | Update task |
| `POST` | `/tasks/{id}/delete` | Delete task |

### Admin
| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/dashboard` | Admin overview |
| `GET` | `/admin/users` | User list |
| `POST` | `/admin/users/{id}/role` | Change user role |
| `POST` | `/admin/users/{id}/toggle-active` | Enable/disable user |