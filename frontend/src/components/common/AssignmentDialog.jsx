import { useEffect, useMemo, useState } from 'react';
import { UserCheck } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { normaliseError } from '@/utils/errors';

/**
 * Handing work to a named person — used by both operational workspaces.
 *
 * The component is deliberately dumb about *who* may be chosen: the caller passes
 * the eligible people, and the server validates the id it is sent. That matters
 * because the two modules have different eligibility rules (a processor can only
 * allocate to themselves, an administrator to any active processor or technician)
 * while the interaction — pick a person, confirm, see the refusal if there is one —
 * is identical. Splitting this in two would mean two places for the same bug.
 *
 * A caller with nobody to choose is shown why rather than an empty dropdown:
 * "no eligible person" is information, and an empty list is not.
 */
export function AssignmentDialog({
  open,
  onClose,
  title = 'Assign this work',
  description,
  assigneeLabel = 'Person',
  people = [],
  peopleLoading = false,
  peopleError = null,
  currentAssigneeId = null,
  onAssign,
  emptyHint = 'No eligible account is available to allocate this work to.',
  selfOption = null,
}) {
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) {
      setSelected('');
      setError(null);
      return;
    }
    setSelected(currentAssigneeId ? String(currentAssigneeId) : '');
  }, [open, currentAssigneeId]);

  const options = useMemo(
    () =>
      people.map((person) => {
        // Who they are, how to reach them, and how much work they are already
        // carrying — the last of which is what makes a list of names a decision
        // rather than a guess. The count is the server's, computed from the open
        // records it holds.
        const parts = [person.email].filter(Boolean);
        if (typeof person.open_work_count === 'number') {
          parts.push(
            person.open_work_count === 1
              ? '1 item of work already open'
              : `${person.open_work_count} items of work already open`,
          );
        }
        return {
          value: String(person.id),
          label: person.name || person.email || String(person.id),
          helper: parts.length ? parts.join(' · ') : undefined,
        };
      }),
    [people],
  );

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onAssign(selected || null);
      onClose?.();
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
          {selfOption ? (
            <Button
              variant="secondary"
              size="sm"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await onAssign(selfOption.id);
                  onClose?.();
                } catch (caught) {
                  setError(normaliseError(caught));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {selfOption.label}
            </Button>
          ) : null}
          <Button size="sm" loading={busy} disabled={!selected} onClick={submit}>
            Assign
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {peopleLoading ? (
          <p className="text-sm text-ink-muted">Loading the accounts that may take this work…</p>
        ) : null}
        {peopleError ? <Alert variant="danger">{peopleError.message}</Alert> : null}
        {!peopleLoading && !peopleError && !options.length && !selfOption ? (
          <Alert variant="warning">{emptyHint}</Alert>
        ) : null}
        {options.length ? (
          <Select
            label={assigneeLabel}
            name="assignee_id"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            options={options}
            placeholder="Choose an account"
            hint="The server checks the account's stored role before the work is allocated."
          />
        ) : null}
        {!options.length && selfOption ? (
          <p className="flex items-start gap-2 text-sm text-ink-soft">
            <UserCheck size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{selfOption.helper || 'You can take this work on yourself.'}</span>
          </p>
        ) : null}
        {error ? <Alert variant="danger">{error.message}</Alert> : null}
      </div>
    </Modal>
  );
}

export default AssignmentDialog;
