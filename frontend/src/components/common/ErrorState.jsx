import { AlertTriangle, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { normaliseError } from '@/utils/errors';

/**
 * Standard error presentation.
 *
 * Accepts anything thrown by the service layer and normalises it, so callers
 * can simply do `<ErrorState error={error} onRetry={refetch} />`.
 */
export function ErrorState({
  error,
  title = 'We could not load this',
  onRetry = null,
  retryLabel = 'Try again',
  className = '',
}) {
  const normalised = error ? normaliseError(error) : null;
  const message =
    normalised?.message ||
    'Something went wrong while talking to the HoneyChain API. Please try again.';

  return (
    <div
      role="alert"
      className={`flex flex-col items-center justify-center gap-3 px-6 py-12 text-center ${className}`}
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-status-danger-bg text-status-danger">
        <AlertTriangle size={22} aria-hidden="true" />
      </span>
      <div>
        <p className="font-medium text-ink">{title}</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-ink-muted">{message}</p>
        {normalised?.code ? (
          <p className="mt-2 font-mono text-xs text-ink-muted">
            {normalised.code}
            {normalised.status ? ` · HTTP ${normalised.status}` : ''}
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" leftIcon={<RefreshCw size={15} />} onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

export default ErrorState;
