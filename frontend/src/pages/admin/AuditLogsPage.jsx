import { useCallback, useEffect, useMemo, useState } from 'react';
import { RotateCcw, ScrollText, Search } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { StatCard } from '@/components/common/StatCard';
import { formatDateTime, titleCase } from '@/utils/format';
import { normaliseError } from '@/utils/errors';
import * as adminService from '@/services/adminService';

const PAGE_SIZE = 25;
const EMPTY_FILTERS = { action: '', entityType: '' };

const ENTITY_OPTIONS = [
  { value: 'user', label: 'User' },
  { value: 'beekeeper', label: 'Beekeeper' },
  { value: 'cluster', label: 'Cluster' },
  { value: 'session', label: 'Session' },
];

const COMMON_ACTIONS = [
  'USER_REGISTERED',
  'USER_LOGIN',
  'USER_LOGIN_FAILED',
  'USER_LOGOUT',
  'PROFILE_UPDATED',
  'BEEKEEPER_CREATED',
  'BEEKEEPER_VERIFIED',
  'BEEKEEPER_REJECTED',
  'USER_ACTIVATED',
  'USER_DEACTIVATED',
  'CLUSTER_CREATED',
  'CLUSTER_UPDATED',
  'CLUSTER_STATUS_CHANGED',
  'CLUSTER_MEMBER_ADDED',
  'CLUSTER_MEMBER_REMOVED',
];

/**
 * Audit log.
 *
 * Append-only record of platform events, newest first. Entries never contain
 * passwords, tokens or other secrets — the API redacts them before writing, so
 * this screen cannot leak what was never stored.
 */
export default function AuditLogsPage() {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activity, setActivity] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { entries, meta: pageMeta } = await adminService.listAuditLogs({
        page,
        pageSize: PAGE_SIZE,
        action: applied.action || undefined,
        entityType: applied.entityType || undefined,
      });
      setRows(entries);
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
    let active = true;
    adminService
      .getActivitySummary({ hours: 24 })
      .then((payload) => {
        if (active) setActivity(payload);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const columns = useMemo(
    () => [
      {
        key: 'created_at',
        header: 'When',
        render: (row) => <span className="whitespace-nowrap">{formatDateTime(row.created_at)}</span>,
      },
      {
        key: 'action',
        header: 'Action',
        render: (row) => (
          <Badge variant="neutral" size="sm">
            {titleCase(row.action)}
          </Badge>
        ),
      },
      {
        key: 'actor',
        header: 'Actor',
        render: (row) =>
          row.actor_email ? (
            <div className="min-w-0">
              <p className="truncate text-ink">{row.actor_email}</p>
              <p className="truncate text-xs text-ink-muted">
                {row.actor_role ? titleCase(row.actor_role) : '—'}
              </p>
            </div>
          ) : (
            <span className="text-ink-muted">System</span>
          ),
      },
      {
        key: 'entity',
        header: 'Entity',
        render: (row) =>
          row.entity_type ? (
            <div className="min-w-0">
              <p className="text-ink">{titleCase(row.entity_type)}</p>
              <p className="truncate font-mono text-xs text-ink-muted">{row.entity_id || '—'}</p>
            </div>
          ) : (
            '—'
          ),
      },
      {
        key: 'description',
        header: 'Details',
        render: (row) => (
          <span className="text-ink-soft">{row.description || '—'}</span>
        ),
      },
      {
        key: 'ip_address',
        header: 'IP',
        render: (row) => <span className="font-mono text-xs text-ink-muted">{row.ip_address || '—'}</span>,
      },
    ],
    [],
  );

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'Audit Logs' }]} />
      <PageHeader
        title="Audit logs"
        description="Registrations, sign-ins, profile edits, verification decisions and account changes — recorded in order and never edited."
      />

      {activity ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard
            label={`Events in the last ${activity.window_hours}h`}
            value={activity.total}
            icon={<ScrollText size={16} />}
          />
          <StatCard
            label="Sign-ins"
            value={activity.by_action?.USER_LOGIN ?? 0}
            tone="forest"
          />
          <StatCard
            label="Verification decisions"
            value={
              (activity.by_action?.BEEKEEPER_VERIFIED ?? 0) +
              (activity.by_action?.BEEKEEPER_REJECTED ?? 0)
            }
            tone="honey"
          />
        </div>
      ) : null}

      <Card>
        <CardBody>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setPage(1);
              setApplied(filters);
            }}
            className="grid gap-3 lg:grid-cols-4"
          >
            <Input
              label="Action"
              name="action"
              placeholder="e.g. BEEKEEPER_VERIFIED"
              leftIcon={<Search size={15} />}
              list="audit-action-options"
              value={filters.action}
              onChange={(event) => setFilters((prev) => ({ ...prev, action: event.target.value }))}
              hint="Exact action code, case-insensitive"
            />
            <datalist id="audit-action-options">
              {COMMON_ACTIONS.map((action) => (
                <option key={action} value={action} />
              ))}
            </datalist>
            <Select
              label="Entity"
              name="entity_type"
              placeholder="Any entity"
              options={ENTITY_OPTIONS}
              value={filters.entityType}
              onChange={(event) => setFilters((prev) => ({ ...prev, entityType: event.target.value }))}
            />
            <div className="flex items-end gap-2 lg:col-span-2">
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
            </div>
          </form>
        </CardBody>
      </Card>

      {error ? <Alert variant="danger">{error.message}</Alert> : null}

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        emptyTitle="No audit entries found"
        emptyDescription="Nothing matches these filters yet. Sign-ins, registrations and edits appear here as they happen."
      />

      <p className="text-xs text-ink-muted">
        Entries are written by the API with passwords, tokens and other secrets redacted, so they can
        never appear on this screen. Nothing here can be edited or deleted.
      </p>
    </div>
  );
}
