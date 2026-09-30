# HoneyChain — Phase 6.1 delivery report

**Role-based workspaces, sidebar and navigation — and the laboratory → beekeeper synchronization**

*Smart India Hackathon 2026 · Problem Statement 26021 · Report generated 27 September 2026*

---

## 1. What this prompt set out to do

Phase 6 gave the platform two new working roles. This prompt makes sure a signed-in user sees **their
own application and nothing else**, and that the laboratory's decision actually travels back to the
people who own the honey.

The requirements, in the words they were given, and where each is answered:

| Requirement | Where it is answered |
| --- | --- |
| A sidebar shows only the items the signed-in role works with | `frontend/src/constants/navigation.js` → `Sidebar.jsx` |
| No "this is not your workspace" / "click here to go to your workspace" / "coming soon" placeholder as the *result of a cross-role link* | placeholder screens deleted; `RoleRoute` redirects instead of explaining |
| Unauthorized URLs are blocked, not merely unlinked | `RoleRoute` (frontend) **and** `require_permission(...)` per API route (backend) |
| One central role→navigation configuration drives items, routes, dashboard, actions, data visibility and edit permissions | `constants/navigation.js` + `core/permissions.py` |
| LAB_TECHNICIAN's dedicated workspace (dashboard, pending tests, tests, samples, completed, profile) | `pages/laboratory/*`, `components/laboratory/*` |
| KVIC sees the same underlying records, scoped to its clusters, in the same shape | KVIC route tree over the shared screens; no KVIC copies |
| BEEKEEPER sees own batch status and the laboratory stage, read-only | `BeekeeperDashboardPage`, `BatchDetailView`, `BatchTimeline`, `QualitySummaryCard` |
| Every other role gets its own workspace only | per-role route trees + `RoleWorkspaceHomePage` for the roles whose modules are not built yet |
| Laboratory completion updates the batch, the audit trail and the beekeeper's view from real API/database state, with no duplicate batch or traceability record | `services/laboratory_service.py` → `batch_lifecycle` → the same batch row everyone reads |

---

## 2. The single source of truth

`frontend/src/constants/navigation.js` holds one record per role:

```js
WORKSPACES = {
  [ROLES.BEEKEEPER]: {
    label: 'Beekeeper workspace',
    short: 'Beekeeper',
    home: '/beekeeper',
    routes: ['/beekeeper'],
    description: 'Your apiary: hives, sensors, harvests and the journey of your honey.',
    sections: [ …, { label: 'Beekeeper', items: [{ label: 'My Hives', to: '/beekeeper/hives', icon: 'Hexagon' }, …] } ],
  },
  …
}
```

Everything else reads that record:

| Question | Helper |
| --- | --- |
| What does this role's sidebar contain? | `navSectionsForRole(role)` |
| Where does this role land? | `workspaceHomeForRole(role)` |
| May this role open this path? | `canRoleOpenPath(role, pathname)` |
| What is this workspace called? | `workspaceLabelForRole(role)` / `roleLabel(role)` |
| What is the current screen called? | `navLabelByPath(path)` |

The route table (`AppRoutes.jsx`) is grouped per role and guarded by the *same* configuration, so a
screen cannot exist in the router without existing in that role's workspace — the two cannot drift.
Role labels, colours and the "soon" wording live beside it in `constants/roles.js`;
`constants/plannedModules.js` is a **roadmap list only** — it is not a navigation source, and an
entry is deleted the moment a real screen replaces it (Processing and the Laboratory were deleted
from it in Phase 6).

The backend keeps its own, independent version of the same decisions in `app/core/permissions.py`
(`Permission` enum + `ROLE_PERMISSIONS`), consumed through `require_permission(...)` dependencies.
The frontend decides what exists; the backend decides what is allowed. Neither trusts the other.

---

## 3. Role-based routing and guards

`routes/RoleRoute.jsx` — two checks, in order:

1. **`allow`** — the roles a screen was written for (`<RoleRoute allow={[ROLES.LAB_TECHNICIAN]}>`).
2. **`canRoleOpenPath(role, pathname)`** — the workspace check, driven by the central
   configuration, so a typed URL outside the role's workspace is not routable.

Failing either one renders `<Navigate to={workspaceHomeForRole(role)} replace />`. Nothing is
explained, nothing is left on a screen belonging to another role, and no "forbidden" page exists
anywhere in the codebase any more (`ForbiddenState.jsx` and `ComingSoonPage.jsx` were deleted).

While the session is still being confirmed (`isLoading`) the guard renders nothing rather than
bouncing a user to a workspace the not-yet-loaded role may not own — a small detail that removes a
real flicker to the wrong home.

`routes/ProtectedRoute.jsx` stays as it was: no token ⇒ `/login`, remembering the requested path.
The signed-in-but-wrong-role case is now always a redirect, never a notice.

Allow-lists as shipped:

| Route tree | Roles |
| --- | --- |
| `/beekeeper/**` | BEEKEEPER |
| `/kvic/**` | KVIC_OFFICER, ADMIN |
| `/laboratory/**` | LAB_TECHNICIAN |
| `/processor/**` | PROCESSOR |
| `/admin/**` | ADMIN |
| `/collection-center`, `/packaging`, `/distributor`, `/retailer`, `/consumer` | the role they belong to (see §5) |

---

## 4. The sidebars, role by role

Every item below was verified in a real browser by
`tests/browser_smoke_role_navigation.py`, which asserts the **exact** set of labels per role — not a
subset, so an extra item fails the walk as loudly as a missing one.

**BEEKEEPER — 9 items** (Dashboard, My Profile, My Hives, IoT Monitoring, AI Insights, Alerts, Honey
Collections, Honey Batches, Traceability). No administration, no laboratory, no processing, no
packaging, no distribution, no KVIC, no blockchain. The beekeeper still *sees* the laboratory stage
of their own batch — read-only (§8) — but has no laboratory screen.

**KVIC_OFFICER — 14 items** (Dashboard, My Profile, Clusters, Beekeepers, Hives, IoT Monitoring, AI
Insights, Alerts, Honey Collections, Honey Batches, Processing, Laboratory, Traceability, Cluster
Analytics). Processing and Laboratory appear here as **oversight**: read-only, scoped to the
officer's clusters, over the same records the processor and the technician write. No platform
administration, no lab-technician controls, no packaging/distribution/consumer items.

**LAB_TECHNICIAN — 8 items** (Dashboard, My Profile, Pending Lab Tests, Laboratory Tests, Samples,
Completed Tests, Reference Parameters, Laboratories). Every one of them is an RBAC-permitted
laboratory function; nothing from administration, KVIC, or another role's pipeline.

**PROCESSOR — 6 items** (Dashboard, My Profile, Awaiting Processing, Processing Runs, Batches,
Processing Units). No laboratory controls, no KVIC, no admin.

**CONSUMER — 2 items** (Dashboard, My Profile) plus the account screens, and a deliberate
future-feature description of the verification module rather than a fake scanner.

**The other four roles** (COLLECTION_CENTER, PACKAGING_UNIT, DISTRIBUTOR, RETAILER) get their own
workspace home that names the module they will work in, labels it as **future work with its phase**,
and offers nothing clickable that does not exist. This is the "deliberately labelled as
future-feature design" case the prompt allows — it is a roadmap for that role, not a placeholder
caused by someone else's navigation item.

`Sidebar.jsx` renders whatever `navSectionsForRole(role)` returns, with an icon map keyed by name
(`Hexagon`, `Radio`, `Factory`, `TestTubes`, `Beaker`, `CheckCheck`, `Ruler`, `Microscope`, `Inbox`,
`Warehouse`, …). The old per-item `"Soon"` badge branch is gone: labels are honest now, so the badge
was describing a state that no longer exists.

---

## 5. Dashboards and landing pages

Each role lands on a page built for its own work, and each one states what it read:

* **BEEKEEPER** — registration card (beekeeper code, verification badge, cluster, location), apiary
  tiles counted from the hive/IoT summaries, a list of the beekeeper's own hives with their paired
  devices, "Your honey's journey" (each batch, its stage, its laboratory outcome), the read-only
  laboratory status panel, and recent harvests. Nowhere on this page can a batch be moved on.
* **LAB_TECHNICIAN** — the laboratory workspace: pending tests, tests in progress, samples, completed
  tests, reference-parameter coverage, and the facilities the tests are attributed to.
* **PROCESSOR** — runs awaiting a unit, runs in progress, completed runs with their measured loss,
  and the units the work happens in.
* **KVIC_OFFICER** — cluster-scoped counters, members and apiaries, harvests and batches in the
  cluster, processing and laboratory oversight (read-only), and cluster analytics.
* **ADMIN** — accounts, the beekeeper registry, every operational module, and the audit trail; the
  console is the one role that may *read* `/kvic`, `/processing` and `/laboratory` for support
  purposes, which is why those trees list ADMIN in their allow-lists.
* **The five unbuilt roles** — `RoleWorkspaceHomePage`, which reads `plannedModules.js` for that
  role and describes what is coming without offering a link that 404s.

---

## 6. Actions, buttons, data visibility and edit permissions

One rule, expressed once per workspace: the same configuration that decides the sidebar decides what
the screens may offer.

* `components/processing/*` and `pages/processing/*` receive `role` and compute
  `canWrite = role === PROCESSOR || role === ADMIN`; a lab technician or KVIC officer opening the
  same screen gets the read-only rendering (the browser walk asserts the KVIC laboratory oversight
  page is read-only, and that the beekeeper's batch page has no laboratory control).
* `components/laboratory/*` compute `canWrite = role === LAB_TECHNICIAN || role === ADMIN`:
  recording a measurement, completing a test and retesting are the technician's; configuring the
  reference ranges in the parameter catalogue is ADMIN's, and the UI simply does not render the
  control for anyone else.
* List screens receive the scoped list endpoints (KVIC lists are filtered by
  `officer_cluster_ids`; a beekeeper's own filter is applied server-side), so "data visibility" is a
  property of the query, not of the rendering.
* The API refuses anything the UI hides: every write route depends on a permission from
  `core/permissions.py`, and `tests/api_smoke_phase6.py` walks the whole RBAC matrix (a beekeeper
  writing a processing run is 403, a laboratory technician creating a processing unit is 403, a KVIC
  officer reading another cluster's batch is 404, and so on).

---

## 7. Laboratory → beekeeper synchronization (the functional core)

When a LAB_TECHNICIAN completes a test, this is everything that happens — in one transaction, all in
the backend:

1. **Required information is validated.** The test must have a sample, a laboratory and at least one
   measurement; the completion request is validated by Pydantic (`extra="forbid"`).
2. **Each measurement is judged** against the reference range in force for its parameter code, and
   the range is snapshotted onto the result row with its source label.
3. **The overall result is computed** by `quality_rules.decide(...)`: a missing required measurement
   or an unconfigured range makes the test `INCONCLUSIVE`; a required failure makes it `FAIL`;
   otherwise `PASS`. The verdict carries its own plain-language reasons.
4. **Status becomes `COMPLETED`** and the decision is stamped with the deciding user.
5. **The batch moves** through `batch_lifecycle.advance()` — the single writer — to `APPROVED` or
   `REJECTED`. An `INCONCLUSIVE` test leaves the batch in `LAB_TESTING`, which is the honest
   outcome: nothing was compared, so nothing is decided.
6. **An audit event** (`LAB_TEST_COMPLETED`, or `LAB_TEST_OVERRIDDEN` with both the computed and the
   overridden result) is written in the same transaction.
7. **No duplicate record is created.** There is no second batch, no copied status column and no
   KVIC-specific copy. The beekeeper's batch page, the KVIC officer's batch page and the
   administrator's view are three views of one row, and the laboratory stage each of them shows
   (`BatchTraceStage.outcome`) is derived from the test that decided it.

What the beekeeper then sees, with no refresh trickery and no frontend-only state: the timeline's
laboratory row changes from *Testing* to **✓ Approved** (or **✕ Rejected**), the quality summary card
shows the measured value with the range it was judged against and the verdict's own words, the batch
status badge reads **Approved**, and packaging/distribution stay honestly *pending*. The beekeeper
has no control on any of it — the read-only rule is enforced by the API's permissions, not by hiding
a button.

KVIC sees the same thing for the batches inside its clusters, because the officer's screens read the
same endpoints; a batch outside the officer's clusters is a 404.

---

## 8. Verification evidence

Everything below was run against the live development stack — PostgreSQL 17.11, FastAPI on `:8000`,
and a production build (`npm run build`) served by `vite preview` on `:4173` — with a real browser
(Playwright/Chromium), not with fixtures in the test process.

| Suite | Result |
| --- | --- |
| `tests/browser_smoke_role_navigation.py` (new) | **63 passed / 0 failed** |
| `tests/browser_smoke.py` | 38 / 0 |
| `tests/browser_smoke_phase2.py` | 28 / 0 |
| `tests/browser_smoke_phase3.py` | 112 / 0 |
| `tests/browser_smoke_phase41.py` | 26 / 0 |
| `tests/browser_smoke_phase5.py` | 51 / 0 |
| `tests/api_smoke_phase{2,3,4,41,5,6}.py` | 43/0, 64/0, 73/0, 43/0, 77/0, 176/0 |
| Full backend pytest (`pytest -q`) | **695 passed / 0 failed** in 871 s |
| `npm run lint` | clean |
| `npm run build` | green (`dist/assets/index-*.js`, ~659 kB, gzip ~172 kB) |

### 8.1 What the role-navigation walk asserts

* **Exact sidebar sets** for BEEKEEPER (9), LAB_TECHNICIAN (8), KVIC_OFFICER (14), PROCESSOR (6) and
  CONSUMER (2), plus "no cross-role label leaks into the beekeeper's navigation".
* **Route guards, in the browser, for five roles:** beekeeper typing `/admin/users`, `/laboratory`,
  `/processor/runs`, `/kvic/batches`; laboratory technician typing `/admin/users`, `/kvic`,
  `/beekeeper/hives`; KVIC typing `/admin/users`, `/laboratory`, `/beekeeper/hives`; processor and
  consumer typing three other-role URLs each — every one ends on the *user's own* workspace, asserted
  by URL, not by a message.
* **No placeholder copy ships:** the walk greps the built bundle for the cross-workspace phrases and
  asserts they are absent, and asserts the five honest empty/loading messages the phase requires are
  present.
* **The laboratory → beekeeper walk** described in §7, end to end, including the read-only checks.
* **No console errors** on any visited screen.

### 8.2 Two defects the walk caught and the fixes

1. **The batch screens died after a laboratory decision.** `QualitySummaryCard` and
   `BatchDetailView` treated `batch.processing` as a list and called `.filter`/`.map` on a value the
   API returns as a single object (`BatchProcessingRef | None`), so React threw
   `TypeError: a.filter is not a function` and the error boundary blanked the beekeeper's batch and
   traceability pages. Fixed: one latest run, one latest test, counts stated when more records exist.
   The walk now asserts the quantities on screen (12.5 kg in, 11.8 kg out), the measured value, and
   the approved status — the assertions that would have caught it in the first place.
2. **The walk itself asserted a value the browser never delivered.** The measurement field is a
   controlled numeric input; the walk's original typing simulation (per-key) kept only the first
   digit of `17.4` while the form was re-rendering. The test now fills the field, asserts what the
   field *contains*, saves, and then asserts what the page shows — which is the behaviour a human
   performs.

A third, smaller correction: the smoke's cleanup deleted measurements by `test_id` where the real
column is `lab_test_id`, so the `DELETE` aborted and left a batch, a processing record and a lab test
in the development database between runs. The cleanup now uses the real key and the leftovers were
removed; every later run starts from the same state.

---

## 9. Acceptance walk (development environment)

```bash
# 1. start the stack
pg_ctlcluster 17 main start
cd backend && .venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.scripts.seed_dev_data
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
cd ../frontend && npm run build && npx vite preview --port 4173 --host 0.0.0.0

# 2. the walk itself, end to end
cd ../backend
SMOKE_BASE_URL=http://localhost:4173 .venv/bin/python tests/browser_smoke_role_navigation.py
```

To see it by hand: sign in as `beekeeper@honeychain.example.com` and note the sidebar (nine items,
no laboratory); as `labtech@honeychain.example.com`, open **Pending Lab Tests**, record a
measurement, and **Complete and decide**; sign back in as the beekeeper and open **Honey Batches** —
the same batch now reads **Approved** with the measured value and the range it was judged against.
Then sign in as `kvic@honeychain.example.com` and open the batch: identical numbers, read-only. In
every session, type `/admin/users` into the address bar: each role is returned to its own dashboard.

---

## 10. Test data and development fixtures

* `seed_dev_data.py` provides the four working roles' accounts (`admin@`, `kvic@`, `beekeeper@`,
  `processor@`, `labtech@`, `consumer@honeychain.example.com`), one cluster, one beekeeper, one hive
  and one ESP32-class device, and is idempotent.
* Telemetry in development comes from `app/scripts/hive_simulator.py` and is stored with
  `source = SIMULATOR`; the dashboards show that label, and nothing fabricates readings when the
  table is empty.
* The role walk builds its own fixtures through the API (a processing unit, a harvest, a batch, a
  run, a `MOISTURE` range of 0–20) and removes them afterwards in foreign-key order.
* The `MOISTURE` range used by the walk is a **development configuration**, not a claim about honey.

---

## 11. Explicitly not built (and why)

Packaging, distribution, QR/customer verification, trust score, blockchain anchoring and smart
contracts remain unbuilt, unrouted, and described as future work — on the role home of the role that
will use them, with the phase they belong to. No sidebar lists a module that does not exist, and no
screen claims a certification, a compliance status or a scientific threshold that the platform did
not have configured.

The beekeeper's laboratory view is intentionally read-only in both layers: no write permission in
`core/permissions.py`, and no control rendered in the UI.

---

## 12. Risks, trade-offs and how they are contained

| Risk | Containment |
| --- | --- |
| The sidebar and the router disagree | one configuration file drives both; the guard reads the same helper the sidebar does |
| Hiding a link is mistaken for security | every write route depends on a backend permission; the smoke asserts the API refusal, not just the missing button |
| A role's landing page becomes a shopping list of other teams' modules | each role lands on its own workspace home; unbuilt modules are described for their own role only |
| KVIC drift (a "KVIC copy" of a record) | KVIC screens read the operational endpoints with cluster-scoped filters; no KVIC-owned mirror tables exist |
| A laboratory decision only changing the screen | the decision path is server-side (`laboratory_service` → `batch_lifecycle`); the browser walk asserts the beekeeper's page after the technician's write |
| Two roles editing the same screen | `role` + `canWrite` per component, mirrored by the API; the read-only paths are asserted in the browser |

---

## 13. Files changed in this prompt

**New**

```
frontend/src/constants/navigation.js              (central role→navigation configuration)
frontend/src/constants/{processing,laboratory}.js
frontend/src/services/{processingService,laboratoryService}.js
frontend/src/components/processing/{ProcessingWorkspace,AwaitingProcessingTable,ProcessingRunTable,ProcessingRunPanel}.jsx
frontend/src/components/laboratory/{LaboratoryWorkspace,AwaitingTestingTable,LabTestTable,LabTestPanel,ParameterCatalogueTable,LaboratoryFacilitiesCard}.jsx
frontend/src/components/collections/{BatchTimeline,QualitySummaryCard}.jsx
frontend/src/pages/{beekeeper,kvic,processing,laboratory,admin,traceability,workspace}/*
frontend/src/pages/workspace/RoleWorkspaceHomePage.jsx
backend/tests/browser_smoke_role_navigation.py
```

**Rewritten**

```
frontend/src/routes/{AppRoutes,RoleRoute}.jsx     (per-role trees; redirect guard)
frontend/src/components/layout/Sidebar.jsx        (renders the central configuration; "Soon" badge gone)
frontend/src/constants/plannedModules.js          (roadmap only — 7 future modules, no stale entries)
frontend/src/pages/dashboard/DashboardPage.jsx    (role-aware landing)
frontend/src/pages/collections/{BatchesPage,BatchDetailPage}.jsx (+ PROCESSOR context)
frontend/src/components/collections/{BatchDetailView,BatchTable,BatchWorkspace}.jsx
frontend/src/pages/beekeeper/BeekeeperDashboardPage.jsx (own record, hives, journey, read-only lab status)
```

**Deleted**

```
frontend/src/pages/ComingSoonPage.jsx
frontend/src/components/common/ForbiddenState.jsx
frontend/src/pages/consumer/ConsumerDashboardPage.jsx
frontend/src/pages/dashboard/SupplyChainDashboardPage.jsx
frontend/src/pages/laboratory/LaboratoryDashboardPage.jsx   (placeholder replaced by the real workspace)
```

**Updated for the new behaviour**

```
frontend/src/constants/{api,collection,roles}.js
frontend/src/services/{collectionService,batchService}.js
backend/tests/{api_smoke_phase5,browser_smoke,browser_smoke_phase2,browser_smoke_phase3,browser_smoke_phase5}.py
```

---

## 14. Where the project stands

A signed-in user now sees one application: their own. The beekeeper sees an apiary, harvests and the
journey of their honey — including the laboratory's decision, read-only. The laboratory technician
sees samples and tests. The processor sees runs and units. The officer sees the cluster and the same
records behind it. The administrator sees the platform. Every typed URL outside a role's workspace
returns that user to their own dashboard, and the API refuses the underlying request regardless of
what the screen would have rendered.

The chain runs end to end on real rows — `KVIC → Cluster → Beekeeper → Hive → IoT → Telemetry → AI →
Collection → Batch → Processing → Laboratory` — with one batch record, one lifecycle writer, one
audit trail, and no duplicate traceability anywhere.
