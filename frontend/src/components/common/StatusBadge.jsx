import { Badge } from '@/components/ui/Badge';

/**
 * Maps a domain status onto a badge.
 *
 * Phase 1 uses it for account and API states. Later phases register the supply
 * chain vocabulary here (PENDING_VERIFICATION, ANCHORED, IN_TRANSIT, PASSED,
 * REJECTED, …) in one place rather than scattering colour logic across tables.
 */

const STATUS_MAP = {
  ACTIVE: { label: 'Active', variant: 'success' },
  INACTIVE: { label: 'Inactive', variant: 'neutral' },
  ONLINE: { label: 'Online', variant: 'success' },
  OFFLINE: { label: 'Offline', variant: 'danger' },
  CHECKING: { label: 'Checking…', variant: 'neutral' },
  DEGRADED: { label: 'Degraded', variant: 'warning' },
  OK: { label: 'Operational', variant: 'success' },
  PLANNED: { label: 'Planned', variant: 'pending' },
  AVAILABLE: { label: 'Available', variant: 'success' },
  NOT_CONFIGURED: { label: 'Not configured', variant: 'neutral' },
  CONFIGURED: { label: 'Configured', variant: 'info' },
};

export function StatusBadge({ status, size = 'md', className = '' }) {
  const key = String(status || '').toUpperCase();
  const entry = STATUS_MAP[key] || { label: status || 'Unknown', variant: 'neutral' };

  return (
    <Badge variant={entry.variant} size={size} className={className}>
      {entry.label}
    </Badge>
  );
}

export default StatusBadge;
