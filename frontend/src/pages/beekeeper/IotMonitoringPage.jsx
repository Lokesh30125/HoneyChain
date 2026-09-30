import { Breadcrumb } from '@/components/common/Breadcrumb';
import { MonitoringOverview } from '@/components/iot/MonitoringOverview';

/**
 * `/beekeeper/iot` — devices on the beekeeper's own hives.
 *
 * The page reads the Prompt-3 IoT APIs: device registry, derived status, sensor
 * configuration and telemetry. Readings are labelled with their source, so
 * simulator or hand-entered values are never shown as hardware data.
 */
export default function IotMonitoringPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Beekeeper', to: '/beekeeper' }, { label: 'IoT monitoring' }]} />
      <MonitoringOverview
        mode="owner"
        title="IoT monitoring"
        description="Devices paired with your hives, what they last reported, and the state of telemetry ingest."
      />
    </div>
  );
}
