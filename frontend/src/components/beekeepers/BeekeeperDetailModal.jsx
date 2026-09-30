import { Building2, History, MapPin, User } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { VerificationBadge, VERIFICATION_DESCRIPTIONS } from '@/components/beekeepers/VerificationBadge';
import { LoadingState } from '@/components/common/LoadingState';
import { ErrorState } from '@/components/common/ErrorState';
import { canVerifyBeekeepers } from '@/constants/roles';
import { formatDateTime } from '@/utils/format';
import { useAuth } from '@/hooks/useAuth';

function Field({ label, value }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{value || '—'}</dd>
    </div>
  );
}

/**
 * Beekeeper detail: the record, its owner, its cluster and the append-only
 * verification history.
 *
 * Verification is offered only to roles that hold the permission, so a KVIC
 * officer sees the action and a beekeeper never does.
 */
export function BeekeeperDetailModal({ open, detail, loading, error, onRetry, onClose, onVerify }) {
  const { role } = useAuth();
  const record = detail?.beekeeper;
  const history = detail?.verification_history || [];
  const allowedNext = detail?.allowed_next_statuses || [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={record ? record.beekeeper_code : 'Beekeeper'}
      description={record ? record.user.name : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          {record && canVerifyBeekeepers(role) && allowedNext.length ? (
            <Button onClick={() => onVerify?.(record, allowedNext)}>Record decision</Button>
          ) : null}
        </>
      }
    >
      {loading ? <LoadingState message="Loading beekeeper…" /> : null}
      {error ? <ErrorState error={error} onRetry={onRetry} /> : null}

      {!loading && !error && record ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <VerificationBadge status={record.verification_status} />
            <p className="text-sm text-ink-muted">
              {VERIFICATION_DESCRIPTIONS[record.verification_status] || ''}
            </p>
          </div>

          <section>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
              <MapPin size={15} aria-hidden="true" /> Apiary
            </h3>
            <dl className="mt-2 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Village" value={record.village} />
              <Field label="Mandal" value={record.mandal} />
              <Field label="District" value={record.district} />
              <Field label="State" value={record.state} />
              <Field label="PIN code" value={record.pincode} />
              <Field
                label="Bee species"
                value={record.bee_species}
              />
              <Field label="Experience" value={record.experience_years != null ? `${record.experience_years} years` : null} />
              <Field label="Hives" value={record.number_of_hives} />
              <Field label="Registered" value={record.registration_date} />
            </dl>
          </section>

          <section>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
              <User size={15} aria-hidden="true" /> Account
            </h3>
            <dl className="mt-2 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Name" value={record.user.name} />
              <Field label="Email" value={record.user.email} />
              <Field label="Phone" value={record.user.phone} />
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-ink-muted">Status</dt>
                <dd className="mt-0.5">
                  <Badge variant={record.user.is_active ? 'success' : 'neutral'} size="sm">
                    {record.user.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </dd>
              </div>
            </dl>
          </section>

          <section>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
              <Building2 size={15} aria-hidden="true" /> Cluster
            </h3>
            <p className="mt-2 text-sm text-ink-soft">
              {record.cluster
                ? `${record.cluster.cluster_name} (${record.cluster.cluster_code})${
                    record.cluster.is_active ? '' : ' — inactive'
                  }`
                : 'Not assigned to a cluster yet.'}
            </p>
          </section>

          <section>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
              <History size={15} aria-hidden="true" /> Verification history
            </h3>
            {history.length ? (
              <ol className="mt-2 space-y-2">
                {history.map((entry) => (
                  <li key={entry.id} className="rounded-lg border border-sand-200 bg-sand-100/40 px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <VerificationBadge status={entry.new_status} size="sm" />
                      <span className="text-xs text-ink-muted">
                        {entry.previous_status ? `from ${entry.previous_status}` : 'registration'} ·{' '}
                        {formatDateTime(entry.changed_at)}
                      </span>
                    </div>
                    {entry.remarks ? (
                      <p className="mt-1.5 text-sm text-ink-soft">{entry.remarks}</p>
                    ) : null}
                    <p className="mt-1 text-xs text-ink-muted">
                      {entry.changed_by_name || 'System'}
                      {entry.changed_by_role ? ` · ${entry.changed_by_role.replace('_', ' ')}` : ''}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="mt-2 text-sm text-ink-muted">No decisions recorded yet.</p>
            )}
          </section>
        </div>
      ) : null}
    </Modal>
  );
}

export default BeekeeperDetailModal;
