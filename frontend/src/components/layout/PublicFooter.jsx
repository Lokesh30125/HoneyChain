import { Link } from 'react-router-dom';

import { Logo } from '@/components/common/Logo';
import { StatusBadge } from '@/components/common/StatusBadge';
import { FOOTER_SECTIONS } from '@/constants/navigation';
import { useApiHealth } from '@/hooks/useApiHealth';

/**
 * Public site footer.
 *
 * Also carries the live API status indicator, which is the quickest way for a
 * developer or evaluator to confirm that the frontend is talking to the
 * backend (`GET /api/v1/health`).
 */
export function PublicFooter() {
  const { status, service, checkedAt } = useApiHealth();
  const year = new Date().getFullYear();

  return (
    <footer className="mt-16 border-t border-forest-800/20 bg-forest-900 text-sand-200">
      <div className="hc-container grid gap-10 py-12 lg:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <Logo inverted showTagline />
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-sand-300">
            HoneyChain connects apiaries, collection centres, laboratories, packagers and
            retailers on one traceability record — so every jar can be verified back to the
            hive it came from.
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-sand-300">API status</span>
            <StatusBadge status={status} size="sm" />
            {service ? <span className="text-sand-400">{service}</span> : null}
            {status === 'offline' ? (
              <span className="text-sand-400">
                Start the backend and reload, or check the Vite proxy target.
              </span>
            ) : null}
          </div>
        </div>

        {FOOTER_SECTIONS.map((section) => (
          <div key={section.title}>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-white">
              {section.title}
            </h2>
            <ul className="mt-4 space-y-2.5 text-sm">
              {section.links.map((link) => (
                <li key={link.label}>
                  <Link
                    to={link.to}
                    className="text-sand-300 transition-colors hover:text-honey-300"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-t border-white/10">
        <div className="hc-container flex flex-col gap-2 py-5 text-xs text-sand-400 sm:flex-row sm:items-center sm:justify-between">
          <p>© {year} HoneyChain. Prototype for Smart India Hackathon 2026 (Problem Statement 26021).</p>
          <p>
            Traceability, monitoring and advisory information only — not a substitute for
            laboratory testing or regulatory certification.
            {checkedAt ? ` API checked ${checkedAt.toLocaleTimeString()}.` : ''}
          </p>
        </div>
      </div>
    </footer>
  );
}

export default PublicFooter;
