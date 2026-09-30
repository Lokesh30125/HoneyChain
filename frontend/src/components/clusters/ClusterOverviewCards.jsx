import { Activity, Hexagon, Radio, Users, Waves } from 'lucide-react';

import { StatCard } from '@/components/common/StatCard';
import { formatDateTime } from '@/utils/format';

/**
 * The cluster's counters, each one counted from the records inside it.
 *
 * Every figure here is a query result over the same rows the beekeeper sees —
 * there is no cluster-side copy to fall out of date. A zero means "nothing
 * stored", so it is shown as a zero rather than hidden or replaced by a dash.
 */
export function ClusterOverviewCards({ overview, loading = false }) {
  if (!overview) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Beekeepers" loading={loading} />
        <StatCard label="Hives" loading={loading} />
        <StatCard label="Devices" loading={loading} />
        <StatCard label="Readings (24 h)" loading={loading} />
      </div>
    );
  }

  const { beekeepers, hives, devices, telemetry } = overview;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        label="Beekeepers"
        value={beekeepers.total}
        helper={`${beekeepers.verified} verified · ${beekeepers.pending} pending`}
        icon={<Users size={16} aria-hidden="true" />}
        tone="honey"
      />
      <StatCard
        label="Hives"
        value={hives.total}
        helper={`${hives.without_device} still without a device`}
        icon={<Hexagon size={16} aria-hidden="true" />}
      />
      <StatCard
        label="Devices"
        value={devices.total}
        helper={`${devices.online} online · ${devices.offline} offline`}
        icon={<Radio size={16} aria-hidden="true" />}
      />
      <StatCard
        label="Readings (24 h)"
        value={telemetry.readings_last_24h}
        helper={
          telemetry.latest_reading_at
            ? `Latest ${formatDateTime(telemetry.latest_reading_at)}`
            : 'No telemetry stored yet'
        }
        icon={<Activity size={16} aria-hidden="true" />}
      />
      <StatCard
        label="Hives reporting"
        value={telemetry.hives_with_telemetry}
        helper={`${telemetry.hives_without_telemetry} with no reading yet`}
        icon={<Waves size={16} aria-hidden="true" />}
      />
    </div>
  );
}

export default ClusterOverviewCards;
