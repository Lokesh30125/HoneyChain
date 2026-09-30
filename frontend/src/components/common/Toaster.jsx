import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, Info, TriangleAlert, XCircle, X } from 'lucide-react';

import { useToast } from '@/hooks/useToast';

/** Renders the active toast queue. Mounted once, near the app root. */

const VARIANTS = {
  success: { wrapper: 'border-status-success/25 bg-white', Icon: CheckCircle2, color: 'text-status-success' },
  danger: { wrapper: 'border-status-danger/25 bg-white', Icon: XCircle, color: 'text-status-danger' },
  warning: { wrapper: 'border-status-warning/30 bg-white', Icon: TriangleAlert, color: 'text-status-warning' },
  info: { wrapper: 'border-status-info/25 bg-white', Icon: Info, color: 'text-status-info' },
};

export function Toaster() {
  const { toasts, dismiss } = useToast();

  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:items-end"
      role="region"
      aria-label="Notifications"
    >
      <AnimatePresence initial={false}>
        {toasts.map((toast) => {
          const { wrapper, Icon, color } = VARIANTS[toast.variant] || VARIANTS.info;
          return (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.18 }}
              className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-card border px-4 py-3 shadow-raised ${wrapper}`}
            >
              <Icon size={18} className={`mt-0.5 flex-none ${color}`} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                {toast.title ? <p className="text-sm font-semibold text-ink">{toast.title}</p> : null}
                {toast.message ? <p className="mt-0.5 text-sm text-ink-soft">{toast.message}</p> : null}
              </div>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                aria-label="Dismiss notification"
                className="rounded p-0.5 text-ink-muted transition-colors hover:text-ink"
              >
                <X size={15} aria-hidden="true" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

export default Toaster;
