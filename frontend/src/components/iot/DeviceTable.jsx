import { useMemo } from 'react';
import { BatteryMedium, Radio, Search, Wifi } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { DataTable } from '@/components/common/DataTable';
import { StatusBadge } from '@/components/common/StatusBadge';
import { DEVICE_STATUSES } from '@/constants/hive';
import { formatDateTime } from '@/utils/format';

/**
 * Device list.
 *
 * Every column is a fact the API returned: the derived status, the battery
 * level from the last packet, when that packet arrived, and how many sensors
 * are collecting. Nothing is extrapolated — a device with no packets shows
 * "Never reported" rather than an assumed state.
 */
export function DeviceTable({
  devices = [],
  loading = false,
  error = null,
  onRetry,
  meta = null,
  onPageChange,
  onSelect,
  selectedId = null,
  filters,
  onFiltersChange,
  onApplyFilters,
  onResetFilters,
  emptyTitle = 'No devices yet',
  emptyDescription = 'Pair an ESP32 hive node with a hive to start collecting readings.',
}) {
  const statusOptions = useMemo(
    () => [{ value: '', label: 'All statuses' }, ...DEVICE_STATUSES],
    [],
  );

  const columns = useMemo(
    () => [
      {
        key: 'device_id',
        header: 'Device',
        render: (row) => (
          <div className="min-w-0">
            <p className="font-medium text-ink">{row.device_id}</p>
            <p className="truncate text-xs text-ink-muted">
              {row.device_name}
              {row.hive_code ? ` · ${row.hive_code}` : ''}
              {row.cluster_code ? ` · ${row.cluster_code}` : ''}
            </p>
          </div>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => (
          <div className="space-y-1">
            <StatusBadge status={row.status} size="sm" />
            <p className="text-[11px] text-ink-muted">
              {row.last_seen ? formatDateTime(row.last_seen) : 'Never reported'}
            </p>
          </div>
        ),
      },
      {
        key: 'battery',
        header: 'Battery',
        render: (row) => (
          <span className="flex items-center gap-1.5 text-xs text-ink-soft">
            <BatteryMedium size={14} aria-hidden="true" />
            {row.battery_level === null || row.battery_level === undefined
              ? '—'
              : `${row.battery_level}%`}
          </span>
        ),
      },
      {
        key: 'signal',
        header: 'Signal',
        render: (row) => (
          <span className="flex items-center gap-1.5 text-xs text-ink-soft">
            <Wifi size={14} aria-hidden="true" />
            {row.signal_strength === null || row.signal_strength === undefined
              ? '—'
              : `${row.signal_strength} dBm`}
          </span>
        ),
      },
      {
        key: 'sensors',
        header: 'Sensors',
        render: (row) => (
          <span className="text-xs text-ink-soft">
            {row.sensors_enabled}/{row.sensors_total} collecting
          </span>
        ),
      },
      {
        key: 'latest',
        header: 'Latest packet',
        render: (row) => (
          <span className="text-xs text-ink-soft">
            {row.latest_reading_at ? formatDateTime(row.latest_reading_at) : '—'}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-3">
      <form onSubmit={onApplyFilters} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Input
          name="device-search"
          placeholder="Search devices or hives"
          leftIcon={<Search size={16} aria-hidden="true" />}
          value={filters.search}
          onChange={(event) => onFiltersChange({ ...filters, search: event.target.value })}
        />
        <Select
          name="device-status"
          options={statusOptions}
          value={filters.status}
          onChange={(event) => onFiltersChange({ ...filters, status: event.target.value })}
        />
        {/* Apply and Reset share one column, exactly as on the hive registry:
            a lone button in a grid cell stretches to the full column width. */}
        <div className="flex gap-2">
          <Button type="submit" variant="secondary" fullWidth>
            Apply
          </Button>
          <Button
            variant="ghost"
            onClick={onResetFilters}
            aria-label="Reset filters"
            leftIcon={<Radio size={15} aria-hidden="true" />}
          >
            Reset
          </Button>
        </div>
      </form>

      <DataTable
        columns={columns}
        rows={devices}
        loading={loading}
        error={error}
        onRetry={onRetry}
        meta={meta}
        onPageChange={onPageChange}
        onRowClick={onSelect ? (row) => onSelect(row) : undefined}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
        caption="IoT devices"
        rowKey={(row) => row.id}
        className={selectedId ? 'rounded-card bg-honey-50/30' : ''}
      />
    </div>
  );
}

export default DeviceTable;
