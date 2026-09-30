import { useCallback, useEffect, useState } from 'react';
import { Activity, Bell, Cpu, Hexagon, Plug, Radio } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { PageHeader } from '@/components/common/PageHeader';
import { StatCard } from '@/components/common/StatCard';
import { DeviceDetailPanel } from '@/components/iot/DeviceDetailPanel';
import { DeviceTable } from '@/components/iot/DeviceTable';
import { DevicePairingModal } from '@/components/iot/DevicePairingModal';
import { formatDateTime } from '@/utils/format';
import { normaliseError } from '@/utils/errors';
import * as hiveService from '@/services/hiveService';
import * as iotService from '@/services/iotService';
import { useToast } from '@/hooks/useToast';

const PAGE_SIZE = 10;
const EMPTY_FILTERS = { search: '', status: '' };

/**
 * IoT monitoring: fleet counters, ingest state, the device list and the detail
 * panel for the selected device.
 *
 * Three things this screen is careful about:
 *
 *  1. **Ingest state is shown, not hidden.** If no MQTT broker is configured it
 *     says so — otherwise "no data" looks like a broken device.
 *  2. **Empty means empty.** With no telemetry the tiles read 0 and the tables
 *     say nothing has arrived; no sample values are invented.
 *  3. **Simulated data is labelled.** Counts include readings from the
 *     simulator, and the detail panel names each reading's source.
 */
export function MonitoringOverview({
  mode = 'owner',
  title = 'IoT monitoring',
  description = 'Devices on your hives, what they last reported, and whether telemetry is arriving.',
}) {
  const toast = useToast();
  const canEdit = mode === 'owner';

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);

  const [devices, setDevices] = useState([]);
  const [meta, setMeta] = useState(null);
  const [summary, setSummary] = useState(null);
  const [last, setLast] = useState(null);
  const [mqtt, setMqtt] = useState(null);
  const [hives, setHives] = useState([]);
  const [selected, setSelected] = useState(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pairingOpen, setPairingOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { devices: rows, meta: pageMeta } = await iotService.listDevices({
        page,
        pageSize: PAGE_SIZE,
        search: applied.search || undefined,
        status: applied.status || undefined,
      });
      setDevices(rows);
      setMeta(pageMeta);
      if (selected && !rows.some((row) => row.id === selected)) setSelected(null);
    } catch (caught) {
      setError(normaliseError(caught));
      setDevices([]);
    } finally {
      setLoading(false);
    }
    // `selected` is intentionally not a dependency: this must not re-run on click.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, applied, refreshKey]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      iotService.getMonitoringSummary(),
      iotService.getLastTelemetry(),
      iotService.getMqttHealth(),
      canEdit ? hiveService.listHives({ pageSize: 100 }) : Promise.resolve({ hives: [] }),
    ]).then(([summaryResult, lastResult, mqttResult, hivesResult]) => {
      if (cancelled) return;
      if (summaryResult.status === 'fulfilled') setSummary(summaryResult.value);
      if (lastResult.status === 'fulfilled') setLast(lastResult.value);
      if (mqttResult.status === 'fulfilled') setMqtt(mqttResult.value);
      if (hivesResult.value?.hives) setHives(hivesResult.value.hives);
    });
    return () => {
      cancelled = true;
    };
  }, [canEdit, refreshKey]);

  const refreshAll = () => setRefreshKey((key) => key + 1);

  const applyFilters = (event) => {
    event?.preventDefault?.();
    setPage(1);
    setApplied(filters);
  };

  const resetFilters = () => {
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setPage(1);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title={title}
        description={description}
        actions={
          <>
            <Button variant="secondary" onClick={refreshAll} leftIcon={<Activity size={16} aria-hidden="true" />}>
              Refresh
            </Button>
            {canEdit ? (
              <Button
                onClick={() => setPairingOpen(true)}
                leftIcon={<Plug size={16} aria-hidden="true" />}
                disabled={hives.length === 0}
              >
                Pair a device
              </Button>
            ) : null}
          </>
        }
      />

      <MqttStateBanner mqtt={mqtt} />
      <LastPacketBanner last={last} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Devices"
          value={summary?.total_devices ?? 0}
          helper={`${summary?.connected_devices ?? 0} reporting`}
          icon={<Cpu size={16} aria-hidden="true" />}
          loading={!summary}
          tone="honey"
        />
        <StatCard
          label="Offline"
          value={summary?.offline_devices ?? 0}
          helper={`No packet in ${Math.round((summary?.offline_threshold_seconds ?? 0) / 60)} min`}
          loading={!summary}
        />
        <StatCard
          label="Sensors collecting"
          value={summary?.sensors_active ?? 0}
          helper="Enabled across all devices"
          loading={!summary}
        />
        <StatCard
          label="Readings · last 24 h"
          value={summary?.readings_last_window ?? 0}
          helper={`Across ${summary?.total_devices ?? 0} paired device(s)`}
          icon={<Hexagon size={16} aria-hidden="true" />}
          loading={!summary}
        />
      </div>

      {summary?.warning_devices ? (
        <Alert variant="warning" title={`${summary.warning_devices} device(s) need attention`}>
          Those devices are reporting but degraded (currently: low battery). Open one to see its last
          packet.
        </Alert>
      ) : null}

      <DeviceTable
        devices={devices}
        loading={loading}
        error={error}
        onRetry={load}
        meta={meta}
        onPageChange={setPage}
        onSelect={(row) => setSelected(row.id)}
        selectedId={selected}
        filters={filters}
        onFiltersChange={setFilters}
        onApplyFilters={applyFilters}
        onResetFilters={resetFilters}
        emptyTitle={canEdit ? 'No devices paired yet' : 'No devices in scope'}
        emptyDescription={
          canEdit
            ? 'Register a hive, then pair an ESP32 node with it. The device appears here as soon as it is registered — and as online only after its first packet.'
            : 'No hives in this scope have a device paired.'
        }
      />

      {selected ? (
        <section className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">Selected device</h2>
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
              Close
            </Button>
          </div>
          <DeviceDetailPanel deviceId={selected} canEdit={canEdit} onChanged={refreshAll} />
        </section>
      ) : null}

      {canEdit ? (
        <DevicePairingModal
          open={pairingOpen}
          hives={hives}
          onClose={() => setPairingOpen(false)}
          onSaved={() => {
            refreshAll();
            toast.success('Device registered', 'It reports as offline until the first packet.');
          }}
        />
      ) : null}
    </div>
  );
}

/** Whether the platform is listening for device packets, stated plainly. */
function MqttStateBanner({ mqtt }) {
  if (!mqtt) return null;

  const tone = {
    connected: { variant: 'success', title: 'MQTT ingest is connected' },
    starting: { variant: 'info', title: 'MQTT ingest is starting' },
    stopped: { variant: 'warning', title: 'MQTT ingest is configured but not running' },
    not_configured: { variant: 'info', title: 'No MQTT broker is configured' },
  }[mqtt.status] || { variant: 'info', title: `MQTT ingest: ${mqtt.status}` };

  return (
    <Alert variant={tone.variant} title={tone.title}>
      {mqtt.status === 'not_configured' ? (
        <>
          Devices that publish over MQTT will not be received until a broker is configured. Telemetry
          can still be submitted over HTTP (<code>POST /api/v1/iot/telemetry</code>), and nothing on
          this screen is fabricated to fill the gap.
        </>
      ) : (
        <>
          {mqtt.broker ? <>Broker <code>{mqtt.broker}</code>. </> : null}
          {mqtt.last_message_at ? `Last message ${formatDateTime(mqtt.last_message_at)}. ` : 'No message received yet. '}
          {mqtt.detail || ''}
        </>
      )}
      {mqtt.stats ? (
        <span className="mt-1.5 flex flex-wrap gap-1.5">
          {Object.entries(mqtt.stats).map(([key, value]) => (
            <Badge key={key} variant="neutral" size="sm">
              {key}: {value}
            </Badge>
          ))}
        </span>
      ) : null}
    </Alert>
  );
}

/** The most recent packet anywhere in scope, or an honest empty state. */
function LastPacketBanner({ last }) {
  if (!last) return null;

  if (!last.has_data) {
    return (
      <Alert variant="info" title="No telemetry has been received yet">
        {last.message || 'Once a device reports, its latest values appear here.'}
      </Alert>
    );
  }

  return (
    <div className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-medium text-ink">
          <Radio size={16} aria-hidden="true" />
          Last packet from {last.device_id}
          {last.hive_code ? ` on ${last.hive_code}` : ''}
        </p>
        <span className="flex items-center gap-2 text-xs text-ink-muted">
          <Bell size={14} aria-hidden="true" />
          {formatDateTime(last.timestamp)} · {last.source}
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[
          ['Temperature', last.temperature, '°C'],
          ['Humidity', last.humidity, '%'],
          ['Weight', last.weight, 'kg'],
          ['Vibration', last.vibration, 'g'],
          ['Acoustic', last.acoustic_level, 'dB'],
        ].map(([label, value, unit]) => (
          <div key={label} className="rounded-lg bg-sand-100/60 px-3 py-2">
            <p className="text-xs text-ink-muted">{label}</p>
            <p className="text-sm font-semibold text-ink">
              {value === null || value === undefined ? '—' : `${Number(value).toFixed(2)} ${unit}`}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-ink-muted">
        Source: {last.source}
        {last.source === 'SIMULATOR' ? ' — produced by the development simulator, not hardware.' : ''}
      </p>
    </div>
  );
}

export default MonitoringOverview;
