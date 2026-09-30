import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Building2, Clock, Filter, RotateCcw, Search, ShieldCheck, Users } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { DataTable } from '@/components/common/DataTable';
import { StatCard } from '@/components/common/StatCard';
import { BeekeeperDetailModal } from '@/components/beekeepers/BeekeeperDetailModal';
import { VerificationBadge } from '@/components/beekeepers/VerificationBadge';
import { VerificationDialog } from '@/components/beekeepers/VerificationDialog';
import { VERIFICATION_STATUSES } from '@/constants/api';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as beekeeperService from '@/services/beekeeperService';

const PAGE_SIZE = 10;

const EMPTY_FILTERS = { search: '', district: '', state: '', verificationStatus: '' };

/**
 * Beekeeper directory.
 *
 * Shared by the administrator and KVIC screens: the table, filters and
 * verification flow are identical, and only the surrounding page differs. Every
 * number shown comes from the API — an empty platform renders zeros and empty
 * states rather than placeholder figures.
 */
export function BeekeeperDirectory() {
  const toast = useToast();

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);

  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [options, setOptions] = useState({ districts: [], states: [] });
  const [summary, setSummary] = useState(null);

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const [detailId, setDetailId] = useState(null);

  const [verifyTarget, setVerifyTarget] = useState(null);
  const [searchParams, setSearchParams] = useSearchParams();
  // Deep link used by the account detail view: /admin/beekeepers?beekeeper=<id>
  const deepLinkId = searchParams.get('beekeeper');
  const openedDeepLink = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { beekeepers, meta: pageMeta } = await beekeeperService.listBeekeepers({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        district: applied.district || undefined,
        state: applied.state || undefined,
        verificationStatus: applied.verificationStatus || undefined,
      });
      setRows(beekeepers);
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
    (async () => {
      try {
        const [filterOptions, counts] = await Promise.all([
          beekeeperService.getFilterOptions(),
          beekeeperService.getBeekeeperSummary(),
        ]);
        if (!active) return;
        setOptions(filterOptions);
        setSummary(counts);
      } catch {
        // Filters and counts are conveniences; the table still works without them.
        if (active) setOptions({ districts: [], states: [] });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const openDetail = async (beekeeperId) => {
    setDetailId(beekeeperId);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const payload = await beekeeperService.getBeekeeper(beekeeperId);
      setDetail(payload);
    } catch (caught) {
      setDetailError(normaliseError(caught));
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (!deepLinkId || openedDeepLink.current) return;
    openedDeepLink.current = true;
    openDetail(deepLinkId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkId]);

  const applyFilters = (event) => {
    event.preventDefault();
    setPage(1);
    setApplied(filters);
  };

  const resetFilters = () => {
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setPage(1);
  };

  const columns = useMemo(
    () => [
      {
        key: 'beekeeper_code',
        header: 'Beekeeper ID',
        render: (row) => <span className="font-medium text-ink">{row.beekeeper_code}</span>,
      },
      {
        key: 'name',
        header: 'Name',
        render: (row) => (
          <div className="min-w-0">
            <p className="truncate font-medium text-ink">{row.name}</p>
            <p className="truncate text-xs text-ink-muted">{row.email}</p>
          </div>
        ),
      },
      {
        key: 'district',
        header: 'Location',
        render: (row) =>
          [row.village, row.district, row.state].filter(Boolean).join(', ') || '—',
      },
      { key: 'number_of_hives', header: 'Hives', render: (row) => row.number_of_hives ?? '—' },
      {
        key: 'cluster_name',
        header: 'Cluster',
        render: (row) => row.cluster_name || <span className="text-ink-muted">Unassigned</span>,
      },
      {
        key: 'verification_status',
        header: 'Verification',
        render: (row) => <VerificationBadge status={row.verification_status} size="sm" />,
      },
      {
        key: 'actions',
        header: '',
        align: 'right',
        render: (row) => (
          <Button size="sm" variant="secondary" onClick={() => openDetail(row.id)}>
            View
          </Button>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-5">
      {summary ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Beekeepers" value={summary.total} icon={<Users size={16} />} />
          <StatCard
            label="Verified"
            value={summary.by_verification_status?.VERIFIED ?? 0}
            helper="Details confirmed by an officer"
            icon={<ShieldCheck size={16} />}
            tone="forest"
          />
          <StatCard
            label="Awaiting review"
            value={
              (summary.by_verification_status?.PENDING ?? 0) +
              (summary.by_verification_status?.UNDER_REVIEW ?? 0)
            }
            helper="Pending or under review"
            icon={<Clock size={16} />}
            tone="honey"
          />
          <StatCard
            label="In a cluster"
            value={summary.assigned_to_cluster}
            icon={<Building2 size={16} />}
          />
        </div>
      ) : null}

      <Card>
        <CardBody>
          <form onSubmit={applyFilters} className="grid gap-3 lg:grid-cols-5">
            <Input
              label="Search"
              name="search"
              placeholder="Beekeeper ID, name or email"
              leftIcon={<Search size={15} />}
              value={filters.search}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
              containerClassName="lg:col-span-2"
            />
            <Select
              label="District"
              name="district"
              placeholder="All districts"
              options={(options.districts || []).map((value) => ({ value, label: value }))}
              value={filters.district}
              onChange={(event) => setFilters((prev) => ({ ...prev, district: event.target.value }))}
            />
            <Select
              label="State"
              name="state"
              placeholder="All states"
              options={(options.states || []).map((value) => ({ value, label: value }))}
              value={filters.state}
              onChange={(event) => setFilters((prev) => ({ ...prev, state: event.target.value }))}
            />
            <Select
              label="Verification"
              name="verification_status"
              placeholder="Any status"
              options={VERIFICATION_STATUSES}
              value={filters.verificationStatus}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, verificationStatus: event.target.value }))
              }
            />
            <div className="flex items-end gap-2 lg:col-span-5">
              <Button type="submit" size="sm" leftIcon={<Filter size={15} />}>
                Apply filters
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                leftIcon={<RotateCcw size={15} />}
                onClick={resetFilters}
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
        error={null}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        onRowClick={(row) => openDetail(row.id)}
        emptyTitle="No beekeepers found"
        emptyDescription="Once beekeepers register — or when the current filters match more records — they appear here."
      />

      <BeekeeperDetailModal
        open={Boolean(detailId)}
        detail={detail}
        loading={detailLoading}
        error={detailError}
        onRetry={() => detailId && openDetail(detailId)}
        onClose={() => {
          setDetailId(null);
          setDetail(null);
          if (deepLinkId) {
            searchParams.delete('beekeeper');
            setSearchParams(searchParams, { replace: true });
          }
        }}
        onVerify={(record, allowedNext) => setVerifyTarget({ record, allowedNext })}
      />

      <VerificationDialog
        open={Boolean(verifyTarget)}
        beekeeper={verifyTarget?.record}
        allowedNext={verifyTarget?.allowedNext || []}
        onClose={() => setVerifyTarget(null)}
        onCompleted={() => {
          toast.info('Verification history updated');
          load();
          if (detailId) openDetail(detailId);
          beekeeperService
            .getBeekeeperSummary()
            .then(setSummary)
            .catch(() => undefined);
        }}
      />
    </div>
  );
}

export default BeekeeperDirectory;
