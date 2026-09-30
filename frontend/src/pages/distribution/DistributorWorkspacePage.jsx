import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { DistributionWorkspace } from '@/components/distribution/DistributionWorkspace';
import { DISTRIBUTION_VIEW_COPY } from '@/constants/distribution';
import { ROLES } from '@/constants/roles';

/**
 * The distributor's own home.
 *
 * Packages the packaging unit released, raised into shipments and moved along the
 * journey the server allows. No placeholder, no gate: the module exists for this
 * role, so this is the working screen.
 */
export default function DistributorWorkspacePage({ view = 'overview', title, description }) {
  const copy = DISTRIBUTION_VIEW_COPY[view] || DISTRIBUTION_VIEW_COPY.overview;
  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title={title || copy.title}
        description={description || copy.description}
        requiredRoles={[ROLES.DISTRIBUTOR]}
      />
      <DistributionWorkspace role={ROLES.DISTRIBUTOR} view={view} />
    </div>
  );
}
