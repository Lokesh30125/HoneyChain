import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Bell, ChevronDown, LogOut, Menu, UserCircle } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { StatusBadge } from '@/components/common/StatusBadge';
import { roleLabel } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import { useApiHealth } from '@/hooks/useApiHealth';

/**
 * Application topbar: mobile menu toggle, API status, notifications
 * placeholder and the account menu.
 */
export function Topbar({ onOpenSidebar, onRequestLogout }) {
  const { user } = useAuth();
  const { status, refresh } = useApiHealth();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 border-b border-sand-200 bg-white px-4 sm:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={onOpenSidebar}
          className="rounded-lg p-2 text-ink-soft transition-colors hover:bg-sand-100 lg:hidden"
          aria-label="Open navigation"
        >
          <Menu size={20} />
        </button>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">HoneyChain Platform</p>
          <p className="hidden truncate text-xs text-ink-muted sm:block">
            Blockchain traceability &amp; smart beekeeping management
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">
        <button
          type="button"
          onClick={refresh}
          title="Re-check API connectivity"
          className="hidden items-center gap-2 rounded-lg border border-sand-200 px-2.5 py-1.5 transition-colors hover:bg-sand-50 sm:flex"
        >
          <span className="text-xs text-ink-muted">API</span>
          <StatusBadge status={status} size="sm" />
        </button>

        <button
          type="button"
          className="relative rounded-lg p-2 text-ink-soft transition-colors hover:bg-sand-100"
          aria-label="Notifications"
          title="Notifications arrive in a later phase"
        >
          <Bell size={18} />
        </button>

        <div className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            className="flex items-center gap-2 rounded-lg border border-sand-200 px-2 py-1.5 transition-colors hover:bg-sand-50"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-forest-700 text-xs font-semibold text-white">
              {(user?.name || 'U').charAt(0).toUpperCase()}
            </span>
            <span className="hidden max-w-[10rem] truncate text-sm font-medium text-ink sm:block">
              {user?.name}
            </span>
            <ChevronDown size={15} className="text-ink-muted" aria-hidden="true" />
          </button>

          {menuOpen ? (
            <div
              role="menu"
              className="absolute right-0 mt-2 w-60 overflow-hidden rounded-card border border-sand-300 bg-white shadow-raised"
            >
              <div className="border-b border-sand-200 px-4 py-3">
                <p className="truncate text-sm font-medium text-ink">{user?.name}</p>
                <p className="truncate text-xs text-ink-muted">{user?.email}</p>
                <Badge variant="forest" size="sm" className="mt-2">
                  {roleLabel(user?.role)}
                </Badge>
              </div>
              <Link
                to="/profile"
                role="menuitem"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2 px-4 py-2.5 text-sm text-ink-soft transition-colors hover:bg-sand-50"
              >
                <UserCircle size={16} aria-hidden="true" />
                My profile
              </Link>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false);
                  onRequestLogout();
                }}
                className="flex w-full items-center gap-2 border-t border-sand-200 px-4 py-2.5 text-left text-sm text-status-danger transition-colors hover:bg-status-danger-bg"
              >
                <LogOut size={16} aria-hidden="true" />
                Logout
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

export default Topbar;
