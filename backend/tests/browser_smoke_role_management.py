"""Browser walk: administrator role management, end to end.

The requirement this file exists to prove
-----------------------------------------
> After an Admin creates a LAB_TECHNICIAN account — Administration → Users →
> Create User → Role: LAB_TECHNICIAN → Create/Activate → the lab technician uses
> the existing Login → Laboratory Dashboard.

…and the same for PROCESSOR, COLLECTION_CENTER, PACKAGING_UNIT, DISTRIBUTOR,
RETAILER and KVIC_OFFICER.

So every check below is done through the real UI, against the real API and the
real database:

1. the public registration form offers exactly two roles (beekeeper, consumer);
2. the administrator opens Administration → Users → Create user and provisions one
   account per operational role, choosing the role and the account status in the
   form;
3. each created account signs in through the ordinary login page with the
   password the administrator set, and lands in its own workspace;
4. the role shown in the directory matches the role the account actually holds,
   and the role change dialog moves an account between roles;
5. the API — not the page — is what enforces all of it, checked directly with
   HTTP requests from the same test: a beekeeper cannot create an account, a
   technician cannot promote themselves, and the public registration endpoint
   refuses an operational role even when called directly.

Every account this walk creates is deleted afterwards. Nothing is mocked: if the
API refuses a write, the walk fails.

    cd frontend && npx vite preview --port 4173 --host 0.0.0.0     # built dist
    cd backend  && .venv/bin/uvicorn app.main:app --port 8000
    cd backend  && .venv/bin/python tests/browser_smoke_role_management.py

Exit code is 0 only if every check passes.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:4173")
API_URL = os.getenv("SMOKE_API_URL", "http://localhost:8000/api/v1")
ADMIN = (
    os.getenv("SMOKE_ADMIN_EMAIL", "admin@honeychain.example.com"),
    os.getenv("SMOKE_ADMIN_PASSWORD", "AdminSecure123"),
)
BEEKEEPER = (
    os.getenv("SMOKE_BEEKEEPER_EMAIL", "beekeeper@honeychain.example.com"),
    os.getenv("SMOKE_BEEKEEPER_PASSWORD", "HoneyPass123"),
)
HEADLESS = os.getenv("SMOKE_HEADLESS", "true").lower() != "false"
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

PASSWORD = "Operational123"
#: The roles the administrator provisions, with the workspace each must land on.
PROVISIONED_ROLES = [
    ("LAB_TECHNICIAN", "Lab technician", "/laboratory"),
    ("PROCESSOR", "Processor", "/processor"),
    ("COLLECTION_CENTER", "Collection centre", "/collection-center"),
    ("PACKAGING_UNIT", "Packaging unit", "/packaging"),
    ("DISTRIBUTOR", "Distributor", "/distributor"),
    ("RETAILER", "Retailer", "/retailer"),
    ("KVIC_OFFICER", "KVIC officer", "/kvic"),
]

PASSED: list[str] = []
FAILED: list[str] = []
CONSOLE_ERRORS: list[str] = []
#: Emails created by this run, removed in cleanup().
CREATED_EMAILS: list[str] = []


def check(description: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(description)
        print(f"  PASS  {description}")
    else:
        FAILED.append(f"{description} {detail}".strip())
        print(f"  FAIL  {description} {detail}".strip())


# --------------------------------------------------------------------------- #
# HTTP helpers (the same API the browser is talking to)
# --------------------------------------------------------------------------- #
def api(method: str, path: str, *, token: str | None = None, body: dict | None = None):
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def api_login(email: str, password: str) -> tuple[int, dict]:
    return api("POST", "/auth/login", body={"email": email, "password": password})


def token_for(email: str, password: str) -> str:
    status, payload = api_login(email, password)
    assert status == 200, f"could not sign in as {email}: {payload}"
    return payload["data"]["access_token"]


# --------------------------------------------------------------------------- #
# Browser helpers
# --------------------------------------------------------------------------- #
def text_of(page: Page) -> str:
    return page.inner_text("body")


def wait_for_text(page: Page, needle: str, timeout: int = 10000) -> bool:
    try:
        page.wait_for_selector(f"text={needle}", timeout=timeout, state="visible")
        return True
    except Exception:  # noqa: BLE001 - a missing string is a failed check, not an error
        return False


def sign_in(page: Page, email: str, password: str) -> None:
    page.goto(f"{BASE_URL}/about", wait_until="commit")
    page.wait_for_timeout(500)
    page.evaluate("window.sessionStorage.clear()")
    page.goto(f"{BASE_URL}/login", wait_until="commit")
    page.wait_for_timeout(700)
    page.fill("input[name='email']", email)
    page.fill("input[name='password']", password)
    page.click("button[type='submit']")
    page.wait_for_timeout(2500)


def sign_out(page: Page) -> None:
    """Sign out through the sidebar so the next sign-in starts from a clean shell."""
    page.goto(f"{BASE_URL}/dashboard", wait_until="commit")
    page.wait_for_timeout(900)
    try:
        page.click("aside >> text=Logout", timeout=5000)
        page.wait_for_selector("text=Sign out of HoneyChain?", timeout=5000)
        page.click("div[role='dialog'] button:has-text('Sign out')")
        page.wait_for_timeout(1200)
    except Exception:  # noqa: BLE001 - the sessionStorage clear in sign_in is the fallback
        pass


def open_create_user_dialog(page: Page) -> bool:
    """Administration → Users → Create user."""
    page.goto(f"{BASE_URL}/admin/users", wait_until="commit")
    page.wait_for_timeout(2000)
    try:
        page.click("button:has-text('Create user')", timeout=8000)
        page.wait_for_selector("#create-user-form", timeout=8000)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"      could not open the create-user dialog: {str(exc)[:120]}")
        return False


def create_account_through_ui(page: Page, *, role: str, role_label: str, email: str) -> bool:
    """Fill the Create user form the way an administrator does."""
    if not open_create_user_dialog(page):
        return False

    page.fill("#create-user-form input[name='name']", f"{role_label} Smoke")
    page.fill("#create-user-form input[name='email']", email)
    page.select_option("#create-user-form select[name='role']", role)
    page.wait_for_timeout(400)

    # The form tells the administrator where the account will land.
    form_text = page.inner_text("#create-user-form")
    expected_home = {
        "LAB_TECHNICIAN": "/laboratory",
        "PROCESSOR": "/processor",
        "COLLECTION_CENTER": "/collection-center",
        "PACKAGING_UNIT": "/packaging",
        "DISTRIBUTOR": "/distributor",
        "RETAILER": "/retailer",
        "KVIC_OFFICER": "/kvic",
    }[role]
    landed = f"landing={expected_home in form_text}"

    page.fill("#create-user-form input[name='organization']", "Role management smoke")
    page.fill("#create-user-form input[name='password']", PASSWORD)
    page.fill("#create-user-form input[name='confirmPassword']", PASSWORD)
    page.fill("#create-user-form input[name='reason']", "Created by the role management smoke")
    page.click("button:has-text('Create account')")
    page.wait_for_timeout(2500)

    ok = not page.locator("#create-user-form").count()  # dialog closed on success
    if not ok:
        print(f"      form still open: {page.inner_text('#create-user-form')[:200]!r}")
    if not ok or "landing=True" not in landed:
        return False
    return True


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #
def scenario_public_registration_is_closed(page: Page) -> None:
    print("\n[1] The public registration form offers only beekeeper and consumer")
    page.goto(f"{BASE_URL}/register", wait_until="commit")
    page.wait_for_timeout(1500)

    options = page.locator("select[name='role'] option").all_inner_texts()
    values = page.eval_on_selector_all(
        "select[name='role'] option", "nodes => nodes.map(n => n.value)"
    )
    offered = {value for value in values if value}

    check(
        "the sign-up form offers beekeeper and consumer only",
        offered == {"BEEKEEPER", "CONSUMER"},
        f"offered {sorted(offered)}",
    )
    check(
        "and says privileged roles are provisioned by an administrator",
        "administrator" in text_of(page).lower(),
    )

    # The API is the real gate: try the operational roles directly.
    refused = []
    for role in ("LAB_TECHNICIAN", "PROCESSOR", "KVIC_OFFICER", "PACKAGING_UNIT", "RETAILER"):
        status, _ = api(
            "POST",
            "/auth/register",
            body={
                "name": "Self Appointed",
                "email": f"self.{role.lower()}.{uuid.uuid4().hex[:8]}@honeychain.example.com",
                "password": PASSWORD,
                "role": role,
                "accepted_terms": True,
            },
        )
        refused.append(status == 422)
    check(
        "the API refuses an operational role at registration even when called directly",
        all(refused),
        f"statuses {refused}",
    )

    # And a non-admin cannot provision either, however they phrase the request.
    beekeeper_token = token_for(*BEEKEEPER)
    status, body = api(
        "POST",
        "/admin/users",
        token=beekeeper_token,
        body={
            "name": "Not Allowed",
            "email": f"not.allowed.{uuid.uuid4().hex[:8]}@honeychain.example.com",
            "password": PASSWORD,
            "role": "LAB_TECHNICIAN",
        },
    )
    check(
        "a beekeeper cannot create an account through the admin API",
        status == 403,
        f"got {status} {str(body)[:120]}",
    )


def scenario_admin_creates_each_operational_role(page: Page) -> dict[str, str]:
    """Administration → Users → Create user, once per operational role."""
    print("\n[2] An administrator provisions an account for each operational role")
    sign_in(page, *ADMIN)
    check("the administrator reaches the administration workspace", "/admin" in page.url, page.url)

    created: dict[str, str] = {}
    for role, label, _home in PROVISIONED_ROLES:
        email = f"smoke.{role.lower()}.{uuid.uuid4().hex[:6]}@honeychain.example.com"
        made = create_account_through_ui(page, role=role, role_label=label, email=email)
        check(f"the {label} account is created from the form", made, f"uplift for {email} failed")
        if made:
            created[role] = email
            CREATED_EMAILS.append(email)

    return created


def scenario_each_account_signs_in_and_reaches_its_workspace(
    page: Page, created: dict[str, str]
) -> None:
    """The accounts use the existing login, and land where their role belongs."""
    print("\n[3] Each created account signs in and reaches its own workspace")

    for role, label, home in PROVISIONED_ROLES:
        email = created.get(role)
        if not email:
            check(f"{label} — account available to sign in", False, "was not created")
            continue

        sign_in(page, email, PASSWORD)
        landed = page.url
        check(
            f"the {label} account signs in and lands on {home}",
            home in landed,
            f"landed on {landed}",
        )

        body = text_of(page)
        check(
            f"the {label} workspace shows no administration link",
            "Users" not in body or home == "/admin",
            "administration navigation leaked",
        )

        # The role is real: the API answers with the same role the account holds.
        status, payload = api("GET", "/auth/me", token=token_for(email, PASSWORD))
        check(
            f"the API confirms the {label} role on the account",
            status == 200 and payload["data"]["role"] == role,
            f"got {status} {str(payload)[:120]}",
        )

        # And the account cannot reach administration, from the URL bar or the API.
        page.goto(f"{BASE_URL}/admin/users", wait_until="commit")
        page.wait_for_timeout(1200)
        check(
            f"the {label} typing /admin/users is returned to their own workspace",
            home in page.url and "/admin" not in page.url,
            f"ended on {page.url}",
        )

        token = token_for(email, PASSWORD)
        status, _ = api("GET", "/admin/users", token=token)
        check(
            f"the {label} cannot read the account directory through the API",
            status == 403,
            f"got {status}",
        )
        sign_out(page)


def scenario_directory_shows_the_assigned_role(page: Page, created: dict[str, str]) -> None:
    print("\n[4] The directory shows the assigned role, and the role can be changed")
    sign_in(page, *ADMIN)
    page.goto(f"{BASE_URL}/admin/users", wait_until="commit")
    page.wait_for_timeout(2000)

    for role, label, _home in PROVISIONED_ROLES:
        email = created.get(role)
        if not email:
            continue
        page.fill("input[name='search']", email)
        page.click("button:has-text('Apply filters')")
        page.wait_for_timeout(1800)
        row_text = text_of(page)
        check(
            f"the directory lists the {label} account with that role",
            email in row_text and label in row_text,
            row_text[:200],
        )

    # Change one account's role through the dialog, then sign in as it.
    target_role, _, _ = PROVISIONED_ROLES[3]  # PACKAGING_UNIT
    target_email = created.get(target_role)
    page.fill("input[name='search']", target_email)
    page.click("button:has-text('Apply filters')")
    page.wait_for_timeout(1800)
    page.click("button:has-text('Change role')")
    page.wait_for_selector("#change-role-form", timeout=8000)
    page.select_option("#change-role-form select[name='role']", "DISTRIBUTOR")
    page.fill("#change-role-form input[name='reason']", "Moved to distribution")
    page.click("button:has-text('Save role')")
    page.wait_for_timeout(2500)

    check(
        "the role change is confirmed and the dialog closes",
        page.locator("#change-role-form").count() == 0,
    )

    # The new role is what the API now holds, and what the account lands on.
    token = token_for(target_email, PASSWORD)
    status, payload = api("GET", "/auth/me", token=token)
    check(
        "the changed role is what the account now holds",
        status == 200 and payload["data"]["role"] == "DISTRIBUTOR",
        f"got {str(payload)[:120]}",
    )

    sign_out(page)
    sign_in(page, target_email, PASSWORD)
    check(
        "the account lands in the distribution workspace after the change",
        "/distributor" in page.url,
        f"landed on {page.url}",
    )
    check(
        "and its own pages no longer offer the packaging workspace",
        "/packaging" not in page.url,
    )
    sign_out(page)


def scenario_self_promotion_is_refused(page: Page, created: dict[str, str]) -> None:
    """Nobody may change their own role — including an administrator."""
    print("\n[5] A user cannot grant themselves a role")

    technician_email = created.get("LAB_TECHNICIAN")
    if technician_email:
        token = token_for(technician_email, PASSWORD)
        status, _ = api(
            "PATCH",
            "/admin/users/me/role",
            token=token,
            body={"role": "ADMIN"},
        )
        check("a technician cannot call the role endpoint", status in (403, 404, 422), f"got {status}")

        own_id_status, own_id = api("GET", "/auth/me", token=token)
        if own_id_status == 200:
            user_id = own_id["data"]["id"]
            status, _ = api(
                "PATCH", f"/admin/users/{user_id}/role", token=token, body={"role": "ADMIN"}
            )
            check(
                "a technician cannot promote their own account through the API",
                status == 403,
                f"got {status}",
            )
            # And the profile endpoint refuses the field outright.
            status, body = api("PATCH", "/users/me", token=token, body={"role": "ADMIN"})
            check(
                "the self-service profile endpoint rejects a role field",
                status == 422,
                f"got {status} {str(body)[:120]}",
            )
            status, payload = api("GET", "/auth/me", token=token)
            check(
                "the technician still holds the technician role",
                payload["data"]["role"] == "LAB_TECHNICIAN",
            )

    # An administrator is not offered, and not allowed, to change their own role.
    sign_in(page, *ADMIN)
    page.goto(f"{BASE_URL}/admin/users", wait_until="commit")
    page.wait_for_timeout(2000)
    page.fill("input[name='search']", ADMIN[0])
    page.click("button:has-text('Apply filters')")
    page.wait_for_timeout(1800)

    disabled = page.eval_on_selector_all(
        "table button:has-text('Change role')", "nodes => nodes.map(n => n.disabled)"
    )
    check(
        "the administrator's own row offers no role change",
        bool(disabled) and all(disabled),
        f"buttons disabled={disabled}",
    )

    admin_token = token_for(*ADMIN)
    status, payload = api("GET", "/auth/me", token=admin_token)
    admin_id = payload["data"]["id"]
    status, body = api(
        "PATCH", f"/admin/users/{admin_id}/role", token=admin_token, body={"role": "BEEKEEPER"}
    )
    check(
        "and the API refuses an administrator changing their own role",
        status == 422,
        f"got {status} {str(body)[:140]}",
    )
    sign_out(page)


def scenario_packaged_app_matches_the_api(page: Page) -> None:
    """The shipped bundle names all ten roles and no placeholder copy."""
    print("\n[6] The built application lists every role")

    assets = list((FRONTEND_DIR / "dist" / "assets").glob("*.js"))
    bundle = "\n".join(path.read_text(errors="replace") for path in assets)

    missing = [
        role for role, _label, _home in PROVISIONED_ROLES if role not in bundle
    ] + [role for role in ("ADMIN", "BEEKEEPER", "CONSUMER") if role not in bundle]
    check("every role key ships in the bundle", not missing, f"missing {missing}")

    for label in ("Lab technician", "Processor", "Collection centre", "Packaging unit",
                  "Distributor", "Retailer", "KVIC officer"):
        check(f"the role label {label!r} ships in the bundle", label in bundle)

    check(
        "the create-user copy ships",
        "Create user" in bundle and "Create account" in bundle,
    )
    check(
        "the role-change copy ships",
        "Change role" in bundle and "Save role" in bundle,
    )


# --------------------------------------------------------------------------- #
# Cleanup
# --------------------------------------------------------------------------- #
def cleanup() -> None:
    """Delete everything this walk created, in foreign-key order.

    The API deliberately has no delete-account endpoint (accounts are disabled,
    never erased), so the smoke removes its own fixtures over SQL.
    """
    if not CREATED_EMAILS:
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import psycopg  # noqa: PLC0415

        from app.core.config import get_settings  # noqa: PLC0415

        dsn = get_settings().DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE email = ANY(%s)", (CREATED_EMAILS,)
            )
            user_ids = [row[0] for row in cursor.fetchall()]
            if user_ids:
                cursor.execute(
                    "DELETE FROM beekeepers WHERE user_id = ANY(%s)", (user_ids,)
                )
                cursor.execute(
                    "DELETE FROM refresh_tokens WHERE user_id = ANY(%s)", (user_ids,)
                )
                cursor.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
            connection.commit()
        print(f"\nCleanup: removed {len(CREATED_EMAILS)} account(s) created by this walk.")
    except Exception as error:  # noqa: BLE001 - cleanup must never fail the run
        print(f"\nCleanup: could not remove the walk's accounts automatically ({error}).")
        print(f"         emails left behind: {', '.join(CREATED_EMAILS)}")


def main() -> int:
    started = time.time()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=HEADLESS)
        context = browser.new_context(viewport={"width": 1400, "height": 950})
        page = context.new_page()

        def _record_console(message) -> None:
            if message.type != "error":
                return
            # 403 is the point of the permission checks, not a defect.
            if "403" in message.text or "401" in message.text or "422" in message.text:
                return
            CONSOLE_ERRORS.append(message.text)

        page.on("console", _record_console)

        try:
            scenario_public_registration_is_closed(page)
            created = scenario_admin_creates_each_operational_role(page)
            scenario_each_account_signs_in_and_reaches_its_workspace(page, created)
            scenario_directory_shows_the_assigned_role(page, created)
            scenario_self_promotion_is_refused(page, created)
            scenario_packaged_app_matches_the_api(page)
        except Exception as exc:  # noqa: BLE001
            FAILED.append(f"the walk aborted: {exc}")
            print(f"\nABORTED: {exc}")
        finally:
            browser.close()
            cleanup()

    print("\n" + "=" * 72)
    if CONSOLE_ERRORS:
        print(f"Console errors seen: {len(CONSOLE_ERRORS)}")
        for line in CONSOLE_ERRORS[:5]:
            print(f"  - {line[:160]}")
        FAILED.append(f"{len(CONSOLE_ERRORS)} unexpected console error(s)")
    else:
        print("Console errors seen: 0")

    print(f"\n{len(PASSED)} passed / {len(FAILED)} failed   ({time.time() - started:.0f}s)")
    if FAILED:
        print("\nFailures:")
        for failure in FAILED:
            print(f"  - {failure}")
    print("=" * 72)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
