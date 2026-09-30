import { useEffect, useState } from 'react';
import { Activity, ArrowRight, BadgeCheck, Cpu, FlaskConical, Hexagon, ScrollText, ShieldCheck, UserCircle } from 'lucide-react';

import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { StatCard } from '@/components/common/StatCard';
import { StatusBadge } from '@/components/common/StatusBadge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { ROLES, ROLE_DESCRIPTIONS, roleLabel } from '@/constants/roles';
import { workspaceForRole, workspaceHomeForRole } from '@/constants/navigation';
import { PLANNED_MODULES } from '@/constants/plannedModules';
import { useAuth } from '@/hooks/useAuth';
import { useApiHealth } from '@/hooks/useApiHealth';
import * as beekeeperService from '@/services/beekeeperService';
import * as hiveService from '@/services/hiveService';
import * as iotService from '@/services/iotService';
import * as laboratoryService from '@/services/laboratoryService';
import * as processingService from '@/services/processingService';

/**
 * The shared dashboard.
 *
 * Every role gets the same account panel and the same live service check; the
 * numbers and the workspace shortcut underneath are chosen by the role, and only
 * from endpoints that role may actually call. There is deliberately no list of
 * "other workspaces" here: a beekeeper has no business in the administration
 * screens and no link to them, and an officer has no link into the laboratory.
 * Each role's own workspace is one click away — in the sidebar, where it belongs.
 */

const WORKSPACE_PANEL = {
  [ROLES.BEEKEEPER]: {
    title: 'Your apiary',
    description: 'Hives and devices on your beekeeper record.',
    tiles: [
      { key: 'hives', label: 'Hives', icon: 'hive', helperKey: 'hivesHelper' },
      { key: 'devices', label: 'Devices reporting', icon: 'device', helperKey: 'devicesHelper' },
    ],
  },
  [ROLES.KVIC_OFFICER]: {
    title: 'Your cluster',
    description: 'Registrations awaiting review, plus hive and device coverage.',
    tiles: [
      { key: 'awaiting', label: 'Awaiting review', icon: 'shield', helperKey: 'awaitingHelper' },
      { key: 'hives', label: 'Hives registered', icon: 'hive', helperKey: 'hivesHelper' },
    ],
  },
  [ROLES.ADMIN]: {
    title: 'Platform',
    description: 'Hives and devices registered across every district.',
    tiles: [
      { key: 'hives', label: 'Hives', icon: 'hive', helperKey: 'hivesHelper' },
      { key: 'devices', label: 'Devices reporting', icon: 'device', helperKey: 'devicesHelper' },
    ],
  },
  [ROLES.PROCESSOR]: {
    title: 'Processing queue',
    description: 'Batches waiting to be processed and the runs already under way.',
    tiles: [
      { key: 'awaitingProcessing', label: 'Awaiting processing', icon: 'factory', helperKey: 'awaitingProcessingHelper' },
      { key: 'runsInProgress', label: 'Runs in progress', icon: 'factory', helperKey: 'runsInProgressHelper' },
    ],
  },
  [ROLES.LAB_TECHNICIAN]: {
    title: 'Laboratory queue',
    description: 'Batches waiting for a sample and tests already open.',
    tiles: [
      { key: 'awaitingTesting', label: 'Awaiting testing', icon: 'flask', helperKey: 'awaitingTestingHelper' },
      { key: 'testsInProgress', label: 'Tests in progress', icon: 'flask', helperKey: 'testsInProgressHelper' },
    ],
  },
};

const PANEL_ICONS = {
  hive: <Hexagon size={16} />,
  device: <Cpu size={16} />,
  shield: <ShieldCheck size={16} />,
  factory: <Activity size={16} />,
  flask: <FlaskConical size={16} />,
};

export default function DashboardPage() {
  const { user } = useAuth();
  const { status, service, checkedAt, refresh } = useApiHealth();
  const [now, setNow] = useState(() => new Date());
  const [numbers, setNumbers] = useState(null);
  const [numbersLoading, setNumbersLoading] = useState(true);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(timer);
  }, []);

  const role = user?.role;
  const homeRoute = workspaceHomeForRole(role);
  const workspace = workspaceForRole(role);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const wants = {
        hives: [ROLES.BEEKEEPER, ROLES.KVIC_OFFICER, ROLES.ADMIN].includes(role),
        devices: [ROLES.BEEKEEPER, ROLES.ADMIN].includes(role),
        awaiting: role === ROLES.KVIC_OFFICER,
        processing: [ROLES.PROCESSOR, ROLES.ADMIN].includes(role),
        laboratory: [ROLES.LAB_TECHNICIAN, ROLES.ADMIN].includes(role),
      };

      const [hives, iot, beekeepers, processing, laboratory] = await Promise.allSettled([
        wants.hives ? hiveService.getHiveSummary() : Promise.resolve(null),
        wants.devices ? iotService.getMonitoringSummary() : Promise.resolve(null),
        wants.awaiting ? beekeeperService.getBeekeeperSummary() : Promise.resolve(null),
        wants.processing ? processingService.getProcessingSummary() : Promise.resolve(null),
        wants.laboratory ? laboratoryService.getTestSummary() : Promise.resolve(null),
      ]);
      if (cancelled) return;

      const byStatus = beekeepers.status === 'fulfilled' ? beekeepers.value?.by_verification_status || {} : {};
      const processingValue = processing.status === 'fulfilled' ? processing.value : null;
      const laboratoryValue = laboratory.status === 'fulfilled' ? laboratory.value : null;
      setNumbers({
        hives: hives.status === 'fulfilled' ? hives.value?.total ?? 0 : null,
        hivesHelper:
          hives.status === 'fulfilled'
            ? `${hives.value?.by_status?.ACTIVE ?? 0} active · ${hives.value?.with_device ?? 0} with a device`
            : 'Unavailable',
        devices: iot.status === 'fulfilled' ? iot.value?.connected_devices ?? 0 : null,
        devicesHelper:
          iot.status === 'fulfilled'
            ? `${iot.value?.total_devices ?? 0} paired · ${iot.value?.offline_devices ?? 0} offline`
            : 'Unavailable',
        // Only a summary that actually arrived produces a number.
        awaiting:
          beekeepers.status === 'fulfilled'
            ? (byStatus.PENDING || 0) + (byStatus.UNDER_REVIEW || 0)
            : null,
        awaitingHelper:
          beekeepers.status === 'fulfilled' ? `${byStatus.VERIFIED ?? 0} verified` : 'Unavailable',
        awaitingProcessing: processingValue?.awaiting_processing ?? null,
        awaitingProcessingHelper: processingValue
          ? `${processingValue.completed ?? 0} runs completed`
          : 'Unavailable',
        runsInProgress: processingValue ? (processingValue.in_progress ?? 0) + (processingValue.pending ?? 0) : null,
        runsInProgressHelper: processingValue ? `${processingValue.awaiting_laboratory ?? 0} awaiting laboratory` : 'Unavailable',
        awaitingTesting: laboratoryValue?.awaiting_testing ?? null,
        awaitingTestingHelper: laboratoryValue ? `${laboratoryValue.pending ?? 0} tests opened` : 'Unavailable',
        testsInProgress: laboratoryValue ? (laboratoryValue.pending ?? 0) + (laboratoryValue.in_progress ?? 0) : null,
        testsInProgressHelper: laboratoryValue
          ? `${laboratoryValue.passed ?? 0} passed · ${laboratoryValue.failed ?? 0} failed`
          : 'Unavailable',
      });
      setNumbersLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [role]);

  const hour = now.getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const panel = WORKSPACE_PANEL[role] || null;
  const plannedForRole = PLANNED_MODULES.filter((module) => module.path === workspace?.home);

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Dashboard' }]} />

      <PageHeader
        title={`${greeting}, ${user?.name?.split(' ')[0] || 'there'}`}
        description="Your HoneyChain account, and the workspace your role works in."
        badge={
          <Badge variant="honey" size="sm">
            {roleLabel(role)}
          </Badge>
        }
        actions={
          <Button to={homeRoute} size="sm" rightIcon={<ArrowRight size={16} />}>
            {workspace ? `Open ${workspace.short.toLowerCase()} workspace` : 'Open my workspace'}
          </Button>
        }
      />

      <section aria-label="Account summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Signed in as" value={roleLabel(role)} helper={ROLE_DESCRIPTIONS[role]} icon={<UserCircle size={16} />} />
        <StatCard
          label="Account status"
          value={user?.is_active ? 'Active' : 'Inactive'}
          helper={user?.email}
          icon={<BadgeCheck size={16} />}
          tone="forest"
        />
        <StatCard
          label="API connectivity"
          value={status === 'online' ? 'Connected' : status === 'checking' ? 'Checking…' : 'Unreachable'}
          helper={checkedAt ? `Last checked ${checkedAt.toLocaleTimeString()}` : service || 'Checking the backend…'}
          icon={<Activity size={16} />}
        />
        <StatCard
          label="Role scope"
          value={workspace ? workspace.short : 'Account only'}
          helper={workspace ? 'Sidebar and routes are scoped to this workspace' : 'No module is built for this role yet'}
          icon={<ShieldCheck size={16} />}
        />
      </section>

      {panel ? (
        <Card className="min-w-0">
          <CardHeader
            title={panel.title}
            description={panel.description}
            icon={<Hexagon size={16} />}
            action={
              <Button to={homeRoute} size="sm" variant="secondary">
                Open workspace
              </Button>
            }
          />
          <CardBody>
            <div className="grid gap-4 sm:grid-cols-2">
              {panel.tiles.map((tile) => (
                <StatCard
                  key={tile.key}
                  label={tile.label}
                  value={numbers?.[tile.key] ?? (numbersLoading ? '…' : '—')}
                  helper={numbers?.[tile.helperKey] || undefined}
                  icon={PANEL_ICONS[tile.icon]}
                  tone={tile.key === 'hives' ? 'honey' : 'default'}
                  loading={numbersLoading}
                />
              ))}
            </div>
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader
            title={workspace ? workspace.label : 'Your workspace'}
            description={workspace?.description || 'Where your day-to-day tasks live.'}
            icon={<ArrowRight size={16} />}
          />
          <CardBody className="space-y-4">
            <p className="text-sm leading-relaxed text-ink-soft">{ROLE_DESCRIPTIONS[role]}</p>
            <div className="flex flex-wrap gap-2">
              <Button to={homeRoute} size="sm">
                Go to my workspace
              </Button>
              <Button to="/profile" size="sm" variant="secondary">
                Review my profile
              </Button>
            </div>
            {plannedForRole.length ? (
              <div className="border-t border-sand-200 pt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Not in this release
                </p>
                <ul className="mt-2 space-y-1 text-sm text-ink-soft">
                  {plannedForRole.map((module) => (
                    <li key={module.path}>
                      <span className="font-medium text-ink">{module.title}</span> — {module.phase.toLowerCase()}.
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-ink-muted">
                  Your module is not built yet, so the platform does not show it as a navigation entry
                  anywhere. When it ships it appears in your own workspace.
                </p>
              </div>
            ) : (
              <p className="border-t border-sand-200 pt-4 text-xs text-ink-muted">
                Your sidebar shows only the modules your role works in. Other roles&apos; workspaces are
                not listed here, and cannot be opened: the API authorises every request.
              </p>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Platform status" description="Live check against the API." icon={<Activity size={16} />} />
          <CardBody className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-ink-soft">Backend service</span>
              <StatusBadge status={status} />
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-ink-soft">Service name</span>
              <span className="text-sm font-medium text-ink">{service || '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-ink-soft">Signed in</span>
              <span className="text-sm font-medium text-ink">{user?.name || '—'}</span>
            </div>
            {status === 'offline' ? (
              <p className="rounded-lg border border-status-warning/30 bg-status-warning-bg px-3 py-2 text-xs text-status-warning">
                The API did not respond. Confirm the backend is running and the Vite proxy target is
                correct, then retry.
              </p>
            ) : null}
            <Button variant="secondary" size="sm" onClick={refresh}>
              Re-check now
            </Button>
          </CardBody>
        </Card>
      </div>

      <Card className="min-w-0">
        <CardHeader
          title="What is live today"
          description="The modules that exist, and the ones that do not."
          icon={<ScrollText size={16} />}
        />
        <CardBody>
          <ul className="grid gap-x-6 gap-y-2 text-sm text-ink-soft sm:grid-cols-2">
            {[
              ['Accounts, roles and profiles', true],
              ['Beekeeper registry & KVIC verification', true],
              ['Hive registry & IoT telemetry', true],
              ['AI decision support & alerts', true],
              ['Harvest records & honey batches', true],
              ['Processing runs & laboratory quality', true],
              ['Packaging, distribution & retailer receipt', true],
              ['Consumer QR verification & blockchain traceability', true],
            ].map(([label, live]) => (
              <li key={label} className="flex items-center gap-2">
                <Badge variant={live ? 'success' : 'pending'} size="sm">
                  {live ? 'Live' : 'Not in this release'}
                </Badge>
                {label}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}
