import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { ArrowRight, KeyRound } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { ROLE_ASSIGNMENT_HINTS, homeRouteForRole, roleLabel } from '@/constants/roles';
import { ALL_ROLE_OPTIONS, adminRoleChangeSchema } from '@/utils/validation';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as adminService from '@/services/adminService';

/**
 * Change the role an account holds.
 *
 * Two things make this consequential, and both are said out loud in the dialog:
 * the account's permissions change the moment it commits, and its live sessions
 * are revoked because of that. The API also refuses the caller's own account —
 * a role-change form is not a way to promote yourself — which is why the caller
 * for a self-edit never even reaches this component.
 */
export function ChangeRoleDialog({ open, account, onClose, onChanged }) {
  const toast = useToast();
  const [formError, setFormError] = useState(null);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(adminRoleChangeSchema),
    defaultValues: { role: account?.role || '', reason: '' },
  });

  useEffect(() => {
    if (open) {
      reset({ role: account?.role || '', reason: '' });
      setFormError(null);
    }
  }, [open, account?.role, reset]);

  const previousRole = account?.role;
  const nextRole = watch('role');
  const changed = Boolean(nextRole) && nextRole !== previousRole;

  const onSubmit = async (values) => {
    setFormError(null);
    try {
      const result = await adminService.setUserRole(
        account.id,
        values.role,
        values.reason || undefined,
      );
      toast.success(
        result.message || `${account.email} is now ${roleLabel(values.role)}`,
        result.sessions_revoked
          ? `${result.sessions_revoked} session(s) signed out; they sign in again with the new role.`
          : undefined,
      );
      onChanged?.(result.user);
      onClose?.();
    } catch (caught) {
      setFormError(normaliseError(caught));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change role"
      description={account ? `${account.name} · ${account.email}` : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="change-role-form"
            loading={isSubmitting}
            disabled={!changed}
          >
            Save role
          </Button>
        </>
      }
    >
      <form id="change-role-form" onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError ? <Alert variant="danger">{formError.message}</Alert> : null}

        <div className="flex flex-wrap items-center gap-2 text-sm text-ink-soft">
          <Badge variant={previousRole === 'ADMIN' ? 'forest' : 'neutral'} size="sm">
            {roleLabel(previousRole)}
          </Badge>
          <ArrowRight size={14} aria-hidden="true" />
          <Badge variant={nextRole === 'ADMIN' ? 'forest' : 'neutral'} size="sm">
            {roleLabel(nextRole || previousRole)}
          </Badge>
          {!changed ? (
            <span className="text-xs text-ink-muted">
              Choose a different role to save a change.
            </span>
          ) : null}
        </div>

        <Select
          label="New role"
          name="role"
          required
          options={ALL_ROLE_OPTIONS}
          error={errors.role?.message}
          hint="All ten platform roles are available; the API enforces what each one may do."
          {...register('role')}
        />

        {changed ? (
          <div className="rounded-lg border border-sand-200 bg-sand-100/40 p-3">
            <p className="text-sm text-ink-soft">
              <span className="font-medium text-ink">{roleLabel(nextRole)}</span>{' '}
              {ROLE_ASSIGNMENT_HINTS[nextRole] || ''}
            </p>
            <p className="mt-1.5 text-xs text-ink-muted">
              This account will land on{' '}
              <span className="font-mono text-ink-soft">{homeRouteForRole(nextRole)}</span> after
              signing in.
            </p>
          </div>
        ) : null}

        <Input
          label="Reason (optional)"
          name="reason"
          placeholder="Moved to the Guntur collection centre"
          error={errors.reason?.message}
          hint="Stored with the change in the audit log, together with the previous role."
          {...register('reason')}
        />

        <Alert variant="warning">
          <span className="flex items-start gap-2">
            <KeyRound size={15} className="mt-0.5 flex-none" aria-hidden="true" />
            <span>
              The account&rsquo;s permissions change with the role, so its live sessions are signed
              out. The person signs in again with the same password and their new workspace. Both the
              old and the new role are written to the audit log, and the change can be reversed the
              same way.
            </span>
          </span>
        </Alert>
      </form>
    </Modal>
  );
}

export default ChangeRoleDialog;
