"""Sign-in (username or email), session timeout, RBAC and legacy password upgrade."""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import AuditLog
from tests.conftest import PASSWORD, login, login_path, user

PUBLIC_ENDPOINTS = {"static", "careers.index", "careers.job_detail", "careers.apply", "careers.talent_pool",
                    "careers.application_done", "careers.check_status", "auth.login", "auth.login_form", "auth.logout",
                    "auth.legacy_login", "favicon"}


def test_login_success_is_audited(client):
    r = login(client, "finance")
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
    assert AuditLog.query.filter_by(action="login.success", username="finance").count() == 1
    assert client.get("/dashboard").status_code == 200


def test_wrong_password_is_audited_but_never_locks(client):
    for _ in range(8):
        r = login(client, "employee", "wrong")
        assert r.status_code == 200 and b"Incorrect username, email or password" in r.data
    assert AuditLog.query.filter_by(action="login.failed").count() == 8
    r = login(client, "employee")            # right password still works: no lockout (SSO will protect sign-in)
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")


def test_inactive_user_cannot_sign_in(client):
    user("employee").active = False
    db.session.commit()
    assert login(client, "employee").status_code == 200
    assert client.get("/dashboard").status_code == 302


def test_login_with_email(client):
    r = client.post("/login/sign-in", data={"login": "FINANCE@test.invalid", "password": PASSWORD})
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")


def test_login_with_shared_email_is_refused(client):
    user("payroll").email = "finance@test.invalid"
    db.session.commit()
    r = client.post("/login/sign-in", data={"login": "finance@test.invalid", "password": PASSWORD})
    assert r.status_code == 200 and b"Incorrect username, email or password" in r.data
    assert login(client, "finance").status_code == 302          # username still works


def test_wrong_email_is_audited(client):
    client.post("/login/staff/sign-in", data={"login": "employee@test.invalid", "password": "nope"})
    assert AuditLog.query.filter_by(action="login.failed", username="employee").count() == 1


def test_no_two_step_verification(app, client):
    assert not [r for r in app.url_map.iter_rules() if "mfa" in r.rule]
    r = login(client, "hradmin")                                  # HR role signs straight in
    assert r.headers["Location"].endswith("/dashboard")


def test_each_audience_has_a_landing_page_then_a_sign_in_page(client):
    for landing, sign_in, title, image in [
            ("/login/staff", "/login/staff/sign-in", b"Staff self-service", b"Background.jpeg"),
            ("/login/manager", "/login/manager/sign-in", b"Manager self-service", b"login-manager.jpg"),
            ("/login", "/login/sign-in", b"HR admin portal", b"login-admin.jpg")]:
        page = client.get(landing + "?next=/budget/").data
        assert title in page and image in page and b"Username or email" not in page, landing
        assert f'href="{sign_in}?next=/budget/"'.encode() in page, landing
        form = client.get(sign_in).data
        body = form.split(b"</title>")[1]
        assert image in form and b"Username or email" in form and title in body, sign_in
    assert client.get("/login/admin").headers["Location"].endswith("/login")
    assert client.get("/login/nobody").status_code == 404
    assert client.get("/login/account").status_code == 404


def test_users_are_sent_to_their_own_sign_in_page(client):
    assert [login_path(u) for u in ("employee", "linemanager", "hod", "hradmin", "finance", "gcoo")] == [
        "/login/staff/sign-in", "/login/manager/sign-in", "/login/manager/sign-in",
        "/login/sign-in", "/login/sign-in", "/login/sign-in"]
    r = client.post("/login/sign-in?next=/budget/", data={"login": "linemanager", "password": PASSWORD})
    assert r.headers["Location"].endswith("/login/manager/sign-in?next=/budget/")
    assert client.get("/dashboard").status_code == 302                    # not signed in on the wrong page
    assert AuditLog.query.filter_by(action="login.wrong_page", username="linemanager").count() == 1
    assert login(client, "linemanager").headers["Location"].endswith("/dashboard")
    assert client.post("/logout").headers["Location"].endswith("/login/manager")


def test_sign_in_returns_to_next_page(client):
    r = client.post("/login/sign-in?next=/budget/", data={"login": "finance", "password": PASSWORD})
    assert r.headers["Location"].endswith("/budget/")


def test_duplicate_user_email_rejected(client):
    login(client, "it")
    u = user("employee")
    r = client.post(f"/admin/users/{u.id}", data={"username": "employee", "full_name": "Employee Tester",
                                                 "email": "finance@test.invalid", "active": "1",
                                                 "roles": ["Employee"]}, follow_redirects=True)
    assert b"already used by finance" in r.data
    assert user("employee").email == "employee@test.invalid"


def test_session_idle_timeout_is_30_minutes(app):
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(minutes=30)
    assert app.config["SESSION_COOKIE_HTTPONLY"]


def test_legacy_werkzeug_hash_upgrades_to_argon2(app, client):
    from werkzeug.security import generate_password_hash
    u = user("payroll")
    u.password_hash = generate_password_hash("Legacy-pass-2026")
    db.session.commit()
    r = login(client, "payroll", "Legacy-pass-2026")
    assert r.status_code == 302
    assert user("payroll").password_hash.startswith("$argon2")


def test_every_staff_route_requires_sign_in(app, client):
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC_ENDPOINTS or "GET" not in rule.methods:
            continue
        url = rule.rule
        for arg in rule.arguments:
            url = url.replace(f"<int:{arg}>", "1").replace(f"<{arg}>", "x")
        r = client.get(url)
        assert r.status_code == 302 and "/login" in r.headers["Location"], f"{rule.endpoint} is not protected"


def test_every_staff_view_has_roles_decorator(app):
    for endpoint, view in app.view_functions.items():
        if endpoint in PUBLIC_ENDPOINTS:
            continue
        assert hasattr(view, "roles_required"), f"{endpoint} has no @roles_required"


@pytest.mark.parametrize("username,url,expected", [
    ("employee", "/admin/users", 403),
    ("employee", "/budget/", 403),
    ("employee", "/recruitment/", 403),
    ("linemanager", "/admin/audit", 403),
    ("finance", "/admin/users", 403),
    ("finance", "/budget/", 200),
    ("compliance", "/admin/audit", 200),
    ("it", "/admin/integrations", 200),
    ("hradmin", "/admin/users", 403),
    ("it", "/admin/users", 200),
    ("it", "/admin/assets", 200),
    ("hradmin", "/admin/assets", 403),
    ("recruiter", "/recruitment/", 200),
    ("hradmin", "/approvals/dashboard", 403),
    ("it", "/approvals/dashboard", 200),
    ("linemanager", "/approvals/dashboard", 403),
])
def test_role_access(client, username, url, expected):
    login(client, username)
    assert client.get(url).status_code == expected


def test_logout(client):
    login(client, "finance")
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302
    assert AuditLog.query.filter_by(action="logout").count() == 1


def test_pages_render_for_each_role(client):
    from tests.conftest import ORG
    pages = ["/dashboard", "/approvals/", "/approvals/delegations", "/notifications", "/me", "/account"]
    for username in ORG:
        login(client, username)
        for url in pages:
            assert client.get(url).status_code == 200, (username, url)
        client.post("/logout")
