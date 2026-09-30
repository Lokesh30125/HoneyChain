import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, Lock, Mail } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { loginSchema } from '@/utils/validation';
import { normaliseError } from '@/utils/errors';

/**
 * Sign-in form.
 *
 * All logic is local to the form: validation via Zod, submission delegated to
 * the `onSubmit` prop (the page wires it to AuthContext). Errors coming back
 * from the API are mapped onto the matching fields where possible.
 */
export function LoginForm({ onSubmit, onSuccess, submitLabel = 'Sign in' }) {
  const [formError, setFormError] = useState(null);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '', rememberMe: false },
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const user = await onSubmit(values);
      onSuccess?.(user);
    } catch (caught) {
      const error = normaliseError(caught);
      setFormError(error);
      // Surface field-level messages from the API (e.g. invalid email format).
      Object.entries(error.fieldErrors).forEach(([field, message]) => {
        if (field === 'email' || field === 'password') {
          setError(field, { type: 'server', message });
        }
      });
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      {formError ? (
        <Alert variant="danger" title="Could not sign you in" onDismiss={() => setFormError(null)}>
          {formError.message}
        </Alert>
      ) : null}

      <Input
        label="Email address"
        name="email"
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        leftIcon={<Mail size={16} />}
        required
        error={errors.email?.message}
        {...register('email')}
      />

      <Input
        label="Password"
        name="password"
        type={showPassword ? 'text' : 'password'}
        autoComplete="current-password"
        placeholder="Your password"
        leftIcon={<Lock size={16} />}
        required
        error={errors.password?.message}
        rightSlot={
          <button
            type="button"
            onClick={() => setShowPassword((visible) => !visible)}
            className="rounded p-1.5 text-ink-muted transition-colors hover:text-ink"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
          >
            {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        }
        {...register('password')}
      />

      <div className="flex items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-sand-400 text-forest-700 focus:ring-honey-500"
            {...register('rememberMe')}
          />
          Keep me signed in
        </label>
        <span className="text-xs text-ink-muted">Sessions are revoked on logout</span>
      </div>

      <Button type="submit" fullWidth size="lg" loading={isSubmitting}>
        {submitLabel}
      </Button>
    </form>
  );
}

export default LoginForm;
