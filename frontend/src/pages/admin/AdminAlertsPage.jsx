import { Breadcrumb } from '@/components/common/Breadcrumb';
import { AlertsWorkspace } from '@/components/ai/AlertsWorkspace';

/**
 * `/admin/alerts` — every alert on the platform, with the full lifecycle.
 *
 * Kept deliberately close to the beekeeper view: the same records, the same
 * actions, the same audit trail — only the scope differs.
 */
export default function AdminAlertsPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'Alerts' }]} />
      <AlertsWorkspace
        mode="staff"
        title="All alerts"
        description="Every recorded finding across the platform, with acknowledgement and resolution state."
        hivePathPrefix="/admin/hives"
      />
    </div>
  );
}
