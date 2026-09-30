import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Eye, EyeOff, Hexagon, Lock, Mail, MapPin, Phone, User } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import {
  BEE_SPECIES_OPTIONS,
  EMPTY_BEEKEEPER_DETAILS,
  ROLE_OPTIONS,
  registerSchema,
} from '@/utils/validation';
import { normaliseError } from '@/utils/errors';

/** Human labels for the fields a server-side error can point at. */
const FIELD_LABELS = {
  name: 'Full name',
  email: 'Email',
  phone: 'Phone',
  password: 'Password',
  confirm_password: 'Password confirmation',
  role: 'Role',
  state: 'State',
  district: 'District',
  organization: 'Organisation',
  accepted_terms: 'Data policy',
  'beekeeper.village': 'Apiary village',
  'beekeeper.mandal': 'Apiary mandal',
  'beekeeper.district': 'Apiary district',
  'beekeeper.state': 'Apiary state',
  'beekeeper.pincode': 'Apiary PIN code',
  'beekeeper.experience_years': 'Years of experience',
  'beekeeper.bee_species': 'Bee species',
  'beekeeper.number_of_hives': 'Number of hives',
};

/**
 * The API reports apiary problems as `beekeeper.experience_years`, while the
 * inputs are registered as `beekeeper.experienceYears`. Without this
 * translation the message is attached to a field that does not exist and
 * disappears — leaving the user with only a generic "Invalid request".
 */
const API_FIELD_TO_FORM_FIELD = {
  experience_years: 'experienceYears',
  number_of_hives: 'numberOfHives',
  bee_species: 'beeSpecies',
};

function formFieldFor(apiField) {
  if (!apiField.startsWith('beekeeper.')) return apiField;
  const nested = apiField.slice('beekeeper.'.length);
  return `beekeeper.${API_FIELD_TO_FORM_FIELD[nested] || nested}`;
}

/**
 * Registration form.
 *
 * Role is chosen here because the platform serves ten different participants;
 * privileged roles (admin, KVIC officer, lab technician) are intentionally not
 * offered — the API rejects them too, so the restriction is not just cosmetic.
 */
export function RegisterForm({ onSubmit, onSuccess, submitLabel = 'Create account' }) {
  const [formError, setFormError] = useState(null);
  const [fieldSummaries, setFieldSummaries] = useState([]);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    setError,
    watch,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      name: '',
      email: '',
      phone: '',
      role: 'BEEKEEPER',
      state: '',
      district: '',
      organization: '',
      password: '',
      confirmPassword: '',
      acceptedTerms: false,
      beekeeper: { ...EMPTY_BEEKEEPER_DETAILS },
    },
  });

  const selectedRole = watch('role');
  const isBeekeeper = selectedRole === 'BEEKEEPER';

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    setFieldSummaries([]);
    const { confirmPassword, acceptedTerms, beekeeper, ...payload } = values;
    void confirmPassword;

    try {
      const result = await onSubmit({
        ...payload,
        phone: payload.phone ? payload.phone : undefined,
        state: payload.state || undefined,
        district: payload.district || undefined,
        organization: payload.organization || undefined,
        accepted_terms: acceptedTerms,
        // Apiary details are only ever sent for a beekeeper — the API rejects
        // them on any other role rather than quietly ignoring them.
        beekeeper:
          isBeekeeper && beekeeper
            ? {
                village: beekeeper.village || null,
                mandal: beekeeper.mandal || null,
                district: beekeeper.district || payload.district || null,
                state: beekeeper.state || payload.state || null,
                pincode: beekeeper.pincode || null,
                experience_years: beekeeper.experienceYears ?? null,
                bee_species: beekeeper.beeSpecies || null,
                number_of_hives: beekeeper.numberOfHives ?? null,
              }
            : undefined,
      });
      onSuccess?.(result);
    } catch (caught) {
      const error = normaliseError(caught);
      setFormError(error);

      // Attach every field message the API sent to the input it belongs to.
      // Cross-field rules (for example "apiary details need the beekeeper role")
      // arrive without a field name; those are listed in the banner only.
      Object.entries(error.fieldErrors).forEach(([apiField, message]) => {
        if (!apiField) return;
        const field = formFieldFor(apiField);
        setError(field === 'confirmPassword' ? 'password' : field, { type: 'server', message });
      });

      // The banner names the fields that failed, so a problem below the fold is
      // never reported as a bare "Invalid request".
      // Cross-field rules have no input to sit under, so they lead the list.
      setFieldSummaries([
        ...(error.formErrors || []).map((message) => ({ label: 'Form', message })),
        ...Object.entries(error.fieldErrors).map(([apiField, message]) => ({
          label: FIELD_LABELS[apiField] || apiField || 'Form',
          message,
        })),
      ]);
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      {formError ? (
        <Alert variant="danger" title="Could not create your account" onDismiss={() => setFormError(null)}>
          {fieldSummaries.length ? (
            <>
              <p>
                {fieldSummaries.length === 1
                  ? 'Please check this field:'
                  : 'Please check these fields:'}
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {fieldSummaries.slice(0, 4).map((item, index) => (
                  <li key={`${item.label}-${index}`}>
                    <span className="font-medium">{item.label}:</span> {item.message}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            formError.message
          )}
        </Alert>
      ) : null}

      <Input
        label="Full name"
        name="name"
        autoComplete="name"
        placeholder="e.g. Ravi Kumar"
        leftIcon={<User size={16} />}
        required
        error={errors.name?.message}
        {...register('name')}
      />

      <div className="grid gap-5 sm:grid-cols-2">
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
          label="Phone (optional)"
          name="phone"
          type="tel"
          autoComplete="tel"
          placeholder="9876543210"
          leftIcon={<Phone size={16} />}
          error={errors.phone?.message}
          hint="Used for cluster coordination only"
          {...register('phone')}
        />
      </div>

      <Select
        label="I am registering as"
        name="role"
        required
        options={ROLE_OPTIONS}
        error={errors.role?.message}
        hint="Privileged roles are provisioned by an administrator"
        {...register('role')}
      />

      <div className="grid gap-5 sm:grid-cols-2">
        <Input
          label="State (optional)"
          name="state"
          placeholder="Andhra Pradesh"
          leftIcon={<MapPin size={16} />}
          error={errors.state?.message}
          {...register('state')}
        />
        <Input
          label="District (optional)"
          name="district"
          placeholder="Guntur"
          error={errors.district?.message}
          {...register('district')}
        />
      </div>

      <Input
        label="Organisation (optional)"
        name="organization"
        placeholder="Co-operative, cluster, lab or company"
        error={errors.organization?.message}
        {...register('organization')}
      />

      {isBeekeeper ? (
        <section className="rounded-card border border-sand-300 bg-sand-100/50 p-4">
          <div className="flex items-start gap-2">
            <span className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-white text-honey-700 ring-1 ring-sand-300">
              <Hexagon size={16} aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-sm font-semibold text-ink">Apiary details</h2>
              <p className="mt-0.5 text-xs text-ink-muted">
                Optional, and you can change them later. A KVIC officer reviews these details before
                your registration is verified — nothing is verified automatically.
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-5 sm:grid-cols-3">
            <Input
              label="Village"
              name="beekeeper.village"
              error={errors.beekeeper?.village?.message}
              {...register('beekeeper.village')}
            />
            <Input
              label="Mandal"
              name="beekeeper.mandal"
              error={errors.beekeeper?.mandal?.message}
              {...register('beekeeper.mandal')}
            />
            <Input
              label="PIN code"
              name="beekeeper.pincode"
              inputMode="numeric"
              maxLength={6}
              error={errors.beekeeper?.pincode?.message}
              {...register('beekeeper.pincode')}
            />
          </div>

          <div className="mt-5 grid gap-5 sm:grid-cols-3">
            <Input
              label="Experience (years)"
              name="beekeeper.experienceYears"
              type="number"
              min={0}
              max={90}
              error={errors.beekeeper?.experienceYears?.message}
              {...register('beekeeper.experienceYears')}
            />
            <Input
              label="Number of hives"
              name="beekeeper.numberOfHives"
              type="number"
              min={0}
              error={errors.beekeeper?.numberOfHives?.message}
              {...register('beekeeper.numberOfHives')}
            />
            <Select
              label="Bee species"
              name="beekeeper.beeSpecies"
              placeholder="Choose a species"
              options={BEE_SPECIES_OPTIONS.map((species) => ({ value: species, label: species }))}
              error={errors.beekeeper?.beeSpecies?.message}
              {...register('beekeeper.beeSpecies')}
            />
          </div>
        </section>
      ) : null}

      <div className="grid gap-5 sm:grid-cols-2">
        <Input
          label="Password"
          name="password"
          type={showPassword ? 'text' : 'password'}
          autoComplete="new-password"
          placeholder="At least 8 characters"
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
        <Input
          label="Confirm password"
          name="confirmPassword"
          type={showPassword ? 'text' : 'password'}
          autoComplete="new-password"
          placeholder="Repeat your password"
          leftIcon={<Lock size={16} />}
          required
          error={errors.confirmPassword?.message}
          {...register('confirmPassword')}
        />
      </div>

      <div>
        <label className="flex items-start gap-2.5 text-sm text-ink-soft">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-sand-400 text-forest-700 focus:ring-honey-500"
            {...register('acceptedTerms')}
          />
          <span>
            I agree that the harvest, handling and quality records I submit may be shown to
            downstream buyers and consumers for traceability purposes.
          </span>
        </label>
        {errors.acceptedTerms ? (
          <p className="mt-1.5 text-sm text-status-danger">{errors.acceptedTerms.message}</p>
        ) : null}
      </div>

      <Button type="submit" fullWidth size="lg" loading={isSubmitting}>
        {submitLabel}
      </Button>
    </form>
  );
}

export default RegisterForm;
