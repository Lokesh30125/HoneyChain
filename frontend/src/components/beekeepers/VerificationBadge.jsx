import { Badge } from '@/components/ui/Badge';

/**
 * Verification state as a badge.
 *
 * The wording is deliberate: "Verified" means an officer confirmed the details,
 * not that the honey is authentic — the platform reports verification of a
 * beekeeper's registration, and never claims more than that.
 */
const VERIFICATION_MAP = {
  PENDING: { label: 'Pending review', variant: 'pending' },
  UNDER_REVIEW: { label: 'Under review', variant: 'info' },
  VERIFIED: { label: 'Verified', variant: 'success' },
  REJECTED: { label: 'Rejected', variant: 'danger' },
  SUSPENDED: { label: 'Suspended', variant: 'warning' },
};

export function VerificationBadge({ status, size = 'md', className = '' }) {
  const key = String(status || '').toUpperCase();
  const entry = VERIFICATION_MAP[key] || { label: status || 'Unknown', variant: 'neutral' };

  return (
    <Badge variant={entry.variant} size={size} className={className}>
      {entry.label}
    </Badge>
  );
}

/** Description shown next to the badge in detail views. */
export const VERIFICATION_DESCRIPTIONS = {
  PENDING: 'Registration received and awaiting review.',
  UNDER_REVIEW: 'An officer is reviewing the submitted details.',
  VERIFIED: 'Details confirmed by a KVIC officer or administrator.',
  REJECTED: 'Registration was reviewed and not approved.',
  SUSPENDED: 'Verification withdrawn pending resolution of an issue.',
};

export function verificationLabel(status) {
  return (VERIFICATION_MAP[String(status || '').toUpperCase()] || {}).label || status || 'Unknown';
}

export default VerificationBadge;
