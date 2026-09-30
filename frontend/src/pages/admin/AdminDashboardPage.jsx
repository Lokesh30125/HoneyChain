import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BarChart, Bar, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Building2, ClipboardList, Cpu, Hexagon, Radio, ScrollText, ShieldCheck, UserCog, Users } from 'lucide-react';

import { DataTable } from '@/components/common/DataTable';
import { ErrorState } from '@/components/common/ErrorState';
import { PageHeader } from '@/components/common/PageHeader';
import { BlockchainHealthCard } from '@/components/blockchain/BlockchainHealthCard';
import { StatCard } from '@/components/common/StatCard';
import { StatusBadge } from '@/components/common/StatusBadge';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { roleLabel } from '@/constants/roles';
import * as adminService from '@/services/adminService';
import * as hiveService from '@/services/hiveService';
import * as iotService from '@/services/iotService';

/**
 * Administrator workspace.
 *
 * Phase 1 reports only what the backend can genuinely answer: account counts by
 * role and the implementation status of each module. The role distribution chart
 * is rendered from real `GET /admin/summary` data.
 */
const ROLE_COLORS = ['#2C6141', '#3D7A52', '#5E9670', '#8FBB9B', '#D99A2B', '#E9AE37', '#B87A1E'];

/** Module keys come from the API; acronyms must not be title-cased blindly. */
const MODULE_LABELS = {
  user_management: 'User & role management',
  beekeeping: 'Beekeeper registry & verification',
  hives: 'Hive registry',
  iot: 'IoT monitoring',
  ai: 'AI assistance',
  blockchain: 'Blockchain traceability',
  supply_chain: 'Supply chain & QR',
};

/** Modules with a working screen today, so the status list links somewhere real. */
const MODULE_ROUTES = {
  hives: '/admin/hives',
  iot: '/admin/iot',
  beekeeping: '/admin/beekeepers',
  user_management: '/admin/users',
  ai: '/admin/insights',
  blockchain: '/admin/blockchain',
  supply_chain: '/admin/batches',
};

export default function AdminDashboardPage() {
  const [summary, setSummary] = useState(null);
  const [summaryError, setSummaryError] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(true);

  // Hive & IoT totals come from the Phase-3 endpoints; they degrade to zero
  // rather than blocking the rest of the page if they fail.
  const [hiveSummary, setHiveSummary] = useState(null);
  const [iotSummary, setIotSummary] = useState(null);

  const [users, setUsers] = useState([]);
  const [meta, setMeta] = useState(null);
  const [usersError, setUsersError] = useState(null);
  const [usersLoading, setUsersLoading] = useState(true);
  const [page, setPage] = useState(1);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      setSummary(await adminService.getPlatformSummary());
    } catch (error) {
      setSummaryError(error);
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  const loadUsers = useCallback(async (nextPage) => {
    setUsersLoading(true);
    setUsersError(null);
    try {
      const result = await adminService.listUsers({ page: nextPage, pageSize: 10 });
      setUsers(result.users);
      setMeta(result.meta);
    } catch (error) {
      setUsersError(error);
    } finally {
      setUsersLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([hiveService.getHiveSummary(), iotService.getMonitoringSummary()]).then(
      ([hives, iot]) => {
        if (cancelled) return;
        if (hives.status === 'fulfilled') setHiveSummary(hives.value);
        if (iot.status === 'fulfilled') setIotSummary(iot.value);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    loadUsers(page);
  }, [loadUsers, page]);

  const byRole = summary?.users?.by_role || {};
  const chartData = Object.entries(byRole)
    .map(([role, count]) => ({ role: roleLabel(role), short: roleLabel(role).split(' ')[0], count }))
    .sort((a, b) => b.count - a.count);

  const columns = [
    {
      key: 'name',
      header: 'Name',
      render: (row) => (
        <div>
          <p className="font-medium text-ink">{row.name}</p>
          <p className="text-xs text-ink-muted">{row.email}</p>
        </div>
      ),
    },
    { key: 'role', header: 'Role', render: (row) => <Badge variant="forest" size="sm">{row.role_label}</Badge> },
    {
      key: 'status',
      header: 'Status',
      render: (row) => <StatusBadge status={row.account_status} size="sm" />,
    },
    {
      key: 'district',
      header: 'District',
      render: (row) => row.district || <span className="text-ink-muted">—</span>,
    },
    {
      key: 'created_at',
      header: 'Joined',
      render: (row) => new Date(row.created_at).toLocaleDateString(),
    },
  ];

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration' }]} />
      <PageHeader
        title="Administration"
        description="Platform-wide visibility across accounts, hives, devices and the honey supply chain — every figure is read from the records."
        badge={<Badge variant="honey" size="sm">Administrator</Badge>}
        actions={
          <>
            <Button to="/admin/hives" variant="secondary" size="sm" leftIcon={<Hexagon size={15} />}>
              Hives
            </Button>
            <Button to="/admin/iot" variant="secondary" size="sm" leftIcon={<Radio size={15} />}>
              IoT
            </Button>
            <Button to="/admin/users" variant="secondary" size="sm" leftIcon={<UserCog size={15} />}>
              Users
            </Button>
            <Button
              to="/admin/beekeepers"
              variant="secondary"
              size="sm"
              leftIcon={<ClipboardList size={15} />}
            >
              Beekeepers
            </Button>
            <Button
              to="/admin/audit-logs"
              variant="secondary"
              size="sm"
              leftIcon={<ScrollText size={15} />}
            >
              Audit log
            </Button>
          </>
        }
      />

      {summaryError ? (
        <Card>
          <ErrorState error={summaryError} onRetry={loadSummary} />
        </Card>
      ) : (
        <section aria-label="Platform summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Registered accounts"
            value={summary?.users?.total ?? '—'}
            helper="All roles"
            icon={<Users size={16} />}
            loading={summaryLoading}
          />
          <StatCard
            label="Active accounts"
            value={summary?.users?.active ?? '—'}
            helper="Enabled for sign-in"
            icon={<ShieldCheck size={16} />}
            tone="forest"
            loading={summaryLoading}
          />
          <StatCard
            label="Beekeepers"
            value={summary?.beekeepers?.total ?? '—'}
            helper={`${summary?.beekeepers?.by_verification_status?.VERIFIED ?? 0} verified`}
            icon={<ClipboardList size={16} />}
            tone="honey"
            loading={summaryLoading}
          />
          <StatCard
            label="Clusters"
            value={summary?.clusters?.total ?? '—'}
            helper={`${summary?.clusters?.active ?? 0} active`}
            icon={<Building2 size={16} />}
            loading={summaryLoading}
          />
          <StatCard
            label="Hives"
            value={hiveSummary?.total ?? '—'}
            helper={`${hiveSummary?.with_device ?? 0} paired with a device`}
            icon={<Hexagon size={16} />}
            tone="honey"
            loading={!hiveSummary}
          />
          <StatCard
            label="Devices reporting"
            value={iotSummary?.connected_devices ?? '—'}
            helper={`${iotSummary?.total_devices ?? 0} paired · ${iotSummary?.offline_devices ?? 0} offline`}
            icon={<Cpu size={16} />}
            tone="forest"
            loading={!iotSummary}
          />
        </section>
      )}

      {/* What the traceability chain has received from this platform, and what
          is still owed to it — real counts, read from the outbox. */}
      <BlockchainHealthCard />

      <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
        <Card>
          <CardHeader
            title="Accounts by role"
            description="Live counts from the platform summary endpoint."
            icon={<Users size={16} />}
          />
          <CardBody>
            {summaryLoading ? (
              <div className="h-56 animate-pulse rounded-lg bg-sand-100" aria-hidden="true" />
            ) : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: -18 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#EFE9DC" vertical={false} />
                    <XAxis
                      dataKey="short"
                      tick={{ fontSize: 11, fill: '#6F7D75' }}
                      interval={0}
                      angle={-30}
                      textAnchor="end"
                      height={60}
                    />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#6F7D75' }} />
                    <Tooltip
                      contentStyle={{
                        borderRadius: 8,
                        border: '1px solid #E1D9C8',
                        fontSize: 12,
                      }}
                      formatter={(value, _name, payload) => [`${value} account(s)`, payload?.payload?.role]}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {chartData.map((entry, index) => (
                        <Cell key={entry.role} fill={ROLE_COLORS[index % ROLE_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Module implementation status"
            description="HoneyChain is delivered in phases; this is the current state."
          />
          <CardBody>
            <ul className="divide-y divide-sand-200">
              {Object.entries(summary?.modules || {}).map(([module, state]) => {
                const label = MODULE_LABELS[module] || module.replace(/_/g, ' ');
                const to = state === 'available' ? MODULE_ROUTES[module] : undefined;
                return (
                  <li key={module} className="flex items-center justify-between gap-3 py-3">
                    {to ? (
                      <Link to={to} className="text-sm text-forest-700 hover:underline">
                        {label}
                      </Link>
                    ) : (
                      <span className="text-sm text-ink-soft">{label}</span>
                    )}
                    <StatusBadge status={state} size="sm" />
                  </li>
                );
              })}
              <li className="flex items-center justify-between gap-3 py-3">
                <span className="text-sm text-ink-soft">Authentication &amp; roles</span>
                <StatusBadge status="ok" size="sm" />
              </li>
            </ul>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Account directory"
          description="Newest registrations first. Status changes are recorded in the audit log."
        />
        <DataTable
          columns={columns}
          rows={users}
          loading={usersLoading}
          error={usersError}
          onRetry={() => loadUsers(page)}
          meta={meta}
          onPageChange={setPage}
          caption="HoneyChain accounts"
          emptyTitle="No accounts yet"
          emptyDescription="Accounts appear here as beekeepers and supply-chain partners register."
        />
      </Card>
    </div>
  );
}
