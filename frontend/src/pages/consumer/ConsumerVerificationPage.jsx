import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Camera, ExternalLink, QrCode, ScanLine, Search } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { QrScannerDialog, CAMERA_ERRORS } from '@/components/trace/QrScannerDialog';
import { TraceReport } from '@/components/trace/TraceReport';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { ROLES } from '@/constants/roles';
import { INVALID_QR_MESSAGE, parseHoneyChainQr } from '@/utils/honeychainQr';

/**
 * The consumer's workspace — a real verification screen, not a notice.
 *
 * A person holding a jar is not a supply-chain operator; what they need is to
 * answer "where did this come from, and what was done to it?" about **one
 * package**. So this screen is exactly that: a box to enter (or paste, or scan)
 * the code from the label, and the same traceability report the public page
 * renders — the same endpoint, the same component, so nothing can drift.
 *
 * The page itself is public: `/trace/{code}` and `/verify/{qrId}` need no
 * account at all (see `TracePage`). This workspace exists for the person who
 * happens to be signed in — it is a convenience, not a gate, and nothing here
 * writes anything: no QR is created, no package is changed, no transaction is
 * recorded. Verification is a read.
 */

/**
 * The code as a person actually has it.
 *
 * People paste the whole link, or scan a label whose link is what the camera
 * reads; the backend answers for a package code (`HC-PKG-2026-000001`) or a QR
 * id (`QR-HC-PKG-2026-000001`). Taking the last path segment of a pasted link
 * turns all four spellings into the same lookup, and it invents nothing: an
 * unparseable value is passed through untouched and the backend decides.
 */
function normaliseCode(raw) {
  const value = (raw || '').trim();
  if (!value) return '';
  if (!value.includes('/') && !value.includes('://')) return value;
  const segments = value.split(/[?#]/)[0].split('/').filter(Boolean);
  return segments.length ? segments[segments.length - 1] : value;
}

/** What to tell a person when the camera could not be started. Manual entry is always offered. */
const CAMERA_MESSAGES = {
  [CAMERA_ERRORS.DENIED]:
    'Camera access was denied. Allow camera permission for this site in your browser settings to scan, or enter the code below.',
  [CAMERA_ERRORS.NO_CAMERA]:
    'No camera was found on this device. Enter the code printed on the label below instead.',
  [CAMERA_ERRORS.IN_USE]:
    'The camera could not be started — another app may be using it. Close it and try again, or enter the code below.',
  // The address, not the browser: browsers only expose a camera to a secure
  // origin (https, or localhost), so on `http://192.168.…` the API is simply
  // absent. Someone opening the app by IP on a phone is the usual case, and the
  // answer is an address they can change — or the printed code.
  [CAMERA_ERRORS.INSECURE_CONTEXT]:
    'This page cannot open the camera here: browsers only allow camera access over a secure connection (https, or localhost), and this page is on a plain http address. Open the app at its https address and scan, or enter the code printed on the label below.',
  [CAMERA_ERRORS.UNSUPPORTED]:
    'This browser cannot open the camera here (camera scanning needs a secure https connection). Enter the code below instead.',
};

export default function ConsumerVerificationPage() {
  const [value, setValue] = useState('');
  //: The code the report is showing — set only when the customer asks for it,
  //: so the screen does not fire a lookup while a code is half-typed.
  const [code, setCode] = useState('');
  const [scannerOpen, setScannerOpen] = useState(false);
  //: A scan that did not produce a verification: an unreadable camera, or a QR
  //: that is not a HoneyChain label. Shown beside the manual form, which stays usable.
  const [scanNotice, setScanNotice] = useState(null);

  const submit = (event) => {
    event.preventDefault();
    setScanNotice(null);
    setCode(normaliseCode(value));
  };

  // A QR was read. The scanner has already released the camera; a HoneyChain code
  // goes into the very same lookup the form uses, anything else is refused.
  const handleScanned = (raw) => {
    setScannerOpen(false);
    const scanned = parseHoneyChainQr(raw);
    if (!scanned) {
      setCode('');
      setScanNotice({ variant: 'danger', message: INVALID_QR_MESSAGE });
      return;
    }
    setScanNotice(null);
    setValue(scanned);
    setCode(normaliseCode(scanned));
  };

  const handleCameraError = (reason) => {
    setScannerOpen(false);
    setScanNotice({
      variant: 'warning',
      message: CAMERA_MESSAGES[reason] || CAMERA_MESSAGES[CAMERA_ERRORS.IN_USE],
    });
  };

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="Consumer workspace"
        description="Scan a jar to read the journey of the honey inside it."
        requiredRoles={[ROLES.CONSUMER]}
      />

      <Card>
        <CardHeader
          title="Verify a product"
          description="Enter the code printed on the label, or paste the link a scan opened."
        />
        <CardBody className="space-y-4">
          {/* One form, defined here rather than as a nested component: a child
              component declared inside render is a new component type on every
              keystroke, which remounts the input and loses the caret after one
              character. */}
          <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <Input
              label="Package code or QR ID"
              name="code"
              placeholder="HC-PKG-2026-000001 or QR-HC-PKG-2026-000001"
              leftIcon={<ScanLine size={15} />}
              hint="Both forms work, and so does the whole link from a scan."
              value={value}
              onChange={(event) => setValue(event.target.value)}
              containerClassName="flex-1"
            />
            <Button type="submit" leftIcon={<Search size={15} />} disabled={!value.trim()}>
              Verify
            </Button>
            <Button
              type="button"
              variant="secondary"
              leftIcon={<Camera size={15} />}
              onClick={() => {
                setScanNotice(null);
                setScannerOpen(true);
              }}
            >
              Scan QR Code
            </Button>
          </form>

          {scanNotice ? (
            <Alert
              variant={scanNotice.variant}
              onDismiss={() => setScanNotice(null)}
            >
              {scanNotice.message}
            </Alert>
          ) : null}

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-sand-200 pt-4">
            <p className="text-xs text-ink-muted">
              <QrCode size={13} className="mr-1 inline" />
              A scan of a HoneyChain label carries the QR ID. The record behind it is read from the
              platform — this screen can show a journey, never change one.
            </p>
            <Link
              to="/how-it-works"
              className="inline-flex items-center gap-1 text-xs text-forest-700"
            >
              How verification works <ExternalLink size={12} />
            </Link>
          </div>
        </CardBody>
      </Card>

      <QrScannerDialog
        open={scannerOpen}
        onClose={() => setScannerOpen(false)}
        onDetected={handleScanned}
        onError={handleCameraError}
      />

      {code ? (
        <TraceReport
          code={code}
          footer={
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setCode('');
                setValue('');
              }}
            >
              Verify another jar
            </Button>
          }
        />
      ) : (
        <Alert variant="info" title="Nothing to verify yet">
          Enter a code above. If you are holding a jar, the code is printed under the QR square — and
          the same page opens without signing in at <code>/trace/&lt;package code&gt;</code>.
        </Alert>
      )}
    </div>
  );
}
