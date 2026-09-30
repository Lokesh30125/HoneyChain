import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { Logo } from '@/components/common/Logo';
import { TraceReport } from '@/components/trace/TraceReport';

/**
 * The customer's page — what a QR code resolves to.
 *
 * It is deliberately not part of the application shell: the person reading it
 * holds a jar, not an account. Everything on it comes from
 * `GET /trace/{package_code}`, whose fields are an allow-list assembled by the
 * backend, so this page can only ever show what a stranger may see.
 *
 * Two routes resolve here — `/trace/:packageCode` (what the label's link
 * carries) and `/verify/:code` (the QR id printed beside the code). The backend
 * resolves either form to the same package, so the page does not have to know
 * which one it was opened with. The report itself lives in `TraceReport`, which
 * the signed-in consumer's workspace renders too — one record, two doors.
 */
export default function TracePage() {
  const params = useParams();
  const packageCode = params.packageCode || params.code || '';

  return (
    <div className="min-h-screen bg-sand-50">
      <header className="border-b border-sand-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-4">
          <Link to="/" className="flex items-center gap-2">
            <Logo size={28} />
          </Link>
          <span className="text-xs text-ink-muted">Traceability of a single package</span>
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-6 px-4 py-8">
        <TraceReport
          code={packageCode}
          footer={
            <Link className="inline-flex items-center gap-1 text-sm text-forest-700" to="/">
              <ArrowLeft size={15} /> About HoneyChain
            </Link>
          }
        />
      </main>
    </div>
  );
}
