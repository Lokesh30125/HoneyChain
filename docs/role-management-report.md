# HoneyChain — Administrator role management report

**Creating operational accounts and assigning roles from Administration → Users**

*Smart India Hackathon 2026 · Problem Statement 26021 · Report generated 28 September 2026*

---

## 1. What this work set out to do

The platform has ten roles and one authentication system. Phase 1 built the role model, Phase 2 the
identity directory, and Phase 6 the workspaces the operational roles sign into. What was missing was
the *administrator's* side of it: a way to **create** an account for an operational role and to
**change** the role an account holds, without a second authentication system, a hard-coded list, or
a role value that only exists in the client.

The requirements, as given, and where each is answered:

| Requirement | Where it is answered |
| --- | --- |
| Ten roles supported end to end | `UserRole` + `ROLE_PERMISSIONS` + `ADMINISTRATION_ROLE_ORDER` (backend), `constants/roles.js` (frontend) |
| Public registration limited to `BEEKEEPER` and `CONSUMER` | `UserRole.self_registrable()` enforced in `AuthService.register`, the registration schema, the `/roles` catalogue and the sign-up form |
| Admin-controlled **Create User** | `POST /api/v1/admin/users` + `components/admin/CreateUserDialog.jsx` |
| 1. Create an operational user | The dialog creates the account on the platform's own `users` table |
| 2. Select the user's role | A role picker listing all ten, with each landing route shown before saving |
| 3. Set the user's account status | `is_active` in the create request — an account can be created disabled |
| 4. Activate / deactivate | The existing `PATCH /admin/users/{id}/status`, unchanged, now reachable from the same page |
| 5. View the assigned role | The directory's Role column, the account detail, and the API's own `role_label` |
| 6. Change the role only when authorized | `Permission.ADMIN_ROLE_ASSIGN`, held by `ADMIN` alone, required on the route **and** re-checked in the service |
| 7. Prevent unauthorized users from changing their own role | `PATCH /admin/users/{id}/role` refuses the caller's own account; `PATCH /users/me` (and `PUT /profile`) reject a `role` field with `422`; only `ADMIN` holds the capability at all |
| Use the existing auth/RBAC — no second system | One `users` table, one bcrypt hashing path, one `/auth/login`, one permission catalogue |
| Role stored in the database and enforced by the backend | The role is a column; `get_current_user` loads the user from the database on every request, so authorisation uses the stored role, never a token claim or a hidden button |

The end-to-end path the prompt asked to be able to walk — *Admin → Administration → Users → Create
User → Role: LAB_TECHNICIAN → Create → the technician signs in with the existing login → Laboratory
dashboard* — is walked by a browser test in §7, for seven operational roles rather than one.

---

## 2. The role catalogue, in one place

Ten roles, one declared order, one label per role, and one answer per role to "may a visitor choose
this?".

```python
# app/models/enums.py
ADMINISTRATION_ROLE_ORDER = (
    UserRole.ADMIN, UserRole.BEEKEEPER, UserRole.CONSUMER, UserRole.KVIC_OFFICER,
    UserRole.COLLECTION_CENTER, UserRole.PROCESSOR, UserRole.LAB_TECHNICIAN,
    UserRole.PACKAGING_UNIT, UserRole.DISTRIBUTOR, UserRole.RETAILER,
)
```

* `UserRole.administration_order()` — the order the admin screen and `GET /api/v1/roles` present.
* `UserRole.assignable_by_admin()` — all ten. Including `ADMIN` itself, because promoting a colleague
  is how a second administrator exists at all; what is *not* possible is assigning a role to
  yourself (§5).
* `UserRole.self_registrable()` — `BEEKEEPER`, `CONSUMER`. The single source of truth for the public
  form, consulted by the registration service, the registration schema and the public catalogue.
* `UserRole.label` — an explicit mapping. The old derivation produced **"Kvic Officer"** and
  **"Collection Center"**; the labels are now "KVIC officer", "Lab technician", "Collection centre",
  "Packaging unit" and so on, identical on the API and in the UI, and pinned by a test.

`GET /api/v1/roles` publishes the same ten rows in the same order, so the picker an administrator
uses cannot drift from the catalogue the API serves.

---

## 3. Database and migration

**No migration was needed, and that is deliberate.** The account model already carried everything
this work needs:

| Column | Role in role management |
| --- | --- |
| `users.role` | The assigned role — a PostgreSQL enum, not free text, so an unknown role cannot be stored |
| `users.is_active`, `deactivated_at` | Account status, set at creation and changed afterwards |
| `users.organization`, `state`, `district` | The laboratory, plant, centre or firm an operational account belongs to |
| `audit_logs.action`, `event_metadata` | `USER_PROVISIONED` and `USER_ROLE_CHANGED` entries; the action column is a plain string precisely so a new phase can add vocabulary without a migration |
| `refresh_tokens` | Revoked in bulk when a role changes |

The two new audit actions are enum values in Python, stored as strings — no DDL. `alembic check`
stays clean and the head remains `9b4d2f81ac07` (Phase 6).

---

## 4. Backend

### 4.1 Capabilities

Two capabilities, deliberately separate:

| Permission | Means | Held by |
| --- | --- | --- |
| `ADMIN_USER_MANAGE` | Create an account for somebody else; activate/deactivate it | `ADMIN` |
| `ADMIN_ROLE_ASSIGN` | Decide *which role* an account holds | `ADMIN` |

Splitting them means "can disable an account" and "can grant a role" cannot be granted together by
accident: if a future support role is given `ADMIN_USER_MANAGE`, it still cannot hand out
`LAB_TECHNICIAN` or `ADMIN`.

Both checks are made **twice on purpose** — as route dependencies *and* from inside
`AdminService._require(...)`. These are the operations where a missing check is a privilege
escalation rather than a cosmetic bug, so the check does not live only in the HTTP layer.

### 4.2 `POST /api/v1/admin/users`

```
AdminUserCreate → AdminService.create_user()
  ├── capability check (ADMIN_USER_MANAGE + ADMIN_ROLE_ASSIGN)
  ├── duplicate email / phone           → 409 DUPLICATE_RESOURCE
  ├── password policy (same as registration: 8–72 bytes, letter + digit)
  ├── bcrypt hash via the existing hash_password()
  ├── insert into the same `users` table with the chosen role and status
  ├── role == BEEKEEPER → the beekeeper record is created in the same transaction (PENDING)
  ├── audit: USER_PROVISIONED (role, status, actor, organisation, apiary code)
  └── 201 { user, message, beekeeper_created }
```

The apiary block is the **same** `BeekeeperCreate` schema the public form sends — one definition of
a beekeeper record, whichever door the account came through — and it is rejected with `422` if it
accompanies any other role.

### 4.3 `PATCH /api/v1/admin/users/{user_id}/role`

Guard rails, in order:

1. the actor must hold `ADMIN_ROLE_ASSIGN` (administrators only);
2. an administrator **cannot change their own role** — otherwise the capability that guards role
   assignment would also be the capability to hand yourself any role;
3. the **last active administrator** cannot be moved off `ADMIN`, mirroring the existing rule that
   the last one cannot be deactivated;
4. live refresh tokens are revoked (`revoke_reason = role_changed`), because the account's
   permissions change the moment this commits;
5. the change is audited with **both** roles — `previous_role` and `new_role` — plus the actor, the
   reason and the number of sessions ended. "What was this account before" is not answerable from
   the new value alone;
6. promoting an account to `BEEKEEPER` creates its missing apiary record; a beekeeper moved to
   another role keeps theirs, because history is never deleted.

A no-op (same role) returns 200 without an audit row or a revocation.

### 4.4 Why a stale token cannot hold an old role

`resolve_user_from_access_token()` validates the JWT signature and then **loads the user from the
database**, returning that row. `Permission` checks read `user.role` from that row. The role claim in
the token is never trusted for authorisation. Two consequences, both asserted in the tests:

* promoting an account changes what its *existing* token may do — immediately;
* deactivating an account ends its access on the next request, without waiting for expiry.

---

## 5. Frontend

| File | What it does |
| --- | --- |
| `constants/roles.js` | `ASSIGNABLE_ROLES` (the ten, in the API's order), the label map, `ROLE_ASSIGNMENT_HINTS` (one line per role, used in both dialogs) |
| `utils/validation.js` | `ALL_ROLE_OPTIONS` (all ten, for the admin picker — separate from `ROLE_OPTIONS`, the two public ones used by the sign-up form), `adminCreateUserSchema`, `adminRoleChangeSchema` |
| `components/admin/CreateUserDialog.jsx` | The create form: name, email, phone, organisation, **role** (all ten), **account status**, password + confirmation, district/state and an audited note. Shows the selected role's purpose and the exact route the account will land on, before saving |
| `components/admin/ChangeRoleDialog.jsx` | The role-change form: previous role → new role, the new role's purpose and landing route, an optional audited reason, and an explicit warning that sessions are revoked |
| `pages/admin/AdminUsersPage.jsx` | "Create user" in the header; "Change role" per row and in the account detail; the Role column and `role_label`; the existing activate/deactivate kept beside them |
| `services/adminService.js` | `createUser(...)`, `setUserRole(...)` |
| `constants/api.js` | `admin.users` (POST), `admin.userRole(id)` |

The controls are hidden where the API would refuse them — an administrator is not offered a role
change on their own row — but that is a courtesy, not the control: the same request sent by hand
gets a `403`/`422` (§7, §8.1).

The create form's copy states the contract plainly: the account signs in at the existing login, it
lands on the workspace named for its role, provisioning a beekeeper account creates the apiary record
that starts *pending review*, and role assignment is enforced by the API.

---

## 6. What this work does **not** do

* **No second authentication system.** There is one `users` table, one bcrypt path, one
  `/auth/login`, one refresh-token store. A created account has no special flags, no "provisioned"
  login route and no seeded password.
* **No client-side authority.** The frontend never decides what a role may do; it decides what to
  render. Every claim in this report is an API response, not a UI state.
* **No role in a token claim that outlives the database.** §4.4.
* **No deletion of accounts.** The API still has no delete-account endpoint: accounts are deactivated
  and kept, so the audit trail and the records pointing at them stay intact. (The browser test
  deletes its own fixtures over SQL, which is test cleanup, not a product capability.)
* **No self-service role change** for anybody, including administrators.
* **No expansion of the public form.** It still offers two roles, and the API still refuses the other
  eight however they are submitted.

---

## 7. Verification

### 7.1 The end-to-end browser walk — `tests/browser_smoke_role_management.py`

**74 passed / 0 failed, 0 console errors (145 s)**, against the live stack: PostgreSQL 17.11, the API
on `:8000` and a production build served by `vite preview` on `:4173`, driven by real Chromium.

| Scenario | What it proves |
| --- | --- |
| 1. Public registration is closed | The sign-up form offers exactly `BEEKEEPER` and `CONSUMER`; the API refuses `LAB_TECHNICIAN`, `PROCESSOR`, `KVIC_OFFICER`, `PACKAGING_UNIT` and `RETAILER` with `422` when called directly; a beekeeper calling `POST /admin/users` gets `403` |
| 2. The administrator provisions one account per operational role | Seven accounts created **through the form** — lab technician, processor, collection centre, packaging unit, distributor, retailer, KVIC officer — each with a role chosen in the picker and the landing route shown by the form |
| 3. Each account signs in and reaches its own workspace | Each of the seven signs in on the ordinary login page and lands on `/laboratory`, `/processor`, `/collection-center`, `/packaging`, `/distributor`, `/retailer`, `/kvic`; `GET /auth/me` returns the stored role; each is redirected away from `/admin/users` in the browser **and** refused `403` by the API |
| 4. The directory shows the assigned role; the role can be changed | Every created account is found by search with its role label; the packaging account is moved to `DISTRIBUTOR` through the dialog, the API confirms the new role, and the account then lands on `/distributor` |
| 5. A user cannot grant themselves a role | A technician calling the role endpoint on their own id → `403`; `PATCH /users/me {"role": …}` → `422`; the technician still holds the technician role; the administrator's own row offers **no** role-change control and the API refuses the same request with `422` |
| 6. The shipped bundle | All ten role keys and all ten labels are present in the built JavaScript; the create-user and role-change copy ships |

The walk deletes every account it created (7 in the last run) and reports the count.

### 7.2 The API suite — `tests/test_admin_user_management.py`

**54 passed / 0 failed (67 s)**, against the real database:

* every one of the ten roles can be created by an administrator, and the role read back from the
  database matches the API response (parametrised over all ten);
* a created account signs in through `/auth/login`, and its reported `home_route` matches
  `ROLE_HOME_ROUTES[role]`;
* a created beekeeper account gets its apiary record (`BKR-…`) and it starts `PENDING`;
* an account created inactive cannot sign in, and can be activated from the directory afterwards;
* creation is audited as `USER_PROVISIONED` with the role in the metadata;
* duplicate email → `409`; weak password → `422`; unknown role → `422`; unknown account → `404`;
* a created lab technician can read `/lab-tests` and is refused `403` by `/admin/summary` and by
  `POST /processing-units` — one role does not carry another's powers;
* **a token minted under one role gains the new role's access the moment the database says so**, and
  loses the old one — the property that makes role management a security control;
* all eight operational roles are refused by public registration (parametrised), while the two public
  roles still register;
* role change: audited with both roles, effective at the next sign-in, sessions revoked, promoting a
  second administrator works and the promoted account can then read `/admin/summary`, promoting to
  `BEEKEEPER` creates the apiary record, the same role is a no-op, the last administrator cannot be
  demoted, and the administrator cannot change their own role even when a second administrator
  exists;
* self-service doors closed: `PATCH /users/me` and `PUT /profile` reject `role` with `422`; a
  beekeeper, a KVIC officer and a lab technician are each refused `403` by both admin endpoints;
* the directory lists an account from every role, filters by role, and the platform summary counts
  every role;
* the role vocabulary, the declared order and the published labels are pinned against the documented
  ten.

### 7.3 Regression suites

| Suite | Result |
| --- | --- |
| Full backend pytest | **749 / 0** (823 s) — see §7.4 |
| `browser_smoke.py` | 38 / 0 (label check updated to the API's own labels) |
| `browser_smoke_phase2.py` | 28 / 0 |
| `browser_smoke_phase3.py` | 112 / 0 |
| `browser_smoke_phase41.py` | 26 / 0 |
| `browser_smoke_phase5.py` | 51 / 0 |
| `browser_smoke_role_navigation.py` | 64 / 0 |
| `api_smoke_phase2/3/4/41/5/6.py` | 43/0, 64/0, 73/0, 43/0, 77/0, 176/0 |
| `npm run lint` | clean |
| `npm run build` | green |

### 7.4 Full backend suite

```
cd backend && .venv/bin/python -m pytest
749 passed, 1 warning in 823.03s (0:13:43)
```

695 tests before this work, 749 after: the 54 new role-management tests, with no existing test
changed except one assertion in `browser_smoke.py` that compared role *labels* and now reads the
API's own labels ("Collection centre", "KVIC officer") instead of a second wording written into the
test. The single warning is Starlette's own `anyio.abc.BlockingPortal` deprecation notice, not this
project's code.

---

## 8. Acceptance walk (development environment)

```bash
# stack
pg_ctlcluster 17 main start
cd backend && .venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.scripts.seed_dev_data
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
cd ../frontend && npm run build && npx vite preview --port 4173 --host 0.0.0.0

# evidence
cd ../backend
.venv/bin/python -m pytest tests/test_admin_user_management.py
SMOKE_BASE_URL=http://localhost:4173 .venv/bin/python tests/browser_smoke_role_management.py
```

By hand, in the browser:

1. sign in as `admin@honeychain.example.com` and open **Administration → Users**;
2. click **Create user**, set Role = `LAB_TECHNICIAN`, status = Active, choose a password, and save —
   the dialog shows the account will sign in at the existing login and land on `/laboratory`;
3. the new account appears in the directory immediately, with its role and status;
4. sign out, sign in with that account: the laboratory workspace opens, and `/admin/users` typed by
   hand returns to `/laboratory`;
5. sign back in as the administrator, use **Change role** on that account to move it to
   `PROCESSOR` — the change is audited, the account's sessions are revoked, and next sign-in lands on
   `/processor`;
6. click **Change role** on your own row: the control is not offered, and the API would refuse it.

---

## 9. Files changed

**Backend — new**

```
tests/test_admin_user_management.py          54 tests
tests/browser_smoke_role_management.py      the end-to-end browser walk
```

**Backend — extended**

```
app/models/enums.py            ADMINISTRATION_ROLE_ORDER, explicit role labels,
                               UserRole.assignable_by_admin()/administration_order(),
                               AuditAction.USER_PROVISIONED
app/core/permissions.py        Permission.ADMIN_ROLE_ASSIGN (ADMIN only) + documentation
app/schemas/admin.py           AdminUserCreate, AdminUserCreateResponse,
                               AdminUserRoleUpdate, AdminUserRoleUpdateResponse
app/services/admin_service.py  create_user(), set_user_role(), _require(), _create_beekeeper_record()
app/services/audit_service.py  user_provisioned(), user_role_changed()
app/services/auth_service.py   REVOKE_ROLE_CHANGED
app/routes/admin.py            POST /admin/users, PATCH /admin/users/{id}/role
app/routes/meta.py             the catalogue is published in the declared order
```

**Frontend — new**

```
src/components/admin/CreateUserDialog.jsx
src/components/admin/ChangeRoleDialog.jsx
```

**Frontend — extended**

```
src/constants/roles.js         ASSIGNABLE_ROLES, corrected label map, ROLE_ASSIGNMENT_HINTS
src/utils/validation.js        ALL_ROLE_OPTIONS (all ten), adminCreateUserSchema, adminRoleChangeSchema
src/services/adminService.js   createUser(), setUserRole()
src/constants/api.js           admin.userRole(id)
src/pages/admin/AdminUsersPage.jsx   Create user, Change role, detail role badge
```

**Documentation**

```
README.md            §12.4 provisioning and self-service rules; permission table; audit vocabulary
docs/api.md          POST /admin/users, PATCH /admin/users/{id}/role, corrected /roles example
docs/role-management-report.md   this report
```

---

## 10. Where the project stands

Every role in the problem statement can now be stood up by an administrator from one screen and used
by its holder immediately, through the platform's single authentication system:

```
ADMIN → Administration → Users → Create user → role → Create
      → the account signs in at the existing login
      → and lands in its own workspace
```

The role is a database column, the capability that assigns it is one permission held by
administrators, the enforcement happens on the server on every request, and nobody — including an
administrator — can change their own role. Packaging, distribution, QR verification and the rest of
the later phases remain unbuilt; their accounts can be provisioned today, and their workspaces say
honestly that the module is still to come.
