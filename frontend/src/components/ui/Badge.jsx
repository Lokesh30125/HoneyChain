/**
 * Small status pill.
 *
 * Status colours keep their conventional meaning platform-wide, so a "warning"
 * reads the same on every screen a beekeeper, lab or KVIC officer visits.
 */

const VARIANTS = {
  neutral: 'bg-sand-100 text-ink-soft border-sand-300',
  success: 'bg-status-success-bg text-status-success border-status-success/25',
  warning: 'bg-status-warning-bg text-status-warning border-status-warning/25',
  danger: 'bg-status-danger-bg text-status-danger border-status-danger/25',
  info: 'bg-status-info-bg text-status-info border-status-info/25',
  pending: 'bg-status-pending-bg text-status-pending border-status-pending/25',
  honey: 'bg-honey-50 text-honey-800 border-honey-300',
  forest: 'bg-forest-50 text-forest-700 border-forest-200',
};

const SIZES = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-xs',
  lg: 'px-3 py-1 text-sm',
};

export function Badge({ children, variant = 'neutral', size = 'md', icon = null, className = '' }) {
  return (
    <span
      className={[
        'inline-flex items-center gap-1 rounded-full border font-medium whitespace-nowrap',
        VARIANTS[variant] || VARIANTS.neutral,
        SIZES[size] || SIZES.md,
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {icon}
      {children}
    </span>
  );
}

export default Badge;
