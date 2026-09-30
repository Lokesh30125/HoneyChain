import { useCallback, useEffect, useMemo, useState } from 'react';
import { PackageSearch, Search } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { DataTable } from '@/components/common/DataTable';
import { unitLabel } from '@/constants/collection';
import { normaliseError } from '@/utils/errors';
import { formatDate } from '@/utils/format';
import * as batchService from '@/services/batchService';
import * as clusterService from '@/services/clusterService';

/**
 * "Add honey batches" — the picker that places **real** batches in a cluster.
 *
 * The rows are the batches themselves: the batch code, the harvest it came from,
 * the beekeeper who produced it, the quantity and the stage it has reached. They
 * are read through the batch endpoints — nothing is typed in here, and nothing is
 * copied into the cluster.
 *
 * Two things the picker is careful about:
 *
 * * A batch that already belongs to **another cluster** is flagged, by code, from
 *   the server's own answer (`placement_label`) *before* it is chosen, and it is
 *   marked as needing confirmation. It is never silently taken: the caller has to
 *   say so, and saying so moves that batch's own cluster link.
 * * A batch already in *this* cluster is shown as such, and selecting it changes
 *   nothing — re-sending it is reported by the API as `already`, not as a
 *   duplicate record.
 *
 * While creating a cluster there is no cluster id yet, so the picker reads the
 * caller's own readable batches (`GET /batches`) and derives the same placement
 * note locally; the server still has the last word when the form is submitted.
 */
export function placementOf(batch, clusterId) {
  if (!batch.cluster_id) {
    return { value: 'unassigned', label: 'No cluster assigned', needsConfirmation: false };
  }
  if (clusterId && batch.cluster_id === clusterId) {
    return { value: 'this_cluster', label: 'Already in this cluster', needsConfirmation: false };
  }
  const cluster = batch.cluster_code || batch.cluster_name || 'another cluster';
  return {
    value: 'other_cluster',
    label: `Currently in ${cluster} — moving it must be confirmed`,
    needsConfirmation: true,
  };
}

export function ClusterBatchPicker({
  //: The cluster being edited. Omitted while creating one.
  clusterId = null,
  //: Batch ids currently selected (controlled by the form).
  selectedIds = [],
  onToggle,
  onSelectMany,
  pageSize = 10,
  emptyHint = 'Batches appear here as soon as a beekeeper completes a harvest.',
}) {
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [assignment, setAssignment] = useState('any');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (clusterId) {
        const { batches, meta: pageMeta } = await clusterService.listBatchCandidates(clusterId, {
          page,
          pageSize,
          search: appliedSearch || undefined,
          assignment,
        });
        setRows(batches);
        setMeta(pageMeta);
      } else {
        // No cluster yet: the scope-wide batch list, filtered the same way. The
        // API applies the filter in the database, before paging.
        const { batches, meta: pageMeta } = await batchService.listBatches({
          page,
          pageSize,
          search: appliedSearch || undefined,
          unclustered: assignment === 'unassigned',
        });
        setRows(batches);
        setMeta(pageMeta);
      }
    } catch (caught) {
      // An empty list is not reported for a failed request: the officer reads the
      // error the API gave, and the button to try again.
      setError(normaliseError(caught));
      setRows([]);
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }, [clusterId, page, pageSize, appliedSearch, assignment]);

  useEffect(() => {
    load();
  }, [load]);

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);

  const columns = [
    {
      key: 'select',
      header: '',
      className: 'w-10',
      render: (row) => (
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-sand-300 text-forest-600 focus:ring-forest-500"
          checked={selected.has(row.id)}
          onChange={() => onToggle?.(row)}
          aria-label={`Select batch ${row.batch_code}`}
          data-testid={`pick-batch-${row.batch_code}`}
        />
      ),
    },
    {
      key: 'batch_code',
      header: 'Batch ID',
      render: (row) => (
        <div className="min-w-0">
          <p className="font-mono text-xs font-medium text-ink">{row.batch_code}</p>
          <p className="text-xs text-ink-muted">{formatDate(row.collection_date)}</p>
        </div>
      ),
    },
    {
      key: 'collection_code',
      header: 'Collection ID',
      render: (row) => <span className="font-mono text-xs text-ink-soft">{row.collection_code}</span>,
    },
    {
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => (
        <div className="min-w-0">
          <p className="truncate text-ink">{row.beekeeper_name || '—'}</p>
          <p className="font-mono text-xs text-ink-muted">{row.beekeeper_code || '—'}</p>
        </div>
      ),
    },
    {
      key: 'honey_type',
      header: 'Honey type',
      // The platform's harvest records carry quantity, unit and dates — there is
      // no honey/floral variety column anywhere in the schema, so the picker says
      // so instead of printing a guess.
      render: () => <span className="text-xs text-ink-muted">Not recorded</span>,
    },
    {
      key: 'quantity',
      header: 'Quantity',
      align: 'right',
      render: (row) => `${Number(row.quantity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(row.unit)}`,
    },
    {
      key: 'status',
      header: 'Current status',
      render: (row) => (
        <Badge variant="info" size="sm">
          {row.status_label || row.status}
        </Badge>
      ),
    },
    {
      key: 'placement',
      header: 'Cluster',
      render: (row) => {
        const placement = row.placement_label
          ? {
              value: row.placement,
              label: row.placement_label,
              needsConfirmation: Boolean(row.requires_confirmation),
            }
          : placementOf(row, clusterId);
        return (
          <div className="min-w-0">
            <Badge
              variant={
                placement.value === 'unassigned'
                  ? 'neutral'
                  : placement.needsConfirmation
                    ? 'warning'
                    : 'success'
              }
              size="sm"
            >
              {placement.value === 'unassigned'
                ? 'No cluster'
                : placement.needsConfirmation
                  ? 'Other cluster'
                  : 'This cluster'}
            </Badge>
            <p className="mt-1 max-w-[16rem] text-xs text-ink-muted">{placement.label}</p>
          </div>
        );
      },
    },
  ];

  const needsConfirmation = rows.filter(
    (row) => selected.has(row.id) && (row.requires_confirmation ?? placementOf(row, clusterId).needsConfirmation),
  );

  const assignmentOptions =
    clusterId === null
      ? [
          { value: 'any', label: 'All batches in my scope' },
          { value: 'unassigned', label: 'Only batches with no cluster' },
        ]
      : [
          { value: 'any', label: 'All batches in my scope' },
          { value: 'unassigned', label: 'No cluster assigned' },
          { value: 'other_cluster', label: 'In another cluster' },
          { value: 'this_cluster', label: 'Already in this cluster' },
        ];

  return (
    <section className="space-y-3" aria-label="Add honey batches">
      <div className="flex flex-wrap items-end gap-3">
        <form
          className="flex flex-1 flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            setPage(1);
            setAppliedSearch(search.trim());
          }}
        >
          <div className="min-w-[12rem] flex-1">
            <Input
              label="Find a batch"
              name="batch-search"
              placeholder="Batch code"
              leftIcon={<Search size={15} />}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <div className="min-w-[12rem]">
            <Select
              label="Show"
              name="batch-assignment"
              options={assignmentOptions}
              value={assignment}
              onChange={(event) => {
                setPage(1);
                setAssignment(event.target.value);
              }}
            />
          </div>
          <Button type="submit" size="sm" variant="secondary" loading={loading}>
            Apply
          </Button>
        </form>
        <div className="flex items-center gap-2 pb-1">
          <Badge variant="honey" size="sm">
            {selectedIds.length} selected
          </Badge>
          {rows.length > 0 && onSelectMany ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => onSelectMany(rows.map((row) => row.id), rows)}
            >
              Select page
            </Button>
          ) : null}
        </div>
      </div>

      {needsConfirmation.length ? (
        <Alert variant="warning" title="These batches already belong to another cluster">
          {needsConfirmation.map((row) => row.batch_code).join(', ')} — moving them changes the cluster
          recorded on those batches themselves. You will be asked to confirm before anything is written.
        </Alert>
      ) : null}

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={error}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        emptyTitle="No batches match this filter"
        emptyDescription={emptyHint}
        caption="Batches available to place in a cluster"
        skeletonRows={4}
      />

      <p className="flex items-start gap-2 text-xs text-ink-muted">
        <PackageSearch size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
        <span>
          Batches are created by completing a harvest, so they are selected here rather than entered.
          Selecting one writes the cluster link on that same batch — its harvest, beekeeper and hives
          stay exactly where they are.
        </span>
      </p>
    </section>
  );
}

export default ClusterBatchPicker;
