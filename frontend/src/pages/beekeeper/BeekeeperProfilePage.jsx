import { useCallback, useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { Building2, ClipboardList, Info, MapPin, Save, Wheat } from 'lucide-react';

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
import {
  VerificationBadge,
  VERIFICATION_DESCRIPTIONS,
} from '@/components/beekeepers/VerificationBadge';
import { BEE_SPECIES_OPTIONS, beekeeperProfileSchema } from '@/utils/validation';
import { formatDate } from '@/utils/format';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as beekeeperService from '@/services/beekeeperService';

function toForm(record) {
  return {
    village: record?.village || '',
    mandal: record?.mandal || '',
    district: record?.district || '',
    state: record?.state || '',
    pincode: record?.pincode || '',
    experienceYears: record?.experience_years ?? '',
    beeSpecies: record?.bee_species || '',
    numberOfHives: record?.number_of_hives ?? '',
  };
}

/**
 * The beekeeper's own record.
 *
 * Only self-service fields are editable: apiary location, experience, species
 * and hive count. The beekeeper code, verification status and cluster are
 * platform-controlled — a beekeeper cannot verify themselves or join a cluster,
 * and the API enforces that even if someone crafts the request.
 */
export default function BeekeeperProfilePage() {
  const toast = useToast();
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [formError, setFormError] = useState(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm({ resolver: zodResolver(beekeeperProfileSchema), defaultValues: toForm(null) });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await beekeeperService.getMyBeekeeperRecord();
      setRecord(payload);
      reset(toForm(payload));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [reset]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const updated = await beekeeperService.updateMyBeekeeperRecord({
        village: values.village || null,
        mandal: values.mandal || null,
        district: values.district || null,
        state: values.state || null,
        pincode: values.pincode || null,
        experience_years: values.experienceYears ?? null,
        bee_species: values.beeSpecies || null,
        number_of_hives: values.numberOfHives ?? null,
      });
      setRecord(updated);
      reset(toForm(updated));
      toast.success('Beekeeper record saved');
    } catch (caught) {
      setFormError(normaliseError(caught));
    }
  });

  if (loading) return <LoadingState message="Loading your beekeeper record…" />;

  if (error) {
    // A non-beekeeper reaching this route gets a clear explanation, not a blank screen.
    return (
      <div className="space-y-6">
        <Breadcrumb items={[{ label: 'My Beekeeper Profile' }]} />
        <ErrorState
          error={error}
          title="No beekeeper record"
          onRetry={load}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'My Beekeeper Profile' }]} />
      <PageHeader
        title="My beekeeper profile"
        description="The apiary details a KVIC officer reviews when your registration is verified."
        badge={<VerificationBadge status={record?.verification_status} />}
      />

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader
            title="Apiary details"
            description="Keep these current — they are what the cluster coordinator sees."
            icon={<ClipboardList size={16} />}
          />
          <CardBody>
            <form onSubmit={submit} noValidate className="space-y-5">
              {formError ? (
                <Alert variant="danger" title="Could not save your record">
                  {formError.message}
                </Alert>
              ) : null}

              <div className="grid gap-5 sm:grid-cols-3">
                <Input
                  label="Village"
                  name="village"
                  error={errors.village?.message}
                  {...register('village')}
                />
                <Input
                  label="Mandal"
                  name="mandal"
                  error={errors.mandal?.message}
                  {...register('mandal')}
                />
                <Input
                  label="District"
                  name="district"
                  error={errors.district?.message}
                  {...register('district')}
                />
                <Input
                  label="State"
                  name="state"
                  leftIcon={<MapPin size={16} />}
                  error={errors.state?.message}
                  {...register('state')}
                />
                <Input
                  label="PIN code"
                  name="pincode"
                  inputMode="numeric"
                  maxLength={6}
                  error={errors.pincode?.message}
                  {...register('pincode')}
                />
              </div>

              <div className="grid gap-5 sm:grid-cols-3">
                <Input
                  label="Experience (years)"
                  name="experienceYears"
                  type="number"
                  min={0}
                  max={90}
                  error={errors.experienceYears?.message}
                  {...register('experienceYears')}
                />
                <Input
                  label="Number of hives"
                  name="numberOfHives"
                  type="number"
                  min={0}
                  error={errors.numberOfHives?.message}
                  {...register('numberOfHives')}
                />
                <Select
                  label="Bee species"
                  name="beeSpecies"
                  placeholder="Choose a species"
                  options={BEE_SPECIES_OPTIONS.map((species) => ({ value: species, label: species }))}
                  error={errors.beeSpecies?.message}
                  {...register('beeSpecies')}
                />
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  type="submit"
                  loading={isSubmitting}
                  disabled={!isDirty}
                  leftIcon={<Save size={16} />}
                >
                  Save changes
                </Button>
                {isDirty ? (
                  <Button variant="ghost" type="button" onClick={() => reset(toForm(record))}>
                    Discard
                  </Button>
                ) : null}
              </div>
            </form>
          </CardBody>
        </Card>

        <div className="space-y-6">
          <Card className="h-fit">
            <CardHeader
              title="Registration"
              description="Assigned by the platform."
              icon={<Wheat size={16} />}
            />
            <CardBody className="space-y-4 text-sm">
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Beekeeper ID</p>
                <p className="mt-0.5 font-mono text-ink">{record?.beekeeper_code || '—'}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">
                  Verification status
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-2">
                  <VerificationBadge status={record?.verification_status} size="sm" />
                </p>
                <p className="mt-1.5 text-xs text-ink-muted">
                  {VERIFICATION_DESCRIPTIONS[record?.verification_status] || ''}
                </p>
              </div>
              {record?.verification_remarks ? (
                <div>
                  <p className="text-xs uppercase tracking-wide text-ink-muted">
                    Officer remarks
                  </p>
                  <p className="mt-0.5 text-ink-soft">{record.verification_remarks}</p>
                </div>
              ) : null}
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">Registered on</p>
                <p className="mt-0.5 text-ink">{formatDate(record?.registration_date)}</p>
              </div>
              {record?.verified_at ? (
                <div>
                  <p className="text-xs uppercase tracking-wide text-ink-muted">Verified on</p>
                  <p className="mt-0.5 text-ink">{formatDate(record?.verified_at)}</p>
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card className="h-fit">
            <CardHeader
              title="KVIC cluster"
              description="Assigned by a KVIC officer."
              icon={<Building2 size={16} />}
            />
            <CardBody className="space-y-3 text-sm">
              {record?.cluster ? (
                <>
                  <p className="font-medium text-ink">
                    {record.cluster.cluster_name}{' '}
                    <span className="font-normal text-ink-muted">({record.cluster.cluster_code})</span>
                  </p>
                  <p className="text-ink-soft">
                    {[record.cluster.district, record.cluster.state].filter(Boolean).join(', ')}
                  </p>
                  <Badge variant={record.cluster.is_active ? 'success' : 'neutral'} size="sm">
                    {record.cluster.is_active ? 'Active cluster' : 'Cluster inactive'}
                  </Badge>
                </>
              ) : (
                <p className="text-ink-soft">
                  You are not part of a cluster yet. An officer assigns clusters after reviewing
                  your registration.
                </p>
              )}
            </CardBody>
          </Card>

          <Alert variant="info" title="What happens next">
            <ul className="mt-1 space-y-1">
              <li className="flex gap-2">
                <Info size={15} className="mt-0.5 flex-none" aria-hidden="true" />
                A KVIC officer reviews your details and records a decision.
              </li>
              <li className="flex gap-2">
                <Info size={15} className="mt-0.5 flex-none" aria-hidden="true" />
                Every decision is kept in an append-only history you can ask about.
              </li>
            </ul>
          </Alert>
        </div>
      </div>
    </div>
  );
}
