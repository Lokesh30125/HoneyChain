import { Inbox } from 'lucide-react';

/**
 * Shown when a request succeeded but there is nothing to display yet —
 * "no hives registered", "no batches in this cluster", …
 */
export function EmptyState({
  title = 'Nothing here yet',
  description,
  icon = null,
  action = null,
  className = '',
}) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 px-6 py-12 text-center ${className}`}>
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-sand-100 text-ink-muted">
        {icon || <Inbox size={22} aria-hidden="true" />}
      </span>
      <div>
        <p className="font-medium text-ink">{title}</p>
        {description ? <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export default EmptyState;
