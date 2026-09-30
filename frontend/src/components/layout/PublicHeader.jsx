import { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { LogIn, Menu, UserPlus, X } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Logo } from '@/components/common/Logo';
import { PUBLIC_NAV_ITEMS } from '@/constants/navigation';
import { useAuth } from '@/hooks/useAuth';

/**
 * Top navigation for the public (marketing) site.
 *
 * Shows "Sign in / Create account" to visitors and a direct link into the
 * dashboard once a session exists.
 */
export function PublicHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { isAuthenticated, user } = useAuth();

  return (
    <header className="sticky top-0 z-40 border-b border-sand-200 bg-sand-50/95 backdrop-blur">
      <div className="hc-container flex h-16 items-center justify-between gap-4">
        <Logo showTagline={false} />

        <nav aria-label="Main" className="hidden items-center gap-1 lg:flex">
          {PUBLIC_NAV_ITEMS.map((item) =>
            item.to.includes('#') ? (
              <a
                key={item.label}
                href={item.to}
                className="rounded-lg px-3 py-2 text-sm font-medium text-ink-soft transition-colors hover:bg-sand-100 hover:text-ink"
              >
                {item.label}
              </a>
            ) : (
              <NavLink
                key={item.label}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  [
                    'rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                    isActive ? 'bg-forest-50 text-forest-800' : 'text-ink-soft hover:bg-sand-100 hover:text-ink',
                  ].join(' ')
                }
              >
                {item.label}
              </NavLink>
            ),
          )}
        </nav>

        <div className="hidden items-center gap-2 lg:flex">
          {isAuthenticated ? (
            <Button to="/dashboard" size="sm" variant="primary">
              {user?.name ? `Continue as ${user.name.split(' ')[0]}` : 'Go to dashboard'}
            </Button>
          ) : (
            <>
              <Button to="/login" size="sm" variant="ghost" leftIcon={<LogIn size={16} />}>
                Login
              </Button>
              <Button to="/register" size="sm" variant="primary" leftIcon={<UserPlus size={16} />}>
                Register
              </Button>
            </>
          )}
        </div>

        <button
          type="button"
          className="rounded-lg p-2 text-ink-soft transition-colors hover:bg-sand-100 lg:hidden"
          onClick={() => setMenuOpen((open) => !open)}
          aria-expanded={menuOpen}
          aria-controls="public-mobile-nav"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {menuOpen ? (
        <div id="public-mobile-nav" className="border-t border-sand-200 bg-sand-50 lg:hidden">
          <nav aria-label="Mobile" className="hc-container flex flex-col py-3">
            {PUBLIC_NAV_ITEMS.map((item) => (
              <Link
                key={item.label}
                to={item.to}
                onClick={() => setMenuOpen(false)}
                className="rounded-lg px-3 py-2.5 text-sm font-medium text-ink-soft hover:bg-sand-100 hover:text-ink"
              >
                {item.label}
              </Link>
            ))}
            <div className="mt-2 flex gap-2 border-t border-sand-200 pt-3">
              {isAuthenticated ? (
                <Button to="/dashboard" fullWidth size="sm" onClick={() => setMenuOpen(false)}>
                  Go to dashboard
                </Button>
              ) : (
                <>
                  <Button to="/login" variant="secondary" size="sm" fullWidth onClick={() => setMenuOpen(false)}>
                    Login
                  </Button>
                  <Button to="/register" size="sm" fullWidth onClick={() => setMenuOpen(false)}>
                    Register
                  </Button>
                </>
              )}
            </div>
          </nav>
        </div>
      ) : null}
    </header>
  );
}

export default PublicHeader;
