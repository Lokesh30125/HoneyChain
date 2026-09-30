import { useCallback, useEffect, useState } from 'react';
import { Copy, HeartPulse, Radio, Send, Trash2, Wrench } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { StatusBadge } from '@/components/common/StatusBadge';
import { SensorConfigTable } from '@/components/iot/SensorConfigTable';
import { SensorSnapshotGrid } from '@/components/iot/SensorSnapshotGrid';
import { TestReadingModal } from '@/components/iot/TestReadingModal';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';
import { useToast } from '@/hooks/useToast';
import * as iotService from '@/services/iotService';

/** "4 min ago" from a seconds delta the API computed. */
function humanAge(seconds) {
  if (seconds === null || seconds === undefined) return null;
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

function DefinitionRow({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-sand-200 py-2 last:border-b-0">
      <dt className="text-xs uppercase tracking-wide text-ink-muted">{label}</dt>
      <dd className="min-w-0 text-right text-sm text-ink">{children}</dd>
    </div>
  );
}

/**
 * One device: what it is, what it last reported, and what can be done to it.
 *
 * Status is whatever the API derived from the last packet. Maintenance is the
 * only change a human can make here, and the copy says why: setting a device
 * ONLINE by hand does not make it online.
 */
export function DeviceDetailPanel({ deviceId, canEdit = true, onChanged }) {
  const toast = useToast();
  const [device, setDevice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [confirming, setConfirming] = useState(null); // 'maintenance' | 'resume' | 'delete'
  const [deleteConflict, setDeleteConflict] = useState(null);
  const [busy, setBusy] = useState(false);
  const [testOpen, setTestOpen] = useState(false);

  const load = useCallback(async () => {
    if (!deviceId) return;
    setLoading(true);
    setError(null);
    try {
      setDevice(await iotService.getDevice(deviceId));
    } catch (caught) {
      setError(normaliseError(caught));
      setDevice(null);
    } finally {
      setLoading(false);
    }
  }, [deviceId]);

  useEffect(() => {
    load();
  }, [load]);

  const changeStatus = async (status) => {
    setBusy(true);
    try {
      const updated = await iotService.setDeviceStatus(device.id, status);
      toast.success(
        status === 'MAINTENANCE'
          ? `${updated.device_id} marked under maintenance`
          : `${updated.device_id} returned to service`,
      );
      setDevice(updated);
      setConfirming(null);
      onChanged?.();
    } catch (caught) {
      toast.error('Could not change the device status', normaliseError(caught).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (confirm = false) => {
    setBusy(true);
    try {
      const result = await iotService.deleteDevice(device.id, { confirm });
      toast.success(
        `${device.device_id} deleted`,
        result.readings_deleted
          ? `${result.readings_deleted} stored reading(s) were deleted with it.`
          : 'It had no stored readings.',
      );
      setConfirming(null);
      setDeleteConflict(null);
      onChanged?.(result);
    } catch (caught) {
      const normalised = normaliseError(caught);
      const details = caught?.response?.data?.error?.details;
      if (normalised.status === 409 && details) {
        setConfirming(null);
        setDeleteConflict(details);
      } else {
        toast.error('Could not delete the device', normalised.message);
        setConfirming(null);
      }
    } finally {
      setBusy(false);
    }
  };

  if (!deviceId) return null;

  if (loading) return <LoadingState message="Loading device…" />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!device) return null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-ink">
            <Radio size={18} aria-hidden="true" />
            {device.device_name}
            <StatusBadge status={device.status} />
          </h2>
          <p className="mt-0.5 text-sm text-ink-muted">
            {device.device_id}
            {device.hive_code ? ` · on ${device.hive_code}` : ''}
            {device.hive_status ? ` · hive ${device.hive_status.toLowerCase()}` : ''}
          </p>
        </div>

        {canEdit ? (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<Send size={15} aria-hidden="true" />}
              onClick={() => setTestOpen(true)}
            >
              Send test reading
            </Button>
            {device.status === 'MAINTENANCE' ? (
              <Button
                variant="secondary"
                size="sm"
                leftIcon={<HeartPulse size={15} aria-hidden="true" />}
                onClick={() => setConfirming('resume')}
              >
                Return to service
              </Button>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                leftIcon={<Wrench size={15} aria-hidden="true" />}
                onClick={() => setConfirming('maintenance')}
              >
                Maintenance
              </Button>
            )}
            <Button
              variant="danger"
              size="sm"
              leftIcon={<Trash2 size={15} aria-hidden="true" />}
              onClick={() => setConfirming('delete')}
            >
              Delete
            </Button>
          </div>
        ) : null}
      </div>

      {device.status === 'MAINTENANCE' ? (
        <Alert variant="info" title="Under maintenance">
          Status stays MAINTENANCE until a person returns the device to service. The offline sweeper
          leaves it alone so a planned outage is not reported as a fault.
        </Alert>
      ) : null}

      {device.status === 'WARNING' ? (
        <Alert variant="warning" title="Reporting, but degraded">
          The device is still sending packets; its battery level is low. This is a hardware
          observation from the packet, not an assessment of the colony.
        </Alert>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
          <h3 className="text-sm font-semibold text-ink">Device</h3>
          <dl className="mt-2">
            <DefinitionRow label="Status">
              <span className="flex items-center justify-end gap-2">
                <StatusBadge status={device.status} size="sm" />
                {device.status_is_derived ? (
                  <Badge variant="neutral" size="sm">
                    derived
                  </Badge>
                ) : null}
              </span>
            </DefinitionRow>
            <DefinitionRow label="Last packet">
              {device.last_seen ? (
                <>
                  {formatDateTime(device.last_seen)}
                  {humanAge(device.seconds_since_last_seen) ? (
                    <span className="block text-xs text-ink-muted">
                      {humanAge(device.seconds_since_last_seen)}
                    </span>
                  ) : null}
                </>
              ) : (
                <span className="text-ink-muted">Nothing received yet</span>
              )}
            </DefinitionRow>
            <DefinitionRow label="Battery">
              {device.battery_level === null || device.battery_level === undefined
                ? '—'
                : `${device.battery_level} %`}
            </DefinitionRow>
            <DefinitionRow label="Signal">
              {device.signal_strength === null || device.signal_strength === undefined
                ? '—'
                : `${device.signal_strength} dBm`}
            </DefinitionRow>
            <DefinitionRow label="Hardware">
              {device.device_type} · {device.connection_type}
            </DefinitionRow>
            <DefinitionRow label="Firmware">
              {device.firmware_version || <span className="text-ink-muted">Not reported</span>}
            </DefinitionRow>
            <DefinitionRow label="Installed">
              {device.installed_at ? formatDateTime(device.installed_at) : '—'}
            </DefinitionRow>
            <DefinitionRow label="Sensors">
              {device.sensors_enabled} of {device.sensors_total} collecting
            </DefinitionRow>
          </dl>

          {device.mqtt_topic ? (
            <div className="mt-3 rounded-lg border border-sand-300 bg-sand-100/60 p-3">
              <p className="text-xs uppercase tracking-wide text-ink-muted">MQTT topic</p>
              <div className="mt-1 flex items-center gap-2">
                <code className="min-w-0 flex-1 break-all font-mono text-[11px] text-ink">
                  {device.mqtt_topic}
                </code>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Copy MQTT topic"
                  onClick={() => {
                    navigator.clipboard?.writeText(device.mqtt_topic);
                    toast.success('Topic copied');
                  }}
                >
                  <Copy size={14} aria-hidden="true" />
                </Button>
              </div>
            </div>
          ) : null}
        </section>

        <section className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
          <h3 className="text-sm font-semibold text-ink">Latest values</h3>
          <p className="mt-0.5 text-xs text-ink-muted">
            {device.latest_reading
              ? `From the packet received ${formatDateTime(device.latest_reading.timestamp)} · ${device.latest_reading.source_label}`
              : 'No packet has been received from this device yet.'}
          </p>
          <div className="mt-3">
            <SensorSnapshotGrid
              sensors={device.sensors}
              reading={device.latest_reading}
              emptyMessage="No sensors configured."
            />
          </div>
        </section>
      </div>

      <section className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
        <h3 className="text-sm font-semibold text-ink">Sensor configuration</h3>
        <p className="mt-0.5 text-xs text-ink-muted">
          Five sensors are created with a hive node. Turn off what the hardware does not carry.
        </p>
        <div className="mt-3">
          <SensorConfigTable
            deviceId={device.id}
            sensors={device.sensors}
            onSaved={() => {
              load();
              onChanged?.();
            }}
          />
        </div>
      </section>

      <TestReadingModal
        open={testOpen}
        device={device}
        onClose={() => setTestOpen(false)}
        onSent={() => {
          load();
          onChanged?.();
        }}
      />

      <ConfirmDialog
        open={confirming === 'maintenance'}
        title={`Take ${device.device_id} out of service?`}
        description="The device stays MAINTENANCE until someone returns it to service, even if it goes quiet."
        confirmLabel="Start maintenance"
        loading={busy}
        onCancel={() => setConfirming(null)}
        onConfirm={() => changeStatus('MAINTENANCE')}
      />

      <ConfirmDialog
        open={confirming === 'resume'}
        title={`Return ${device.device_id} to service?`}
        description="Status is recomputed from the next packet, so the device will show offline until it reports."
        confirmLabel="Return to service"
        loading={busy}
        onCancel={() => setConfirming(null)}
        onConfirm={() => changeStatus('ONLINE')}
      />

      <ConfirmDialog
        open={confirming === 'delete'}
        title={`Delete ${device.device_id}?`}
        description="The device and its sensor configuration are removed. Stored readings are deleted with it if it has any."
        confirmLabel="Delete device"
        variant="danger"
        loading={busy}
        onCancel={() => setConfirming(null)}
        onConfirm={() => remove(false)}
      />

      {deleteConflict ? (
        <ConfirmDialog
          open
          title={`${device.device_id} has stored readings`}
          description={`The platform found ${deleteConflict.reading_count ?? 0} reading(s) for this device. Deleting the device deletes that history with it — it cannot be recovered.`}
          confirmLabel="Delete device and history"
          variant="danger"
          loading={busy}
          onCancel={() => setDeleteConflict(null)}
          onConfirm={() => remove(true)}
        />
      ) : null}
    </div>
  );
}

export default DeviceDetailPanel;
