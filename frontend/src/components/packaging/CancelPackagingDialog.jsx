import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';

/**
 * Cancelling a packaging run.
 *
 * A cancellation is a record, not a deletion: the run keeps its number, its
 * quantities and the reason, and the honey goes back to being approved and
 * unpacked. The reason is asked for because a cancelled run is the first thing
 * anybody asks about later, and "cancelled" on its own answers nothing.
 */
export function CancelPackagingDialog({ open, run = null, onClose, onConfirm, submitting = false }) {
  const [reason, setReason] = useState('');

  useEffect(() => {
    if (open) setReason('');
  }, [open, run?.id]);

  return (
    <Modal
      open={open}
      onClose={submitting ? () => {} : onClose}
      title="Cancel this packaging run?"
      description={
        run
          ? `${run.packaging_code} · ${run.batch_code}. The run is kept in the history and no honey is consumed by it.`
          : undefined
      }
      size="md"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={submitting}>
            Keep it open
          </Button>
          <Button
            variant="danger"
            size="sm"
            loading={submitting}
            disabled={reason.trim().length < 3}
            onClick={() => onConfirm?.(reason.trim())}
            data-testid="confirm-cancel-packaging"
          >
            Cancel the run
          </Button>
        </div>
      }
    >
      <Input
        label="Why did this run not happen?"
        name="reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="For example: the batch was redirected to another unit"
        hint="At least three characters. The reason is stored on the record and in the audit log."
        data-testid="cancel-packaging-reason"
      />
    </Modal>
  );
}

export default CancelPackagingDialog;
