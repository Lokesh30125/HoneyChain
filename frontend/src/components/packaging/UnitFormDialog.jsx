import { useEffect, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as packagingService from '@/services/packagingService';

const EMPTY = {
  name: '',
  registration_identifier: '',
  location: '',
  address: '',
  district: '',
  state: '',
  contact_email: '',
  contact_phone: '',
  capacity_kg_per_day: '',
  status: 'ACTIVE',
  notes: '',
};

const STATUS_OPTIONS = [
  { value: 'ACTIVE', label: 'Active — takes packaging work' },
  { value: 'INACTIVE', label: 'Inactive — retired, takes no new work' },
];

/**
 * Register or edit a packaging unit.
 *
 * A packaging facility is a registered business, so the form asks for the two
 * things that identify one: **the name** and **the registration identifier**. The
 * identifier is required rather than optional because a register in which half the
 * entries cannot be told apart is not a register; a facility that genuinely has no
 * number is recorded as "Not registered", which is an answer, instead of a blank.
 *
 * Everything here is written to the database and read back — nothing is stored on
 * the client, and no unit code is typed: `HC-PKUNIT-…` is issued by the server, the
 * same way every other reference in the platform is.
 *
 * The fields are ordinary controlled inputs. They take continuous typing: an input
 * that accepts one character is a defect, not a quirk, and this form is covered by
 * the input test alongside every other screen.
 */
export function UnitFormDialog({ open, unit = null, onClose, onSaved }) {
  const toast = useToast();
  const isEdit = Boolean(unit);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});

  useEffect(() => {
    if (!open) return;
    setError(null);
    setFieldErrors({});
    setForm(
      unit
        ? {
            name: unit.name || '',
            registration_identifier: unit.registration_identifier || '',
            location: unit.location || '',
            address: unit.address || '',
            district: unit.district || '',
            state: unit.state || '',
            contact_email: unit.contact_email || '',
            contact_phone: unit.contact_phone || '',
            capacity_kg_per_day: unit.capacity_kg_per_day ? String(unit.capacity_kg_per_day) : '',
            status: unit.status || 'ACTIVE',
            notes: unit.notes || '',
          }
        : EMPTY,
    );
  }, [open, unit]);

  const setField = (field) => (event) => {
    const { value } = event.target;
    setForm((current) => ({ ...current, [field]: value }));
  };

  function validate() {
    const errors = {};
    if (form.name.trim().length < 2) {
      errors.name = 'Give the unit a name of at least 2 characters.';
    }
    if (form.registration_identifier.trim().length < 2) {
      errors.registration_identifier =
        'Record the facility\u2019s registration number, or write "Not registered".';
    }
    if (form.contact_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.contact_email.trim())) {
      errors.contact_email = 'Enter a valid email address.';
    }
    if (form.capacity_kg_per_day && !(Number(form.capacity_kg_per_day) > 0)) {
      errors.capacity_kg_per_day = 'Enter the daily capacity as a positive number, or leave it blank.';
    }
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSubmit(event) {
    event?.preventDefault();
    if (!validate()) return;
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: form.name.trim(),
        registration_identifier: form.registration_identifier.trim(),
        location: form.location.trim() || null,
        address: form.address.trim() || null,
        district: form.district.trim() || null,
        state: form.state.trim() || null,
        status: form.status,
        ...(form.contact_email.trim() ? { contact_email: form.contact_email.trim() } : {}),
        ...(form.contact_phone.trim() ? { contact_phone: form.contact_phone.trim() } : {}),
        ...(form.capacity_kg_per_day
          ? { capacity_kg_per_day: Number(form.capacity_kg_per_day) }
          : {}),
        ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
      };
      const saved = isEdit
        ? await packagingService.updateUnit(unit.id, payload)
        : await packagingService.createUnit(payload);
      // The write is done. The toast names the server-issued code, which is the
      // receipt that the row exists and what it is called.
      toast.success(
        isEdit ? `Unit ${saved.unit_code} updated` : `Unit ${saved.unit_code} registered`,
        saved.name,
      );
      try {
        onSaved?.(saved);
      } catch {
        // A failure to reload the list is the list's problem, not the write's:
        // reporting it here would say the registration failed when it did not.
      }
      onClose?.();
    } catch (caught) {
      const normalised = normaliseError(caught);
      setFieldErrors(normalised.fieldErrors || {});
      setError(normalised);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={saving ? () => {} : onClose}
      size="lg"
      title={isEdit ? 'Edit packaging unit' : 'Register a packaging unit'}
      description={
        isEdit
          ? `${unit.unit_code} · the unit code is issued by the platform and cannot be changed`
          : 'The facility that fills and codes the packages. Accounts are attached to it afterwards.'
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="unit-form"
            loading={saving}
            data-testid="submit-packaging-unit"
          >
            {isEdit ? 'Save changes' : 'Register unit'}
          </Button>
        </>
      }
    >
      <form id="unit-form" className="space-y-4" onSubmit={handleSubmit} noValidate>
        {error ? <Alert variant="danger">{error.message}</Alert> : null}

        <Input
          label="Unit name"
          name="name"
          required
          value={form.name}
          onChange={setField('name')}
          error={fieldErrors.name}
          placeholder="Guntur Honey Packing Unit"
          hint="A facility could have more than one packing line — the code tells them apart later."
          data-testid="unit-name"
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Registration identifier"
            name="registration_identifier"
            required
            value={form.registration_identifier}
            onChange={setField('registration_identifier')}
            error={fieldErrors.registration_identifier}
            placeholder="FSSAI 12345678901234"
            hint='The facility&rsquo;s own registration number, or "Not registered" if it has none.'
            data-testid="unit-registration"
          />
          <Input
            label="Location"
            name="location"
            value={form.location}
            onChange={setField('location')}
            error={fieldErrors.location}
            placeholder="Guntur"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="District"
            name="district"
            value={form.district}
            onChange={setField('district')}
            error={fieldErrors.district}
            placeholder="Guntur"
          />
          <Input
            label="State"
            name="state"
            value={form.state}
            onChange={setField('state')}
            error={fieldErrors.state}
            placeholder="Andhra Pradesh"
          />
        </div>

        <Input
          label="Address"
          name="address"
          value={form.address}
          onChange={setField('address')}
          error={fieldErrors.address}
          placeholder="12 Market Road, Guntur 522001"
          hint="Where the facility actually is. Shown on the operator's own workspace."
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Contact email"
            name="contact_email"
            type="email"
            value={form.contact_email}
            onChange={setField('contact_email')}
            error={fieldErrors.contact_email}
            placeholder="unit@example.com"
          />
          <Input
            label="Contact phone"
            name="contact_phone"
            type="tel"
            value={form.contact_phone}
            onChange={setField('contact_phone')}
            error={fieldErrors.contact_phone}
            placeholder="9876543210"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="Status"
            name="status"
            required
            options={STATUS_OPTIONS}
            value={form.status}
            onChange={setField('status')}
            error={fieldErrors.status}
            hint="An inactive unit keeps every run it recorded and can take no new work."
          />
          <Input
            label="Capacity (optional)"
            name="capacity_kg_per_day"
            type="number"
            step="0.001"
            min="0"
            value={form.capacity_kg_per_day}
            onChange={setField('capacity_kg_per_day')}
            error={fieldErrors.capacity_kg_per_day}
            hint="Kilograms per day, as the facility states it."
          />
        </div>

        <Input
          label="Notes (optional)"
          name="notes"
          value={form.notes}
          onChange={setField('notes')}
          error={fieldErrors.notes}
          hint="Anything the next administrator should know about this facility."
        />
      </form>
    </Modal>
  );
}

export default UnitFormDialog;
