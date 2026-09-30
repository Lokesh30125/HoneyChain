/**
 * Minimal toast queue.
 *
 * Scoped deliberately: it holds transient notifications only. Anything that
 * must survive a navigation (like the session) lives in AuthContext, and
 * server data lives in the page that requested it.
 */

import { createContext, useCallback, useMemo, useRef, useState } from 'react';

export const ToastContext = createContext(null);

const DEFAULT_DURATION = 5000;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (toast) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const entry = {
        id,
        variant: toast.variant || 'info',
        title: toast.title || '',
        message: toast.message || '',
      };
      setToasts((current) => [...current, entry]);

      const duration = toast.duration ?? DEFAULT_DURATION;
      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration),
        );
      }
      return id;
    },
    [dismiss],
  );

  const value = useMemo(
    () => ({
      toasts,
      dismiss,
      success: (title, message) => push({ variant: 'success', title, message }),
      error: (title, message) => push({ variant: 'danger', title, message, duration: 8000 }),
      info: (title, message) => push({ variant: 'info', title, message }),
      warning: (title, message) => push({ variant: 'warning', title, message }),
      push,
    }),
    [toasts, dismiss, push],
  );

  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}
