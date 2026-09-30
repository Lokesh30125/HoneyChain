import { Radio } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/common/EmptyState';
import { formatDateTime } from '@/utils/format';

/** One stored value, or an explicit "not recorded" — never a stand-in zero. */
function Value({ label, value, unit }) {
  return (
    <div className="rounded-lg border border-sand-200 bg-white p-3">
      <p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold text-ink">
        {value === null || value === undefined ? (
          <span className="text-sm font-normal text-ink-muted">Not recorded</span>
        ) : (
          <>
            {value}
            {unit ? <span className="ml-1 text-sm font-normal text-ink-muted">{unit}</span> : null}
          </>
        )}
      </p>
    </div>
  );
}

/**
 * The newest reading in the cluster, with the chain that carried it.
 *
 * The panel exists to make the relationship visible: a number on this screen
 * came from a device, on a hive, kept by a beekeeper, inside this cluster. When
 * nothing is stored the panel says exactly that — `has_data: false` is shown as
 * an empty state, not as a row of zeroes that would read like a measurement.
 */
export function ClusterTelemetryPanel({ telemetry, loading = false }) {
  const reading = telemetry?.reading;

  return (
    <Card>
      <CardHeader
        title="Latest telemetry"
        description="The most recent packet stored for any hive in this cluster."
        action={
          reading?.source_label ? (
            <Badge variant={reading.source === 'REAL_DEVICE' ? 'success' : 'neutral'}>
              {reading.source_label}
            </Badge>
          ) : null
        }
      />
      <CardBody>
        {loading ? (
          <p className="text-sm text-ink-muted">Reading the latest stored packet…</p>
        ) : !telemetry?.has_data || !reading ? (
          <EmptyState
            icon={<Radio size={20} aria-hidden="true" />}
            title="No telemetry data available yet"
            description={
              telemetry?.hive_count
                ? `${telemetry.hive_count} hive(s) are registered in this cluster, but no device has sent a reading yet.`
                : 'This cluster has no hives yet, so there is nothing to report.'
            }
          />
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-sm text-ink-soft">
              <span className="font-medium text-ink">{telemetry.hive_code}</span>
              <span aria-hidden="true">·</span>
              <span>{telemetry.device_id}</span>
              {telemetry.device_status ? (
                <Badge variant="neutral" size="sm">
                  {telemetry.device_status}
                </Badge>
              ) : null}
              <span aria-hidden="true">·</span>
              <span>
                kept by {telemetry.beekeeper_name || 'a beekeeper'}
                {telemetry.beekeeper_code ? ` (${telemetry.beekeeper_code})` : ''}
              </span>
            </div>

            <p className="text-xs text-ink-muted">
              Received {formatDateTime(reading.timestamp)} · {telemetry.hives_reporting} of{' '}
              {telemetry.hive_count} hives have reported
            </p>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Value label="Temperature" value={reading.temperature} unit="°C" />
              <Value label="Humidity" value={reading.humidity} unit="%" />
              <Value label="Weight" value={reading.weight} unit="kg" />
              <Value label="Vibration" value={reading.vibration} />
              <Value label="Acoustic level" value={reading.acoustic_level} />
              <Value label="Battery" value={reading.battery_level} unit="%" />
            </div>

            <p className="text-xs text-ink-muted">
              Stored values only. They describe what the sensors recorded; the platform does not
              read colony health from a single packet.
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export default ClusterTelemetryPanel;
