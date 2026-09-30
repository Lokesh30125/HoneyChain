import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { Building2, FlaskConical, Info } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import {
  ROLE_ASSIGNMENT_HINTS,
  ROLES,
  homeRouteForRole,
  roleLabel,
} from '@/constants/roles';
import { ALL_ROLE_OPTIONS, adminCreateUserSchema } from '@/utils/validation';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as adminService from '@/services/adminService';
import * as packagingService from '@/services/packagingService';

const EMPTY = {
  name: '',
  email: '',
  phone: '',
  // No role is assumed: the administrator chooses one, and the schema refuses none.
  role: '',
  status: 'active',
  organization: '',
  state: '',
  district: '',
  password: '',
  confirmPassword: '',
  reason: '',
  packaging_unit_id: '',
};

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active — can sign in immediately' },
  { value: 'inactive', label: 'Inactive — created but cannot sign in yet' },
];

/**
 * Create an operational account.
 *
 * The administrator chooses the role; the API stores it on the account and the
 * permission table enforces it from then on. The account signs in through the
 * ordinary login form and lands in its own workspace — the form says which one,
 * so the choice is visible before it is made rather than discovered afterwards.
 *
 * A BEEKEEPER account is created together with its apiary record (the API does
 * both in one transaction), which is why the role hint says so.
 */
export function CreateUserDialog({ open, onClose, onCreated }) {
  const toast = useToast();
  const [formError, setFormError] = useState(null);
  // The facilities an account may be attached to. Read from the registry the
  // Administration → Packaging Units screen maintains — there is no second list.
  const [units, setUnits] = useState([]);
  const [unitsLoading, setUnitsLoading] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(adminCreateUserSchema),
    defaultValues: EMPTY,
  });

  useEffect(() => {
    if (open) {
      reset(EMPTY);
      setFormError(null);
    }
  }, [open, reset]);

  const role = watch('role');
  const landing = homeRouteForRole(role);
  const packagingUnitId = watch('packaging_unit_id');

  // Loaded when the dialog opens rather than on every render, and only needed for
  // the role that has a facility: a laboratory technician has no use for the list.
  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    setUnitsLoading(true);
    packagingService
      .listUnits({ pageSize: 100 })
      .then(({ units: rows }) => {
        if (!cancelled) setUnits(rows || []);
      })
      .catch(() => {
        if (!cancelled) setUnits([]);
      })
      .finally(() => {
        if (!cancelled) setUnitsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const onSubmit = async (values) => {
    setFormError(null);
    if (values.role === ROLES.PACKAGING_UNIT && !values.packaging_unit_id) {
      setFormError({
        message:
          'Attach this packaging account to a unit. Register the unit first under Administration → Packaging Units if it is not listed.',
      });
      return;
    }
    try {
      const result = await adminService.createUser({
        name: values.name,
        email: values.email,
        password: values.password,
        role: values.role,
        phone: values.phone || undefined,
        organization: values.organization || undefined,
        state: values.state || undefined,
        district: values.district || undefined,
        isActive: values.status === 'active',
        reason: values.reason || undefined,
        packagingUnitId: values.packaging_unit_id || undefined,
      });

      toast.success(
        result.message || `Account created as ${roleLabel(values.role)}`,
        `${values.email} — signs in at ${landing}`,
      );
      onCreated?.(result.user);
      onClose?.();
    } catch (caught) {
      setFormError(normaliseError(caught));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Create user"
      description="Provision an account for an operational role. It uses the same sign-in as every other account."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" form="create-user-form" loading={isSubmitting}>
            Create account
          </Button>
        </>
      }
    >
      <form id="create-user-form" onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError ? <Alert variant="danger">{formError.message}</Alert> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Full name"
            name="name"
            required
            autoComplete="off"
            placeholder="Sita Rao"
            error={errors.name?.message}
            {...register('name')}
          />
          <Input
            label="Email"
            name="email"
            type="email"
            required
            autoComplete="off"
            placeholder="sita.rao@honeychain.example.com"
            error={errors.email?.message}
            hint="This is the sign-in identity."
            {...register('email')}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Phone (optional)"
            name="phone"
            type="tel"
            placeholder="9876543210"
            error={errors.phone?.message}
            {...register('phone')}
          />
          <Input
            label="Organisation (optional)"
            name="organization"
            placeholder="Guntur District Laboratory"
            error={errors.organization?.message}
            hint="The laboratory, plant, centre or firm this account works for."
            {...register('organization')}
          />
        </div>

        <Select
          label="Role"
          name="role"
          required
          placeholder="Select role"
          options={ALL_ROLE_OPTIONS}
          error={errors.role?.message}
          hint="The role is stored on the account and enforced by the API on every request."
          {...register('role')}
        />

        <div className="rounded-lg border border-sand-200 bg-sand-100/40 p-3">
          <p className="text-sm text-ink-soft">
            <span className="font-medium text-ink">{roleLabel(role)}</span>{' '}
            {ROLE_ASSIGNMENT_HINTS[role] || ''}
          </p>
          <p className="mt-1.5 flex items-center gap-1.5 text-xs text-ink-muted">
            <FlaskConical size={13} aria-hidden="true" />
            Signs in at the existing login and lands on{' '}
            <span className="font-mono text-ink-soft">{landing}</span>
          </p>
        </div>

        {role === ROLES.PACKAGING_UNIT ? (
          <div className="space-y-2">
            <Select
              label="Packaging unit"
              name="packaging_unit_id"
              required
              options={units.map((unit) => ({
                value: unit.id,
                label: `${unit.name} · ${unit.unit_code}${
                  unit.is_active === false ? ' (inactive)' : ''
                }`,
              }))}
              placeholder={
                unitsLoading
                  ? 'Loading the units...'
                  : units.length
                    ? 'Select packaging unit'
                    : 'No packaging unit registered yet'
              }
              error={errors.packaging_unit_id?.message}
              hint="Where this operator works. They see this unit automatically at sign-in and cannot pack under another."
              {...register('packaging_unit_id')}
            />
            {!unitsLoading && !units.length ? (
              <p className="text-xs text-ink-muted">
                Register the facility first under{' '}
                <span className="font-medium text-ink-soft">Administration → Packaging Units</span>,
                then create this account.
              </p>
            ) : null}
            {packagingUnitId ? (
              <p className="flex items-center gap-1.5 text-xs text-ink-muted">
                <Building2 size={13} aria-hidden="true" />
                The operator signs in at the existing login and lands on /packaging with this unit
                already selected.
              </p>
            ) : null}
          </div>
        ) : null}

        <Select
          label="Account status"
          name="status"
          required
          options={STATUS_OPTIONS}
          error={errors.status?.message}
          hint="An inactive account exists but cannot sign in until an administrator activates it."
          {...register('status')}
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Password"
            name="password"
            type="password"
            required
            autoComplete="new-password"
            error={errors.password?.message}
            hint="At least 8 characters, with letters and numbers."
            {...register('password')}
          />
          <Input
            label="Confirm password"
            name="confirmPassword"
            type="password"
            required
            autoComplete="new-password"
            error={errors.confirmPassword?.message}
            {...register('confirmPassword')}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <Input
            label="District (optional)"
            name="district"
            placeholder="Guntur"
            error={errors.district?.message}
            {...register('district')}
          />
          <Input
            label="State (optional)"
            name="state"
            placeholder="Andhra Pradesh"
            error={errors.state?.message}
            {...register('state')}
          />
          <Input
            label="Note (optional)"
            name="reason"
            placeholder="Joined this week"
            error={errors.reason?.message}
            hint="Recorded in the audit log."
            {...register('reason')}
          />
        </div>

        <Alert variant="info">
          <span className="flex items-start gap-2">
            <Info size={15} className="mt-0.5 flex-none" aria-hidden="true" />
            <span>
              Share the password with the person directly. The account appears in this directory
              immediately, its creation is written to the audit log, and the role can be changed here
              later. Role assignment is enforced by the API — this form is the only way to grant a
              role, and no user can grant one to themselves.
            </span>
          </span>
        </Alert>

        {role === ROLES.BEEKEEPER ? (
          <p className="text-xs text-ink-muted">
            A beekeeper account is created together with its apiary record, which starts{' '}
            <Badge variant="pending" size="sm">
              Pending review
            </Badge>{' '}
            — the apiary is verified by a KVIC officer afterwards, not by this form.
          </p>
        ) : null}
      </form>
    </Modal>
  );
}

export default CreateUserDialog;
