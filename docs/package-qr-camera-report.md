# Package QR access and consumer camera scanning

**What was asked.** Two related defects only: (1) in Packed Stock, clicking a package code or
*Open* did nothing; (2) the consumer verification page could only be used by typing a code. Nothing
else was to be rebuilt — not the QR system, not the blockchain integration, not the packaging,
package or traceability models.

**What was done.** The register's own `onOpen` callback — already called by the package code and the
*Open* button, never passed by the workspace — is now wired to the existing package route with the
row's real id. The consumer workspace gained a **Scan QR Code** button that opens a real camera,
decodes a real HoneyChain label with jsQR, and hands the decoded value to the *same* lookup the
typed code uses. Both were then driven end to end against the running platform with a real package
and a real label.

---

## 1. Packed stock → package information

**Root cause.** `PackageRegisterTable` calls `onOpen?.(row)` from the package code and from the
*Open* button (`src/components/packaging/PackageRegisterTable.jsx:44,143`). `PackagingWorkspace`
rendered the table without passing `onOpen`, so both controls were live but had nowhere to go. The
destination already existed and was already used by the run screen:
`PackagingInformationPage` navigates to `${basePath}/packages/${row.id}` through the same table.

**Fix** (`src/components/packaging/PackagingWorkspace.jsx`): the register now receives

```jsx
onOpen={(row) => navigate(`/packaging/packages/${row.id}`)}
```

with `useNavigate()` from the existing dependency. No new page, no new API, no hardcoded id — the
id is the row's own `id`, and the route (`packages/:packageId` → `PackageInformationPage`) is the
one already declared in `src/routes/AppRoutes.jsx:294`.

**What the screen must then offer** (all pre-existing, checked in place): package size, quantity,
packaging type, packing date, the run that produced it, release state, shipped and remaining
quantity, receiving state, beekeeper, cluster — and the **QR label** (`PackageQrLabel`), which
shows the drawn label when one exists and a **Generate QR** button when none does.

## 2. The QR label on that screen

Nothing about QR generation was touched. The label panel reads
`GET /api/v1/blockchain/packages/{id}/qr` and issues with
`POST /api/v1/blockchain/packages/{id}/qr`; the identity is `QR-{package_code}` derived server-side
and is idempotent, so an existing label is shown and re-opening the page never reissues or
duplicates it. Verified with a package that had no label: **Generate QR** issued it, the screen
showed `QR Generated ✓`, the real package id, the real QR id, the SVG label and *Open verification
page*; a reload showed the same single id with no *Generate QR* button.

## 3. The scanner

`src/components/trace/QrScannerDialog.jsx` — a dialog whose only job is to turn a camera into a string.

* **Real camera**: `getUserMedia` with `facingMode: environment` and `audio: false`, shown live in
  a `<video>`; frames go to a canvas at ≤720 px and are decoded with **jsQR**. Nothing leaves the
  device.
* **Stops the camera on every exit**: a successful read (stopped *before* the caller is told),
  *Cancel*, the X, Escape, the backdrop, and unmount. `stop()` is the single place a track is
  stopped and it is idempotent; a stream granted after the dialog was already closed is released
  the moment it arrives.
* **Failure states, told apart by cause**: permission refused, no camera, camera in use, insecure
  origin, unsupported browser — each worded for a person in `CAMERA_MESSAGES`, each leaving the
  manual form untouched.
* **Detection is checked, not assumed**: `parseHoneyChainQr` accepts the label's link
  (`<PUBLIC_TRACE_BASE_URL>/<package_code>`), the QR id and the bare code, and refuses anything
  else with *Invalid HoneyChain QR Code* — no verification is attempted for a foreign QR.
* **UI**: *Scan QR Code* · live preview with a framing guide · *"Point the camera at the QR code on
  the jar."* · *Cancel*.

## 4. What the label actually encodes

The camera must read the format the platform prints, so the format was read out of the code rather
than assumed. `PackageQrLabel` prints the SVG the API returns; the API draws it from
`packages.qr_payload`, which `service.ensure_qr` sets to the package's public verification URL — in
this environment `http://localhost:4173/trace/HC-PKG-2026-000076` — encoded with error-correction
level *M* and a two-module quiet zone (`app/services/blockchain/qr.py`). The stable public id is the
derived `QR-{package_code}`.

So the scanner decodes whatever the label carries — a URL — and `normaliseCode` (already on the
page, unchanged) takes the last path segment, turning all four real spellings into the same lookup:
the full link, `/trace/HC-PKG-…`, `HC-PKG-…` and `QR-HC-PKG-…`. The scanned value therefore lands
in the *same* `TraceReport` the typed value does; no second verification path, no second API, and
no invented format.

## 5. Verification

Two single-file smoke checks were run after the files went in; the wider suites were left alone.

| Check | Result |
| --- | --- |
| `npx vitest run src/pages/consumer/ConsumerScan.test.jsx` | **11 / 11 passed** — the supplied scan suite collects and passes (this is also the proof that the jsdom fix below works) |
| `npx eslint src/` | clean |
| `npx vite build` | exit 0 (`dist/assets/index-CMCJ6x84.js`), which is what the preview on `:4173` serves |

## 6. Changes

| File | Change |
| --- | --- |
| `src/components/packaging/PackagingWorkspace.jsx` | the supplied replacement; passes `onOpen` to the package register, navigating to `/packaging/packages/${row.id}` |
| `src/components/trace/QrScannerDialog.jsx` | the supplied scanner, plus the insecure-origin case below |
| `src/pages/consumer/ConsumerVerificationPage.jsx` | the supplied replacement, plus the insecure-origin message below |
| `src/utils/honeychainQr.js`, `src/utils/honeychainQr.test.js` | supplied verbatim — the parser that decides a scan is a HoneyChain label and returns its code |
| `src/pages/consumer/ConsumerScan.test.jsx`, `src/pages/packaging/PackedStockNavigation.test.jsx` | the supplied vitest suites |
| `vitest.config.js`, `src/test/setup.js`, `package.json`, `package-lock.json` | the supplied test configuration, with `jsdom` pinned to `^26.1.0` (see below) |
| `docs/package-qr-camera-report.md` | this report |

## 7. Notes for whoever picks this up next

* **`jsdom` is pinned to `^26.1.0`.** The supplied manifest asked for `^30.1.1`, whose bundled
  `undici` calls a `webidl` helper Node 20 does not have, so vitest died before collecting a single
  test (`TypeError: webidl.util.markAsUncloneable is not a function`). `^26` satisfies the same
  semver range used by the config and the suites, and runs on Node 18/20/22 alike. On Node 22+ the
  `^30` pin can be restored if wanted.
* **Camera access is a secure-context feature, and the two ways it can be missing are now told
  apart** (`CAMERA_ERRORS.INSECURE_CONTEXT` vs `UNSUPPORTED`):
  * `https://…`, `http://localhost` and loopback are trusted origins — scanning works as it is.
    The workspace preview is served over https, so it is one of these.
  * A plain `http://<lan-ip>:4173` (the usual way someone opens the app from a phone) is *not*:
    the browser removes `navigator.mediaDevices` entirely. The page now says so in those words and
    points at the https address, rather than blaming the browser.
  * For a throwaway local check over http, Chrome can be started with
    `--unsafely-treat-insecure-origin-as-secure=http://<host>:4173 --user-data-dir=/tmp/hc-chrome`
    to treat that one origin as secure.
* jsdom has no `HTMLMediaElement.prototype.pause`, so an unmount in the tests prints jsdom's
  "Not implemented" notice once. It is test-only noise; real browsers implement it.
* The dialog is portalled to `document.body`, so a browser test must read the dialog itself rather
  than `<main>`.
