import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { PackagingWorkspace } from '@/components/packaging/PackagingWorkspace';
import { PACKAGING_VIEW_COPY } from '@/constants/packaging';
import { ROLES } from '@/constants/roles';

/**
 * Packed stock — the package register read straight from the database.
 *
 * One row per package that exists, with its size, the run that produced it, the
 * batch it carries and how far it has travelled since. Nothing here is derived
 * from a plan: if a package is not a row in the register it is not stock.
 */
export default function PackedStockPage() {
  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title="Packed stock"
        description={`${PACKAGING_VIEW_COPY.packages.description} Read from the package register, including anything already released for distribution.`}
        requiredRoles={[ROLES.PACKAGING_UNIT]}
      />
      <PackagingWorkspace role={ROLES.PACKAGING_UNIT} view="packages" />
    </div>
  );
}
