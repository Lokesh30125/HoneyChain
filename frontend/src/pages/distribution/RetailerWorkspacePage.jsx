import { WorkspaceHeader } from '@/components/common/WorkspaceHeader';
import { RetailWorkspace } from '@/components/distribution/RetailWorkspace';
import { RETAILER_VIEW_COPY } from '@/constants/distribution';
import { ROLES } from '@/constants/roles';

/**
 * The retailer's own home: what is on its way, what arrived, and the chain behind
 * every package it holds.
 */
export default function RetailerWorkspacePage({ view = 'overview', title, description }) {
  const copy = RETAILER_VIEW_COPY[view] || RETAILER_VIEW_COPY.overview;
  return (
    <div className="space-y-6">
      <WorkspaceHeader
        title={title || copy.title}
        description={description || copy.description}
        requiredRoles={[ROLES.RETAILER]}
      />
      <RetailWorkspace role={ROLES.RETAILER} view={view} />
    </div>
  );
}
