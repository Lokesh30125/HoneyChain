import { useEffect, useMemo, useState } from 'react';
import { useFieldArray, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { AlertTriangle, Plus, Trash2, Wheat } from 'lucide-react';
import { z } from 'zod';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { COLLECTION_MESSAGES, COLLECTION_UNITS } from '@/constants/collection';

/**
 * The harvest form.
 *
 * Two fields that a naive implementation would include are missing on purpose:
 * **beekeeper** and **cluster**. The backend derives both from the signed-in
 * beekeeper's own record and their current cluster membership, so offering the
 * choice would be offering a capability the API refuses. The panel says where the
 * record will land instead, so the beekeeper is never guessing.
 *
 * Quantities are entered per hive. The total is the sum of what was actually
 * weighed at each hive — not a separate number that could disagree with its
 * parts — and when only one hive is selected a single total is enough.
 */

const PER_HIVE_MAX = 500;

const schema = z.object({
  collection_date: z.string().min(1, 'Choose the date the honey was harvested'),
  unit: z.enum(['KG', 'GRAM']),
  status: z.enum(['PLANNED', 'IN_PROGRESS']),
  notes: z.string().max(2000, 'Notes are limited to 2000 characters').optional().or(z.literal('')),
  hives: z
    .array(
      z.object({
        hive_id: z.string().min(1, 'Choose a hive'),
        quantity: z
          .string()
          .optional()
          .or(z.literal(''))
          .refine(
            (value) => value === '' || (Number(value) > 0 && Number(value) <= PER_HIVE_MAX),
            `Quantity must be between 0 and ${PER_HIVE_MAX}`,
          ),
      }),
    )
    .min(1, COLLECTION_MESSAGES.emptyEligibleHives),
});

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function RecordCollectionPanel({
  eligibleHives = [],
  loadingHives = false,
  clusterLabel = null,
  onSubmit,
  submitting = false,
  error = null,
  onDismissError,
}) {
  const [reusedNotice, setReusedNotice] = useState(false);
  const {
    register,
    control,
    handleSubmit,
    watch,
    reset,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: {
      collection_date: todayIso(),
      unit: 'KG',
      status: 'IN_PROGRESS',
      notes: '',
      hives: [{ hive_id: '', quantity: '' }],
    },
  });

  const { fields, append, remove } = useFieldArray({ control, name: 'hives' });
  const watched = watch('hives');
  const unit = watch('unit');

  const hiveOptions = useMemo(
    () => eligibleHives.map((hive) => ({
      value: hive.id,
      label: `${hive.hive_code}${hive.village ? ` · ${hive.village}` : ''}`,
    })),
    [eligibleHives],
  );

  // A hive can only contribute once; options already chosen elsewhere are marked
  // as taken so the same hive cannot be added twice and double-counted.
  const chosen = new Set((watched || []).map((row) => row.hive_id).filter(Boolean));

  const totalPreview = (watched || []).reduce((sum, row) => sum + (Number(row?.quantity) || 0), 0);

  useEffect(() => {
    if (!reusedNotice) return undefined;
    const timer = setTimeout(() => setReusedNotice(false), 5000);
    return () => clearTimeout(timer);
  }, [reusedNotice]);

  const submit = async (values) => {
    const rows = values.hives.filter((row) => row.hive_id);
    const single = rows.length === 1;
    // Send per-hive quantities when they were given; otherwise a single hive
    // carries the harvest and the server assigns the total to it.
    const payload = {
      hives: rows.map((row) => ({
        hive_id: row.hive_id,
        ...(row.quantity !== '' && row.quantity !== undefined ? { quantity: row.quantity } : {}),
      })),
      collection_date: values.collection_date,
      unit: values.unit,
      status: values.status,
      ...(values.notes ? { notes: values.notes } : {}),
    };

    if (single && rows[0].quantity === '') {
      // Nothing to send yet: the server needs one quantity or the other.
      setReusedNotice(false);
      return;
    }

    const result = await onSubmit({
      ...payload,
      ...(single ? { total_quantity: rows[0].quantity } : {}),
    });
    if (result?.reused) setReusedNotice(true);
    if (result?.ok !== false) {
      reset({
        collection_date: todayIso(),
        unit: values.unit,
        status: values.status,
        notes: '',
        hives: [{ hive_id: '', quantity: '' }],
      });
    }
  };

  const noHives = !loadingHives && eligibleHives.length === 0;

  return (
    <Card>
      <CardHeader
        title="Record a collection"
        description="Select the hives the honey came from and enter what was actually harvested."
        icon={<Wheat size={18} aria-hidden="true" />}
      />
      <CardBody className="space-y-5">
        {noHives ? (
          <Alert variant="info" title={COLLECTION_MESSAGES.emptyEligibleHives}>
            Register a hive in My Hives first — a harvest has to name the hives it came from, and a
            hive under maintenance or retired cannot be harvested.
          </Alert>
        ) : null}

        {error ? (
          <Alert variant="danger" title="The collection could not be recorded" onClose={onDismissError}>
            {error}
          </Alert>
        ) : null}

        {reusedNotice ? (
          <Alert variant="warning" title="This harvest was already recorded">
            A collection with the same reference already exists, so it was returned instead of
            being recorded twice.
          </Alert>
        ) : null}

        <form className="space-y-5" onSubmit={handleSubmit(submit)} noValidate>
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-ink">Source hives</p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                leftIcon={<Plus size={14} aria-hidden="true" />}
                onClick={() => append({ hive_id: '', quantity: '' })}
                disabled={fields.length >= eligibleHives.length}
              >
                Add hive
              </Button>
            </div>

            {fields.map((field, index) => (
              <div key={field.id} className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]">
                <Select
                  label={index === 0 ? 'Hive' : undefined}
                  placeholder={loadingHives ? 'Loading hives...' : 'Choose a hive'}
                  options={hiveOptions.map((option) => ({
                    ...option,
                    label: chosen.has(option.value) && option.value !== watched?.[index]?.hive_id
                      ? `${option.label} (already selected)`
                      : option.label,
                  }))}
                  error={errors.hives?.[index]?.hive_id?.message}
                  {...register(`hives.${index}.hive_id`)}
                />
                <Input
                  label={index === 0 ? `Quantity (${unit === 'GRAM' ? 'g' : 'kg'})` : undefined}
                  type="number"
                  step="0.001"
                  min="0"
                  inputMode="decimal"
                  placeholder="0.000"
                  error={errors.hives?.[index]?.quantity?.message}
                  {...register(`hives.${index}.quantity`)}
                />
                <div className={index === 0 ? 'sm:pt-6' : ''}>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label="Remove hive"
                    leftIcon={<Trash2 size={14} aria-hidden="true" />}
                    onClick={() => (fields.length > 1 ? remove(index) : null)}
                    disabled={fields.length === 1}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            ))}

            <p className="text-xs text-ink-muted">
              {totalPreview > 0
                ? `Total from the hives entered: ${totalPreview} ${unit === 'GRAM' ? 'g' : 'kg'}`
                : 'Enter what was taken from each hive — the harvest total is the sum of these.'}
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Input
              label="Collection date"
              type="date"
              max={todayIso()}
              error={errors.collection_date?.message}
              {...register('collection_date')}
            />
            <Select label="Unit" options={COLLECTION_UNITS} error={errors.unit?.message} {...register('unit')} />
            <Select
              label="Stage"
              options={[
                { value: 'IN_PROGRESS', label: 'In progress' },
                { value: 'PLANNED', label: 'Planned' },
              ]}
              hint="Completion is its own step and creates the batch."
              error={errors.status?.message}
              {...register('status')}
            />
          </div>

          <Input
            label="Notes"
            placeholder="Floral source, weather, anything worth recording"
            error={errors.notes?.message}
            {...register('notes')}
          />

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-ink-muted">
              {clusterLabel
                ? `Recorded against your apiary and the cluster it belongs to: ${clusterLabel}.`
                : 'Recorded against your apiary. You are not in a cluster yet, so the harvest is recorded without one.'}
            </p>
            <Button type="submit" loading={submitting} disabled={noHives} leftIcon={<Wheat size={16} aria-hidden="true" />}>
              Save collection
            </Button>
          </div>

          {errors.hives?.message ? (
            <Alert variant="danger" title={<span className="flex items-center gap-2"><AlertTriangle size={16} aria-hidden="true" /> {errors.hives.message}</span>} />
          ) : null}
        </form>
      </CardBody>
    </Card>
  );
}

export default RecordCollectionPanel;
