import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { Info } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { SelectWithOther } from '@/components/ui/SelectWithOther';
import { CONNECTION_TYPES, DEVICE_TYPES } from '@/constants/hive';
import { normaliseError } from '@/utils/errors';
import { deviceSchema } from '@/utils/validation';
import { useToast } from '@/hooks/useToast';
import * as iotService from '@/services/iotService';

const EMPTY = {
  deviceId: '',
  deviceName: '',
  hiveId: '',
  deviceType: 'ESP32',
  deviceTypeOther: '',
  connectionType: 'MQTT',
  firmwareVersion: '',
  installedAt: '',
};

/**
 * Pair a device with a hive.
 *
 * The device id is the hardware identifier printed on the board and is used as
 * the MQTT topic segment, so it is fixed once registered — it cannot be
 * corrected later without registering a new device. The topic itself is derived
 * by the backend (`<prefix>/devices/<device_id>/telemetry`); the form only
 * shows what it will be.
 *
 * The five sensors a hive node carries are created with the device, enabled,
 * with the default sampling intervals. Enabling or retuning them happens on the
 * device screen afterwards.
 */
export function DevicePairingModal({ open, hives = [], defaultHiveId = '', onClose, onSaved }) {
  const toast = useToast();
  const [formError, setFormError] = useState(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(deviceSchema), defaultValues: EMPTY });

  useEffect(() => {
    if (!open) return;
    setFormError(null);
    reset({ ...EMPTY, hiveId: defaultHiveId });
  }, [open, defaultHiveId, reset]);

  const deviceId = watch('deviceId');
  const hiveOptions = hives.map((hive) => ({
    value: hive.id,
    label: `${hive.hive_code}${hive.location_label ? ` — ${hive.location_label}` : ''}`,
  }));

  const submit = async (values) => {
    setFormError(null);
    try {
      const saved = await iotService.registerDevice({
        device_id: values.deviceId.trim().toUpperCase(),
        device_name: values.deviceName.trim(),
        ...(values.deviceType === 'OTHER'
          ? { device_type_other: values.deviceTypeOther.trim() }
          : {}),
        hive_id: values.hiveId,
        device_type: values.deviceType,
        // Omit what was left blank rather than sending null: the API validates
        // these fields strictly and its defaults are the right answer.
        ...(values.connectionType ? { connection_type: values.connectionType } : {}),
        ...(values.firmwareVersion.trim()
          ? { firmware_version: values.firmwareVersion.trim() }
          : {}),
        ...(values.installedAt
          ? { installed_at: new Date(values.installedAt).toISOString() }
          : {}),
      });
      toast.success(
        `${saved.device_id} registered`,
        `It will show as offline until the first packet arrives. Sensors: ${saved.sensors?.length ?? 0}.`,
      );
      onSaved?.(saved);
      onClose?.();
    } catch (caught) {
      setFormError(normaliseError(caught));
    }
  };

  const previewTopic = deviceId
    ? `honeychain/devices/${deviceId.trim().toUpperCase()}/telemetry`
    : 'honeychain/devices/<device-id>/telemetry';

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Pair a device with a hive"
      description="The device appears as offline until it sends its first packet — the platform never assumes a device is alive."
      size="lg"
    >
      <form onSubmit={handleSubmit(submit)} className="space-y-4" noValidate>
        {formError ? (
          <Alert variant="danger" title="Could not register this device">
            {formError.message}
          </Alert>
        ) : null}

        {hives.length === 0 ? (
          <Alert variant="warning" title="Register a hive first">
            A device reports on exactly one hive, so there has to be a hive to attach it to.
          </Alert>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Device id (hardware label)"
            name="deviceId"
            placeholder="ESP32-GNT-0002"
            required
            hint="Printed on the board. Used in the MQTT topic, so it cannot be changed later."
            error={errors.deviceId?.message}
            {...register('deviceId')}
          />
          <Input
            label="Device name"
            name="deviceName"
            placeholder="North field node"
            required
            error={errors.deviceName?.message}
            {...register('deviceName')}
          />
          <Select
            label="Hive"
            name="hiveId"
            required
            options={hiveOptions}
            placeholder="Choose a hive"
            error={errors.hiveId?.message}
            {...register('hiveId')}
          />
          <SelectWithOther
            label="Device type"
            name="deviceType"
            options={DEVICE_TYPES}
            value={watch('deviceType')}
            onChange={(event) =>
              setValue('deviceType', event.target.value, { shouldValidate: true })
            }
            otherValue={watch('deviceTypeOther')}
            onOtherChange={(text) =>
              setValue('deviceTypeOther', text, { shouldValidate: true, shouldDirty: true })
            }
            error={errors.deviceType?.message || errors.deviceTypeOther?.message}
            otherLabel="Specify the hardware"
            otherPlaceholder="For example: custom LoRa board rev C"
            hint="Choose Other for boards outside the list"
          />
          <Select
            label="Connection"
            name="connectionType"
            options={[{ value: '', label: 'Platform default (MQTT)' }, ...CONNECTION_TYPES]}
            error={errors.connectionType?.message}
            {...register('connectionType')}
          />
          <Input
            label="Firmware version"
            name="firmwareVersion"
            placeholder="1.0.3"
            error={errors.firmwareVersion?.message}
            {...register('firmwareVersion')}
          />
          <Input
            label="Installed on"
            name="installedAt"
            type="date"
            error={errors.installedAt?.message}
            {...register('installedAt')}
          />
        </div>

        <div className="rounded-lg border border-sand-300 bg-sand-100/60 p-3 text-xs text-ink-soft">
          <p className="flex items-center gap-1.5 font-medium text-ink">
            <Info size={14} aria-hidden="true" />
            MQTT topic this device will publish to
          </p>
          <p className="mt-1 break-all font-mono text-[11px] text-ink">{previewTopic}</p>
          <p className="mt-1.5">
            Five sensors — temperature, humidity, weight, vibration and acoustic activity — are
            created with the device and can be turned off or retuned afterwards.
          </p>
        </div>

        <div className="flex justify-end gap-2 border-t border-sand-200 pt-4">
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" loading={isSubmitting} disabled={hives.length === 0}>
            Register device
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default DevicePairingModal;
