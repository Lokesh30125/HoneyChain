import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';

/** Inline message block for form-level and page-level feedback. */

const VARIANTS = {
  info: {
    wrapper: 'border-status-info/25 bg-status-info-bg text-status-info',
    Icon: Info,
  },
  success: {
    wrapper: 'border-status-success/25 bg-status-success-bg text-status-success',
    Icon: CheckCircle2,
  },
  warning: {
    wrapper: 'border-status-warning/30 bg-status-warning-bg text-status-warning',
    Icon: TriangleAlert,
  },
  danger: {
    wrapper: 'border-status-danger/25 bg-status-danger-bg text-status-danger',
    Icon: AlertCircle,
  },
};

export function Alert({ variant = 'info', title, children, onDismiss, className = '' }) {
  const { wrapper, Icon } = VARIANTS[variant] || VARIANTS.info;

  return (
    <div
      role={variant === 'danger' ? 'alert' : 'status'}
      className={['flex items-start gap-3 rounded-lg border px-4 py-3 text-sm', wrapper, className]
        .filter(Boolean)
        .join(' ')}
    >
      <Icon size={18} className="mt-0.5 flex-none" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className={title ? 'mt-0.5' : ''}>{children}</div> : null}
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="flex-none rounded p-0.5 transition-opacity hover:opacity-70"
          aria-label="Dismiss message"
        >
          <X size={16} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}

export default Alert;
