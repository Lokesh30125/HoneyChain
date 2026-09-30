import { useCallback, useEffect, useMemo, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { ClusterBatchPicker, placementOf } from '@/components/clusters/ClusterBatchPicker';
import { unitLabel } from '@/constants/collection';
import { normaliseError } from '@/utils/errors';
import { clusterSchema } from '@/utils/validation';
import { useToast } from '@/hooks/useToast';
import * as batchService from '@/services/batchService';
import * as clusterService from '@/services/clusterService';

const EMPTY = {
  clusterName: '',
  district: '',
  state: '',
  description: '',
  coordinatorName: '',
  coordinatorPhone: '',
};

//: How many of a cluster's held batches the edit form loads to work from. The
//: API caps a page at 100; a cluster with more than that is reported rather than
//: silently truncated, because the form must not claim to represent them all.
const HELD_PAGE_SIZE = 100;

function toPayload(values) {
  return {
    cluster_name: values.clusterName,
    district: values.district,
    state: values.state,
    description: values.description || null,
    coordinator_name: values.coordinatorName || null,
    coordinator_phone: values.coordinatorPhone || null,
  };
}

/**
 * Create or edit a KVIC cluster, including the **honey batches it holds**.
 *
 * The batch section is the same picker the cluster's own page uses: it lists real
 * batches (code, harvest, beekeeper, quantity, stage) read from the batch
 * endpoints, and choosing one writes the cluster link on that batch. Nothing is
 * typed in, nothing is copied, and a batch that already belongs to another cluster
 * is flagged and refused until the officer confirms the move explicitly.
 *
 * On create the whole thing is one request (`batch_ids` on the cluster payload),
 * so a cluster is never created empty because half the write failed. On edit the
 * fields are saved first and then the batch changes are applied one by one — each
 * answer is reported, including the ones that fail, which is why "saved" and
 * "batches applied" are announced separately rather than blended together.
 *
 * The cluster code is not an input: the backend generates `KVIC-<DIST>-001` so
 * codes stay unique and sequential. It is shown read-only when editing, because
 * it is immutable and may already be printed on records.
 */
export function ClusterFormModal({ open, cluster = null, onClose, onSaved }) {
  const toast = useToast();
  const [formError, setFormError] = useState(null);
  const isEdit = Boolean(cluster);

  //: The batches chosen on this form (batch ids).
  const [picked, setPicked] = useState([]);
  //: The batches the cluster holds *now* — read from the cluster's own endpoint
  //: when the edit form opens, so the form starts from what is stored.
  const [held, setHeld] = useState(null);
  const [heldError, setHeldError] = useState(null);
  const [loadingHeld, setLoadingHeld] = useState(false);

  //: The batch rows the picker has shown and the officer has chosen. Used to
  //: decide *before* saving whether a choice needs an explicit move; the server
  //: still has the last word when the request is sent.
  const [pickedRows, setPickedRows] = useState([]);

  const [confirmMove, setConfirmMove] = useState(false);
  const [confirmRemoval, setConfirmRemoval] = useState(false);
  const [pendingValues, setPendingValues] = useState(null);
  const [progress, setProgress] = useState(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(clusterSchema), defaultValues: EMPTY });

  const loadHeld = useCallback(async () => {
    if (!cluster?.id) {
      setHeld([]);
      setHeldError(null);
      return;
    }
    setLoadingHeld(true);
    setHeldError(null);
    try {
      const { batches, meta } = await batchService.getClusterBatches(cluster.id, {
        pageSize: HELD_PAGE_SIZE,
      });
      setHeld(batches);
      // The form opens with the cluster's current batches ticked: adding is then
      // an extra tick and removing is an untick, and the difference between the
      // two is exactly what gets written.
      setPicked(batches.map((row) => row.id));
      const total = meta?.total_items;
      if (typeof total === 'number' && total > batches.length) {
        setHeldError(
          new Error(
            `This cluster holds ${total} batches; the form loaded the first ${batches.length}. ` +
              'Add or remove the rest from the cluster page, where the list is paged.',
          ),
        );
      }
    } catch (caught) {
      setHeld(null);
      setHeldError(normaliseError(caught));
    } finally {
      setLoadingHeld(false);
    }
  }, [cluster?.id]);

  useEffect(() => {
    if (!open) return;
    reset(
      cluster
        ? {
            clusterName: cluster.cluster_name || '',
            district: cluster.district || '',
            state: cluster.state || '',
            description: cluster.description || '',
            coordinatorName: cluster.coordinator_name || '',
            coordinatorPhone: cluster.coordinator_phone || '',
          }
        : EMPTY,
    );
    setFormError(null);
    setProgress(null);
    setConfirmMove(false);
    setConfirmRemoval(false);
    setPendingValues(null);
    setPickedRows([]);
    if (cluster) {
      setHeld(null);
      setPicked([]);
      loadHeld();
    } else {
      setHeld([]);
      setPicked([]);
      setHeldError(null);
    }
  }, [open, cluster, reset, loadHeld]);

  //: Batches the cluster holds now, keyed for quick lookup.
  const heldIds = useMemo(() => (held || []).map((row) => row.id), [held]);
  //: Chosen but not currently held — these will be placed on save.
  const addedIds = useMemo(() => picked.filter((id) => !heldIds.includes(id)), [picked, heldIds]);
  //: Held but no longer chosen — these are removed from the cluster on save.
  const removedRows = useMemo(
    () => (held || []).filter((row) => !picked.includes(row.id)),
    [held, picked],
  );

  const cacheRows = useCallback((rows) => {
    if (!rows?.length) return;
    setPickedRows((previous) => {
      const seen = new Set(previous.map((row) => row.id));
      const fresh = rows.filter((row) => !seen.has(row.id));
      return fresh.length ? [...previous, ...fresh] : previous;
    });
  }, []);

  const onToggle = (batch) => {
    setPicked((previous) =>
      previous.includes(batch.id)
        ? previous.filter((id) => id !== batch.id)
        : [...previous, batch.id],
    );
  };

  const onSelectMany = (ids) => {
    setPicked((previous) => Array.from(new Set([...previous, ...ids])));
  };

  /**
   * Which of the chosen batches need an explicit move: they belong to another
   * cluster right now. Read from the server's own `requires_confirmation` where it
   * answered one, and from the batch's own cluster fields otherwise.
   */
  const movingIds = useMemo(() => {
    if (!addedIds.length) return [];
    const byId = new Map([...(held || []), ...pickedRows].map((row) => [row.id, row]));
    return addedIds.filter((id) => {
      const row = byId.get(id);
      if (!row) return false;
      return row.requires_confirmation ?? placementOf(row, cluster?.id).needsConfirmation;
    });
  }, [addedIds, held, pickedRows, cluster?.id]);

  const submit = async (values) => {
    setFormError(null);
    setProgress(null);

    // 1) Create: one request, cluster and batches together.
    if (!isEdit) {
      try {
        const saved = await clusterService.createCluster({
          ...toPayload(values),
          batch_ids: picked,
          reassign: movingIds.length > 0,
        });
        toast.success(
          `Cluster ${saved.cluster_code} created`,
          picked.length
            ? `${saved.cluster_name} · ${saved.batch_count} batch${saved.batch_count === 1 ? '' : 'es'} placed`
            : saved.cluster_name,
        );
        finish(saved);
      } catch (caught) {
        setFormError(normaliseError(caught));
      }
      return;
    }

    // 2) Edit: the fields first, then the batch changes. Each outcome is told
    //    apart, so a saved cluster is never reported as unsaved.
    let saved;
    try {
      saved = await clusterService.updateCluster(cluster.id, toPayload(values));
    } catch (caught) {
      setFormError(normaliseError(caught));
      return;
    }

    const problems = [];
    if (addedIds.length) {
      try {
        await clusterService.assignBatches(cluster.id, addedIds, {
          reassign: movingIds.length > 0,
        });
      } catch (caught) {
        problems.push(`batches were not placed: ${normaliseError(caught).message}`);
      }
    }
    for (const row of removedRows) {
      try {
        await clusterService.detachBatch(cluster.id, row.id);
      } catch (caught) {
        problems.push(`${row.batch_code} was not removed: ${normaliseError(caught).message}`);
      }
    }

    if (problems.length) {
      // The cluster fields *were* saved. Saying otherwise would send the officer
      // back to re-save a record that already has these values.
      setProgress({
        variant: 'warning',
        title: `Cluster ${saved.cluster_code} was saved, but part of the batch change did not apply`,
        message: problems.join(' · '),
      });
      toast.error(`Cluster ${saved.cluster_code} saved`, problems.join(' · '));
      return;
    }

    toast.success(
      `Cluster ${saved.cluster_code} updated`,
      [
        addedIds.length ? `${addedIds.length} batch(es) placed` : null,
        removedRows.length ? `${removedRows.length} batch(es) removed` : null,
      ]
        .filter(Boolean)
        .join(' · ') || saved.cluster_name,
    );
    finish(saved);
  };

  const finish = (saved) => {
    try {
      onSaved?.(saved);
    } catch {
      // Swallowed on purpose: the caller reports it where the list is.
    }
    onClose?.();
  };

  //: What the primary button does: submit the fields, after confirming a move
  //: or a removal when one is queued.
  const onSubmit = handleSubmit(async (values) => {
    setPendingValues(values);
    if (movingIds.length > 0) {
      setConfirmMove(true);
      return;
    }
    if (isEdit && removedRows.length > 0) {
      setConfirmRemoval(true);
      return;
    }
    await submit(values);
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? 'Edit cluster' : 'Create a KVIC cluster'}
      description={
        isEdit
          ? `${cluster.cluster_code} · the code cannot be changed`
          : 'The cluster code is generated automatically from the district.'
      }
      size="xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="cluster-form"
            loading={isSubmitting}
            data-testid="submit-cluster-form"
          >
            {isEdit ? 'Save changes' : 'Create cluster'}
          </Button>
        </>
      }
    >
      <form id="cluster-form" onSubmit={onSubmit} className="space-y-5" noValidate>
        {formError ? <Alert variant="danger">{formError.message}</Alert> : null}
        {progress ? (
          <Alert variant={progress.variant} title={progress.title}>
            {progress.message}
          </Alert>
        ) : null}

        <Input
          label="Cluster name"
          name="clusterName"
          required
          error={errors.clusterName?.message}
          {...register('clusterName')}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="District"
            name="district"
            required
            error={errors.district?.message}
            {...register('district')}
          />
          <Input
            label="State"
            name="state"
            required
            error={errors.state?.message}
            {...register('state')}
          />
          <Input
            label="Coordinator name"
            name="coordinatorName"
            error={errors.coordinatorName?.message}
            {...register('coordinatorName')}
          />
          <Input
            label="Coordinator phone"
            name="coordinatorPhone"
            error={errors.coordinatorPhone?.message}
            {...register('coordinatorPhone')}
          />
        </div>

        <Input
          label="Description"
          name="description"
          error={errors.description?.message}
          hint="Optional. Anything that helps identify the cluster later."
          {...register('description')}
        />

        <section className="space-y-3 border-t border-sand-200 pt-4" aria-label="Honey batches">
          <header className="space-y-1">
            <h3 className="text-sm font-semibold text-ink">Honey batches in this cluster</h3>
            <p className="text-sm text-ink-soft">
              Batches are produced by completing a harvest, so they are selected here rather than
              created. Hives are not assigned directly: a batch already carries its collection, its
              beekeeper and the hives behind it.
            </p>
          </header>

          {isEdit ? (
            loadingHeld ? (
              <p className="text-sm text-ink-muted">Loading the batches this cluster holds…</p>
            ) : heldError ? (
              <Alert variant="warning" title="Unable to load the batches this cluster holds">
                {heldError.message} Saving now changes the cluster&apos;s fields only — no batch is
                added or removed, because this form does not know what it holds.
              </Alert>
            ) : (
              <div className="space-y-2">
                <p className="text-xs uppercase tracking-wide text-ink-muted">
                  Currently held ({heldIds.length})
                </p>
                {heldIds.length === 0 ? (
                  <p className="text-sm text-ink-muted">
                    No batches in this cluster yet. Choose one below to place it here.
                  </p>
                ) : (
                  <ul className="flex flex-wrap gap-2">
                    {(held || []).map((row) => {
                      const stillHeld = picked.includes(row.id);
                      return (
                        <li key={row.id}>
                          <Badge variant={stillHeld ? 'forest' : 'danger'} size="sm">
                            {row.batch_code} · {row.beekeeper_code || 'beekeeper not recorded'} ·{' '}
                            {Number(row.quantity ?? 0).toLocaleString(undefined, {
                              maximumFractionDigits: 3,
                            })}{' '}
                            {unitLabel(row.unit)}
                            {stillHeld ? '' : ' → will be removed'}
                          </Badge>
                        </li>
                      );
                    })}
                  </ul>
                )}
                {removedRows.length ? (
                  <p className="text-xs text-status-warning">
                    Saving will remove {removedRows.length} batch(es) from this cluster. The batches
                    themselves are untouched — you will be asked to confirm.
                  </p>
                ) : null}
              </div>
            )
          ) : (
            <p className="text-sm text-ink-muted">
              Pick the batches to place in the new cluster. They are written together with the
              cluster, so the cluster is never created half-populated.
            </p>
          )}

          <ClusterBatchPicker
            clusterId={cluster?.id || null}
            selectedIds={picked}
            onToggle={(batch) => {
              cacheRows([batch]);
              onToggle(batch);
            }}
            onSelectMany={(ids, rows) => {
              // The rows the picker offered are cached so the confirmation step
              // can name a batch that has to be moved rather than guess at it.
              cacheRows(rows || []);
              onSelectMany(ids);
            }}
          />
        </section>
      </form>

      <ConfirmDialog
        open={confirmMove}
        title="Some of these batches belong to another cluster"
        description="Confirming moves them: the change is written on those batches themselves (and on their harvests), so the honey stops being reported under the previous cluster. The batches, beekeepers and hives are otherwise untouched."
        confirmLabel="Move and save"
        loading={isSubmitting}
        onConfirm={() => {
          setConfirmMove(false);
          // A removal queued behind the move still has to be confirmed on its own.
          if (isEdit && removedRows.length > 0) {
            setConfirmRemoval(true);
            return;
          }
          if (pendingValues) submit(pendingValues);
        }}
        onCancel={() => setConfirmMove(false)}
      />

      <ConfirmDialog
        open={confirmRemoval}
        title={`Remove ${removedRows.length} batch(es) from this cluster?`}
        description={`${removedRows
          .map((row) => row.batch_code)
          .join(', ')} will no longer be reported under ${cluster?.cluster_code || 'this cluster'}. The batches, their harvests, their beekeepers and their hives keep their own records.`}
        confirmLabel="Remove and save"
        variant="danger"
        loading={isSubmitting}
        onConfirm={() => {
          setConfirmRemoval(false);
          if (pendingValues) submit(pendingValues);
        }}
        onCancel={() => setConfirmRemoval(false)}
      />
    </Modal>
  );
}

export default ClusterFormModal;
