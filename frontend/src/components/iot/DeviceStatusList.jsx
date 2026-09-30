import { BatteryMedium, Radio, Wifi } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/common/EmptyState';
import { StatusBadge } from '@/components/common/StatusBadge';
import { formatDateTime } from '@/utils/format';

/** "12 min ago" from the seconds delta the API computed. */
function humanAge(seconds) {
  if (seconds === null || seconds === undefined) return null;
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

/** "never reported" / "12 Sep 2026, 4:35 pm (12 min ago)". */
function lastPacketLabel(device) {
  if (!device.last_seen) return 'no packet yet';
  const age = humanAge(device.seconds_since_last_seen);
  return `${formatDateTime(device.last_seen)}${age ? ` (${age})` : ''}`;
}

/**
 * Compact device list for dashboards: status, when it last reported, battery and
 * signal — the four things that say whether hardware is healthy today.
 *
 * All four are values the API derived from the last packet; nothing here is
 * inferred on the client.
 */
export function DeviceStatusList({ devices = [], loading = false, actionTo, actionLabel }) {
  if (loading) {
    return (
      <div className="space-y-2" aria-hidden="true">
        {[0, 1, 2].map((row) => (
          <div key={row} className="h-14 animate-pulse rounded-lg bg-sand-100" />
        ))}
      </div>
    );
  }

  if (!devices.length) {
    return (
      <EmptyState
        icon={<Radio size={22} aria-hidden="true" />}
        title="No IoT devices connected"
        description="Pair an ESP32 device with a hive to start receiving telemetry."
        action={
          actionTo ? (
            <Button to={actionTo} size="sm" variant="secondary">
              {actionLabel || 'Manage hives'}
            </Button>
          ) : null
        }
      />
    );
  }

  return (
    <ul className="divide-y divide-sand-200">
      {devices.map((device) => (
        <li key={device.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-sm font-medium text-ink">
              {device.device_id}
              <StatusBadge status={device.status} size="sm" />
            </p>
            <p className="truncate text-xs text-ink-muted">
              {device.device_name}
              {device.hive_code ? ` · ${device.hive_code}` : ''} · last packet{' '}
              {lastPacketLabel(device)}
            </p>
          </div>

          <div className="flex items-center gap-4 text-xs text-ink-soft">
            <span className="flex items-center gap-1.5">
              <BatteryMedium size={14} aria-hidden="true" />
              {device.battery_level === null || device.battery_level === undefined
                ? '—'
                : `${device.battery_level}%`}
            </span>
            <span className="flex items-center gap-1.5">
              <Wifi size={14} aria-hidden="true" />
              {device.signal_strength === null || device.signal_strength === undefined
                ? '—'
                : `${device.signal_strength} dBm`}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

export default DeviceStatusList;
