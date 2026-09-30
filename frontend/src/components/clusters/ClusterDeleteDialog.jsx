import { useCallback, useEffect, useMemo, useState } from 'react';
import { Ban, ShieldAlert } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { LoadingState } from '@/components/common/LoadingState';
import { normaliseError } from '@/utils/errors';
import * as clusterService from '@/services/clusterService';

/**
 * Removing a cluster — and the two ways that can end.
 *
 * The counts are read from the API before anything is typed, because they are the
 * answer to the only question this dialog is really asking: *is anything recorded
 * here?* They are counted from the tables, not from the row on the list screen,
 * which may be a page old.
 *
 * **Nothing is recorded under it.** The removal goes ahead. The code has to be
 * typed to confirm, so a click that was not meant cannot remove a register entry.
 *
 * **Records exist.** The API refuses it with the counts, and the dialog turns into
 * the explanation: this honey was harvested, tested and packed, and the cluster is
 * what ties those records together. The officer is offered the operation that
 * actually achieves what they want — *deactivate* — which takes the cluster out of
 * use while every record keeps its place. There is no override here, and no
 * cascading delete: history is not something a confirmation box can discard.
 */
export function ClusterDeleteDialog({
  open,
  cluster = null,
  onClose,
  onDeleted,
  onDeactivate,
  deactivating = false,
}) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);

  const [confirmation, setConfirmation] = useState('');
  const [reason, setReason] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [blocked, setBlocked] = useState(null);

  const load = useCallback(async () => {
    if (!cluster?.id) return;
    setLoading(true);
    setLoadError(null);
    try {
      const record = await clusterService.getCluster(cluster.id);
      setDetail(record);
      // The API's own verdict, so the button offered here matches what the server
      // would answer — the screen never promises a deletion it cannot make.
      if (record?.can_delete === false) {
        setBlocked({ message: record.delete_blocked_reason, counts: record.dependencies });
      }
    } catch (caught) {
      setLoadError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [cluster?.id]);

  useEffect(() => {
    if (!open) return;
    setConfirmation('');
    setReason('');
    setBlocked(null);
    setDetail(null);
    load();
  }, [open, load]);

  const counts = useMemo(() => {
    const source = blocked?.counts || detail?.dependencies || null;
    if (!source || typeof source !== 'object') return [];
    return Object.entries(source).filter(([, value]) => Number(value) > 0);
  }, [blocked, detail]);

  const totalRecords = useMemo(
    () => counts.reduce((sum, [, value]) => sum + Number(value), 0),
    [counts],
  );

  const canConfirm = confirmation.trim() === (cluster?.cluster_code || '').trim();

  async function handleDelete() {
    if (!canConfirm) return;
    setDeleting(true);
    setBlocked(null);
    try {
      const removed = await clusterService.deleteCluster(cluster.id, { reason: reason.trim() });
      onDeleted?.(removed || cluster);
      onClose?.();
    } catch (caught) {
      const error = normaliseError(caught);
      // A refusal is not a failure of the screen: it is the API telling the officer
      // what is there. The counts come back on the error, so they are shown rather
      // than a bare "conflict".
      if (error.status === 409) {
        setBlocked({ message: error.message, counts: error.details || {} });
      } else {
        setLoadError(error);
      }
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={deleting ? () => {} : onClose}
      title={blocked ? 'This cluster cannot be removed' : 'Remove this cluster?'}
      description={
        cluster ? `${cluster.cluster_code} · ${cluster.cluster_name}` : undefined
      }
      size="lg"
      footer={
        blocked ? (
          <>
            <Button variant="secondary" onClick={onClose} disabled={deactivating}>
              Keep it as it is
            </Button>
            {onDeactivate ? (
              <Button variant="secondary" onClick={onDeactivate} loading={deactivating}>
                Deactivate instead
              </Button>
            ) : null}
          </>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose} disabled={deleting}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleDelete}
              loading={deleting}
              disabled={!canConfirm || loading}
              data-testid="confirm-cluster-delete"
            >
              Remove cluster
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        {loading ? <LoadingState message="Checking what is recorded under this cluster…" /> : null}
        {loadError ? <Alert variant="danger">{loadError.message}</Alert> : null}

        {blocked ? (
          <Alert variant="warning" title="Records are associated with this cluster">
            <span className="flex flex-col gap-2">
              <span>{blocked.message}</span>
              {counts.length ? (
                <span className="flex flex-wrap gap-1.5">
                  {counts.map(([label, value]) => (
                    <Badge key={label} variant="neutral" size="sm">
                      {label}: {value}
                    </Badge>
                  ))}
                </span>
              ) : null}
              <span className="flex items-start gap-1.5 text-xs">
                <Ban size={13} className="mt-0.5 flex-none" aria-hidden="true" />
                Nothing has been deleted, and nothing was going to be: batches, harvests and
                packages are never removed to make a register entry disappear.
              </span>
            </span>
          </Alert>
        ) : null}

        {!loading && !blocked ? (
          <>
            <div className="rounded-lg border border-sand-300 bg-sand-50 px-4 py-3 text-sm">
              <p className="text-ink-soft">
                {totalRecords === 0 ? (
                  <>
                    Nothing is recorded under this cluster — no beekeepers, hives, collections,
                    batches, tests, runs or packages. It can be removed.
                  </>
                ) : (
                  <>
                    <span className="font-medium text-ink">{totalRecords}</span> record(s) are
                    recorded under this cluster. The server checks again before removing anything.
                  </>
                )}
              </p>
            </div>

            <Input
              label={`Type ${cluster?.cluster_code || 'the cluster code'} to confirm`}
              name="confirmation"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder={cluster?.cluster_code || ''}
              hint="Removing a cluster from the register is deliberate. Typing the code is how it stays deliberate."
              autoComplete="off"
              data-testid="cluster-delete-confirmation"
            />

            <Input
              label="Reason (optional)"
              name="reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Created in error; replaced by KVIC-GNT-007"
              hint="Recorded in the audit log with the cluster's code, name and district."
            />

            <Alert variant="info">
              <span className="flex items-start gap-2">
                <ShieldAlert size={15} className="mt-0.5 flex-none" aria-hidden="true" />
                <span>
                  If any record is attached, the removal is refused with the counts and this dialog
                  offers deactivation instead. Nothing is ever cascade-deleted.
                </span>
              </span>
            </Alert>
          </>
        ) : null}
      </div>
    </Modal>
  );
}

export default ClusterDeleteDialog;
