import { Breadcrumb } from '@/components/common/Breadcrumb';
import { MonitoringOverview } from '@/components/iot/MonitoringOverview';

/**
 * `/kvic/iot` — device fleet across the hives the officer oversees.
 *
 * Read-only: an officer can see device status, last seen, battery, signal and
 * the latest readings, but cannot pair, re-configure or delete hardware. The
 * API enforces the same boundary.
 */
export default function KvicIotPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC', to: '/kvic' }, { label: 'IoT monitoring' }]} />
      <MonitoringOverview
        mode="oversight"
        title="IoT monitoring"
        description="Devices across the beekeepers you oversee, with their derived status and the ingest state of the platform."
      />
    </div>
  );
}
