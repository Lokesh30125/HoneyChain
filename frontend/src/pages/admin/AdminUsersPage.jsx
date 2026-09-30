import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, RotateCcw, Search, ShieldCheck, Shuffle, UserCheck, UserX } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { PageHeader } from '@/components/common/PageHeader';
import { StatCard } from '@/components/common/StatCard';
import { VerificationBadge } from '@/components/beekeepers/VerificationBadge';
import { CreateUserDialog } from '@/components/admin/CreateUserDialog';
import { ChangeRoleDialog } from '@/components/admin/ChangeRoleDialog';
import { ALL_ROLE_OPTIONS } from '@/utils/validation';
import { formatDate, formatDateTime, titleCase } from '@/utils/format';
import { normaliseError } from '@/utils/errors';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/useToast';
import * as adminService from '@/services/adminService';

const PAGE_SIZE = 10;
const EMPTY_FILTERS = { search: '', role: '' };

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
];

/**
 * Identity directory and role management.
 *
 * Administrators can see every account, filter it, activate or deactivate it,
 * **create** an account for any of the ten roles, and **change** the role an
 * account holds. All four are audited, and all four are enforced by the API:
 * this page decides what a person is offered, never what they are allowed, and
 * an administrator is not offered a role change for their own account because
 * the backend refuses that outright (a role form must not be a way to promote
 * yourself).
 */
export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const toast = useToast();

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [summary, setSummary] = useState(null);
  const [statusTarget, setStatusTarget] = useState(null);
  const [statusSaving, setStatusSaving] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [roleTarget, setRoleTarget] = useState(null);

  const [detailId, setDetailId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { users, meta: pageMeta } = await adminService.listUsers({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        role: applied.role || undefined,
        isActive: statusFilter === '' ? undefined : statusFilter === 'active',
      });
      setRows(users);
      setMeta(pageMeta);
    } catch (caught) {
      setError(normaliseError(caught));
      setRows([]);
      setMeta(null);
    } finally {
      setLoading(false);
    }
  }, [page, applied, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let active = true;
    adminService
      .getPlatformSummary()
      .then((payload) => {
        if (active) setSummary(payload);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const openDetail = async (userId) => {
    setDetailId(userId);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      setDetail(await adminService.getUserDetail(userId));
    } catch (caught) {
      setDetailError(normaliseError(caught));
    } finally {
      setDetailLoading(false);
    }
  };

  const toggleStatus = async () => {
    if (!statusTarget) return;
    setStatusSaving(true);
    try {
      const result = await adminService.setUserStatus(
        statusTarget.id,
        !statusTarget.is_active,
        statusTarget.is_active ? 'Deactivated from the identity directory' : undefined,
      );
      toast.success(result.message || 'Account updated', statusTarget.email);
      setStatusTarget(null);
      load();
    } catch (caught) {
      toast.error('Could not change the account status', normaliseError(caught).message);
    } finally {
      setStatusSaving(false);
    }
  };

  const columns = useMemo(
    () => [
      {
        key: 'name',
        header: 'Name',
        render: (row) => (
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 truncate font-medium text-ink">
              {row.name}
              {row.id === currentUser?.id ? (
                <span className="text-xs font-normal text-ink-muted">(you)</span>
              ) : null}
            </p>
            <p className="truncate text-xs text-ink-muted">{row.phone || 'No phone on record'}</p>
          </div>
        ),
      },
      { key: 'email', header: 'Email', render: (row) => <span className="text-ink-soft">{row.email}</span> },
      {
        key: 'role',
        header: 'Role',
        render: (row) => (
          <Badge variant={row.role === ROLES.ADMIN ? 'forest' : 'neutral'} size="sm">
            {row.role_label || titleCase(row.role)}
          </Badge>
        ),
      },
      {
        key: 'is_active',
        header: 'Status',
        render: (row) => (
          <Badge variant={row.is_active ? 'success' : 'danger'} size="sm">
            {row.is_active ? 'Active' : 'Inactive'}
          </Badge>
        ),
      },
      { key: 'created_at', header: 'Registered', render: (row) => formatDate(row.created_at) },
      {
        key: 'last_login_at',
        header: 'Last login',
        render: (row) => (row.last_login_at ? formatDateTime(row.last_login_at) : 'Never'),
      },
      {
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="secondary" onClick={() => openDetail(row.id)}>
              View
            </Button>
            <Button
              size="sm"
              variant="ghost"
              leftIcon={<Shuffle size={14} />}
              // The API refuses a role change on your own account, so the
              // control is not offered for one either.
              disabled={row.id === currentUser?.id}
              title={
                row.id === currentUser?.id
                  ? 'You cannot change your own role'
                  : 'Change the role this account holds'
              }
              onClick={() => setRoleTarget(row)}
            >
              Change role
            </Button>
            <Button
              size="sm"
              variant={row.is_active ? 'ghost' : 'secondary'}
              disabled={row.id === currentUser?.id}
              onClick={() => setStatusTarget(row)}
            >
              {row.is_active ? 'Deactivate' : 'Activate'}
            </Button>
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [currentUser?.id],
  );

  const detailAccount = detail?.user;

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'Users' }]} />
      <PageHeader
        title="Users"
        description="Every account on the platform, with the role that governs what it can reach."
        actions={
          <>
            <Button to="/admin/beekeepers" variant="secondary" size="sm">
              Beekeeper directory
            </Button>
            <Button
              size="sm"
              leftIcon={<Plus size={15} />}
              onClick={() => setCreateOpen(true)}
            >
              Create user
            </Button>
          </>
        }
      />

      {summary ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Accounts" value={summary.users.total} icon={<ShieldCheck size={16} />} />
          <StatCard
            label="Active"
            value={summary.users.active}
            tone="forest"
            icon={<UserCheck size={16} />}
          />
          <StatCard
            label="Inactive"
            value={summary.users.inactive}
            icon={<UserX size={16} />}
          />
          <StatCard
            label="Beekeepers"
            value={summary.beekeepers.total}
            tone="honey"
            helper="Registered apiaries"
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
              label="Search"
              name="search"
              placeholder="Name, email or phone"
              leftIcon={<Search size={15} />}
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
              containerClassName="lg:col-span-2"
            />
            <Select
              label="Role"
              name="role"
              placeholder="All roles"
              options={ALL_ROLE_OPTIONS}
              value={filters.role}
              onChange={(event) => setFilters((prev) => ({ ...prev, role: event.target.value }))}
            />
            <Select
              label="Status"
              name="status"
              placeholder="Any status"
              options={STATUS_OPTIONS}
              value={statusFilter}
              onChange={(event) => {
                setPage(1);
                setStatusFilter(event.target.value);
              }}
            />
            <div className="flex items-end gap-2 lg:col-span-4">
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
        emptyTitle="No accounts found"
        emptyDescription="Adjust the search or filters. New registrations appear here immediately."
      />

      {/* Account detail — read-only review of one account and its recent activity. */}
      <Modal
        open={Boolean(detailId)}
        onClose={() => setDetailId(null)}
        size="lg"
        title={detailAccount ? detailAccount.name : 'Account'}
        description={detailAccount?.email}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDetailId(null)}>
              Close
            </Button>
            <Button
              leftIcon={<Shuffle size={15} />}
              disabled={detailAccount?.id === currentUser?.id}
              title={
                detailAccount?.id === currentUser?.id
                  ? 'You cannot change your own role'
                  : undefined
              }
              onClick={() => {
                setRoleTarget(detailAccount);
                setDetailId(null);
              }}
            >
              Change role
            </Button>
          </>
        }
      >
        {detailLoading ? <LoadingState message="Loading account…" /> : null}
        {detailError ? (
          <ErrorState error={detailError} onRetry={() => detailId && openDetail(detailId)} />
        ) : null}

        {detailAccount ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={detailAccount.role === ROLES.ADMIN ? 'forest' : 'neutral'} size="sm">
                Role: {detailAccount.role_label || titleCase(detailAccount.role)}
              </Badge>
              <Badge variant={detailAccount.is_active ? 'success' : 'danger'} size="sm">
                {detailAccount.is_active ? 'Active' : 'Inactive'}
              </Badge>
              <Badge variant={detailAccount.is_verified ? 'info' : 'neutral'} size="sm">
                {detailAccount.is_verified ? 'Contact verified' : 'Contact not verified'}
              </Badge>
            </div>

            <dl className="grid gap-3 sm:grid-cols-3">
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-muted">Phone</dt>
                <dd className="mt-0.5 text-sm text-ink">{detailAccount.phone || '—'}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-muted">Location</dt>
                <dd className="mt-0.5 text-sm text-ink">
                  {[detailAccount.district, detailAccount.state].filter(Boolean).join(', ') || '—'}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-muted">Organisation</dt>
                <dd className="mt-0.5 text-sm text-ink">{detailAccount.organization || '—'}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-muted">Registered</dt>
                <dd className="mt-0.5 text-sm text-ink">{formatDateTime(detailAccount.created_at)}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-ink-muted">Last sign-in</dt>
                <dd className="mt-0.5 text-sm text-ink">
                  {detailAccount.last_login_at ? formatDateTime(detailAccount.last_login_at) : 'Never'}
                </dd>
              </div>
            </dl>

            {detail.beekeeper ? (
              <section className="rounded-lg border border-sand-200 bg-sand-100/40 p-3">
                <h3 className="text-sm font-semibold text-ink">Beekeeper record</h3>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm text-ink">
                    {detail.beekeeper.beekeeper_code}
                  </span>
                  <VerificationBadge status={detail.beekeeper.verification_status} size="sm" />
                </div>
                <p className="mt-1.5 text-sm text-ink-soft">
                  {[
                    detail.beekeeper.district,
                    detail.beekeeper.state,
                    detail.beekeeper.number_of_hives != null
                      ? `${detail.beekeeper.number_of_hives} hives`
                      : null,
                    detail.beekeeper.cluster_name,
                  ]
                    .filter(Boolean)
                    .join(' · ') || 'No apiary details recorded.'}
                </p>
                <Button
                  to={`/admin/beekeepers?beekeeper=${detail.beekeeper.id}`}
                  variant="secondary"
                  size="sm"
                  className="mt-3"
                >
                  Open in directory
                </Button>
              </section>
            ) : null}

            <section>
              <h3 className="text-sm font-semibold text-ink">Recent activity</h3>
              {detail.recent_activity?.length ? (
                <ul className="mt-2 space-y-2">
                  {detail.recent_activity.map((entry) => (
                    <li
                      key={entry.id}
                      className="rounded-lg border border-sand-200 px-3 py-2 text-sm"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-ink">{titleCase(entry.action)}</span>
                        <span className="text-xs text-ink-muted">
                          {formatDateTime(entry.created_at)}
                        </span>
                      </div>
                      {entry.description ? (
                        <p className="mt-0.5 text-xs text-ink-soft">{entry.description}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-ink-muted">No recorded activity yet.</p>
              )}
              <Button to="/admin/audit-logs" variant="link" size="sm" className="mt-3">
                Open the full audit log
              </Button>
            </section>
          </div>
        ) : null}
      </Modal>

      <CreateUserDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setPage(1);
          load();
        }}
      />

      <ChangeRoleDialog
        open={Boolean(roleTarget)}
        account={roleTarget}
        onClose={() => setRoleTarget(null)}
        onChanged={() => load()}
      />

      <ConfirmDialog
        open={Boolean(statusTarget)}
        title={statusTarget?.is_active ? 'Deactivate this account?' : 'Activate this account?'}
        description={
          statusTarget?.is_active
            ? `${statusTarget?.email} will be signed out and cannot sign in again until reactivated. Their records are kept.`
            : `${statusTarget?.email} will be able to sign in again.`
        }
        confirmLabel={statusTarget?.is_active ? 'Deactivate' : 'Activate'}
        variant={statusTarget?.is_active ? 'danger' : 'primary'}
        loading={statusSaving}
        onConfirm={toggleStatus}
        onCancel={() => setStatusTarget(null)}
      />

      <p className="text-xs text-ink-muted">
        New accounts for operational roles — laboratory technicians, processors, collection
        centres, packaging units, distributors, retailers and KVIC officers — are created here with{' '}
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="underline decoration-honey-400"
        >
          Create user
        </button>
        . Self-registration stays limited to beekeepers and consumers. Looking for apiary records?
        The{' '}
        <Link to="/admin/beekeepers" className="underline decoration-honey-400">
          beekeeper directory
        </Link>{' '}
        lists them with verification status.
      </p>
    </div>
  );
}
