import { useEffect, useMemo, useState } from 'react';
import { Building2 } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { SelectWithOther } from '@/components/ui/SelectWithOther';
import { PACKAGING_TYPES, packageSizeOptions } from '@/constants/packaging';
import { formatNumber } from '@/utils/format';

/**
 * Opening a packaging run against an approved batch.
 *
 * The dialog's only job is to collect what the operator knows and let the server
 * check it. It shows the approved quantity, what is already packed and what is
 * therefore left — read from the batch — and refuses, before sending anything, a
 * quantity that is not a positive number, a count that is not a whole number, or
 * a figure that plainly exceeds the remainder. The server checks all of it again,
 * because a client-side check is a courtesy and never the rule.
 *
 * Two of these fields are not really questions:
 *
 * * **The packaging unit** is where the signed-in operator works, and that is a
 *   fact about their account, not a choice. When the account is attached to one
 *   facility the dialog states it and does not offer it as a dropdown — there is
 *   nothing to choose. A dropdown appears only for a caller who may genuinely work
 *   across several facilities, which in practice is an administrator.
 * * **The packaging type and package size** start on *"Select packaging type"* and
 *   *"Select package size"*. No container and no size is guessed on the operator's
 *   behalf: a jar pressed by default would be recorded as a fact about the honey
 *   when nobody had said it. "Other" asks for the custom wording, and a size that
 *   is not one of the standard ones is typed.
 *
 * Nothing here can set a status or a code: a run is `PENDING` because the server
 * says so, and it is numbered `HC-PACK-…` by the server too.
 */
export function CreatePackagingDialog({
  open,
  onClose,
  batch = null,
  units = [],
  //: True when the caller's own account is attached to exactly one facility, in
  //: which case the unit is shown rather than offered.
  unitLocked = false,
  //: Sizes this packaging unit has already packed, read from its own completed and
  //: open runs. They are added to the standard sizes — never substituted for them —
  //: because a real size this facility used before is worth offering back.
  sizeHistory = [],
  onSubmit,
  submitting = false,
  error = null,
}) {
  const [form, setForm] = useState({
    packaging_unit_id: '',
    packaging_type: '',
    packaging_type_other: '',
    packaged_quantity: '',
    package_size: '',
    package_size_choice: '',
    number_of_packages: '',
    notes: '',
  });
  const [fieldErrors, setFieldErrors] = useState({});

  const remaining = batch ? Number(batch.remaining_quantity || 0) : 0;
  // Which batch this run is for. The row that opens this dialog is an
  // approved-batch list item, which names its batch as `batch_id`; a batch detail
  // names it `id`. Both mean the same record, so the dialog reads whichever it was
  // handed. (Sending the field the caller happened not to have would post a request
  // with no batch in it at all — a hole the API would have to catch with a 422.)
  const batchId = batch?.batch_id || batch?.id || null;
  const unitLabel = batch?.unit_label || 'unit';

  const attachedUnit = unitLocked ? units[0] || null : null;

  // The standard sizes in the batch's own unit, plus whatever this facility has
  // packed before. The size travels to the server as a number in the batch's unit;
  // the platform applies no conversion of its own, so the conversion happens here
  // where it can be seen.
  const sizeOptions = useMemo(
    () => [
      ...packageSizeOptions(batch?.unit, { extraSizes: sizeHistory }).map((option) => ({
        ...option,
        label: option.label,
      })),
      { value: 'OTHER', label: 'Other — specify the package size' },
    ],
    [batch?.unit, sizeHistory],
  );

  useEffect(() => {
    if (!open) return;
    setForm({
      packaging_unit_id: attachedUnit?.id || '',
      packaging_type: '',
      packaging_type_other: '',
      // The remainder is the natural first suggestion, and it is still only a
      // suggestion: the operator can pack less, never more.
      packaged_quantity: remaining > 0 ? String(remaining) : '',
      package_size: '',
      package_size_choice: '',
      number_of_packages: '',
      notes: '',
    });
    setFieldErrors({});
  }, [open, attachedUnit, remaining]);

  // Choosing a size keeps the number in step, and abandoning a typed one clears
  // it: a size typed for the previous choice must not sit behind the new one.
  function chooseSize(event) {
    const next = event.target.value;
    setForm((current) => ({
      ...current,
      package_size_choice: next,
      package_size: next === 'OTHER' ? '' : next,
    }));
  }

  const setField = (field) => (event) => {
    const { value } = event.target;
    setForm((current) => ({ ...current, [field]: value }));
  };

  function validate() {
    const errors = {};
    const quantity = Number(form.packaged_quantity);
    const size = Number(form.package_size);
    const count = Number(form.number_of_packages);

    if (!batchId) {
      errors.batch_id = 'This dialog needs the batch it is packing; reopen it from the worklist.';
    }
    if (!form.packaging_unit_id) {
      errors.packaging_unit_id = units.length
        ? 'Choose the packaging unit that is doing the work.'
        : 'This account is not attached to a packaging unit yet. An administrator attaches one from Administration → Packaging Units.';
    }
    if (!form.packaging_type) {
      errors.packaging_type = 'Choose what the honey is being packed into.';
    }
    if (form.packaging_type === 'OTHER' && !form.packaging_type_other.trim()) {
      errors.packaging_type_other = 'Say what the container is: "Other" on its own records nothing.';
    }
    if (!form.packaged_quantity || Number.isNaN(quantity) || quantity <= 0) {
      errors.packaged_quantity = 'Enter how much honey is being packed, as a positive number.';
    } else if (quantity > remaining) {
      errors.packaged_quantity = `Only ${formatNumber(remaining)} is left to pack on this batch.`;
    }
    if (!form.package_size_choice) {
      errors.package_size_choice = 'Choose the size of one package, or choose Other to type it.';
    }
    if (!form.package_size || Number.isNaN(size) || size <= 0) {
      errors.package_size = 'Enter the size of one package, as a positive number.';
    }
    if (
      !form.number_of_packages ||
      Number.isNaN(count) ||
      !Number.isInteger(count) ||
      count <= 0
    ) {
      errors.number_of_packages = 'Enter how many packages are being filled, as a whole number.';
    } else if (!Number.isNaN(size) && size > 0) {
      const total = size * count;
      if (Math.abs(total - quantity) > 0.0001) {
        errors.number_of_packages = `${count} × ${formatNumber(size)} is ${formatNumber(total)}, not ${formatNumber(quantity)}.`;
      }
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  function handleSubmit(event) {
    event?.preventDefault();
    if (!validate()) return;
    onSubmit?.({
      batch_id: batchId,
      packaging_unit_id: form.packaging_unit_id,
      packaging_type: form.packaging_type,
      ...(form.packaging_type === 'OTHER'
        ? { packaging_type_other: form.packaging_type_other.trim() }
        : {}),
      packaged_quantity: form.packaged_quantity,
      package_size: form.package_size,
      number_of_packages: Number(form.number_of_packages),
      ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Open a packaging run"
      description={
        batch
          ? `${batch.batch_code} · ${formatNumber(batch.approved_quantity)} ${batch.unit_label || ''} approved, ${formatNumber(batch.packaged_quantity)} already packed`
          : undefined
      }
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} loading={submitting} data-testid="submit-packaging">
            Open the run
          </Button>
        </div>
      }
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        {error ? <Alert variant="danger">{error}</Alert> : null}

        <div className="rounded-lg border border-sand-300 bg-sand-50 px-4 py-3 text-sm">
          <p className="text-ink-soft">
            Approval available to pack:{' '}
            <span className="font-medium text-ink">
              {formatNumber(remaining)} {batch?.unit_label || ''}
            </span>
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            This is the laboratory-approved quantity minus everything already packed on this batch.
            It is read from the batch&apos;s records and cannot be increased here.
          </p>
        </div>

        {attachedUnit ? (
          // The operator's own facility, stated rather than asked. Showing a
          // dropdown here would invite a choice the account is not entitled to
          // make, and the server refuses it anyway.
          <div>
            <p className="hc-label">Packaging unit</p>
            <div className="flex items-start gap-3 rounded-lg border border-sand-300 bg-white px-3 py-3">
              <Building2 size={18} className="mt-0.5 shrink-0 text-honey-600" aria-hidden="true" />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">
                  {attachedUnit.name}
                  <span className="ml-2 font-normal text-ink-muted">{attachedUnit.unit_code}</span>
                </p>
                <p className="mt-0.5 text-xs text-ink-muted">
                  The facility your account is attached to. This run is recorded against it.
                </p>
              </div>
            </div>
          </div>
        ) : (
          <Select
            label="Packaging unit"
            name="packaging_unit_id"
            required
            value={form.packaging_unit_id}
            onChange={setField('packaging_unit_id')}
            error={fieldErrors.packaging_unit_id}
            options={units.map((unit) => ({
              value: unit.id,
              label: `${unit.name} · ${unit.unit_code}`,
            }))}
            placeholder={units.length ? 'Select packaging unit' : 'No packaging unit available'}
            hint={
              units.length > 1
                ? 'Which facility is doing the work. Your account may work at more than one.'
                : undefined
            }
          />
        )}

        <SelectWithOther
          label="Packaging type"
          name="packaging_type"
          required
          value={form.packaging_type}
          onChange={setField('packaging_type')}
          options={PACKAGING_TYPES}
          placeholder="Select packaging type"
          otherValue={form.packaging_type_other}
          onOtherChange={(text) => setForm((current) => ({ ...current, packaging_type_other: text }))}
          otherLabel="Custom packaging type"
          otherPlaceholder="For example: 500 g glass jar with brass lid"
          error={fieldErrors.packaging_type || fieldErrors.packaging_type_other}
          hint="What the honey goes into. Choose Other for containers outside the list."
        />

        <div className="grid gap-4 sm:grid-cols-3">
          <Input
            label={`Honey being packed (${batch?.unit_label || 'unit'})`}
            name="packaged_quantity"
            type="number"
            step="0.001"
            min="0"
            required
            value={form.packaged_quantity}
            onChange={setField('packaged_quantity')}
            error={fieldErrors.packaged_quantity}
          />
          <div>
            <Select
              label={`Package size (${unitLabel})`}
              name="package_size_choice"
              required
              value={form.package_size_choice}
              onChange={chooseSize}
              options={sizeOptions}
              placeholder="Select package size"
              error={fieldErrors.package_size_choice}
              hint="Sizes are recorded in the batch's own unit. Choose Other to type a different one."
            />
            {form.package_size_choice === 'OTHER' ? (
              <Input
                containerClassName="mt-3"
                label="Specify package size"
                name="package_size"
                type="number"
                step="0.001"
                min="0"
                required
                value={form.package_size}
                onChange={setField('package_size')}
                error={fieldErrors.package_size}
                hint={`In ${unitLabel}.`}
                data-testid="package-size-other"
              />
            ) : form.package_size_choice ? (
              <p className="mt-3 text-xs text-ink-muted">
                Each package will be recorded as {formatNumber(form.package_size)} {unitLabel}.
              </p>
            ) : null}
          </div>
          <Input
            label="Number of packages"
            name="number_of_packages"
            type="number"
            step="1"
            min="1"
            required
            value={form.number_of_packages}
            onChange={setField('number_of_packages')}
            error={fieldErrors.number_of_packages}
          />
        </div>

        <Input
          label="Notes"
          name="notes"
          value={form.notes}
          onChange={setField('notes')}
          hint="Optional. Anything the next person reading this run should know."
        />
      </form>
    </Modal>
  );
}

export default CreatePackagingDialog;
