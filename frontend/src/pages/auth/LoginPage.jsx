import { useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { AuthLayout } from '@/components/layout/AuthLayout';
import { LoginForm } from '@/components/forms/LoginForm';
import { Alert } from '@/components/ui/Alert';
import { homeRouteForRole } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/useToast';

/**
 * Sign-in page.
 *
 * After a successful login the user is sent to their role's workspace (or back
 * to the page they originally requested, captured by ProtectedRoute).
 */
export default function LoginPage() {
  const { login, isAuthenticated, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();

  const redirectTo = location.state?.from || null;

  // Already signed in? Skip the form.
  useEffect(() => {
    if (isAuthenticated && user) {
      navigate(redirectTo || homeRouteForRole(user.role), { replace: true });
    }
  }, [isAuthenticated, user, navigate, redirectTo]);

  const handleSuccess = (profile) => {
    toast.success('Welcome back', `Signed in as ${profile.name}.`);
    navigate(redirectTo || homeRouteForRole(profile.role), { replace: true });
  };

  return (
    <AuthLayout
      title="Sign in to HoneyChain"
      subtitle="Use the account created for your role in the honey supply chain."
      footer={
        <p>
          New to HoneyChain?{' '}
          <Link to="/register" className="hc-link">
            Create an account
          </Link>
        </p>
      }
    >
      {location.state?.registered ? (
        <Alert variant="success" className="mb-5" title="Account created">
          Your account is ready. Sign in to continue.
        </Alert>
      ) : null}

      {location.state?.sessionExpired ? (
        <Alert variant="warning" className="mb-5" title="Session ended">
          For your security we signed you out. Please sign in again.
        </Alert>
      ) : null}

      <LoginForm onSubmit={login} onSuccess={handleSuccess} />
    </AuthLayout>
  );
}
