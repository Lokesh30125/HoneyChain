import { useCallback, useEffect, useState } from 'react';
import { Info, Ruler } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import * as laboratoryService from '@/services/laboratoryService';
import { normaliseError } from '@/utils/errors';

/**
 * The parameter catalogue.
 *
 * This is where *meaning* is configured, and it is deliberately explicit about
 * that: the platform ships every parameter with **no reference range** and none
 * marked required. A range can only be set together with the source it came from —
 * a laboratory's own method sheet, a buyer's specification, a procurement
 * standard — because HoneyChain does not own a scientific threshold and will not
 * invent one.
 *
 * A parameter with no range is not an unfinished row; it is the reason a test can
 * honestly come back inconclusive.
 */
export function ParameterCatalogueTable({ canConfigure = false }) {
  const [parameters, setParameters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setParameters(await laboratoryService.listParameters());
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <LoadingState message="Loading the parameter catalogue..." />;
  if (error) return <ErrorState error={error} onRetry={load} />;

  const configured = parameters.filter((parameter) => parameter.is_configured).length;

  return (
    <Card>
      <CardHeader
        title="Reference parameters"
        description="What this platform can measure, and — where somebody told it — the range a value is judged against."
        icon={<Ruler size={18} aria-hidden="true" />}
        action={
          <Badge variant={configured ? 'info' : 'neutral'} size="sm">
            {configured} of {parameters.length} configured
          </Badge>
        }
      />
      <CardBody className="space-y-4">
        <Alert variant="info" icon={<Info size={16} aria-hidden="true" />}>
          No range is shipped with this platform. Until one is configured from a stated source, a
          measurement is stored and marked <strong>Not evaluated</strong> — never Pass, never Fail.
        </Alert>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-sand-200 text-sm">
            <thead className="bg-sand-100/70">
              <tr>
                {['Parameter', 'Unit', 'Reference range', 'Source', 'Required', 'State', ''].map((header) => (
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
              {parameters.map((parameter) => (
                <tr key={parameter.code} data-parameter={parameter.code}>
                  <td className="px-4 py-3">
                    <span className="font-medium text-ink">{parameter.name}</span>
                    <span className="ml-2 font-mono text-xs text-ink-muted">{parameter.code}</span>
                    {parameter.description ? (
                      <p className="mt-0.5 max-w-md text-xs text-ink-muted">{parameter.description}</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-ink-soft">{parameter.unit_label}</td>
                  <td className="px-4 py-3 text-ink-soft">
                    {parameter.reference_min === null && parameter.reference_max === null ? (
                      <span className="text-ink-muted">Not configured</span>
                    ) : (
                      `${parameter.reference_min ?? '—'} – ${parameter.reference_max ?? '—'}`
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-ink-muted">{parameter.reference_source || '—'}</td>
                  <td className="px-4 py-3">
                    {parameter.is_required ? (
                      <Badge variant="warning" size="sm">
                        Required
                      </Badge>
                    ) : (
                      <span className="text-xs text-ink-muted">Optional</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={parameter.is_active ? 'success' : 'neutral'} size="sm">
                      {parameter.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {canConfigure ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setFormError(null);
                          setEditing(parameter);
                        }}
                      >
                        Configure
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardBody>

      <Modal
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
        title={editing ? `Configure ${editing.name}` : 'Configure'}
        description="A range and the source it came from are recorded together; the platform stores both."
        footer={
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setEditing(null);
                setFormError(null);
              }}
            >
              Close
            </Button>
            <Button
              size="sm"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                setFormError(null);
                try {
                  const payload = {
                    ...(editing.reference_min === '' || editing.reference_min === null
                      ? {}
                      : { reference_min: editing.reference_min }),
                    ...(editing.reference_max === '' || editing.reference_max === null
                      ? {}
                      : { reference_max: editing.reference_max }),
                    ...(editing.reference_source ? { reference_source: editing.reference_source } : {}),
                    is_required: Boolean(editing.is_required),
                    is_active: Boolean(editing.is_active),
                  };
                  await laboratoryService.updateParameter(editing.code, payload);
                  setEditing(null);
                  await load();
                } catch (caught) {
                  setFormError(normaliseError(caught));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Save the configuration
            </Button>
          </div>
        }
      >
        {editing ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label={`Minimum (${editing.unit_label})`}
                name="reference_min"
                type="number"
                step="0.0001"
                value={editing.reference_min ?? ''}
                onChange={(event) => setEditing({ ...editing, reference_min: event.target.value })}
                hint="Leave both empty to keep the parameter unjudged."
              />
              <Input
                label={`Maximum (${editing.unit_label})`}
                name="reference_max"
                type="number"
                step="0.0001"
                value={editing.reference_max ?? ''}
                onChange={(event) => setEditing({ ...editing, reference_max: event.target.value })}
              />
            </div>
            <Input
              label="Source of this range"
              name="reference_source"
              value={editing.reference_source || ''}
              onChange={(event) => setEditing({ ...editing, reference_source: event.target.value })}
              placeholder="For example: laboratory method sheet 04/2026"
              hint="Required whenever a range is set. Where the number came from is part of the record."
              required
            />
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={Boolean(editing.is_required)}
                  onChange={(event) => setEditing({ ...editing, is_required: event.target.checked })}
                />
                Required for a decision
              </label>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={Boolean(editing.is_active)}
                  onChange={(event) => setEditing({ ...editing, is_active: event.target.checked })}
                />
                Active
              </label>
            </div>
            {formError ? <Alert variant="danger">{formError.message}</Alert> : null}
          </div>
        ) : null}
      </Modal>
    </Card>
  );
}

export default ParameterCatalogueTable;
