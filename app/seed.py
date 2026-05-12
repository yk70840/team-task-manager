from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database import Base, async_session, engine
from app.models import Project, ProjectMember, Task, TaskPriority, TaskStatus, User, UserRole


SEED_USERS = [
    {
        "username": "superadmin",
        "email": "superadmin@example.com",
        "password": "superadmin123",
        "role": UserRole.superadmin,
    },
    {
        "username": "admin",
        "email": "admin@example.com",
        "password": "admin123",
        "role": UserRole.admin,
    },
    {
        "username": "member",
        "email": "member@example.com",
        "password": "member123",
        "role": UserRole.member,
    },
]

# ---------------------------------------------------------------------------
# Demo data — only created on a fresh DB (skipped if projects already exist)
# ---------------------------------------------------------------------------

def _past(days: int) -> datetime:
    """UTC datetime `days` days ago (negative = in the future)."""
    return datetime.now(UTC) - timedelta(days=days)


SEED_PROJECTS = [
    {
        "name": "Website Redesign",
        "description": "Full redesign of the company marketing site.",
        "owner": "admin",
        "members": ["member"],
        "tasks": [
            {
                "title": "Wireframe homepage layout",
                "description": "Create low-fidelity wireframes for the new homepage.",
                "status": TaskStatus.completed,
                "priority": TaskPriority.high,
                "due_date": _past(10),          # finished, was due 10 days ago
                "assignee": "member",
            },
            {
                "title": "Write copy for About page",
                "description": "Draft and review content for the About Us section.",
                "status": TaskStatus.in_progress,
                "priority": TaskPriority.medium,
                "due_date": _past(3),           # ⚠ overdue — was due 3 days ago
                "assignee": "member",
            },
            {
                "title": "Implement dark-mode toggle",
                "description": "Add a CSS class-based dark mode and persist preference in localStorage.",
                "status": TaskStatus.todo,
                "priority": TaskPriority.low,
                "due_date": _past(-7),          # due in 7 days
                "assignee": "admin",
            },
            {
                "title": "Cross-browser QA testing",
                "description": "Test on Chrome, Firefox, Safari, and Edge.",
                "status": TaskStatus.todo,
                "priority": TaskPriority.high,
                "due_date": _past(1),           # ⚠ overdue — was due yesterday
                "assignee": None,
            },
        ],
    },
    {
        "name": "Mobile App — v2.0",
        "description": "Feature release: push notifications, offline mode, and performance overhaul.",
        "owner": "admin",
        "members": ["member"],
        "tasks": [
            {
                "title": "Design push notification UX",
                "description": "Spec out opt-in flow and notification templates.",
                "status": TaskStatus.completed,
                "priority": TaskPriority.medium,
                "due_date": _past(14),
                "assignee": "admin",
            },
            {
                "title": "Implement offline caching with Service Workers",
                "description": "Cache API responses and static assets for offline use.",
                "status": TaskStatus.in_progress,
                "priority": TaskPriority.high,
                "due_date": _past(2),           # ⚠ overdue
                "assignee": "member",
            },
            {
                "title": "Performance profiling — reduce JS bundle size",
                "description": "Target < 200 KB gzipped. Use code-splitting and tree shaking.",
                "status": TaskStatus.todo,
                "priority": TaskPriority.high,
                "due_date": _past(-3),          # due in 3 days
                "assignee": "member",
            },
        ],
    },
    {
        "name": "Internal Tooling",
        "description": "Admin dashboard improvements and CI/CD pipeline upgrades.",
        "owner": "member",
        "members": [],
        "tasks": [
            {
                "title": "Set up GitHub Actions for auto-deploy",
                "description": "On merge to main, build Docker image and push to Railway.",
                "status": TaskStatus.in_progress,
                "priority": TaskPriority.high,
                "due_date": _past(5),           # ⚠ overdue
                "assignee": "member",
            },
            {
                "title": "Add Sentry error tracking",
                "description": "Integrate Sentry SDK and configure alerts for server errors.",
                "status": TaskStatus.todo,
                "priority": TaskPriority.medium,
                "due_date": _past(-5),          # due in 5 days
                "assignee": "member",
            },
            {
                "title": "Write runbook for on-call rotation",
                "description": "Document escalation paths, alert meanings, and rollback steps.",
                "status": TaskStatus.todo,
                "priority": TaskPriority.low,
                "due_date": _past(-14),         # due in 14 days
                "assignee": None,
            },
        ],
    },
]


async def seed_database():
    async with async_session() as db:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            from app.auth import hash_password

            # ── 1. Seed users ────────────────────────────────────────────
            user_map: dict[str, User] = {}
            for seed in SEED_USERS:
                result = await db.execute(select(User).where(User.email == seed["email"]))
                existing = result.scalars().first()

                if not existing:
                    user = User(
                        username=seed["username"],
                        email=seed["email"],
                        hashed_password=hash_password(seed["password"]),
                        role=seed["role"],
                        is_active=True,
                    )
                    db.add(user)
                    await db.flush()  # get user.id before commit
                    print(f"  Created {seed['role'].value}: {seed['email']} / {seed['password']}")
                    user_map[seed["username"]] = user
                else:
                    if existing.role != seed["role"]:
                        existing.role = seed["role"]
                        print(f"  Updated role for {seed['email']} → {seed['role'].value}")
                    else:
                        print(f"  Already exists: {seed['email']}")
                    user_map[seed["username"]] = existing

            await db.commit()

            # ── 2. Seed demo projects & tasks (skip if any project exists) ──
            existing_projects = await db.execute(select(Project).limit(1))
            if existing_projects.scalars().first():
                print("  Demo projects already exist — skipping.")
                return

            for proj_data in SEED_PROJECTS:
                owner = user_map[proj_data["owner"]]

                project = Project(
                    name=proj_data["name"],
                    description=proj_data["description"],
                    created_by=owner.id,
                )
                db.add(project)
                await db.flush()  # get project.id

                # Add owner as member
                db.add(ProjectMember(user_id=owner.id, project_id=project.id))

                # Add other members
                for member_name in proj_data["members"]:
                    member_user = user_map.get(member_name)
                    if member_user:
                        db.add(ProjectMember(user_id=member_user.id, project_id=project.id))

                # Add tasks
                for task_data in proj_data["tasks"]:
                    assignee = user_map.get(task_data["assignee"]) if task_data["assignee"] else None
                    task = Task(
                        title=task_data["title"],
                        description=task_data["description"],
                        status=task_data["status"],
                        priority=task_data["priority"],
                        due_date=task_data["due_date"],
                        assigned_to=assignee.id if assignee else None,
                        project_id=project.id,
                    )
                    db.add(task)

                print(f"  Created project: '{proj_data['name']}' ({len(proj_data['tasks'])} tasks)")

            await db.commit()

        except Exception as e:
            await db.rollback()
            raise e
