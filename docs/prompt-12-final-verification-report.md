# Prompt 12 — final verification, security and deployment

Everything below was **run**, not inferred from code: against a live API on the
development PostgreSQL database, in a real browser, and as a Docker Compose
deployment. Records created by the checks are marked TEST.

## Result

| Feature | Result | How it was tested |
| --- | --- | --- |
| Authentication | PASS | all 10 roles signed in (API + browser); sign-out/in keeps state; page reload keeps the session in production mode (Docker) |
| RBAC | PASS | 14 cross-role writes/reads refused by the **backend** (401/403); browser: each role's sidebar shows only its modules, every entry opens, another role's URL bounces home |
| KVIC Cluster → Batch | PASS | UI: New cluster → typed fields → selected 2 existing batches → move confirmed → cluster listed with 2 batches → opened → reload + sign-out/in → same 2 batches, analytics from them |
| Collection | PASS | beekeeper harvest → exactly one batch; collection-centre workspace opens |
| Processing | PASS | run opened/started/completed; lab sees the batch in `LAB_TESTING` |
| Laboratory | PASS | PASS → approved + on packaging worklist; FAIL → `REJECTED`, packaging refused (409); INCONCLUSIVE → not approved; HOLD → `LAB_HOLD`; Proceed Anyway refused without its confirmation word, accepted with it, written to the audit log |
| Packaging | PASS | approved batch → run → exactly the declared packages, codes generated, listed in Packed stock; completing twice refused |
| QR Generation | PASS | new **QR Code Generation** screen: real package IDs, Generate QR → SVG label + ledger event; refresh and re-issue return the same `QR-HC-PKG-…` id and event; View QR re-opens it |
| Consumer QR Scan | PARTIAL | the camera cannot be granted in the test browser: the page reports the denial clearly and keeps manual entry working; QR decoding is covered by the existing `ConsumerScan` unit tests. **A scan with a physical camera still needs a manual check.** |
| Consumer Manual Verification | PASS | typed `QR-HC-PKG-2026-000001` → the exact package, its batch and the real journey; package code, QR id and unknown code (404) checked over the API |
| Distribution | PASS | released package → shipment → dispatch; a second dispatch refused; KVIC reads the same shipment |
| Retailer Receipt | PASS | retailer sees the shipment, confirms after the carrier's delivery; another retailer can neither read nor receive it (404); a repeated receipt writes one event |
| Blockchain | PASS | external ledger reachable; **all 76 events of the test runs CONFIRMED**; retries/refreshes produced no duplicate event or tx id; admin ledger lists exactly the batch's events |
| Traceability | PASS | unified chain (batch → collection → beekeeper → hive → processing → lab → packaging → packages → shipments → receipts → events); future steps shown as not reached |
| Cross-role synchronization | PASS | every stage re-read by the next role from the same record id (Prompt 11 probe, 41/41) |
| Input/forms | PASS | full values typed into login, cluster, consumer verify and search fields without focus loss; no remounting components found |
| Security | PASS | no stack trace / SQL / path / secret in any error; public health endpoints no longer echo exception text; docs off in production; secrets only in git-ignored env files |
| Production Build | PASS | `vite build` OK, 37/37 frontend tests, 0 lint errors; backend starts and connects; see backend suite below |
| Docker/Deployment | PASS | `docker compose up -d --build`: db, backend, frontend all healthy; migrations ran; admin bootstrapped; SPA, `/trace/…` and `/api` served through nginx; browser sign-in works |

**Backend test suite:** see the last section.

Probes: `backend/tests/prompt11_core_flow.py` (41 checks) and
`backend/tests/prompt12_final_checks.py` (88 checks) — both 0 failures.
Data-consistency queries (18): 0 problems (no duplicate batches, collections,
packages, QR codes, event or tx ids; no package on the wrong batch, QR on the
wrong package, shipment on a non-retailer or wrong batch; no orphaned events).

## Defects found and fixed in this phase

| Area | Defect | Fix |
| --- | --- | --- |
| QR | no QR Code Generation screen; QR state not in the package list | `/packaging/qr` page + sidebar entry; `qr_issued`, `qr_id`, `qr_generated_at` on package rows |
| Dropdowns | processing type defaulted to Filtering and hid "Other"; new user defaulted to Lab Technician; lab override defaulted to Pass; sample unit defaulted to Gram; shipment pre-selected the first package | "Select …" placeholders, required choice, Other → text field |
| Links | admin/KVIC processing-run links and lab-test links pointed at routes those roles cannot open (lab links also forced a full reload) | per-role base paths, KVIC run-detail route, client-side navigation |
| Tests | two tests expected a carrier's delivery to complete a batch | updated to the receipt rule |
| Security | public `/health/detailed` and `/health/mqtt`, and IoT batch ingest, echoed exception text | generic messages; details logged |
| Security | API docs exposed in production | disabled in production |
| Config | production accepted localhost URLs, a blockchain with no URL, and development switches | refused at start-up |
| Config | dev database password hard-coded as a default | removed (lives in `backend/.env`) |
| Seed | dev seed guarded only by `ENVIRONMENT` | also refuses unless development/testing and a local database |
| Deployment | no Docker setup; production env template out of date | Dockerfiles, nginx config, `docker-compose.yml`, `.env.docker.example`, `docs/deployment.md` |

## Things to know

* **The development `.env` points at a real, shared ledger service.** Every
  verification run wrote its TEST events there (all confirmed). Ledger
  transactions cannot be removed.
* `backend/.env` / `.env.development` hold development credentials (placeholder
  JWT secret, local DB password). They are git-ignored; never deploy them.
* KVIC officers read every cluster (no officer↔cluster assignment exists); a
  packaging-unit account can register units. Both are existing design decisions
  left unchanged.

## Backend test suite
