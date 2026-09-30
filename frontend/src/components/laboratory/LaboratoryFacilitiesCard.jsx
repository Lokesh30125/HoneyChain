import { useCallback, useEffect, useState } from 'react';
import { Microscope } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { LAB_MESSAGES } from '@/constants/laboratory';
import * as laboratoryService from '@/services/laboratoryService';
import { normaliseError } from '@/utils/errors';

/**
 * The laboratories this platform knows about.
 *
 * A facility is reused across tests, never re-created per sample: one row, one
 * code, and every test that names it. `accredited` is what the facility *stated*
 * when it was registered — it is shown with that wording because HoneyChain does
 * not verify accreditation and does not claim it on anyone's behalf.
 */
const BLANK = { name: '', location: '', district: '', registration_identifier: '', accredited: null };

export function LaboratoryFacilitiesCard({ canManage = false }) {
  const [facilities, setFacilities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await laboratoryService.listFacilities({ pageSize: 100 });
      setFacilities(payload.facilities);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <LoadingState message="Loading laboratories..." />;
  if (error) return <ErrorState error={error} onRetry={load} />;

  return (
    <Card>
      <CardHeader
        title="Laboratories"
        description="Reused across tests — a facility is registered once and referenced by every sample it handles."
        icon={<Microscope size={18} aria-hidden="true" />}
        action={
          canManage ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setFormError(null);
                setForm({ ...BLANK });
              }}
            >
              Register a laboratory
            </Button>
          ) : null
        }
      />
      <CardBody>
        {facilities.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-sand-200 text-sm">
              <thead className="bg-sand-100/70">
                <tr>
                  {['Code', 'Name', 'Location', 'Accreditation', 'Status', 'Tests'].map((header) => (
                    <th
                      key={header}
                      scope="col"
                      className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-sand-100">
                {facilities.map((facility) => (
                  <tr key={facility.id}>
                    <td className="px-4 py-3 font-mono text-xs text-ink-soft">{facility.laboratory_code}</td>
                    <td className="px-4 py-3 font-medium text-ink">{facility.name}</td>
                    <td className="px-4 py-3 text-ink-soft">
                      {[facility.location, facility.district].filter(Boolean).join(', ') || '—'}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {facility.accredited === true ? (
                        <span className="text-ink-soft">Stated as accredited</span>
                      ) : facility.accredited === false ? (
                        <span className="text-ink-soft">Stated as not accredited</span>
                      ) : (
                        <span className="text-ink-muted">Not stated</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-ink-soft">{facility.status_label || facility.status}</td>
                    <td className="px-4 py-3 text-ink-soft">{facility.test_count ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-ink-muted">{LAB_MESSAGES.facilitiesEmpty}</p>
        )}
      </CardBody>

      <Modal
        open={Boolean(form)}
        onClose={() => setForm(null)}
        title="Register a laboratory"
        description="The server issues the laboratory code. Accreditation is recorded as you state it, and never asserted by the platform."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => setForm(null)}>
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              disabled={!form || form.name.trim().length < 2}
              onClick={async () => {
                setBusy(true);
                setFormError(null);
                try {
                  await laboratoryService.createFacility({
                    name: form.name.trim(),
                    ...(form.location ? { location: form.location } : {}),
                    ...(form.district ? { district: form.district } : {}),
                    ...(form.registration_identifier
                      ? { registration_identifier: form.registration_identifier }
                      : {}),
                    ...(form.accredited === null ? {} : { accredited: form.accredited }),
                  });
                  setForm(null);
                  await load();
                } catch (caught) {
                  setFormError(normaliseError(caught));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Register
            </Button>
          </div>
        }
      >
        {form ? (
          <div className="space-y-3">
            <Input
              label="Name"
              name="facility_name"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Location"
                name="facility_location"
                value={form.location}
                onChange={(event) => setForm({ ...form, location: event.target.value })}
              />
              <Input
                label="District"
                name="facility_district"
                value={form.district}
                onChange={(event) => setForm({ ...form, district: event.target.value })}
              />
            </div>
            <Input
              label="Registration identifier"
              name="facility_registration"
              value={form.registration_identifier}
              onChange={(event) => setForm({ ...form, registration_identifier: event.target.value })}
              hint="Optional, recorded as stated."
            />
            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={form.accredited === true}
                onChange={(event) => setForm({ ...form, accredited: event.target.checked ? true : null })}
              />
              The laboratory states that it is accredited
            </label>
            {formError ? <Alert variant="danger">{formError.message}</Alert> : null}
          </div>
        ) : null}
      </Modal>
    </Card>
  );
}

export default LaboratoryFacilitiesCard;
