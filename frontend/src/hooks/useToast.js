import { useContext } from 'react';

import { ToastContext } from '@/context/ToastContext';

/** Access the toast queue (success / error / info notifications). */
export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used inside <ToastProvider>');
  }
  return context;
}

export default useToast;
