import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { Sidebar } from '@/components/layout/Sidebar';
import { Topbar } from '@/components/layout/Topbar';
import { useAuth } from '@/hooks/useAuth';
import { useToast } from '@/hooks/useToast';

/**
 * Shell for every authenticated screen: sidebar (drawer on mobile), topbar and
 * the routed page. Logout confirmation lives here so any screen can request it
 * through the same dialog.
 */
export function DashboardLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const { logout } = useAuth();
  const toast = useToast();
  const location = useLocation();

  const confirmLogout = async () => {
    setLoggingOut(true);
    try {
      await logout();
      toast.success('Signed out', 'Your session has been ended on this device.');
    } catch {
      toast.error('Signed out locally', 'We could not reach the server to revoke the session.');
    } finally {
      setLoggingOut(false);
      setLogoutOpen(false);
    }
  };

  return (
    <div className="min-h-screen bg-sand-50">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-72 lg:block">
        <Sidebar onRequestLogout={() => setLogoutOpen(true)} />
      </aside>

      {/* Mobile drawer */}
      {sidebarOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-ink/40"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 w-72 shadow-raised">
            <Sidebar
              onNavigate={() => setSidebarOpen(false)}
              onRequestLogout={() => {
                setSidebarOpen(false);
                setLogoutOpen(true);
              }}
            />
          </div>
        </div>
      ) : null}

      <div className="lg:pl-72">
        <Topbar onOpenSidebar={() => setSidebarOpen(true)} onRequestLogout={() => setLogoutOpen(true)} />
        <main id="main-content" key={location.pathname} className="animate-fade-in px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-content">
            <Outlet />
          </div>
        </main>
      </div>

      <ConfirmDialog
        open={logoutOpen}
        title="Sign out of HoneyChain?"
        description="Your refresh token will be revoked on the server for this device."
        confirmLabel="Sign out"
        variant="danger"
        loading={loggingOut}
        onConfirm={confirmLogout}
        onCancel={() => setLogoutOpen(false)}
      />
    </div>
  );
}

export default DashboardLayout;
