import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { verificationLabel } from '@/components/beekeepers/VerificationBadge';
import { normaliseError } from '@/utils/errors';
import { verificationSchema } from '@/utils/validation';
import { useToast } from '@/hooks/useToast';
import * as beekeeperService from '@/services/beekeeperService';

/**
 * Verification decision dialog.
 *
 * Only the transitions the backend will accept are offered — `allowedNext` comes
 * from the detail payload, so the form cannot present an option that would fail.
 * Rejections and suspensions require a remark, which the schema enforces before
 * the request is sent.
 */
export function VerificationDialog({ open, beekeeper, allowedNext = [], onClose, onCompleted }) {
  const toast = useToast();
  const [formError, setFormError] = useState(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(verificationSchema),
    defaultValues: { status: allowedNext[0] || 'UNDER_REVIEW', remarks: '' },
  });

  useEffect(() => {
    if (open) {
      reset({ status: allowedNext[0] || 'UNDER_REVIEW', remarks: '' });
      setFormError(null);
    }
  }, [open, allowedNext, reset]);

  const onSubmit = async (values) => {
    setFormError(null);
    try {
      const updated = await beekeeperService.changeVerification(beekeeper.id, {
        status: values.status,
        remarks: values.remarks || undefined,
      });
      toast.success(
        `${beekeeper.beekeeper_code} is now ${verificationLabel(values.status).toLowerCase()}`,
      );
      onCompleted?.(updated);
      onClose?.();
    } catch (caught) {
      setFormError(normaliseError(caught));
    }
  };

  const options = allowedNext.map((status) => ({ value: status, label: verificationLabel(status) }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Record a verification decision"
      description={
        beekeeper
          ? `${beekeeper.beekeeper_code} · currently ${verificationLabel(beekeeper.verification_status)}`
          : undefined
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" form="verification-form" loading={isSubmitting}>
            Save decision
          </Button>
        </>
      }
    >
      <form id="verification-form" onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        {formError ? <Alert variant="danger">{formError.message}</Alert> : null}

        <Select
          label="New status"
          name="status"
          required
          options={options}
          error={errors.status?.message}
          hint="The workflow only allows the next valid states for this record."
          {...register('status')}
        />

        <Input
          label="Remarks"
          name="remarks"
          error={errors.remarks?.message}
          hint="Recorded in the verification history and the audit log. Required to reject or suspend."
          {...register('remarks')}
        />

        <p className="text-xs text-ink-muted">
          This decision is appended to the beekeeper&rsquo;s verification history. Entries are never
          edited or deleted.
        </p>
      </form>
    </Modal>
  );
}

export default VerificationDialog;
