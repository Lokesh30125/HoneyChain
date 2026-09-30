import { Link, useNavigate } from 'react-router-dom';

import { AuthLayout } from '@/components/layout/AuthLayout';
import { RegisterForm } from '@/components/forms/RegisterForm';
import { homeRouteForRole } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/useToast';

/**
 * Registration page.
 *
 * A successful sign-up opens a session immediately (the API returns a token
 * pair), so the user lands in their workspace without a second login step.
 */
export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  const handleSuccess = (result) => {
    const name = result.user?.name || 'there';
    toast.success('Account created', `Welcome to HoneyChain, ${name}.`);

    // A beekeeper's record starts as PENDING — say so now rather than letting
    // them wonder why nothing is verified yet.
    if (result.beekeeper?.beekeeper_code) {
      toast.info(
        `Beekeeper ID ${result.beekeeper.beekeeper_code}`,
        'Your registration is pending review by a KVIC officer. You can complete your profile meanwhile.',
      );
    }

    // The API owns the role → route mapping; fall back only if it is absent.
    navigate(result.home_route || homeRouteForRole(result.user?.role), { replace: true });
  };

  return (
    <AuthLayout
      title="Create your HoneyChain account"
      subtitle="Choose the role that matches your participation in the honey value chain. You can be moved to a different role later by an administrator."
      footer={
        <p>
          Already registered?{' '}
          <Link to="/login" className="hc-link">
            Sign in
          </Link>
        </p>
      }
    >
      <RegisterForm onSubmit={register} onSuccess={handleSuccess} />
    </AuthLayout>
  );
}
