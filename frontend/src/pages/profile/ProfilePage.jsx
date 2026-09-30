import { useCallback, useEffect, useMemo, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { IdCard, Mail, MapPin, Phone, ShieldCheck, User } from 'lucide-react';
import { z } from 'zod';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { PageHeader } from '@/components/common/PageHeader';
import { VerificationBadge } from '@/components/beekeepers/VerificationBadge';
import { GENDER_OPTIONS, profileDetailsSchema } from '@/utils/validation';
import { formatDateTime } from '@/utils/format';
import { normaliseError } from '@/utils/errors';
import { ROLES, roleLabel } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/useToast';
import * as authService from '@/services/authService';
import * as profileService from '@/services/profileService';

const accountSchema = z.object({
  name: z
    .string({ required_error: 'Please enter your full name' })
    .trim()
    .min(2, 'Name must be at least 2 characters')
    .max(120, 'Name must be 120 characters or fewer'),
  phone: z
    .string()
    .trim()
    .optional()
    .or(z.literal(''))
    .refine(
      (value) => !value || /^(\+?\d{8,15})$/.test(value.replace(/[\s-]/g, '')),
      { message: 'Enter a valid phone number, e.g. 9876543210 or +919876543210' },
    ),
});

const EMPTY_DETAILS = {
  profilePhoto: '',
  dateOfBirth: '',
  gender: '',
  address: '',
  village: '',
  mandal: '',
  district: '',
  state: '',
  pincode: '',
};

function detailsToForm(profile) {
  return {
    profilePhoto: profile?.profile_photo || '',
    dateOfBirth: profile?.date_of_birth || '',
    gender: profile?.gender || '',
    address: profile?.address || '',
    village: profile?.village || '',
    mandal: profile?.mandal || '',
    district: profile?.district || '',
    state: profile?.state || '',
    pincode: profile?.pincode || '',
  };
}

/**
 * Profile page.
 *
 * Two audiences in one screen: every role sees Personal, Location and Account;
 * a beekeeper additionally sees their apiary summary with a link to the fuller
 * beekeeper profile.
 *
 * Email, role and account status are read-only here — they are administrator
 * controlled, and the API rejects attempts to change them rather than silently
 * ignoring them.
 */
export default function ProfilePage() {
  const { user, applyProfile } = useAuth();
  const toast = useToast();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [detailsError, setDetailsError] = useState(null);
  const [accountError, setAccountError] = useState(null);

  const accountForm = useForm({
    resolver: zodResolver(accountSchema),
    defaultValues: { name: user?.name || '', phone: user?.phone || '' },
  });

  const detailsForm = useForm({
    resolver: zodResolver(profileDetailsSchema),
    defaultValues: EMPTY_DETAILS,
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await profileService.getMyProfile();
      setData(payload);
      detailsForm.reset(detailsToForm(payload.profile));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
    // Forms are stable instances; re-running on their identity would refetch on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Name and phone belong to the account, not the profile payload, so they are
  // seeded from the session and refreshed whenever the session user changes.
  useEffect(() => {
    accountForm.reset({ name: user?.name || '', phone: user?.phone || '' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.name, user?.phone]);

  const submitAccount = accountForm.handleSubmit(async (values) => {
    setAccountError(null);
    try {
      // Name and phone live on the account; the profile endpoint never touches them.
      const updated = await authService.updateProfile({
        name: values.name,
        phone: values.phone || null,
      });
      applyProfile(updated);
      setData((previous) =>
        previous ? { ...previous, account: { ...previous.account, ...updated } } : previous,
      );
      toast.success('Account details saved');
    } catch (caught) {
      setAccountError(normaliseError(caught));
    }
  });

  const submitDetails = detailsForm.handleSubmit(async (values) => {
    setDetailsError(null);
    try {
      const payload = await profileService.updateMyProfile({
        profile_photo: values.profilePhoto || null,
        date_of_birth: values.dateOfBirth || null,
        gender: values.gender || null,
        address: values.address || null,
        village: values.village || null,
        mandal: values.mandal || null,
        district: values.district || null,
        state: values.state || null,
        pincode: values.pincode || null,
      });
      setData(payload);
      detailsForm.reset(detailsToForm(payload.profile));
      toast.success('Profile details saved');
    } catch (caught) {
      setDetailsError(normaliseError(caught));
    }
  });

  const beekeeper = data?.beekeeper;
  const account = data?.account;

  const accountBadges = useMemo(() => {
    if (!account) return null;
    return (
      <>
        <Badge variant="forest" size="sm">
          {account.role_label || roleLabel(account.role)}
        </Badge>
        <Badge variant={account.is_active ? 'success' : 'neutral'} size="sm">
          {account.is_active ? 'Active' : 'Inactive'}
        </Badge>
        <Badge variant={account.is_verified ? 'info' : 'neutral'} size="sm">
          {account.is_verified ? 'Contact verified' : 'Contact not verified'}
        </Badge>
      </>
    );
  }, [account]);

  if (loading) return <LoadingState message="Loading your profile…" />;
  if (error) return <ErrorState error={error} onRetry={load} />;

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'My Profile' }]} />
      <PageHeader
        title="My profile"
        description="Details attached to the records you create. Only what you provide is stored — every optional field can stay empty."
        badge={accountBadges}
      />

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Personal details"
              description="Optional background information."
              icon={<User size={16} />}
            />
            <CardBody>
              <form onSubmit={submitDetails} noValidate className="space-y-5">
                {detailsError ? (
                  <Alert variant="danger" title="Could not save your details">
                    {detailsError.message}
                  </Alert>
                ) : null}

                <div className="grid gap-5 sm:grid-cols-2">
                  <Input
                    label="Date of birth"
                    name="dateOfBirth"
                    type="date"
                    error={detailsForm.formState.errors.dateOfBirth?.message}
                    {...detailsForm.register('dateOfBirth')}
                  />
                  <Select
                    label="Gender"
                    name="gender"
                    placeholder="Prefer not to say"
                    options={GENDER_OPTIONS}
                    error={detailsForm.formState.errors.gender?.message}
                    {...detailsForm.register('gender')}
                  />
                </div>

                <Input
                  label="Address"
                  name="address"
                  error={detailsForm.formState.errors.address?.message}
                  hint="House or street address, if you want it on record."
                  {...detailsForm.register('address')}
                />

                <Input
                  label="Profile photo link"
                  name="profilePhoto"
                  placeholder="https://…"
                  error={detailsForm.formState.errors.profilePhoto?.message}
                  hint="Optional. Uploads arrive in a later phase; a link works today."
                  {...detailsForm.register('profilePhoto')}
                />

                <div className="border-t border-sand-200 pt-5">
                  <h3 className="text-sm font-semibold text-ink">Location</h3>
                  <p className="mt-0.5 text-xs text-ink-muted">
                    Used to place your records on the traceability map and to match you to a KVIC
                    cluster.
                  </p>
                </div>

                <div className="grid gap-5 sm:grid-cols-3">
                  <Input
                    label="Village"
                    name="village"
                    error={detailsForm.formState.errors.village?.message}
                    {...detailsForm.register('village')}
                  />
                  <Input
                    label="Mandal"
                    name="mandal"
                    error={detailsForm.formState.errors.mandal?.message}
                    {...detailsForm.register('mandal')}
                  />
                  <Input
                    label="District"
                    name="district"
                    error={detailsForm.formState.errors.district?.message}
                    {...detailsForm.register('district')}
                  />
                  <Input
                    label="State"
                    name="state"
                    leftIcon={<MapPin size={16} />}
                    error={detailsForm.formState.errors.state?.message}
                    {...detailsForm.register('state')}
                  />
                  <Input
                    label="PIN code"
                    name="pincode"
                    inputMode="numeric"
                    maxLength={6}
                    error={detailsForm.formState.errors.pincode?.message}
                    {...detailsForm.register('pincode')}
                  />
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button type="submit" loading={detailsForm.formState.isSubmitting}>
                    Save details
                  </Button>
                  {detailsForm.formState.isDirty ? (
                    <Button
                      variant="ghost"
                      type="button"
                      onClick={() => detailsForm.reset(detailsToForm(data?.profile))}
                    >
                      Discard
                    </Button>
                  ) : null}
                </div>
              </form>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Account & contact"
              description="Your name and phone number, as they appear on records."
              icon={<Phone size={16} />}
            />
            <CardBody>
              <form onSubmit={submitAccount} noValidate className="space-y-5">
                {accountError ? (
                  <Alert variant="danger" title="Could not save your account details">
                    {accountError.message}
                  </Alert>
                ) : null}

                <Input
                  label="Full name"
                  name="name"
                  required
                  leftIcon={<User size={16} />}
                  error={accountForm.formState.errors.name?.message}
                  {...accountForm.register('name')}
                />

                <Input
                  label="Phone"
                  name="phone"
                  type="tel"
                  leftIcon={<Phone size={16} />}
                  error={accountForm.formState.errors.phone?.message}
                  hint="Leave blank to remove. Used for cluster coordination only."
                  {...accountForm.register('phone')}
                />

                <div className="flex flex-wrap gap-2">
                  <Button
                    type="submit"
                    loading={accountForm.formState.isSubmitting}
                    disabled={!accountForm.formState.isDirty}
                  >
                    Save account details
                  </Button>
                  {accountForm.formState.isDirty ? (
                    <Button
                      variant="ghost"
                      type="button"
                      onClick={() =>
                        accountForm.reset({
                          name: account?.name || '',
                          phone: account?.phone || '',
                        })
                      }
                    >
                      Discard
                    </Button>
                  ) : null}
                </div>
              </form>
            </CardBody>
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="h-fit">
            <CardHeader
              title="Account"
              description="Managed by the platform."
              icon={<ShieldCheck size={16} />}
            />
            <CardBody className="space-y-4 text-sm">
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Email</p>
                <p className="mt-0.5 flex items-center gap-2 text-ink">
                  <Mail size={15} className="text-ink-muted" aria-hidden="true" />
                  {account?.email}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Role</p>
                <p className="mt-1">
                  <Badge variant="forest" size="sm">
                    {account?.role_label || roleLabel(account?.role)}
                  </Badge>
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Registered</p>
                <p className="mt-0.5 text-ink">{formatDateTime(account?.created_at)}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Last sign-in</p>
                <p className="mt-0.5 text-ink">{formatDateTime(account?.last_login_at)}</p>
              </div>
              <p className="border-t border-sand-200 pt-3 text-xs text-ink-muted">
                To change your email or role, contact a platform administrator. Changes are recorded
                in the audit log.
              </p>
            </CardBody>
          </Card>

          {beekeeper ? (
            <Card className="h-fit">
              <CardHeader
                title="Beekeeper record"
                description="Your registration with the platform."
                icon={<IdCard size={16} />}
              />
              <CardBody className="space-y-4 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium text-ink">
                    {beekeeper.beekeeper_code}
                  </span>
                  <VerificationBadge status={beekeeper.verification_status} size="sm" />
                </div>

                <dl className="grid grid-cols-2 gap-3">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-ink-muted">Experience</dt>
                    <dd className="mt-0.5 text-ink">
                      {beekeeper.experience_years != null
                        ? `${beekeeper.experience_years} years`
                        : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-ink-muted">Hives</dt>
                    <dd className="mt-0.5 text-ink">{beekeeper.number_of_hives ?? '—'}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-xs uppercase tracking-wide text-ink-muted">Bee species</dt>
                    <dd className="mt-0.5 text-ink">{beekeeper.bee_species || '—'}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-xs uppercase tracking-wide text-ink-muted">KVIC cluster</dt>
                    <dd className="mt-0.5 text-ink">
                      {beekeeper.cluster_name
                        ? `${beekeeper.cluster_name} (${beekeeper.cluster_code})`
                        : 'Not assigned yet — a KVIC officer assigns clusters.'}
                    </dd>
                  </div>
                </dl>

                {user?.role === ROLES.BEEKEEPER ? (
                  <Button to="/beekeeper/profile" variant="secondary" size="sm">
                    Open beekeeper profile
                  </Button>
                ) : null}
              </CardBody>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
