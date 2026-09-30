import { BrowserRouter } from 'react-router-dom';

import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { Toaster } from '@/components/common/Toaster';
import { AuthProvider } from '@/context/AuthContext';
import { ToastProvider } from '@/context/ToastContext';
import { AppRoutes } from '@/routes/AppRoutes';

/**
 * Application root.
 *
 * Provider order matters: the error boundary must sit outside everything so a
 * crash anywhere renders a usable message; toasts wrap auth so authentication
 * failures can be reported with the same mechanism as any other error.
 */
export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <ToastProvider>
          <AuthProvider>
            <AppRoutes />
            <Toaster />
          </AuthProvider>
        </ToastProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
