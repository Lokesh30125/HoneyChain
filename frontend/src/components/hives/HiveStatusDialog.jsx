import { useEffect, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { HIVE_STATUSES, HIVE_STATUS_HELP } from '@/constants/hive';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as hiveService from '@/services/hiveService';

/**
 * Change a hive's lifecycle status.
 *
 * REMOVED is offered here as well as through the delete action, because
 * retiring a hive (history kept, still readable) and deleting one are different
 * intentions and the operator should be able to pick the one they mean. The
 * reason is optional but recorded in the audit log when given.
 */
export function HiveStatusDialog({ open, hive = null, onClose, onSaved }) {
  const toast = useToast();
  const [status, setStatus] = useState('ACTIVE');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open || !hive) return;
    setStatus(hive.status || 'ACTIVE');
    setReason('');
    setError(null);
  }, [open, hive]);

  if (!hive) return null;

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await hiveService.setHiveStatus(hive.id, status, reason.trim() || undefined);
      toast.success(
        `${updated.hive_code} is now ${updated.status_label || updated.status}`,
        reason.trim() ? 'The reason was recorded in the audit log.' : undefined,
      );
      onSaved?.(updated);
      onClose?.();
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Change status of ${hive.hive_code}`}
      description="Status changes are recorded in the platform audit log with the previous value."
      size="sm"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={submit} loading={saving} disabled={status === hive.status}>
            Save status
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error ? (
          <Alert variant="danger" title="Status not changed">
            {error.message}
          </Alert>
        ) : null}

        <Select
          label="New status"
          name="hive-status"
          options={HIVE_STATUSES}
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          hint={HIVE_STATUS_HELP[status]}
        />

        <div>
          <label htmlFor="hive-status-reason" className="hc-label">
            Reason (optional)
          </label>
          <textarea
            id="hive-status-reason"
            rows={2}
            maxLength={500}
            className="hc-textarea"
            placeholder="e.g. moved to the mustard field, super added"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      </div>
    </Modal>
  );
}

export default HiveStatusDialog;
