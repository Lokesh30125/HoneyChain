import { Breadcrumb } from '@/components/common/Breadcrumb';
import { InsightsWorkspace } from '@/components/ai/InsightsWorkspace';

/**
 * `/kvic/insights` — the same assessment view, widened to the apiaries the
 * officer oversees. The scope is decided by the API, not by this page.
 */
export default function KvicInsightsPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC Cluster', to: '/kvic' }, { label: 'AI insights' }]} />
      <InsightsWorkspace
        mode="staff"
        title="Cluster AI insights"
        description="Health indicators, risk bands and projections for the hives in the apiaries you oversee."
        hivePathPrefix="/kvic/hives"
      />
    </div>
  );
}
