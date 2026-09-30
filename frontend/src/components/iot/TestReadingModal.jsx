import { useEffect, useState } from 'react';
import { Send } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { CONFIGURABLE_SENSOR_TYPES } from '@/constants/hive';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as iotService from '@/services/iotService';

/**
 * Post one reading by hand.
 *
 * This exists so the ingest path can be exercised without hardware: the same
 * endpoint, validation and storage the MQTT consumer uses. A reading posted
 * here is stored with source MANUAL — never as REAL_DEVICE — and every screen
 * that shows it says so. Nothing is generated for you: an empty field means
 * that measurement was not taken.
 */
export function TestReadingModal({ open, device = null, onClose, onSent }) {
  const toast = useToast();
  const [values, setValues] = useState({});
  const [error, setError] = useState(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (open) {
      setValues({});
      setError(null);
    }
  }, [open, device]);

  if (!device) return null;

  const filled = Object.values(values).filter((value) => value !== '' && value !== undefined).length;

  const submit = async (event) => {
    event.preventDefault();
    setError(null);

    const payload = { device_id: device.device_id };
    for (const [key, value] of Object.entries(values)) {
      if (value === '' || value === undefined) continue;
      const number = Number(value);
      if (Number.isNaN(number)) {
        setError({ message: `"${value}" is not a number.` });
        return;
      }
      payload[key] = number;
    }

    setSending(true);
    try {
      const result = await iotService.postTelemetry(payload);
      toast.success(
        result.duplicate ? 'That instant was already recorded' : 'Reading stored as MANUAL',
        `${result.device_id} · ${result.device_status}`,
      );
      onSent?.(result);
      onClose?.();
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Send a test reading for ${device.device_id}`}
      description="Stored through the same ingest endpoint the MQTT consumer uses, labelled MANUAL."
    >
      <form onSubmit={submit} className="space-y-4">
        {error ? (
          <Alert variant="danger" title="The reading was not stored">
            {error.message}
            {error.details?.length ? (
              <ul className="mt-1 list-disc pl-4 text-xs">
                {error.details.map((detail) => (
                  <li key={detail.field || detail.message}>
                    {detail.field ? `${detail.field}: ` : ''}
                    {detail.message}
                  </li>
                ))}
              </ul>
            ) : null}
          </Alert>
        ) : null}

        <p className="text-sm text-ink-soft">
          Fill in only what you measured. Values outside the accepted range are rejected rather than
          clamped, so a typo cannot be stored as a plausible-looking reading.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          {CONFIGURABLE_SENSOR_TYPES.map((sensor) => (
            <Input
              key={sensor.value}
              label={`${sensor.label} (${sensor.unit})`}
              name={sensor.readingKey}
              inputMode="decimal"
              value={values[sensor.readingKey] ?? ''}
              onChange={(event) =>
                setValues((current) => ({ ...current, [sensor.readingKey]: event.target.value }))
              }
            />
          ))}
          <Input
            label="Battery (%)"
            name="battery_level"
            inputMode="numeric"
            value={values.battery_level ?? ''}
            onChange={(event) =>
              setValues((current) => ({ ...current, battery_level: event.target.value }))
            }
          />
        </div>

        <div className="flex justify-end gap-2 border-t border-sand-200 pt-4">
          <Button variant="secondary" onClick={onClose} disabled={sending}>
            Cancel
          </Button>
          <Button
            type="submit"
            loading={sending}
            disabled={filled === 0}
            leftIcon={<Send size={15} aria-hidden="true" />}
          >
            Send reading
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default TestReadingModal;
