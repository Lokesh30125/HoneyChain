import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { LoadingState } from '@/components/common/LoadingState';
import { useAuth } from '@/hooks/useAuth';

/**
 * Guards authenticated areas.
 *
 * While the session is being confirmed (`/auth/me`) a loading state is shown
 * rather than redirecting — otherwise a page refresh would flash the login
 * screen before the stored token is validated.
 */
export function ProtectedRoute({ children }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sand-50">
        <LoadingState message="Restoring your session…" />
      </div>
    );
  }

  if (!isAuthenticated) {
    // Remember where the user was heading so login can return them there.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return children ?? <Outlet />;
}

export default ProtectedRoute;
