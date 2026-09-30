import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { PackagingWorkspace } from '@/components/packaging/PackagingWorkspace';
import { PACKAGING_VIEW_COPY } from '@/constants/packaging';
import { ROLES } from '@/constants/roles';

/**
 * The work list a packaging unit starts from: batches the laboratory approved,
 * with what is left to pack on each. A rejected or still-untested batch is not
 * filtered out on this screen — it is never returned by the server in the first
 * place, because the query asks for the statuses that may be packed.
 */
export default function ApprovedBatchesPage() {
  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title={PACKAGING_VIEW_COPY.approved.title}
        description={PACKAGING_VIEW_COPY.approved.description}
        requiredRoles={[ROLES.PACKAGING_UNIT]}
      />
      <PackagingWorkspace role={ROLES.PACKAGING_UNIT} view="approved" />
    </div>
  );
}
