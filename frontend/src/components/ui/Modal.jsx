import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';

/**
 * Accessible modal dialog.
 *
 * Implemented with a portal + focus trap basics: focus moves into the dialog on
 * open, Escape closes it, and the page behind is not scrollable. Kept generic so
 * every dialog in the application reuses it.
 *
 * ## Why the focus effect depends on `open` alone
 *
 * The dialog takes focus the moment it opens, so a keyboard user lands inside it.
 * That must happen **once per open**, and nothing else may move focus afterwards —
 * a field the user is typing in must keep it.
 *
 * It previously listed `onClose` as a dependency too. Callers pass `onClose` as an
 * inline arrow function (`onClose={() => setOpen(false)}`), which is a new
 * function on every render, so any state change — including one keystroke — re-ran
 * the effect and pulled focus back to the dialog panel. The visible result was an
 * input that accepted exactly one character per click, in every form inside a
 * dialog. `onClose` is now held in a ref and read through it, so the latest
 * handler is always used while the effect itself runs only when `open` changes;
 * the effect also refuses to move focus if it is already inside the dialog.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer = null,
  size = 'md',
  closeOnBackdrop = true,
}) {
  const panelRef = useRef(null);
  // The latest `onClose`, read at call time. Keeps the effect below independent of
  // the handler's identity, so a re-render cannot restart it.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Only take focus if it is not already inside the dialog: reopening focus on a
    // re-render would interrupt whoever is typing.
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) {
      panel.focus();
    }

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current?.();
      }
    };
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  const widths = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
    '2xl': 'max-w-6xl',
  };

  /*
   * Height strategy.
   *
   * The dialog is capped to the viewport and scrolls *internally*: the header
   * and footer stay put and the body scrolls. Without this, a long review (a
   * beekeeper record plus its verification history) grew taller than the screen
   * and could not be reached at all, because the page behind it is locked.
   *
   * `dvh` rather than `vh` so mobile browser chrome does not clip the footer;
   * the wrapper also scrolls as a fallback for very short viewports.
   */
  const constrained = size !== 'full';

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto overscroll-contain p-0 sm:items-center sm:p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <div
            className="absolute inset-0 bg-ink/40"
            onClick={closeOnBackdrop ? onClose : undefined}
            aria-hidden="true"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="hc-modal-title"
            tabIndex={-1}
            className={[
              'relative flex w-full flex-col rounded-t-card border border-sand-300 bg-white shadow-raised sm:rounded-card',
              widths[size] || widths.md,
              constrained ? 'max-h-[calc(100dvh-1rem)] sm:max-h-[calc(100dvh-2rem)]' : '',
            ].join(' ')}
            initial={{ opacity: 0, y: 12, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.99 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            <div className="flex flex-none items-start justify-between gap-4 border-b border-sand-200 px-5 py-4">
              <div className="min-w-0">
                <h2 id="hc-modal-title" className="text-base font-semibold text-ink">
                  {title}
                </h2>
                {description ? <p className="mt-1 text-sm text-ink-muted">{description}</p> : null}
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1 text-ink-muted transition-colors hover:bg-sand-100 hover:text-ink"
                aria-label="Close dialog"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>

            {/* `min-h-0` is what lets this region scroll instead of stretching
                the dialog past the viewport. */}
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-4">
              {children}
            </div>

            {footer ? (
              <div className="flex flex-none flex-wrap justify-end gap-2 rounded-b-card border-t border-sand-200 bg-sand-100/60 px-5 py-3">
                {footer}
              </div>
            ) : null}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

export default Modal;
