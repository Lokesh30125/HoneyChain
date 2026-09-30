import { Breadcrumb } from '@/components/common/Breadcrumb';
import { AlertsWorkspace } from '@/components/ai/AlertsWorkspace';

/**
 * `/beekeeper/alerts` — findings raised from the beekeeper's own telemetry.
 *
 * Alerts are the one place where the platform interrupts: they are deliberately
 * scarce, and each one carries the reading, the band it left, and the record of
 * who acknowledged or resolved it.
 */
export default function AlertsPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Beekeeper', to: '/beekeeper' }, { label: 'Alerts' }]} />
      <AlertsWorkspace
        mode="owner"
        title="Alerts"
        description="Findings from your own hives that deserve a look, with what was done about each one."
        hivePathPrefix="/beekeeper/hives"
      />
    </div>
  );
}
