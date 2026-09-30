import { Navigate, useLocation } from 'react-router-dom';

import { canRoleOpenPath, workspaceHomeForRole } from '@/constants/navigation';
import { useAuth } from '@/hooks/useAuth';

/**
 * Role-aware route guard.
 *
 * Two layers, deliberately:
 *
 * 1. `allow` (optional) restricts a screen to the roles it was written for.
 * 2. The workspace check uses the central navigation configuration, so the route
 *    table cannot drift from the sidebar: a path outside the signed-in role's
 *    workspace is not routable even if somebody types it.
 *
 * A user who reaches a path that is not theirs is sent to their own workspace —
 * not shown a "this is not your workspace" notice, and never left on a screen
 * belonging to another role. The backend authorises every request as well; this
 * guard decides which screens exist for a role, not what data it may read.
 *
 * Usage: <Route element={<RoleRoute allow={[ROLES.ADMIN]} />}> … </Route>
 */
export function RoleRoute({ allow = [], children, redirectTo = null }) {
  const { role, isLoading } = useAuth();
  const { pathname } = useLocation();

  // While the session is being confirmed, render nothing rather than bouncing
  // the user to a workspace the still-loading role might not own.
  if (isLoading) return null;

  const roleAllowed = !allow.length || allow.includes(role);
  const pathAllowed = canRoleOpenPath(role, pathname);

  if (roleAllowed && pathAllowed) {
    return children ?? null;
  }

  const fallback = redirectTo || workspaceHomeForRole(role);
  return <Navigate to={fallback} replace />;
}

export default RoleRoute;
