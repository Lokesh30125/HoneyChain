import { NavLink } from 'react-router-dom';
import {
  AlertTriangle,
  Beaker,
  BellRing,
  Blocks,
  Building2,
  ChartColumn,
  CheckCheck,
  ClipboardList,
  Factory,
  FileBarChart,
  FlaskConical,
  Hexagon,
  History,
  Inbox,
  LayoutDashboard,
  LogOut,
  Microscope,
  Package,
  PackageCheck,
  PauseCircle,
  Radio,
  Route,
  Ruler,
  ScanLine,
  QrCode,
  ScrollText,
  Settings,
  ShieldCheck,
  Sparkles,
  Store,
  TestTubes,
  Truck,
  UserCheck,
  UserCircle,
  Users,
  Warehouse,
  Wheat,
} from 'lucide-react';

import { Logo } from '@/components/common/Logo';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { navSectionsForRole } from '@/constants/navigation';
import { homeRouteForRole, roleLabel } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

/**
 * Every icon a navigation entry may reference.
 *
 * Navigation is data, so the icon name is a string; this map is the only place
 * that turns those strings into components. An unknown name falls back to a
 * neutral icon instead of crashing the shell.
 */
const ICONS = {
  QrCode,
  LayoutDashboard,
  Blocks,
  History,
  UserCheck,
  UserCircle,
  ClipboardList,
  Hexagon,
  Radio,
  Sparkles,
  Wheat,
  Package,
  BellRing,
  FileBarChart,
  Users,
  Building2,
  ScrollText,
  Settings,
  PackageCheck,
  Factory,
  FlaskConical,
  Truck,
  Store,
  ScanLine,
  ShieldCheck,
  Route,
  ChartColumn,
  TestTubes,
  Beaker,
  CheckCheck,
  Ruler,
  Microscope,
  Inbox,
  Warehouse,
  PauseCircle,
  AlertTriangle,
};

/**
 * Application sidebar.
 *
 * Renders exactly the sections the signed-in role's workspace declares — a
 * beekeeper never sees an administration link and an administrator never sees the
 * beekeeper's hives. There is no "coming soon" entry and no borrowed module: if a
 * screen does not exist it is not listed, and if it is listed it is routed, because
 * both come from the same configuration.
 */
export function Sidebar({ onNavigate, onRequestLogout }) {
  const { user } = useAuth();
  const role = user?.role;
  const homeRoute = homeRouteForRole(role);
  const sections = navSectionsForRole(role);

  return (
    <div className="flex h-full flex-col bg-forest-900 text-sand-200">
      <div className="flex h-16 flex-none items-center border-b border-white/10 px-4">
        <Logo to="/dashboard" inverted size={28} />
      </div>

      <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3 py-4">
        {sections.map((section, index) => (
          <div key={section.label} className={index === 0 ? '' : 'mt-6'}>
            <p className="px-2 pb-2 text-xs font-semibold uppercase tracking-wide text-sand-400">
              {section.label}
            </p>
            <ul className="space-y-1">
              {section.items.map((item) => {
                const Icon = ICONS[item.icon] || LayoutDashboard;
                const isOwnWorkspace = item.to === homeRoute;

                return (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === '/dashboard'}
                      onClick={onNavigate}
                      className={({ isActive }) =>
                        [
                          'flex items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                          isActive
                            ? 'bg-honey-500/15 text-honey-200 ring-1 ring-inset ring-honey-500/30'
                            : 'text-sand-300 hover:bg-white/5 hover:text-white',
                        ].join(' ')
                      }
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <Icon size={18} className="flex-none" aria-hidden="true" />
                        <span className="truncate">{item.label}</span>
                      </span>
                      {isOwnWorkspace ? (
                        <Badge variant="honey" size="sm">
                          Your role
                        </Badge>
                      ) : null}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="flex-none border-t border-white/10 p-4">
        <div className="mb-3">
          <p className="truncate text-sm font-medium text-white">{user?.name || 'Signed in'}</p>
          <p className="truncate text-xs text-sand-400">{roleLabel(role)}</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          fullWidth
          leftIcon={<LogOut size={15} />}
          onClick={onRequestLogout}
          className="border-white/20 bg-white/5 text-sand-100 hover:bg-white/10"
        >
          Logout
        </Button>
      </div>
    </div>
  );
}

export default Sidebar;
