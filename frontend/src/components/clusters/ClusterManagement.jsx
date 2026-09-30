import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, Eye, Pencil, Plus, RotateCcw, Search, Trash2, UserCog, Users } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { Link } from 'react-router-dom';
import { StatCard } from '@/components/common/StatCard';
import { ClusterDeleteDialog } from '@/components/clusters/ClusterDeleteDialog';
import { ClusterFormModal } from '@/components/clusters/ClusterFormModal';
import { ClusterMembersModal } from '@/components/clusters/ClusterMembersModal';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as clusterService from '@/services/clusterService';

const PAGE_SIZE = 10;
const EMPTY_FILTERS = { search: '', district: '', state: '' };

/**
 * Cluster management: create, edit, activate/deactivate and manage members.
 *
 * Scope stops there — no production or coverage analytics in this phase, so the
 * page shows counts it can actually query and nothing it cannot.
 */
export function ClusterManagement({ detailBasePath = null }) {
  const toast = useToast();
  const navigate = useNavigate();

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [membersFor, setMembersFor] = useState(null);
  const [statusTarget, setStatusTarget] = useState(null);
  const [statusSaving, setStatusSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  //: The cluster just created, named on screen until the next refresh. It is the
  //: receipt for the write: the same id and code the API returned.
  const [justCreated, setJustCreated] = useState(null);
  //: Set when the write succeeded but the list that should show it did not load.
  //: Kept separate from `error` because it is not a failure of the creation, and
  //: conflating the two is exactly the bug being fixed here.
  const [refreshNotice, setRefreshNotice] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { clusters, meta: pageMeta } = await clusterService.listClusters({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        district: applied.district || undefined,
        state: applied.state || undefined,
        isActive: statusFilter === '' ? undefined : statusFilter === 'active',
      });
      setRows(clusters);
      setMeta(pageMeta);
      setRefreshNotice(null);
      return true;
    } catch (caught) {
      setError(normaliseError(caught));
      setRows([]);
      // Reported to the caller so a write that has already succeeded is not
      // announced as a failure just because this read did not come back.
      return false;
    } finally {
      setLoading(false);
    }
  }, [page, applied, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const totals = useMemo(
    () => ({
      total: meta?.total_items ?? 0,
      active: rows.filter((row) => row.is_active).length,
      members: rows.reduce((sum, row) => sum + (row.member_count || 0), 0),
      // Counted by the API from `honey_batches.cluster_id` for the rows on this
      // page — the same number the cluster's own batch table has rows.
      batches: rows.reduce((sum, row) => sum + (row.batch_count || 0), 0),
    }),
    [meta, rows],
  );

  /**
   * What happens after a cluster is created.
   *
   * Two outcomes, told apart on purpose. The list is refreshed and, when the
   * refresh fails, the officer reads that the cluster **was** created and that the
   * *list* could not be reloaded — with a button to try again. The earlier
   * behaviour reported the refresh failure as a creation failure, which sent people
   * back to a form to create a second copy of a cluster that already existed.
   */
  const handleCreated = async (created) => {
    setJustCreated(created);
    const refreshed = await load();
    if (!refreshed) {
      setRefreshNotice(
        `Cluster ${created.cluster_code} was created, but the cluster list could not be refreshed.`,
      );
    }
  };

  const handleDeleted = async (removed) => {
    toast.success(
      `Cluster ${removed?.cluster_code || ''} removed`,
      'Nothing was recorded under it, so no record was affected.',
    );
    setJustCreated(null);
    await load();
  };

  const deactivateBlockedCluster = async () => {
    if (!deleteTarget) return;
    setStatusSaving(true);
    try {
      await clusterService.setClusterStatus(deleteTarget.id, false, 'Cluster kept for its records');
      toast.success(`${deleteTarget.cluster_code} deactivated`, 'Its records keep their cluster.');
      setDeleteTarget(null);
      await load();
    } catch (caught) {
      toast.error('Could not deactivate the cluster', normaliseError(caught).message);
    } finally {
      setStatusSaving(false);
    }
  };

  const toggleStatus = async () => {
    if (!statusTarget) return;
    setStatusSaving(true);
    try {
      await clusterService.setClusterStatus(statusTarget.id, !statusTarget.is_active);
      toast.success(
        `${statusTarget.cluster_code} ${statusTarget.is_active ? 'deactivated' : 'activated'}`,
      );
      setStatusTarget(null);
      load();
    } catch (caught) {
      toast.error('Could not change the cluster status', normaliseError(caught).message);
    } finally {
      setStatusSaving(false);
    }
  };

  const columns = useMemo(
    () => [
      {
        key: 'cluster_code',
        header: 'Code',
        render: (row) => <span className="font-medium text-ink">{row.cluster_code}</span>,
      },
      {
        key: 'cluster_name',
        header: 'Cluster',
        render: (row) => (
          <div className="min-w-0">
            {/* One cluster, one record: this link opens the cluster's view of
                its members' hives, devices, telemetry and analyses. */}
            {detailBasePath ? (
              <Link
                to={`${detailBasePath}/${row.id}`}
                className="truncate font-medium text-forest-700 underline-offset-2 hover:underline"
              >
                {row.cluster_name}
              </Link>
            ) : (
              <p className="truncate font-medium text-ink">{row.cluster_name}</p>
            )}
            <p className="truncate text-xs text-ink-muted">
              {[row.district, row.state].filter(Boolean).join(', ')}
            </p>
          </div>
        ),
      },
      {
        key: 'coordinator_name',
        header: 'Coordinator',
        render: (row) =>
          row.coordinator_name ? (
            <div className="min-w-0">
              <p className="truncate text-ink">{row.coordinator_name}</p>
              <p className="truncate text-xs text-ink-muted">{row.coordinator_phone || '—'}</p>
            </div>
          ) : (
            '—'
          ),
      },
      { key: 'member_count', header: 'Members', align: 'right', render: (row) => row.member_count ?? 0 },
      {
        key: 'batch_count',
        header: 'Batches',
        align: 'right',
        render: (row) => row.batch_count ?? 0,
      },
      {
        key: 'is_active',
        header: 'Status',
        render: (row) => (
          <Badge variant={row.is_active ? 'success' : 'neutral'} size="sm">
            {row.is_active ? 'Active' : 'Inactive'}
          </Badge>
        ),
      },
      {
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => (
          <div className="flex justify-end gap-2">
            {detailBasePath ? (
              <Button size="sm" variant="secondary" onClick={() => navigate(`${detailBasePath}/${row.id}`)}>
                <Eye size={14} className="mr-1" aria-hidden="true" /> View
              </Button>
            ) : null}
            <Button size="sm" variant="secondary" onClick={() => setMembersFor(row)}>
              <Users size={14} className="mr-1" aria-hidden="true" /> Members
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setEditing(row);
                setFormOpen(true);
              }}
            >
              <Pencil size={14} aria-hidden="true" />
              <span className="sr-only">Edit {row.cluster_code}</span>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setStatusTarget(row)}
              aria-label={row.is_active ? `Deactivate ${row.cluster_code}` : `Activate ${row.cluster_code}`}
            >
              <UserCog size={14} aria-hidden="true" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setDeleteTarget(row)}
              aria-label={`Remove ${row.cluster_code}`}
              data-testid={`delete-cluster-${row.cluster_code}`}
            >
              <Trash2 size={14} aria-hidden="true" />
            </Button>
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detailBasePath],
  );

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Clusters" value={totals.total} icon={<Building2 size={16} />} />
        <StatCard label="Active on this page" value={totals.active} tone="forest" />
        <StatCard
          label="Members on this page"
          value={totals.members}
          helper="Assigned beekeepers"
          tone="honey"
        />
        <StatCard
          label="Batches on this page"
          value={totals.batches}
          helper="Placed in these clusters"
        />
      </div>

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
              label="Search"
              name="search"
              placeholder="Name, code or coordinator"
              leftIcon={<Search size={15} />}
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
            />
            <Input
              label="District"
              name="district"
              value={filters.district}
              onChange={(event) => setFilters((prev) => ({ ...prev, district: event.target.value }))}
            />
            <Input
              label="State"
              name="state"
              value={filters.state}
              onChange={(event) => setFilters((prev) => ({ ...prev, state: event.target.value }))}
            />
            <Select
              label="Status"
              name="status"
              placeholder="Any status"
              options={[
                { value: 'active', label: 'Active' },
                { value: 'inactive', label: 'Inactive' },
              ]}
              value={statusFilter}
              onChange={(event) => {
                setPage(1);
                setStatusFilter(event.target.value);
              }}
            />
            <div className="flex flex-wrap items-end gap-2 lg:col-span-4">
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
                  setStatusFilter('');
                  setPage(1);
                }}
              >
                Reset
              </Button>
              <Button
                type="button"
                size="sm"
                className="ml-auto"
                leftIcon={<Plus size={15} />}
                onClick={() => {
                  setEditing(null);
                  setFormOpen(true);
                }}
              >
                New cluster
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

      {justCreated ? (
        <Alert
          variant="success"
          title={`Cluster ${justCreated.cluster_code} created`}
          onDismiss={() => setJustCreated(null)}
        >
          {justCreated.cluster_name} · {[justCreated.district, justCreated.state].filter(Boolean).join(', ')}
          {justCreated.batch_count
            ? ` · ${justCreated.batch_count} batch${justCreated.batch_count === 1 ? '' : 'es'} placed`
            : ' · no batches placed yet'}
          {detailBasePath ? (
            <>
              {' '}
              <Link
                to={`${detailBasePath}/${justCreated.id}`}
                className="font-medium underline underline-offset-2"
              >
                Open the cluster
              </Link>
            </>
          ) : null}
        </Alert>
      ) : null}

      {refreshNotice ? (
        <Alert
          variant="warning"
          title="Cluster created, but the list did not reload"
          onDismiss={() => setRefreshNotice(null)}
        >
          <span className="flex flex-wrap items-center gap-2">
            <span>{refreshNotice} The cluster is stored — refreshing again will show it.</span>
            <Button
              size="sm"
              variant="secondary"
              loading={loading}
              onClick={async () => {
                await load();
              }}
            >
              Refresh
            </Button>
          </span>
        </Alert>
      ) : null}

      {error && !rows.length ? <Alert variant="danger">{error.message}</Alert> : null}

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        error={null}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        emptyTitle="No clusters found"
        emptyDescription="Create a cluster to group beekeepers in a district under one coordinator."
      />

      <ClusterFormModal
        open={formOpen}
        cluster={editing}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSaved={handleCreated}
      />

      <ClusterDeleteDialog
        open={Boolean(deleteTarget)}
        cluster={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDeleted={handleDeleted}
        onDeactivate={deactivateBlockedCluster}
        deactivating={statusSaving}
      />

      <ClusterMembersModal
        open={Boolean(membersFor)}
        cluster={membersFor}
        onClose={() => setMembersFor(null)}
        onChanged={load}
      />

      <ConfirmDialog
        open={Boolean(statusTarget)}
        title={statusTarget?.is_active ? 'Deactivate this cluster?' : 'Activate this cluster?'}
        description={
          statusTarget?.is_active
            ? 'Existing members keep their records, but the cluster cannot accept new ones until it is reactivated.'
            : 'The cluster will be able to accept new members again.'
        }
        confirmLabel={statusTarget?.is_active ? 'Deactivate' : 'Activate'}
        loading={statusSaving}
        onConfirm={toggleStatus}
        onCancel={() => setStatusTarget(null)}
      />
    </div>
  );
}

export default ClusterManagement;
