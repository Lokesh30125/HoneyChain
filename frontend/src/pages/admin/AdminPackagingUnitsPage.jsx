import { useCallback, useEffect, useMemo, useState } from 'react';
import { Building2, Factory, Pencil, Plus, RotateCcw, Search, UserCog, Users } from 'lucide-react';

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
import { UnitFormDialog } from '@/components/packaging/UnitFormDialog';
import { UnitMembersModal } from '@/components/packaging/UnitMembersModal';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as packagingService from '@/services/packagingService';

const PAGE_SIZE = 10;
const EMPTY_FILTERS = { search: '', status: '' };

/**
 * Administration → Packaging Units.
 *
 * The register of the facilities that pack and code honey. It exists because the
 * packaging role needs somewhere to work: a run has to name the unit that did the
 * work, and an operator has to belong to one. Before this screen there was no way
 * to create either from the platform, which is why the packaging workspace used to
 * say it had no unit registered — a sentence that was true and had no remedy.
 *
 * Everything shown here is read from the database and every figure is counted: the
 * unit code is issued by the server, the people count is the accounts attached to
 * the unit, and the run count is the packaging runs recorded against it.
 *
 * A packaging unit is **not** created through public registration. It is a
 * registered business, registered by an administrator, which is why it lives in
 * Administration rather than in the menu everyone sees.
 */
export default function AdminPackagingUnitsPage() {
  const toast = useToast();

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [membersFor, setMembersFor] = useState(null);
  const [justRegistered, setJustRegistered] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { units, meta: pageMeta } = await packagingService.listUnits({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
      });
      const filtered = applied.status
        ? units.filter((unit) => unit.status === applied.status)
        : units;
      setRows(filtered);
      setMeta(pageMeta);
      return true;
    } catch (caught) {
      setError(normaliseError(caught));
      setRows([]);
      return false;
    } finally {
      setLoading(false);
    }
  }, [page, applied]);

  useEffect(() => {
    load();
  }, [load]);

  const totals = useMemo(
    () => ({
      listed: meta?.total_items ?? rows.length,
      active: rows.filter((unit) => unit.status === 'ACTIVE').length,
      people: rows.reduce((sum, unit) => sum + (unit.member_count || 0), 0),
      runs: rows.reduce((sum, unit) => sum + (unit.packaging_run_count || 0), 0),
    }),
    [meta, rows],
  );

  const columns = useMemo(
    () => [
      {
        key: 'name',
        header: 'Unit',
        render: (row) => (
          <div className="min-w-0">
            <p className="truncate font-medium text-ink">{row.name}</p>
            <p className="truncate font-mono text-xs text-ink-muted">{row.unit_code}</p>
          </div>
        ),
      },
      {
        key: 'registration_identifier',
        header: 'Registration',
        render: (row) => (
          <span className="text-sm text-ink-soft">{row.registration_identifier || '—'}</span>
        ),
      },
      {
        key: 'location',
        header: 'Where',
        render: (row) => (
          <div className="min-w-0">
            <p className="truncate text-sm text-ink-soft">
              {[row.location, row.district].filter(Boolean).join(', ') || '—'}
            </p>
            <p className="truncate text-xs text-ink-muted">{row.state || ''}</p>
          </div>
        ),
      },
      {
        key: 'contact',
        header: 'Contact',
        render: (row) => (
          <div className="min-w-0">
            <p className="truncate text-sm text-ink-soft">{row.contact_email || '—'}</p>
            <p className="truncate text-xs text-ink-muted">{row.contact_phone || ''}</p>
          </div>
        ),
      },
      {
        key: 'member_count',
        header: 'People',
        align: 'right',
        render: (row) => row.member_count ?? 0,
      },
      {
        key: 'packaging_run_count',
        header: 'Runs',
        align: 'right',
        render: (row) => row.packaging_run_count ?? 0,
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => (
          <Badge variant={row.status === 'ACTIVE' ? 'success' : 'neutral'} size="sm">
            {row.status_label || row.status}
          </Badge>
        ),
      },
      {
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => (
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setMembersFor(row)}
              data-testid={`unit-members-${row.unit_code}`}
            >
              <Users size={14} className="mr-1" aria-hidden="true" /> People
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(row);
                setFormOpen(true);
              }}
              aria-label={`Edit ${row.unit_code}`}
            >
              <Pencil size={14} aria-hidden="true" />
            </Button>
          </div>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[{ label: 'Administration', to: '/admin' }, { label: 'Packaging Units' }]}
      />
      <PageHeader
        title="Packaging Units"
        description="The facilities that pack and code honey, and the accounts that work at each one. A packaging operator sees their own unit at sign-in and can pack under no other."
        actions={
          <Button
            size="sm"
            leftIcon={<Plus size={15} aria-hidden="true" />}
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
            data-testid="register-packaging-unit"
          >
            Register unit
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Units registered" value={totals.listed} icon={<Factory size={16} />} />
        <StatCard
          label="Active on this page"
          value={totals.active}
          tone="forest"
          helper="Taking packaging work"
        />
        <StatCard
          label="Accounts attached"
          value={totals.people}
          icon={<UserCog size={16} />}
          helper="Operators who work at a unit"
        />
        <StatCard
          label="Packaging runs"
          value={totals.runs}
          tone="honey"
          helper="Recorded against these units"
        />
      </div>

      <Card>
        <CardBody>
          <form
            className="grid gap-3 lg:grid-cols-4"
            onSubmit={(event) => {
              event.preventDefault();
              setPage(1);
              setApplied(filters);
            }}
          >
            <Input
              label="Search"
              name="search"
              placeholder="Name, code or registration number"
              leftIcon={<Search size={15} />}
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
            />
            <Select
              label="Status"
              name="status"
              placeholder="Any status"
              options={[
                { value: 'ACTIVE', label: 'Active' },
                { value: 'INACTIVE', label: 'Inactive' },
              ]}
              value={filters.status}
              onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
            />
            <div className="flex flex-wrap items-end gap-2 lg:col-span-2">
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

      {justRegistered ? (
        <Alert
          variant="success"
          title={`Unit ${justRegistered.unit_code} registered`}
          onDismiss={() => setJustRegistered(null)}
        >
          {justRegistered.name} is now available when a packaging account is created or edited.
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
        emptyTitle="No packaging unit registered"
        emptyDescription="Register the facility that packs the honey. Without one, a packaging account has nowhere to work and the run form has nothing to record against."
      />

      <p className="flex items-start gap-2 text-xs text-ink-muted">
        <Building2 size={14} className="mt-0.5 flex-none" aria-hidden="true" />
        A unit is a registry record, not an account: it is never created through public registration,
        and it is never deleted while runs are recorded against it — a facility that stops working is
        set to inactive so its packing history keeps its place.
      </p>

      <UnitFormDialog
        open={formOpen}
        unit={editing}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSaved={async (saved) => {
          setJustRegistered(saved);
          const refreshed = await load();
          if (!refreshed) {
            toast.warning(
              `Unit ${saved?.unit_code || ''} was registered, but the list could not be refreshed`,
            );
          }
        }}
      />

      <UnitMembersModal
        open={Boolean(membersFor)}
        unit={membersFor}
        onClose={() => setMembersFor(null)}
        onChanged={load}
      />
    </div>
  );
}
