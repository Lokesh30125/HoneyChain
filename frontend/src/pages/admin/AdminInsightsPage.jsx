import { Breadcrumb } from '@/components/common/Breadcrumb';
import { InsightsWorkspace } from '@/components/ai/InsightsWorkspace';

/**
 * `/admin/insights` — platform-wide AI oversight.
 *
 * Every counter and row here is derived from stored analyses across all hives;
 * an administrator can also trigger a bulk run, which writes one audit entry per
 * hive analysed.
 */
export default function AdminInsightsPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'AI insights' }]} />
      <InsightsWorkspace
        mode="staff"
        title="AI oversight"
        description="Health indicators, risk bands and projections across every hive on the platform."
        hivePathPrefix="/admin/hives"
      />
    </div>
  );
}
