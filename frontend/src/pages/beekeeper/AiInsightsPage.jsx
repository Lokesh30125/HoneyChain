import { Breadcrumb } from '@/components/common/Breadcrumb';
import { InsightsWorkspace } from '@/components/ai/InsightsWorkspace';

/**
 * `/beekeeper/insights` — the AI overview for the signed-in beekeeper's apiary.
 *
 * The workspace is shared with the staff views; the API narrows every list and
 * every counter to the caller's own hives, so the page does not filter anything
 * itself.
 */
export default function AiInsightsPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Beekeeper', to: '/beekeeper' }, { label: 'AI insights' }]} />
      <InsightsWorkspace
        mode="owner"
        title="AI insights"
        description="Colony health indicators, risk bands and yield projections built from the telemetry your devices recorded."
        hivePathPrefix="/beekeeper/hives"
      />
    </div>
  );
}
