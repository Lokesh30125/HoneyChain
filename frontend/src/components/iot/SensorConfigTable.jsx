import { useState } from 'react';
import { Save } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { sensorMeta } from '@/constants/hive';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as iotService from '@/services/iotService';

/**
 * Sensor configuration for one device.
 *
 * Each row can be enabled or disabled and re-tuned. The bounds shown are the
 * validity range the API accepts for that sensor — a value outside them is
 * refused as implausible. They are *not* health or disease thresholds, and the
 * copy here says so, because a dashboard that implies otherwise would be making
 * a claim the data cannot support.
 */
function SensorRow({ deviceId, sensor, onSaved }) {
  const toast = useToast();
  const [enabled, setEnabled] = useState(sensor.enabled);
  const [interval, setInterval] = useState(String(sensor.sampling_interval));
  const [saving, setSaving] = useState(false);
  const meta = sensorMeta(sensor.sensor_type);

  const dirty = enabled !== sensor.enabled || interval !== String(sensor.sampling_interval);

  const save = async () => {
    setSaving(true);
    try {
      const updated = await iotService.updateSensor(deviceId, sensor.sensor_type, {
        enabled,
        sampling_interval: Number(interval),
      });
      toast.success(`${updated.sensor_name} updated`);
      onSaved?.(updated);
    } catch (caught) {
      toast.error('Could not update this sensor', normaliseError(caught).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr className="border-t border-sand-200">
      <td className="px-3 py-2.5">
        <p className="text-sm font-medium text-ink">{sensor.sensor_name}</p>
        <p className="text-xs text-ink-muted">
          {sensor.unit}
          {sensor.min_valid_value !== null && sensor.max_valid_value !== null
            ? ` · accepted ${sensor.min_valid_value}–${sensor.max_valid_value}`
            : ''}
        </p>
      </td>
      <td className="px-3 py-2.5">
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-sand-300 text-forest-700 focus:ring-honey-500"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            aria-label={`Collect ${sensor.sensor_name}`}
          />
          {enabled ? 'Collecting' : 'Disabled'}
        </label>
      </td>
      <td className="px-3 py-2.5">
        <Input
          name={`interval-${sensor.sensor_type}`}
          inputMode="numeric"
          value={interval}
          onChange={(event) => setInterval(event.target.value)}
          aria-label={`${sensor.sensor_name} sampling interval in seconds`}
          containerClassName="w-28"
          hint={meta ? 'seconds' : undefined}
        />
      </td>
      <td className="px-3 py-2.5 text-right">
        <Button variant="secondary" size="sm" onClick={save} disabled={!dirty} loading={saving}>
          <Save size={15} aria-hidden="true" />
        </Button>
      </td>
    </tr>
  );
}

export function SensorConfigTable({ deviceId, sensors = [], onSaved }) {
  if (!sensors.length) {
    return (
      <p className="rounded-lg border border-dashed border-sand-300 bg-sand-50/60 px-4 py-5 text-center text-sm text-ink-muted">
        This device has no sensors configured.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <caption className="sr-only">Sensor configuration for this device</caption>
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-ink-muted">
            <th scope="col" className="px-3 py-2">Sensor</th>
            <th scope="col" className="px-3 py-2">Collection</th>
            <th scope="col" className="px-3 py-2">Expected interval</th>
            <th scope="col" className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {sensors.map((sensor) => (
            <SensorRow
              key={sensor.sensor_type}
              deviceId={deviceId}
              sensor={sensor}
              onSaved={onSaved}
            />
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-muted">
        Accepted ranges are data-validity bounds: a packet outside them is rejected as implausible.
        They are not health, disease or yield thresholds.
      </p>
    </div>
  );
}

export default SensorConfigTable;
