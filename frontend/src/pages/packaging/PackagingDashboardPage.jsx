import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { PackagingWorkspace } from '@/components/packaging/PackagingWorkspace';
import { PACKAGING_VIEW_COPY } from '@/constants/packaging';
import { ROLES } from '@/constants/roles';

/**
 * The packaging unit's own home.
 *
 * It is the packaging workspace — the same component an administrator uses from
 * the administration screens — shown for the role it was written for. There is no
 * placeholder notice on this route and no gate in front of it: the module exists,
 * so the role that works in it gets the working screen.
 */
export default function PackagingDashboardPage() {
  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title={PACKAGING_VIEW_COPY.overview.title}
        description={PACKAGING_VIEW_COPY.overview.description}
        requiredRoles={[ROLES.PACKAGING_UNIT]}
      />
      <PackagingWorkspace role={ROLES.PACKAGING_UNIT} view="overview" />
    </div>
  );
}
