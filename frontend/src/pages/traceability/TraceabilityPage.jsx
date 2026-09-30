import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Route } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { DataTable } from '@/components/common/DataTable';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { SupplyChainPanel } from '@/components/trace/SupplyChainPanel';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { BatchTimeline } from '@/components/collections/BatchTimeline';
import { QualitySummaryCard } from '@/components/collections/QualitySummaryCard';
import { BATCH_STATUS_META, BATCH_STATUS_OPTIONS, COLLECTION_MESSAGES, unitLabel } from '@/constants/collection';
import { ROLES } from '@/constants/roles';
import * as batchService from '@/services/batchService';
import { normaliseError } from '@/utils/errors';
import { formatDate } from '@/utils/format';

/**
 * Traceability — the journey of every batch in the reader's scope.
 *
 * A list of batches with the stage each has reached, and — when one is selected —
 * its full timeline and quality summary. The beekeeper reads their own honey here;
 * a KVIC officer reads the batches of the clusters they oversee. Both read the
 * same rows, and the laboratory outcome shown is the one the laboratory recorded.
 */
function BatchJourneyTable({ batches, loading, error, onRetry, meta, onPageChange, basePath }) {
  const columns = [
    {
      key: 'batch_code',
      header: 'Batch',
      render: (row) => (
        <Link className="font-mono text-sm font-medium text-forest-700 hover:underline" to={`${basePath}/batches/${row.id}`}>
          {row.batch_code}
        </Link>
      ),
    },
    { key: 'collection_date', header: 'Harvest date', render: (row) => formatDate(row.collection_date) },
    {
      key: 'quantity',
      header: 'Quantity',
      align: 'right',
      render: (row) =>
        `${Number(row.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unitLabel(row.unit)}`,
    },
    {
      key: 'stage',
      header: 'Stage reached',
      render: (row) => {
        const meta_ = BATCH_STATUS_META[row.status] || null;
        return (
          <span className="flex flex-col gap-1">
            <Badge variant={meta_?.variant || 'neutral'} size="sm">
              {row.status_label || meta_?.label || row.status}
            </Badge>
            <span className="text-xs text-ink-muted">{row.current_stage_label || meta_?.stage || row.current_stage}</span>
          </span>
        );
      },
    },
    {
      key: 'beekeeper',
      header: 'Beekeeper',
      render: (row) => <span className="text-sm text-ink-soft">{row.beekeeper_name || row.beekeeper_code || '—'}</span>,
    },
    {
      key: 'cluster',
      header: 'Cluster',
      render: (row) => (row.cluster_code ? <span className="text-xs text-ink-soft">{row.cluster_code}</span> : <span className="text-xs text-ink-muted">—</span>),
    },
    {
      key: 'journey',
      header: 'Journey',
      render: (row) => (
        <Link className="text-sm text-forest-700 hover:underline" to={`${basePath}/traceability/${row.id}`}>
          View journey
        </Link>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={batches}
      loading={loading}
      error={error}
      onRetry={onRetry}
      meta={meta}
      onPageChange={onPageChange}
      emptyTitle={COLLECTION_MESSAGES.emptyBatches}
      emptyDescription="A batch is created when a harvest is completed; its journey starts there."
      caption="Batch traceability"
    />
  );
}

export default function TraceabilityPage({ role = ROLES.BEEKEEPER, basePath = '/beekeeper' }) {
  const { batchId } = useParams();
  const [batches, setBatches] = useState([]);
  const [meta, setMeta] = useState(null);
  const [selected, setSelected] = useState(null);
  const [selectedError, setSelectedError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ page: 1, search: '', status: '' });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await batchService.listBatches({
        page: filters.page,
        pageSize: 20,
        search: filters.search || undefined,
        status: filters.status || undefined,
      });
      setBatches(payload.batches);
      setMeta(payload.meta);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setSelectedError(null);
    if (!batchId) {
      setSelected(null);
      return undefined;
    }
    let cancelled = false;
    setSelected(null);
    batchService
      .getBatch(batchId)
      .then((payload) => {
        if (!cancelled) setSelected(payload);
      })
      .catch((caught) => {
        // An unknown id, a batch outside this account's scope or a failed request
        // is said out loud — never an endless "loading".
        if (!cancelled) {
          setSelected(null);
          setSelectedError(normaliseError(caught));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [batchId]);

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="Traceability"
        description={
          role === ROLES.KVIC_OFFICER
            ? 'Every batch produced in your clusters, with the stage it has reached today.'
            : 'Every batch your harvests produced, and how far each one has travelled.'
        }
        requiredRoles={[role]}
      />

      <Card>
        <CardHeader
          title="Batches"
          description="Filter by batch code or stage, then open one to read its full journey."
          icon={<Route size={16} />}
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Input
              label="Search"
              name="trace_search"
              value={filters.search}
              onChange={(event) => setFilters((f) => ({ ...f, search: event.target.value, page: 1 }))}
              placeholder="Batch code"
            />
            <label className="block">
              <span className="hc-label">Stage</span>
              <select
                name="trace_status"
                className="h-11 w-full rounded-lg border border-sand-300 bg-white px-3 text-sm text-ink"
                value={filters.status}
                onChange={(event) => setFilters((f) => ({ ...f, status: event.target.value, page: 1 }))}
              >
                <option value="">Any stage</option>
                {BATCH_STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <BatchJourneyTable
            batches={batches}
            loading={loading}
            error={error}
            onRetry={() => load()}
            meta={meta}
            onPageChange={(page) => setFilters((f) => ({ ...f, page }))}
            basePath={basePath}
          />
        </CardBody>
      </Card>

      {selected ? (
        <>
          <Card>
            <CardHeader
              title={`Batch ${selected.batch_code}`}
              description="Its stage today, read from the records each module wrote."
              action={
                <Button to={`${basePath}/batches/${selected.id}`} size="sm" variant="secondary">
                  Open the full batch record
                </Button>
              }
            />
            <CardBody>
              <BatchTimeline stages={selected.timeline} />
            </CardBody>
          </Card>
          <SupplyChainPanel batchId={selected.id} />
          <QualitySummaryCard batch={selected} />
        </>
      ) : batchId && selectedError ? (
        <Card>
          <CardBody>
            <ErrorState
              error={selectedError}
              title={
                selectedError.status === 404
                  ? 'This batch was not found, or it is outside your scope'
                  : 'This batch could not be loaded'
              }
            />
          </CardBody>
        </Card>
      ) : batchId ? (
        <LoadingState message="Loading batch information…" />
      ) : null}
    </div>
  );
}
