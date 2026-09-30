import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Blocks,
  CheckCheck,
  Link2,
  RefreshCw,
  RotateCcw,
  Search,
  ServerCog,
  TriangleAlert,
} from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { StatCard } from '@/components/common/StatCard';
import {
  BLOCKCHAIN_EVENT_TYPES,
  BLOCKCHAIN_STATUS_OPTIONS,
  blockchainStatusMeta,
  eventTypeLabel,
} from '@/constants/blockchain';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import * as blockchainService from '@/services/blockchainService';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';

const PAGE_SIZE = 25;
const EMPTY_FILTERS = { search: '', txType: '', status: '', dateFrom: '', dateTo: '' };

/**
 * The traceability ledger.
 *
 * The same screen for the two accounts that may read the whole register — an
 * administrator reads every event, a KVIC officer reads the events of the
 * clusters they oversee, narrowed by the backend, not by this component — with
 * the operator's controls (sync now, retry a failed event) shown only to the
 * administrator who has the permission for them.
 *
 * The one rule this screen keeps: a status is a statement about the chain, and
 * nothing here may say more than the recorded status does. There is no
 * "verified" label outside CONFIRMED, and the chain's own ledger is shown
 * beside HoneyChain's events rather than blended into them, because the
 * transactions written before this platform wrote any are history — recorded,
 * readable, and never attached to a batch that did not produce them.
 */
export default function BlockchainLedgerPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === ROLES.ADMIN;
  const basePath = isAdmin ? '/admin' : '/kvic';

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [action, setAction] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);

  const [selected, setSelected] = useState(null);
  const [chainRows, setChainRows] = useState(null);
  const [chainError, setChainError] = useState(null);
  const [chainLoading, setChainLoading] = useState(false);

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await blockchainService.getHealth());
      setHealthError(null);
    } catch (caught) {
      setHealthError(normaliseError(caught));
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { transactions, meta: pageMeta } = await blockchainService.listTransactions({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        txType: applied.txType || undefined,
        status: applied.status || undefined,
        dateFrom: applied.dateFrom ? `${applied.dateFrom}T00:00:00` : undefined,
        dateTo: applied.dateTo ? `${applied.dateTo}T23:59:59` : undefined,
      });
      setRows(transactions);
      setMeta(pageMeta);
    } catch (caught) {
      setError(normaliseError(caught));
      setRows([]);
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }, [page, applied]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  const loadChain = useCallback(async () => {
    setChainLoading(true);
    setChainError(null);
    try {
      setChainRows(await blockchainService.getChainLedger({ limit: 100 }));
    } catch (caught) {
      setChainError(normaliseError(caught));
    } finally {
      setChainLoading(false);
    }
  }, []);

  const synchronise = async () => {
    setBusy(true);
    setAction(null);
    setActionError(null);
    try {
      const result = await blockchainService.sync();
      setAction(
        result.enabled === false
          ? 'The integration is switched off: the events are recorded as skipped, and a sweep after it is switched on writes them to the chain.'
          : `${result.submitted} submitted · ${result.confirmed} confirmed · ${result.failed} failed · ${result.outstanding} still outstanding.`,
      );
      await Promise.all([load(), loadHealth()]);
      if (chainRows) await loadChain();
    } catch (caught) {
      setActionError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  const retry = async (row) => {
    setBusy(true);
    setAction(null);
    setActionError(null);
    try {
      const updated = await blockchainService.retryTransaction(row.id);
      setSelected(updated);
      setAction(
        updated.status === 'CONFIRMED'
          ? `${updated.event_id} is now confirmed on the chain (${updated.tx_id}).`
          : `${updated.event_id}: ${updated.status_label}${updated.last_error ? ` — ${updated.last_error}` : ''}`,
      );
      await Promise.all([load(), loadHealth()]);
    } catch (caught) {
      setActionError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  const columns = useMemo(
    () => [
      {
        key: 'created_at',
        header: 'Recorded',
        render: (row) => <span className="whitespace-nowrap">{formatDateTime(row.created_at)}</span>,
      },
      {
        key: 'event',
        header: 'Event',
        render: (row) => (
          <div className="min-w-0">
            <p className="text-ink">{row.tx_type_label || eventTypeLabel(row.tx_type)}</p>
            <p className="truncate font-mono text-xs text-ink-muted">{row.event_id}</p>
          </div>
        ),
      },
      {
        key: 'record',
        header: 'Record',
        render: (row) =>
          row.batch_code ? (
            row.batch_id ? (
              <Link
                className="font-mono text-sm font-medium text-forest-700 hover:underline"
                to={`${basePath}/batches/${row.batch_id}`}
              >
                {row.batch_code}
              </Link>
            ) : (
              <span className="font-mono text-sm">{row.batch_code}</span>
            )
          ) : (
            <span className="text-ink-muted">—</span>
          ),
      },
      {
        key: 'status',
        header: 'Chain status',
        render: (row) => {
          const meta_ = blockchainStatusMeta(row.status);
          return (
            <div className="min-w-0">
              <Badge variant={meta_.variant} size="sm">
                {row.status_label || meta_.label}
              </Badge>
              <p className="mt-1 text-xs text-ink-muted">{meta_.hint}</p>
            </div>
          );
        },
      },
      {
        key: 'tx_id',
        header: 'Transaction',
        render: (row) =>
          row.tx_id ? (
            <span className="font-mono text-xs text-ink-soft" title={row.tx_id}>
              {row.tx_id.slice(0, 12)}…
            </span>
          ) : (
            <span className="text-xs text-ink-muted">Not on the chain</span>
          ),
      },
      {
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => (
          <Button size="sm" variant="secondary" onClick={() => setSelected(row)}>
            Details
          </Button>
        ),
      },
    ],
    [basePath],
  );

  const chainColumns = useMemo(
    () => [
      {
        key: 'timestamp',
        header: 'When',
        render: (row) => <span className="whitespace-nowrap">{formatDateTime(row.timestamp)}</span>,
      },
      {
        key: 'tx_type',
        header: 'Type',
        render: (row) => eventTypeLabel(row.tx_type),
      },
      {
        key: 'batch_id',
        header: 'Batch reference',
        render: (row) => <span className="font-mono text-xs">{row.batch_id || '—'}</span>,
      },
      {
        key: 'link',
        header: 'HoneyChain record',
        render: (row) =>
          row.honey_chain_recorded ? (
            <div className="min-w-0">
              <Badge variant="success" size="sm">
                Recorded here
              </Badge>
              <p className="truncate font-mono text-xs text-ink-muted">{row.matched_event_id}</p>
            </div>
          ) : (
            <Badge variant="neutral" size="sm">
              Not linked to this platform
            </Badge>
          ),
      },
      {
        key: 'tx_id',
        header: 'Transaction id',
        render: (row) => (
          <span className="font-mono text-xs text-ink-soft" title={row.tx_id}>
            {row.tx_id?.slice(0, 16)}…
          </span>
        ),
      },
    ],
    [],
  );

  const service = health?.service || null;
  const counts = health?.honeychain || null;

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: isAdmin ? 'Administration' : 'KVIC', to: basePath },
          { label: 'Blockchain ledger' },
        ]}
      />
      <PageHeader
        title="Blockchain ledger"
        description={
          isAdmin
            ? 'Every supply-chain event this platform recorded, with what the blockchain service did with it.'
            : 'The traceability events of the clusters you oversee — the same records, narrowed to your scope.'
        }
      />

      {healthError ? (
        <Alert variant="warning" title="Unable to read blockchain health">
          {healthError.message} The ledger below is still read from the database, so it remains
          accurate; only the service's own state is missing.
        </Alert>
      ) : null}

      {service ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Blockchain service"
            value={service.reachable ? 'Connected' : 'Not reachable'}
            helper={
              service.reachable
                ? `${service.ledger_transactions ?? 0} transactions on the chain · ${service.latency_ms ?? '—'} ms`
                : service.message || 'The configured service did not answer a read.'
            }
            icon={<ServerCog size={16} />}
            tone={service.reachable ? 'forest' : 'warning'}
          />
          <StatCard
            label="Confirmed here"
            value={counts?.confirmed ?? 0}
            helper={
              counts?.last_confirmed_at
                ? `Last: ${formatDateTime(counts.last_confirmed_at)}`
                : 'Nothing confirmed yet.'
            }
            icon={<CheckCheck size={16} />}
            tone="forest"
          />
          <StatCard
            label="Waiting to be written"
            value={(counts?.pending ?? 0) + (counts?.submitted ?? 0)}
            helper="Recorded in HoneyChain, not yet confirmed on the chain."
            icon={<RefreshCw size={16} />}
            tone="honey"
          />
          <StatCard
            label="Failed"
            value={counts?.failed ?? 0}
            helper={
              counts?.failed
                ? 'These events are not on the chain. Retry them, or use Sync now.'
                : 'No event is stuck.'
            }
            icon={<TriangleAlert size={16} />}
            tone={counts?.failed ? 'warning' : 'forest'}
          />
        </div>
      ) : null}

      {action ? <Alert variant="info">{action}</Alert> : null}
      {actionError ? <Alert variant="danger">{actionError.message}</Alert> : null}

      <Card>
        <CardBody>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setPage(1);
              setApplied(filters);
            }}
            className="grid gap-3 lg:grid-cols-6"
          >
            <Input
              label="Search"
              name="search"
              placeholder="Event, batch or transaction id"
              leftIcon={<Search size={15} />}
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
              containerClassName="lg:col-span-2"
            />
            <Select
              label="Event type"
              name="tx_type"
              placeholder="Any event"
              options={BLOCKCHAIN_EVENT_TYPES}
              value={filters.txType}
              onChange={(event) => setFilters((prev) => ({ ...prev, txType: event.target.value }))}
            />
            <Select
              label="Chain status"
              name="status"
              placeholder="Any status"
              options={BLOCKCHAIN_STATUS_OPTIONS}
              value={filters.status}
              onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
            />
            <Input
              label="From"
              name="date_from"
              type="date"
              value={filters.dateFrom}
              onChange={(event) => setFilters((prev) => ({ ...prev, dateFrom: event.target.value }))}
            />
            <Input
              label="To"
              name="date_to"
              type="date"
              value={filters.dateTo}
              onChange={(event) => setFilters((prev) => ({ ...prev, dateTo: event.target.value }))}
            />
            <div className="flex items-end gap-2 lg:col-span-6">
              <Button type="submit" size="sm">
                Apply filters
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                leftIcon={<RotateCcw size={15} />}
                onClick={() => {
                  setFilters(EMPTY_FILTERS);
                  setApplied(EMPTY_FILTERS);
                  setPage(1);
                }}
              >
                Reset
              </Button>
              {isAdmin ? (
                <Button
                  type="button"
                  size="sm"
                  variant="primary"
                  leftIcon={<RefreshCw size={15} />}
                  loading={busy}
                  onClick={synchronise}
                >
                  Sync now
                </Button>
              ) : null}
            </div>
          </form>
        </CardBody>
      </Card>

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={error}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        emptyTitle="No events recorded yet"
        emptyDescription="Every collection, batch, processing run, test, package and shipment records an event here as it happens — nothing is written in advance."
      />

      {isAdmin ? (
        <Card>
          <CardHeader
            title="The chain's own ledger"
            description="What the blockchain service reports, exactly as it reports it — including the transactions written before this platform wrote any."
            action={
              <Button
                size="sm"
                variant="secondary"
                leftIcon={<Blocks size={15} />}
                loading={chainLoading}
                onClick={loadChain}
              >
                {chainRows ? 'Reload' : 'Read the chain'}
              </Button>
            }
          />
          <CardBody>
            {chainError ? <Alert variant="danger">{chainError.message}</Alert> : null}
            {chainRows ? (
              <>
                <DataTable
                  columns={chainColumns}
                  rows={chainRows}
                  rowKey={(row) => row.tx_id}
                  emptyTitle="The chain holds no transactions"
                />
                <p className="mt-3 flex items-start gap-2 text-xs text-ink-muted">
                  <Link2 size={14} className="mt-0.5 shrink-0" />
                  Rows marked “Not linked to this platform” were written to the chain before
                  HoneyChain recorded them, or by another writer. They are shown here and nowhere
                  else: no batch, timeline or customer page claims them, because no record of ours
                  produced them.
                </p>
              </>
            ) : (
              <p className="text-sm text-ink-soft">
                Read the chain to compare its ledger with the events above.
              </p>
            )}
          </CardBody>
        </Card>
      ) : null}

      <Modal
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected ? selected.tx_type_label || eventTypeLabel(selected.tx_type) : 'Transaction'}
        description={selected?.event_id}
        size="lg"
        footer={
          selected ? (
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-ink-muted">
                {selected.status === 'CONFIRMED'
                  ? 'This event is written to the chain.'
                  : blockchainStatusMeta(selected.status).hint}
              </span>
              {isAdmin && selected.status === 'FAILED' ? (
                <Button size="sm" loading={busy} onClick={() => retry(selected)}>
                  Retry submission
                </Button>
              ) : null}
            </div>
          ) : null
        }
      >
        {selected ? (
          <div className="space-y-4 text-sm">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Chain status</p>
                <div className="mt-1">
                  <Badge variant={blockchainStatusMeta(selected.status).variant} size="sm">
                    {selected.status_label || blockchainStatusMeta(selected.status).label}
                  </Badge>
                </div>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Transaction id</p>
                <p className="mt-1 break-all font-mono text-xs">
                  {selected.tx_id || 'Not on the chain yet'}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Batch</p>
                <p className="mt-1 font-mono text-xs">{selected.batch_code || '—'}</p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Recorded</p>
                <p className="mt-1">{formatDateTime(selected.created_at)}</p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Submitted</p>
                <p className="mt-1">{selected.submitted_at ? formatDateTime(selected.submitted_at) : '—'}</p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">Confirmed</p>
                <p className="mt-1">{selected.confirmed_at ? formatDateTime(selected.confirmed_at) : '—'}</p>
              </div>
            </div>

            {selected.last_error ? (
              <Alert variant="danger" title="Last attempt">
                {selected.last_error} (attempt {selected.attempt_count})
              </Alert>
            ) : null}

            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                What was submitted
              </p>
              <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-sand-50 p-3 text-xs">
                {JSON.stringify(selected.payload, null, 2)}
              </pre>
              <p className="mt-1 text-xs text-ink-muted">
                The event's own summary — identifiers, quantities, the actor and the moment. The
                measurements, documents and notes behind it stay in HoneyChain.
              </p>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
