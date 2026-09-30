import { useContext } from 'react';

import { AuthContext } from '@/context/AuthContext';

/** Access the authentication context. Throws if used outside the provider. */
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return context;
}

export default useAuth;
