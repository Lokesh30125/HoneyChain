import { Breadcrumb } from '@/components/common/Breadcrumb';
import { AlertsWorkspace } from '@/components/ai/AlertsWorkspace';

/**
 * `/kvic/alerts` — findings across the hives in the officer's scope.
 *
 * The acknowledgement recorded here is attributed to the officer who made it,
 * because the audit trail names the acting account.
 */
export default function KvicAlertsPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC Cluster', to: '/kvic' }, { label: 'Alerts' }]} />
      <AlertsWorkspace
        mode="staff"
        title="Cluster alerts"
        description="Recorded findings across the hives you oversee, and how each one was handled."
        hivePathPrefix="/kvic/hives"
      />
    </div>
  );
}
