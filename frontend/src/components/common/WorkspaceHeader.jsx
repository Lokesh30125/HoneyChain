import { roleLabel } from '@/constants/roles';
import { Badge } from '@/components/ui/Badge';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { useAuth } from '@/hooks/useAuth';

/**
 * Shared header for role workspaces: breadcrumb, title, the signed-in role and a
 * badge marking whether this is the user's own workspace.
 */
export function WorkspaceHeader({ title, description, requiredRoles = [], actions = null }) {
  const { user } = useAuth();
  const isOwnWorkspace = requiredRoles.length === 0 || requiredRoles.includes(user?.role);

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: title }]} />
      <PageHeader
        title={title}
        description={description}
        badge={
          <Badge variant={isOwnWorkspace ? 'honey' : 'neutral'} size="sm">
            {isOwnWorkspace ? roleLabel(user?.role) : `Viewing as ${roleLabel(user?.role)}`}
          </Badge>
        }
        actions={actions}
      />
    </div>
  );
}

export default WorkspaceHeader;
