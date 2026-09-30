import { Breadcrumb } from '@/components/common/Breadcrumb';
import { MonitoringOverview } from '@/components/iot/MonitoringOverview';

/**
 * `/admin/iot` — every device on the platform, with ingest state.
 *
 * Read-only: administrators watch device health and whether telemetry is
 * arriving. Pairing and sensor configuration belong to the beekeeper.
 */
export default function AdminIotPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'IoT monitoring' }]} />
      <MonitoringOverview
        mode="oversight"
        title="IoT monitoring"
        description="Device fleet across the platform, with derived status, last packet and the state of MQTT ingest."
      />
    </div>
  );
}
