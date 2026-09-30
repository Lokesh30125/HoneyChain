import { useCallback, useEffect, useState } from 'react';
import { QrCode, RefreshCw } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { DataTable } from '@/components/common/DataTable';
import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { PackageQrLabel } from '@/components/blockchain/PackageQrLabel';
import { ROLES } from '@/constants/roles';
import * as packagingService from '@/services/packagingService';
import { normaliseError } from '@/utils/errors';
import { formatDate } from '@/utils/format';

/**
 * QR Code Generation — the packages this unit packed, and each one's label.
 *
 * Every row is a real package from the register (`GET /packages`, scoped to the
 * caller's facility by the server). "Generate QR" issues the package's QR
 * identity through the existing blockchain endpoint — once: issuing again
 * returns the same identity, so a refresh or a second click never creates
 * another QR. "View QR" re-opens the label that already exists.
 */
export default function QrGenerationPage() {
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ page: 1, search: '' });
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await packagingService.listPackages({
        page: filters.page,
        pageSize: 20,
        search: filters.search || undefined,
      });
      setRows(payload.packages || []);
      setMeta(payload.meta || null);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

  const columns = [
    {
      key: 'package_code',
      header: 'Package ID',
      render: (row) => <span className="font-mono text-sm font-medium text-ink">{row.package_code}</span>,
    },
    { key: 'batch_code', header: 'Batch', render: (row) => <span className="font-mono text-xs">{row.batch_code}</span> },
    {
      key: 'size',
      header: 'Size',
      render: (row) => `${Number(row.package_size).toLocaleString()} ${row.unit_label || row.unit}`,
    },
    { key: 'packaging_date', header: 'Packed', render: (row) => formatDate(row.packaging_date) },
    { key: 'status', header: 'Status', render: (row) => <Badge size="sm">{row.status_label || row.status}</Badge> },
    {
      key: 'qr',
      header: 'QR',
      render: (row) =>
        row.qr_issued ? (
          <span className="font-mono text-xs text-ink-soft">{row.qr_id}</span>
        ) : (
          <span className="text-xs text-ink-muted">Not generated</span>
        ),
    },
    {
      key: 'actions',
      header: 'Actions',
      render: (row) =>
        row.status === 'CANCELLED' ? (
          <span className="text-xs text-ink-muted">Cancelled</span>
        ) : (
          <Button
            size="sm"
            variant={row.qr_issued ? 'secondary' : 'primary'}
            onClick={() => setSelected(row)}
            data-testid={`qr-${row.package_code}`}
          >
            {row.qr_issued ? 'View QR' : 'Generate QR'}
          </Button>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="QR Code Generation"
        description="Each package's QR identity, issued once and read from the package record."
        requiredRoles={[ROLES.PACKAGING_UNIT]}
      />
      <Card>
        <CardHeader
          title="Packages"
          description="Generate a package's QR, or open the label that was already issued."
          icon={<QrCode size={16} />}
          action={
            <Button size="sm" variant="secondary" leftIcon={<RefreshCw size={14} />} onClick={load} loading={loading}>
              Refresh
            </Button>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Search"
              name="qr_search"
              placeholder="Package or batch code"
              value={filters.search}
              onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value, page: 1 }))}
            />
          </div>
          <DataTable
            columns={columns}
            rows={rows}
            loading={loading}
            error={error}
            onRetry={load}
            meta={meta}
            onPageChange={(page) => setFilters((current) => ({ ...current, page }))}
            emptyTitle="No packages yet"
            emptyDescription="Packages appear here when a packaging run is completed."
            caption="Packages and their QR labels"
          />
        </CardBody>
      </Card>

      <Modal
        open={Boolean(selected)}
        onClose={() => {
          setSelected(null);
          load();
        }}
        title={selected ? `QR label — ${selected.package_code}` : ''}
        size="md"
      >
        {selected ? (
          <PackageQrLabel packageId={selected.id} packageCode={selected.package_code} onIssued={load} />
        ) : null}
      </Modal>
    </div>
  );
}
