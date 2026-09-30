import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { alertTypeLabel } from '@/constants/ai';

/**
 * Acknowledge / resolve / reopen, with an optional note.
 *
 * The note is the only free text in the alert lifecycle and it is worth having:
 * "resolved" on its own loses the reason, and the audit trail is meant to be
 * readable by someone else six months later. It caps at the API's 500 characters.
 */
const COPY = {
  acknowledge: {
    title: 'Acknowledge this alert',
    description: 'Marks it as seen. It stays open until the underlying reading changes or you resolve it.',
    confirm: 'Acknowledge',
    placeholder: 'What did you check, and what did you find? (optional)',
  },
  resolve: {
    title: 'Resolve this alert',
    description: 'Closes it. If the same pattern is recorded again, a new alert will be raised after the cooldown.',
    confirm: 'Resolve',
    placeholder: 'How was it resolved? (optional)',
  },
  reopen: {
    title: 'Reopen this alert',
    description: 'Puts it back on the list as open, so it is not lost.',
    confirm: 'Reopen',
    placeholder: 'Why reopen it? (optional)',
  },
};

export function AlertActionDialog({ open, alert, action, onClose, onConfirm, busy = false }) {
  const [note, setNote] = useState('');
  const copy = COPY[action] || COPY.acknowledge;

  useEffect(() => {
    if (open) setNote('');
  }, [open, action, alert?.id]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={copy.title}
      description={copy.description}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button loading={busy} onClick={() => onConfirm(note.trim() || undefined)}>
            {copy.confirm}
          </Button>
        </div>
      }
    >
      {alert ? (
        <div className="space-y-3">
          <div className="rounded-lg border border-sand-200 bg-sand-50 p-3">
            <p className="text-xs uppercase tracking-wide text-ink-muted">
              {alertTypeLabel(alert.alert_type)} · {alert.hive_code || 'hive'}
            </p>
            <p className="mt-1 text-sm font-medium text-ink">{alert.title}</p>
            <p className="mt-1 text-sm text-ink-soft">{alert.message}</p>
          </div>

          <div>
            <label htmlFor="alert-note" className="hc-label">
              Note
            </label>
            <textarea
              id="alert-note"
              className="hc-textarea"
              rows={3}
              maxLength={500}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder={copy.placeholder}
            />
            <p className="mt-1 text-xs text-ink-muted">{note.length}/500</p>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

export default AlertActionDialog;
