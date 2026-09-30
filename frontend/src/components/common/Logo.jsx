import { Link } from 'react-router-dom';

/**
 * HoneyChain wordmark.
 *
 * The hexagon is the hive cell; the inner bar suggests a chain link and a
 * ledger entry — trust and immutability rather than cryptocurrency imagery.
 */
export function LogoMark({ size = 32, className = '' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      role="img"
      aria-label="HoneyChain"
    >
      <path
        d="M32 6 53 18v28L32 58 11 46V18z"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinejoin="round"
        opacity="0.85"
      />
      <path d="M32 20c6.1 0 11 4.4 11 9.8s-4.9 9.8-11 9.8-11-4.4-11-9.8S25.9 20 32 20z" fill="currentColor" />
      <path d="M25 45h14" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ to = '/', inverted = false, size = 32, showTagline = false, className = '' }) {
  return (
    <Link
      to={to}
      className={`inline-flex items-center gap-2.5 rounded-lg ${className}`}
      aria-label="HoneyChain home"
    >
      <span className={inverted ? 'text-honey-400' : 'text-honey-500'}>
        <LogoMark size={size} />
      </span>
      <span className="leading-tight">
        <span
          className={`block text-lg font-semibold tracking-tight ${inverted ? 'text-white' : 'text-forest-800'}`}
        >
          HoneyChain
        </span>
        {showTagline ? (
          <span className={`block text-xs ${inverted ? 'text-sand-200' : 'text-ink-muted'}`}>
            Traceable honey &amp; smart beekeeping
          </span>
        ) : null}
      </span>
    </Link>
  );
}

export default Logo;
