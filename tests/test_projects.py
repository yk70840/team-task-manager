"""
Tests for project listing, task-add permission enforcement, and role hierarchy.
Covers:
  - Projects list page shows owner badge for all users
  - Filter buttons appear for all users
  - Only project owner / higher-ranked admin can add tasks
  - Admin cannot add tasks to a superadmin-owned project
  - Superadmin can add tasks to any project
  - Member cannot add tasks to another user's project
"""

import asyncio
from app.auth import hash_password
from app.models import User, UserRole, Project, ProjectMember, Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _make_user(session_factory, username, email, role=UserRole.member.value):
    async def _create():
        async with session_factory() as s:
            u = User(
                username=username,
                email=email,
                hashed_password=hash_password("password123"),
                role=role,
                is_active=True,
            )
            s.add(u)
            await s.commit()
            await s.refresh(u)
            return u
    return _run(_create())


def _make_project(session_factory, name, owner_id):
    async def _create():
        async with session_factory() as s:
            p = Project(name=name, description="desc", created_by=owner_id)
            s.add(p)
            await s.commit()
            await s.refresh(p)
            # also add creator as member
            s.add(ProjectMember(user_id=owner_id, project_id=p.id))
            await s.commit()
            return p
    return _run(_create())


def _add_member(session_factory, project_id, user_id):
    async def _add():
        async with session_factory() as s:
            s.add(ProjectMember(project_id=project_id, user_id=user_id))
            await s.commit()
    return _run(_add())


def _login(client, email):
    """Log in and return the client (session cookie is stored automatically)."""
    client.post(
        "/login",
        data={"email": email, "password": "password123"},
        follow_redirects=False,
    )
    return client


def _logout(client):
    client.get("/logout", follow_redirects=False)


# ---------------------------------------------------------------------------
# Projects list — owner badge
# ---------------------------------------------------------------------------

class TestProjectsListOwnerBadge:
    """The owner badge is visible to every user role."""

    def test_member_sees_own_project_as_you(self, client, test_db_engine):
        _, sf = test_db_engine
        member = _make_user(sf, "m_badge", "m_badge@x.com", UserRole.member.value)
        _make_project(sf, "My Project", member.id)

        _login(client, "m_badge@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        assert "You" in resp.text

    def test_member_sees_other_owner_username(self, client, test_db_engine):
        _, sf = test_db_engine
        owner = _make_user(sf, "owner_u", "owner_u@x.com", UserRole.member.value)
        viewer = _make_user(sf, "viewer_u", "viewer_u@x.com", UserRole.member.value)
        proj = _make_project(sf, "Other Project", owner.id)
        _add_member(sf, proj.id, viewer.id)

        _login(client, "viewer_u@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        assert "owner_u" in resp.text

    def test_admin_sees_owner_badge_on_all_projects(self, client, test_db_engine):
        _, sf = test_db_engine
        member = _make_user(sf, "m_for_admin", "m_for_admin@x.com", UserRole.member.value)
        admin = _make_user(sf, "a_badge", "a_badge@x.com", UserRole.admin.value)
        _make_project(sf, "Member's Project", member.id)
        _make_project(sf, "Admin's Project", admin.id)

        _login(client, "a_badge@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        # Admin's own projects show "You"
        assert "You" in resp.text
        # Other owner's username is visible
        assert "m_for_admin" in resp.text


# ---------------------------------------------------------------------------
# Projects list — filter buttons
# ---------------------------------------------------------------------------

class TestProjectsListFilter:
    """Filter buttons appear for all user roles."""

    def _assert_filters_visible(self, resp):
        assert "All projects" in resp.text
        assert "My projects" in resp.text

    def test_member_sees_filter_buttons(self, client, test_db_engine):
        _, sf = test_db_engine
        u = _make_user(sf, "m_filter", "m_filter@x.com", UserRole.member.value)
        _make_project(sf, "Proj", u.id)

        _login(client, "m_filter@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        self._assert_filters_visible(resp)

    def test_admin_sees_filter_buttons(self, client, test_db_engine):
        _, sf = test_db_engine
        u = _make_user(sf, "a_filter", "a_filter@x.com", UserRole.admin.value)
        _make_project(sf, "Proj A", u.id)

        _login(client, "a_filter@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        self._assert_filters_visible(resp)

    def test_superadmin_sees_filter_buttons(self, client, test_db_engine):
        _, sf = test_db_engine
        u = _make_user(sf, "sa_filter", "sa_filter@x.com", UserRole.superadmin.value)
        _make_project(sf, "Proj SA", u.id)

        _login(client, "sa_filter@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        self._assert_filters_visible(resp)


# ---------------------------------------------------------------------------
# Task creation permissions
# ---------------------------------------------------------------------------

class TestTaskCreationPermissions:
    """Enforce: owner / superadmin / outranking-admin can create tasks."""

    # --- Project owner ---

    def test_project_owner_can_see_new_task_button(self, client, test_db_engine):
        _, sf = test_db_engine
        owner = _make_user(sf, "owner_t", "owner_t@x.com", UserRole.member.value)
        proj = _make_project(sf, "Owner Proj", owner.id)

        _login(client, "owner_t@x.com")
        resp = client.get(f"/projects/{proj.id}")
        assert resp.status_code == 200
        assert "New Task" in resp.text

    def test_project_owner_can_create_task(self, client, test_db_engine):
        _, sf = test_db_engine
        owner = _make_user(sf, "owner_c", "owner_c@x.com", UserRole.member.value)
        proj = _make_project(sf, "Owner Create", owner.id)

        _login(client, "owner_c@x.com")
        resp = client.post(
            f"/projects/{proj.id}/tasks/create",
            data={"title": "Owner Task", "priority": "medium"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    # --- Non-owner member ---

    def test_non_owner_member_cannot_see_new_task_button(self, client, test_db_engine):
        _, sf = test_db_engine
        owner = _make_user(sf, "owner_nb", "owner_nb@x.com", UserRole.member.value)
        non_owner = _make_user(sf, "non_owner_nb", "non_owner_nb@x.com", UserRole.member.value)
        proj = _make_project(sf, "No Button Proj", owner.id)
        _add_member(sf, proj.id, non_owner.id)

        _login(client, "non_owner_nb@x.com")
        resp = client.get(f"/projects/{proj.id}")
        assert resp.status_code == 200
        assert "New Task" not in resp.text

    def test_non_owner_member_cannot_post_task(self, client, test_db_engine):
        _, sf = test_db_engine
        owner = _make_user(sf, "owner_np", "owner_np@x.com", UserRole.member.value)
        non_owner = _make_user(sf, "non_owner_np", "non_owner_np@x.com", UserRole.member.value)
        proj = _make_project(sf, "No Post Proj", owner.id)
        _add_member(sf, proj.id, non_owner.id)

        _login(client, "non_owner_np@x.com")
        resp = client.post(
            f"/projects/{proj.id}/tasks/create",
            data={"title": "Sneaky Task", "priority": "low"},
            follow_redirects=False,
        )
        # Must be blocked — either 403 or redirect to error
        assert resp.status_code in (302, 403)

    # --- Superadmin ---

    def test_superadmin_can_add_task_to_any_project(self, client, test_db_engine):
        _, sf = test_db_engine
        member = _make_user(sf, "m_sa_t", "m_sa_t@x.com", UserRole.member.value)
        superadmin = _make_user(sf, "sa_t", "sa_t@x.com", UserRole.superadmin.value)
        proj = _make_project(sf, "Member Proj for SA", member.id)

        _login(client, "sa_t@x.com")
        # Button should be visible
        page = client.get(f"/projects/{proj.id}")
        assert page.status_code == 200
        assert "New Task" in page.text

        # POST should succeed
        resp = client.post(
            f"/projects/{proj.id}/tasks/create",
            data={"title": "SA Task", "priority": "high"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    # --- Admin vs member-owned project ---

    def test_admin_can_add_task_to_member_project(self, client, test_db_engine):
        _, sf = test_db_engine
        member = _make_user(sf, "m_at", "m_at@x.com", UserRole.member.value)
        admin = _make_user(sf, "a_at", "a_at@x.com", UserRole.admin.value)
        proj = _make_project(sf, "Member Proj for Admin", member.id)

        _login(client, "a_at@x.com")
        page = client.get(f"/projects/{proj.id}")
        assert page.status_code == 200
        assert "New Task" in page.text

        resp = client.post(
            f"/projects/{proj.id}/tasks/create",
            data={"title": "Admin Task", "priority": "medium"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    # --- Admin vs superadmin-owned project ---

    def test_admin_cannot_add_task_to_superadmin_project(self, client, test_db_engine):
        _, sf = test_db_engine
        superadmin = _make_user(sf, "sa_own", "sa_own@x.com", UserRole.superadmin.value)
        admin = _make_user(sf, "a_blocked", "a_blocked@x.com", UserRole.admin.value)
        proj = _make_project(sf, "SA Proj", superadmin.id)
        _add_member(sf, proj.id, admin.id)

        _login(client, "a_blocked@x.com")
        # Admin is a member so CAN view the project detail page
        page = client.get(f"/projects/{proj.id}")
        assert page.status_code == 200
        # But the New Task button must NOT appear
        assert "New Task" not in page.text

        # POST is still blocked
        resp = client.post(
            f"/projects/{proj.id}/tasks/create",
            data={"title": "Admin Sneaky", "priority": "low"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)

    # --- Admin vs admin-owned project (same rank) ---

    def test_admin_cannot_add_task_to_peer_admin_project(self, client, test_db_engine):
        _, sf = test_db_engine
        admin1 = _make_user(sf, "a1_peer", "a1_peer@x.com", UserRole.admin.value)
        admin2 = _make_user(sf, "a2_peer", "a2_peer@x.com", UserRole.admin.value)
        proj = _make_project(sf, "Admin1 Proj", admin1.id)
        _add_member(sf, proj.id, admin2.id)

        _login(client, "a2_peer@x.com")
        page = client.get(f"/projects/{proj.id}")
        assert page.status_code == 200
        assert "New Task" not in page.text

        resp = client.post(
            f"/projects/{proj.id}/tasks/create",
            data={"title": "Peer Sneaky", "priority": "low"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)

    # --- Task create GET page respects permission ---

    def test_task_create_page_blocked_for_non_owner(self, client, test_db_engine):
        _, sf = test_db_engine
        owner = _make_user(sf, "owner_pg", "owner_pg@x.com", UserRole.member.value)
        outsider = _make_user(sf, "outsider_pg", "outsider_pg@x.com", UserRole.member.value)
        proj = _make_project(sf, "Owner Page Proj", owner.id)
        _add_member(sf, proj.id, outsider.id)

        _login(client, "outsider_pg@x.com")
        resp = client.get(f"/projects/{proj.id}/tasks/create")
        # Should return a 403 error page, not 200
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin project visibility — hierarchy enforcement
# ---------------------------------------------------------------------------

class TestAdminProjectVisibility:
    """Admins must NOT see or access superadmin-owned projects."""

    def test_admin_cannot_see_superadmin_project_in_list(self, client, test_db_engine):
        _, sf = test_db_engine
        superadmin = _make_user(sf, "sa_vis", "sa_vis@x.com", UserRole.superadmin.value)
        admin = _make_user(sf, "a_vis", "a_vis@x.com", UserRole.admin.value)
        _make_project(sf, "SA Secret Project", superadmin.id)

        _login(client, "a_vis@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        # Superadmin project must not appear in admin's list
        assert "SA Secret Project" not in resp.text

    def test_superadmin_sees_all_projects_in_list(self, client, test_db_engine):
        _, sf = test_db_engine
        member = _make_user(sf, "m_sa_list", "m_sa_list@x.com", UserRole.member.value)
        superadmin = _make_user(sf, "sa_list", "sa_list@x.com", UserRole.superadmin.value)
        _make_project(sf, "Member Visible Proj", member.id)

        _login(client, "sa_list@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        # Superadmin must see member-owned projects
        assert "Member Visible Proj" in resp.text

    def test_admin_cannot_access_superadmin_project_detail(self, client, test_db_engine):
        _, sf = test_db_engine
        superadmin = _make_user(sf, "sa_det", "sa_det@x.com", UserRole.superadmin.value)
        admin = _make_user(sf, "a_det", "a_det@x.com", UserRole.admin.value)
        proj = _make_project(sf, "SA Detail Proj", superadmin.id)

        _login(client, "a_det@x.com")
        resp = client.get(f"/projects/{proj.id}")
        # Admin should get 403 on a superadmin-owned project
        assert resp.status_code == 403

    def test_admin_can_access_member_project_detail(self, client, test_db_engine):
        _, sf = test_db_engine
        member = _make_user(sf, "m_det2", "m_det2@x.com", UserRole.member.value)
        admin = _make_user(sf, "a_det2", "a_det2@x.com", UserRole.admin.value)
        proj = _make_project(sf, "Member Detail Proj", member.id)

        _login(client, "a_det2@x.com")
        resp = client.get(f"/projects/{proj.id}")
        # Admin CAN access a member-owned project
        assert resp.status_code == 200

    def test_admin_member_of_superadmin_project_can_view_it(self, client, test_db_engine):
        """Membership overrides the hierarchy block — admin added to a superadmin
        project should be able to view it (but still not add tasks)."""
        _, sf = test_db_engine
        superadmin = _make_user(sf, "sa_mem", "sa_mem@x.com", UserRole.superadmin.value)
        admin = _make_user(sf, "a_mem", "a_mem@x.com", UserRole.admin.value)
        proj = _make_project(sf, "SA Project With Admin Member", superadmin.id)
        _add_member(sf, proj.id, admin.id)  # explicitly add admin as member

        _login(client, "a_mem@x.com")
        # Admin is a member so CAN view the project
        resp = client.get(f"/projects/{proj.id}")
        assert resp.status_code == 200
        # But still cannot add tasks
        post = client.post(
            f"/projects/{proj.id}/tasks/create",
            data={"title": "Sneaky Task", "priority": "low"},
            follow_redirects=False,
        )
        assert post.status_code in (302, 403)

    def test_admin_member_of_superadmin_project_appears_in_list(self, client, test_db_engine):
        """A superadmin project where admin is a member should appear in admin's project list."""
        _, sf = test_db_engine
        superadmin = _make_user(sf, "sa_lst2", "sa_lst2@x.com", UserRole.superadmin.value)
        admin = _make_user(sf, "a_lst2", "a_lst2@x.com", UserRole.admin.value)
        proj = _make_project(sf, "Invited SA Project", superadmin.id)
        _add_member(sf, proj.id, admin.id)

        _login(client, "a_lst2@x.com")
        resp = client.get("/projects/")
        assert resp.status_code == 200
        assert "Invited SA Project" in resp.text


# ---------------------------------------------------------------------------
# Existing smoke tests (kept for regression)
# ---------------------------------------------------------------------------

def test_home_redirects_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/login"


def test_register_and_dashboard_access(client):
    response = client.post(
        "/register",
        data={
            "username": "tester_smoke",
            "email": "tester_smoke@example.com",
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
    assert "tester_smoke" in dashboard_response.text
