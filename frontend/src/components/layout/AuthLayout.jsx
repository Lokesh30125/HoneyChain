import { Link } from 'react-router-dom';
import { ShieldCheck } from 'lucide-react';

import { Logo } from '@/components/common/Logo';

/**
 * Split layout for the sign-in and registration screens: the form on one side,
 * a short statement of what the platform does on the other. On mobile the panel
 * collapses so the form is immediately visible.
 */
export function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_1.05fr]">
      {/* Form column */}
      <div className="flex flex-col justify-center bg-sand-50 px-4 py-10 sm:px-8">
        <div className="mx-auto w-full max-w-md">
          <Logo showTagline />
          <div className="mt-8">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
            {subtitle ? <p className="mt-2 text-sm text-ink-soft">{subtitle}</p> : null}
          </div>
          <div className="mt-7">{children}</div>
          {footer ? <div className="mt-6 text-sm text-ink-soft">{footer}</div> : null}
          <p className="mt-10 text-xs text-ink-muted">
            <Link to="/" className="hc-link">
              ← Back to the public site
            </Link>
          </p>
        </div>
      </div>

      {/* Context column (hidden on small screens) */}
      <aside className="hidden flex-col justify-center bg-forest-900 px-10 py-14 text-sand-200 lg:flex">
        <div className="max-w-lg">
          <span className="inline-flex items-center gap-2 rounded-full border border-honey-500/40 bg-honey-500/10 px-3 py-1 text-xs font-medium text-honey-200">
            <ShieldCheck size={14} aria-hidden="true" />
            Traceability from hive to consumer
          </span>
          <h2 className="mt-6 text-2xl font-semibold tracking-tight text-white">
            One account, the workspace your role needs
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-sand-300">
            Beekeepers record hives and harvests. Collection centres, processors and packagers add
            their handling events. Laboratories attach test results. KVIC sees cluster-level
            summaries. Consumers verify a jar before buying.
          </p>

          <ul className="mt-8 space-y-4 text-sm">
            {[
              'Role-based access enforced by the API on every request.',
              'Quality results stay attached to the batch they describe.',
              'Records are anchored so a past entry cannot be silently changed.',
              'Designed to work on the phones beekeepers already carry.',
            ].map((line) => (
              <li key={line} className="flex gap-3">
                <span className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full bg-honey-400" aria-hidden="true" />
                <span className="text-sand-300">{line}</span>
              </li>
            ))}
          </ul>

          <p className="mt-10 text-xs text-sand-400">
            Beekeeper, KVIC, hive/IoT monitoring, batch traceability and blockchain anchoring are
            live today. AI assistance is released in a later phase.
          </p>
        </div>
      </aside>
    </div>
  );
}

export default AuthLayout;
