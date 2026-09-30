import { useCallback, useEffect, useMemo, useState } from 'react';
import { UserMinus, UserPlus, Users } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { LoadingState } from '@/components/common/LoadingState';
import { ROLES } from '@/constants/roles';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as adminService from '@/services/adminService';
import * as packagingService from '@/services/packagingService';

/**
 * The accounts that work at a packaging unit.
 *
 * Attaching an account is what makes an operator see a facility at sign-in, so it
 * is the same decision as "who works here". The selector offers accounts holding
 * the packaging-unit role, and says where each one works already — an account
 * attached to another facility is shown with that facility's name rather than
 * silently moved when someone picks it by mistake.
 *
 * The move itself is one API call: the service detaches the account from wherever
 * it was and attaches it here, and both ends are audited. Nothing is stored on the
 * client; the modal re-reads the unit afterwards, so what is on screen is what the
 * database says.
 */
export function UnitMembersModal({ open, unit = null, onClose, onChanged }) {
  const toast = useToast();
  const [members, setMembers] = useState([]);
  const [accountOptions, setAccountOptions] = useState([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!unit?.id) return;
    setLoading(true);
    setError(null);
    try {
      const [record, accounts] = await Promise.all([
        packagingService.listUnits({ pageSize: 100 }),
        adminService
          .listUsers({ role: ROLES.PACKAGING_UNIT, pageSize: 100 })
          .catch(() => ({ users: [] })),
      ]);
      const fresh = (record.units || []).find((row) => row.id === unit.id) || null;
      setMembers(fresh?.members || []);
      setAccountOptions(accounts.users || []);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [unit?.id]);

  useEffect(() => {
    if (!open) return;
    setSelected('');
    load();
  }, [open, load]);

  const attachedIds = useMemo(() => new Set(members.map((member) => member.id)), [members]);

  const options = useMemo(
    () =>
      accountOptions.map((account) => {
        const here = attachedIds.has(account.id);
        const elsewhere =
          account.packaging_unit_id && account.packaging_unit_id !== unit?.id
            ? account.packaging_unit_name || 'another unit'
            : null;
        return {
          value: account.id,
          label: `${account.name || account.email}${
            here
              ? ' — already works here'
              : elsewhere
                ? ` — works at ${elsewhere} (will be moved)`
                : ' — not attached to a unit'
          }`,
          disabled: here,
        };
      }),
    [accountOptions, attachedIds, unit?.id],
  );

  async function attach() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await packagingService.addUnitMember(unit.id, { user_id: selected });
      toast.success('Account attached', `${updated.name} works at this unit from now on.`);
      setSelected('');
      setMembers(updated.members || []);
      onChanged?.();
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function detach(member) {
    setBusy(true);
    setError(null);
    try {
      const updated = await packagingService.removeUnitMember(unit.id, member.id);
      toast.success(
        'Account detached',
        `${member.name || member.email} no longer works at this unit. Their runs keep the unit they were made in.`,
      );
      setMembers(updated.members || []);
      onChanged?.();
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={busy ? () => {} : onClose}
      size="lg"
      title={unit ? `People at ${unit.name}` : 'People at this unit'}
      description={
        unit
          ? `${unit.unit_code} · a packaging account sees this facility automatically at sign-in`
          : undefined
      }
      footer={
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Close
        </Button>
      }
    >
      <div className="space-y-4">
        {error ? <Alert variant="danger">{error.message}</Alert> : null}

        <div className="rounded-lg border border-sand-300 bg-sand-50 px-4 py-3">
          <p className="text-sm text-ink-soft">
            An account attached here works at this facility and no other. Detaching an account does
            not touch the runs it recorded — a run keeps the unit that actually did the work.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <Select
            containerClassName="min-w-0 flex-1"
            label="Attach an account"
            name="member_id"
            options={options}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            placeholder={
              options.length ? 'Select a packaging-unit account' : 'No packaging-unit account exists yet'
            }
            hint="Create the account first under Administration → Users, choosing the packaging role."
            disabled={busy || !options.length}
          />
          <Button
            onClick={attach}
            loading={busy}
            disabled={!selected}
            leftIcon={<UserPlus size={15} aria-hidden="true" />}
            data-testid="attach-unit-member"
          >
            Attach
          </Button>
        </div>

        {loading ? <LoadingState message="Loading the people at this unit…" /> : null}

        {!loading ? (
          members.length ? (
            <ul className="divide-y divide-sand-200 rounded-lg border border-sand-300">
              {members.map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">{member.name}</p>
                    <p className="truncate text-xs text-ink-muted">{member.email}</p>
                  </div>
                  <div className="flex flex-none items-center gap-2">
                    <Badge variant={member.is_active ? 'success' : 'neutral'} size="sm">
                      {member.is_active ? 'Active account' : 'Inactive account'}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => detach(member)}
                      disabled={busy}
                      aria-label={`Detach ${member.email}`}
                    >
                      <UserMinus size={14} aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="flex items-center gap-2 text-sm text-ink-muted">
              <Users size={15} aria-hidden="true" />
              Nobody works at this unit yet. Attach an account above — until then the unit has no
              operator, and an operator with no unit is refused at the packaging run.
            </p>
          )
        ) : null}
      </div>
    </Modal>
  );
}

export default UnitMembersModal;
