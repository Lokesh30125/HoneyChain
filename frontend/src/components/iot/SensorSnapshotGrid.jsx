import { Radio } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { sensorMeta } from '@/constants/hive';
import { formatDateTime } from '@/utils/format';

/**
 * Current value of every sensor a device reports.
 *
 * A sensor with no value is shown as "No reading yet" rather than 0 — a zero
 * would be a measurement, and nothing was measured. The source and time of each
 * value come from the stored reading, so the panel never invents freshness.
 */
export function SensorSnapshotGrid({ sensors = [], reading = null, emptyMessage }) {
  if (!sensors.length) {
    return (
      <div className="rounded-lg border border-dashed border-sand-300 bg-sand-50/60 px-4 py-6 text-center text-sm text-ink-muted">
        {emptyMessage || 'No sensors are configured on this device yet.'}
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {sensors.map((sensor) => {
        const meta = sensorMeta(sensor.sensor_type);
        const value = sensor.value ?? (meta ? reading?.[meta.readingKey] : null);
        const recordedAt = sensor.recorded_at || reading?.timestamp;
        const hasValue = value !== null && value !== undefined;

        return (
          <div
            key={`${sensor.sensor_type}-${sensor.sensor_name}`}
            className="rounded-lg border border-sand-300 bg-white p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-ink">{sensor.sensor_name}</p>
              <Badge variant={sensor.enabled ? 'success' : 'neutral'} size="sm">
                {sensor.enabled ? 'Enabled' : 'Disabled'}
              </Badge>
            </div>

            <p className="mt-2 text-xl font-semibold tracking-tight text-ink">
              {hasValue
                ? `${Number(value).toFixed(meta?.precision ?? 2)} ${sensor.unit || meta?.unit || ''}`.trim()
                : '—'}
            </p>

            <p className="mt-0.5 text-xs text-ink-muted">
              {hasValue ? (
                <>
                  {formatDateTime(recordedAt)}
                  {reading?.source_label ? ` · ${reading.source_label}` : ''}
                </>
              ) : (
                'No reading yet'
              )}
            </p>

            <p className="mt-1 text-[11px] text-ink-muted">
              Expected every {Math.round((sensor.sampling_interval || 0) / 60) || '<1'} min
            </p>
          </div>
        );
      })}
    </div>
  );
}

/** Compact "no device" panel used by hive detail screens. */
export function NoDevicePanel({ hiveCode }) {
  return (
    <div className="rounded-lg border border-dashed border-sand-300 bg-sand-50/60 px-4 py-6 text-center">
      <Radio size={20} className="mx-auto text-ink-muted" aria-hidden="true" />
      <p className="mt-2 text-sm font-medium text-ink">No device paired with this hive</p>
      <p className="mx-auto mt-1 max-w-md text-xs text-ink-muted">
        {hiveCode ? `${hiveCode} has` : 'This hive has'} no sensor node attached, so there is no
        telemetry to show. Pair a device to start collecting readings.
      </p>
    </div>
  );
}

export default SensorSnapshotGrid;
