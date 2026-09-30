import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';

/**
 * Confirmation dialog for destructive or irreversible actions
 * (sign out, deactivate an account, revoke a batch, …).
 */
export function ConfirmDialog({
  open,
  title = 'Please confirm',
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'primary',
  loading = false,
  onConfirm,
  onCancel,
}) {
  return (
    <Modal
      open={open}
      onClose={loading ? () => {} : onCancel}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={variant} size="sm" onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-sm text-ink-soft">
        This action will be recorded in the platform audit log.
      </p>
    </Modal>
  );
}

export default ConfirmDialog;
