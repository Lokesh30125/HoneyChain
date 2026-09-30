import { ChevronRight, Home } from 'lucide-react';
import { Link } from 'react-router-dom';

/**
 * Breadcrumb trail. Items accept an optional `to`; the last item is the current
 * page and is marked with `aria-current`.
 */
export function Breadcrumb({ items = [], className = '' }) {
  if (!items.length) return null;

  return (
    <nav aria-label="Breadcrumb" className={className}>
      <ol className="flex flex-wrap items-center gap-1.5 text-sm text-ink-muted">
        <li>
          <Link
            to="/dashboard"
            className="flex items-center gap-1 rounded transition-colors hover:text-forest-700"
          >
            <Home size={14} aria-hidden="true" />
            <span className="sr-only sm:not-sr-only">Dashboard</span>
          </Link>
        </li>

        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className="flex items-center gap-1.5">
              <ChevronRight size={14} className="text-sand-400" aria-hidden="true" />
              {item.to && !isLast ? (
                <Link to={item.to} className="rounded transition-colors hover:text-forest-700">
                  {item.label}
                </Link>
              ) : (
                <span aria-current={isLast ? 'page' : undefined} className="text-ink-soft">
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default Breadcrumb;
