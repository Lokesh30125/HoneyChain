/**
 * Navigation models — one workspace per role.
 *
 * This file is the single source of truth for *who sees what*. The sidebar is
 * rendered from it, the router is guarded by it, and the dashboards read their
 * labels from it, so a module cannot be reachable from a hint in one place and
 * invisible in another.
 *
 * Two rules the shape of the data enforces:
 *
 * 1. A workspace declares its own sections. There is no shared list filtered at
 *    render time, so an entry cannot leak into an unrelated role's sidebar by
 *    being added in the wrong place.
 * 2. A workspace declares the route prefixes its role may open. A path outside
 *    them is not rendered *and* not routable — a typed URL lands the user back in
 *    their own workspace instead of on a "this is not your workspace" screen.
 *
 * Nothing in this file implies a feature exists. Entries exist only for screens
 * that are built; modules that are not built yet are described once in
 * `plannedModules.js` and shown as roadmap notes on the dashboards, never as
 * sidebar links.
 */

import { ROLES } from '@/constants/roles';

/** Public marketing site navigation (labels + anchors on the landing page). */
export const PUBLIC_NAV_ITEMS = [
  { label: 'Home', to: '/' },
  { label: 'How It Works', to: '/how-it-works' },
  { label: 'For Beekeepers', to: '/#beekeepers' },
  { label: 'Traceability', to: '/#traceability' },
  { label: 'Technology', to: '/#technology' },
  { label: 'About', to: '/about' },
];

/** Footer link groups. */
export const FOOTER_SECTIONS = [
  {
    title: 'Platform',
    links: [
      { label: 'How It Works', to: '/how-it-works' },
      { label: 'Smart Beekeeping', to: '/#beekeeping' },
      { label: 'Blockchain Traceability', to: '/#traceability' },
      { label: 'Consumer Verification', to: '/#consumer' },
    ],
  },
  {
    title: 'Who it serves',
    links: [
      { label: 'Beekeepers', to: '/#beekeepers' },
      { label: 'Processors & Packagers', to: '/#supply-chain' },
      { label: 'KVIC & Clusters', to: '/#impact' },
      { label: 'Consumers', to: '/#consumer' },
    ],
  },
  {
    title: 'Platform status',
    links: [
      { label: 'About HoneyChain', to: '/about' },
      { label: 'Contact', to: '/contact' },
      { label: 'Sign in', to: '/login' },
      { label: 'Create account', to: '/register' },
    ],
  },
];

/** Every signed-in user starts and ends their day with these two screens. */
const ACCOUNT_SECTIONS = [
  {
    label: 'Workspace',
    items: [
      { label: 'Dashboard', to: '/dashboard', icon: 'LayoutDashboard' },
      { label: 'My Profile', to: '/profile', icon: 'UserCircle' },
    ],
  },
];

/**
 * Workspace definitions, keyed by role.
 *
 * `routes` lists the path prefixes the role may open, on top of `/dashboard` and
 * `/profile` which everybody has. `sections` is exactly what its sidebar renders.
 */
export const WORKSPACES = {
  [ROLES.BEEKEEPER]: {
    label: 'Beekeeper workspace',
    short: 'Beekeeper',
    home: '/beekeeper',
    routes: ['/beekeeper'],
    description: 'Your apiary: hives, sensors, harvests and the journey of your honey.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Beekeeper',
        items: [
          { label: 'My Hives', to: '/beekeeper/hives', icon: 'Hexagon' },
          { label: 'IoT Monitoring', to: '/beekeeper/iot', icon: 'Radio' },
          { label: 'AI Insights', to: '/beekeeper/insights', icon: 'Sparkles' },
          { label: 'Alerts', to: '/beekeeper/alerts', icon: 'BellRing' },
          { label: 'Honey Collections', to: '/beekeeper/collections', icon: 'Wheat' },
          { label: 'Honey Batches', to: '/beekeeper/batches', icon: 'Package' },
          { label: 'Traceability', to: '/beekeeper/traceability', icon: 'Route' },
        ],
      },
    ],
  },

  [ROLES.KVIC_OFFICER]: {
    label: 'KVIC officer workspace',
    short: 'KVIC',
    home: '/kvic',
    routes: ['/kvic'],
    description:
      'Your clusters: members, apiaries, harvests and the quality outcome of the honey they produced.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'KVIC',
        items: [
          { label: 'Clusters', to: '/kvic/clusters', icon: 'Building2' },
          { label: 'Beekeepers', to: '/kvic/beekeepers', icon: 'ClipboardList' },
          { label: 'Hives', to: '/kvic/hives', icon: 'Hexagon' },
          { label: 'IoT Monitoring', to: '/kvic/iot', icon: 'Radio' },
          { label: 'AI Insights', to: '/kvic/insights', icon: 'Sparkles' },
          { label: 'Alerts', to: '/kvic/alerts', icon: 'BellRing' },
          { label: 'Honey Collections', to: '/kvic/collections', icon: 'Wheat' },
          { label: 'Honey Batches', to: '/kvic/batches', icon: 'Package' },
          { label: 'Processing', to: '/kvic/processing', icon: 'Factory' },
          { label: 'Laboratory', to: '/kvic/laboratory', icon: 'FlaskConical' },
          { label: 'Traceability', to: '/kvic/traceability', icon: 'Route' },
          { label: 'Blockchain Ledger', to: '/kvic/blockchain', icon: 'Blocks' },
          { label: 'Cluster Analytics', to: '/kvic/cluster-analytics', icon: 'ChartColumn' },
        ],
      },
    ],
  },

  [ROLES.LAB_TECHNICIAN]: {
    label: 'Laboratory workspace',
    short: 'Laboratory',
    home: '/laboratory',
    routes: ['/laboratory'],
    description:
      'Samples waiting for testing, the work allocated to you, the measurements you record against them, and the completed tests they decide.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Laboratory',
        items: [
          { label: 'Dashboard', to: '/laboratory', icon: 'LayoutDashboard' },
          { label: 'Pending Lab Tests', to: '/laboratory/pending', icon: 'TestTubes' },
          { label: 'Assigned Lab Tests', to: '/laboratory/assigned', icon: 'UserCheck' },
          { label: 'Awaiting a Sample', to: '/laboratory/awaiting', icon: 'Beaker' },
          { label: 'Completed Tests', to: '/laboratory/completed', icon: 'CheckCheck' },
          { label: 'On Hold', to: '/laboratory/held', icon: 'PauseCircle' },
          { label: 'Test History', to: '/laboratory/tests', icon: 'History' },
        ],
      },
      {
        label: 'Records',
        items: [
          { label: 'Samples', to: '/laboratory/samples', icon: 'Beaker' },
          { label: 'Reference Parameters', to: '/laboratory/parameters', icon: 'Ruler' },
          { label: 'Laboratories', to: '/laboratory/facilities', icon: 'Microscope' },
        ],
      },
    ],
  },

  [ROLES.PROCESSOR]: {
    label: 'Processing workspace',
    short: 'Processing',
    home: '/processor',
    routes: ['/processor'],
    description:
      'Batches waiting to be processed, the work allocated to you, the runs you record, and what has left for the laboratory.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Processing',
        items: [
          { label: 'Dashboard', to: '/processor', icon: 'LayoutDashboard' },
          { label: 'Pending Batches', to: '/processor/pending', icon: 'Inbox' },
          { label: 'Assigned Batches', to: '/processor/assigned', icon: 'UserCheck' },
          { label: 'Processing', to: '/processor/processing', icon: 'Factory' },
          { label: 'Completed Processing', to: '/processor/completed', icon: 'CheckCheck' },
          { label: 'Processing History', to: '/processor/history', icon: 'History' },
        ],
      },
      {
        label: 'Records',
        items: [
          { label: 'Collected Batches', to: '/processor/awaiting', icon: 'Inbox' },
          { label: 'All Runs', to: '/processor/runs', icon: 'ClipboardList' },
          { label: 'Batches', to: '/processor/batches', icon: 'Package' },
          { label: 'Processing Units', to: '/processor/units', icon: 'Warehouse' },
        ],
      },
    ],
  },

  [ROLES.ADMIN]: {
    label: 'Administration',
    short: 'Administration',
    home: '/admin',
    routes: ['/admin', '/kvic', '/processing', '/laboratory'],
    description: 'Accounts, the beekeeper registry, every operational module and the audit trail.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Administration',
        items: [
          { label: 'Users', to: '/admin/users', icon: 'Users' },
          { label: 'Beekeepers', to: '/admin/beekeepers', icon: 'ClipboardList' },
          { label: 'Clusters', to: '/admin/clusters', icon: 'Building2' },
          { label: 'Packaging Units', to: '/admin/packaging-units', icon: 'Factory' },
          { label: 'Hives', to: '/admin/hives', icon: 'Hexagon' },
          { label: 'IoT Monitoring', to: '/admin/iot', icon: 'Radio' },
          { label: 'AI Insights', to: '/admin/insights', icon: 'Sparkles' },
          { label: 'Alerts', to: '/admin/alerts', icon: 'BellRing' },
        ],
      },
      {
        label: 'Supply chain',
        items: [
          { label: 'Honey Collections', to: '/admin/collections', icon: 'Wheat' },
          { label: 'Honey Batches', to: '/admin/batches', icon: 'Package' },
          { label: 'Processing', to: '/admin/processing', icon: 'Factory' },
          { label: 'Laboratory', to: '/admin/laboratory', icon: 'FlaskConical' },
        ],
      },
      {
        label: 'Platform',
        items: [
          { label: 'Blockchain Ledger', to: '/admin/blockchain', icon: 'Blocks' },
          { label: 'Audit Logs', to: '/admin/audit-logs', icon: 'ScrollText' },
          { label: 'KVIC Oversight', to: '/kvic', icon: 'ShieldCheck' },
        ],
      },
    ],
  },

  // The intake point for the apiaries of a district. It reads the harvests and
  // the batches they produced — the same rows the beekeeper and the officer read,
  // narrowed to its district — and writes none of them: a harvest is recorded by
  // the beekeeper who collected the honey.
  [ROLES.COLLECTION_CENTER]: {
    label: 'Collection centre workspace',
    short: 'Collection centre',
    home: '/collection-center',
    routes: ['/collection-center'],
    description:
      'Intake of raw honey from the apiaries in your district: every harvest received, with the batch it became.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Intake',
        items: [
          { label: 'Honey Collections', to: '/collection-center', icon: 'Wheat' },
        ],
      },
    ],
  },

  [ROLES.PACKAGING_UNIT]: {
    label: 'Packaging workspace',
    short: 'Packaging',
    home: '/packaging',
    routes: ['/packaging'],
    description:
      'Batches the laboratory approved, the honey packed into individually coded packages, and the stock that leaves for distribution.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Packaging',
        items: [
          { label: 'Approved batches', to: '/packaging/approved', icon: 'Inbox' },
          { label: 'Packaging runs', to: '/packaging/runs', icon: 'Boxes' },
          { label: 'Packed stock', to: '/packaging/stock', icon: 'PackageCheck' },
          { label: 'QR Code Generation', to: '/packaging/qr', icon: 'QrCode' },
          { label: 'Packaging history', to: '/packaging/history', icon: 'History' },
        ],
      },
    ],
  },

  [ROLES.DISTRIBUTOR]: {
    label: 'Distribution workspace',
    short: 'Distribution',
    home: '/distributor',
    routes: ['/distributor'],
    description: 'Released packages, the shipments they travel on, and what has been received.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Distribution',
        items: [
          { label: 'Ready for dispatch', to: '/distributor/ready', icon: 'PackageOpen' },
          { label: 'Shipments', to: '/distributor/shipments', icon: 'Truck' },
          { label: 'In transit', to: '/distributor/transit', icon: 'Route' },
          { label: 'Delivered', to: '/distributor/delivered', icon: 'PackageCheck' },
        ],
      },
    ],
  },

  [ROLES.RETAILER]: {
    label: 'Retail workspace',
    short: 'Retail',
    home: '/retailer',
    routes: ['/retailer'],
    description: 'Shipments on their way to you, the packages you have received, and where each came from.',
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Retail',
        items: [
          { label: 'Incoming shipments', to: '/retailer/inbound', icon: 'Inbox' },
          { label: 'Received packages', to: '/retailer/received', icon: 'PackageCheck' },
        ],
      },
    ],
  },

  [ROLES.CONSUMER]: {
    label: 'Consumer workspace',
    short: 'Consumer',
    home: '/consumer',
    routes: ['/consumer'],
    description: 'Scan a jar to read the journey of the honey inside it.',
    // One entry, because the consumer's work is one screen: enter a code,
    // read the record. The public landing page's explanation belongs to the
    // public site, not to this role's sidebar.
    sections: [
      ...ACCOUNT_SECTIONS,
      {
        label: 'Verify',
        items: [{ label: 'Verify a product', to: '/consumer', icon: 'QrCode' }],
      },
    ],
  },
};

/** Roles that reach the KVIC screens as oversight rather than as their home. */
const KVIC_OVERSIGHT_ROLES = [ROLES.ADMIN];

/** Dashboard, the account screens and the public pages everybody may open. */
const COMMON_ROUTES = ['/dashboard', '/profile'];

/** The workspace definition for a role, or `null` when the role is unknown. */
export function workspaceForRole(role) {
  return WORKSPACES[role] || null;
}

/** Sidebar sections for a signed-in role — empty when the role has no workspace. */
export function navSectionsForRole(role) {
  return workspaceForRole(role)?.sections || [];
}

/** The home route of a role's own workspace (falls back to the shared dashboard). */
export function workspaceHomeForRole(role) {
  return workspaceForRole(role)?.home || '/dashboard';
}

/** Human label of a role's workspace, for headers and breadcrumbs. */
export function workspaceLabelForRole(role) {
  return workspaceForRole(role)?.label || 'Workspace';
}

/**
 * Every route prefix a role may open.
 *
 * Used by the router guard. The backend re-authorises every request regardless —
 * this decides which screens are *reachable*, never which data is readable.
 */
export function allowedRoutePrefixes(role) {
  const workspace = workspaceForRole(role);
  const prefixes = [...COMMON_ROUTES];
  if (workspace) prefixes.push(...workspace.routes);
  if (KVIC_OVERSIGHT_ROLES.includes(role)) prefixes.push('/kvic');
  return prefixes;
}

/** Is this path inside the role's own workspace (or a shared screen)? */
export function canRoleOpenPath(role, pathname) {
  if (!pathname) return false;
  const path = pathname.length > 1 && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
  return allowedRoutePrefixes(role).some(
    (prefix) => path === prefix || path.startsWith(`${prefix}/`),
  );
}

/**
 * Compatibility helper for the workspace components: the sections a role sees,
 * flattened into a single lookup of `path → label`.
 */
export function navLabelByPath(role) {
  const labels = {};
  navSectionsForRole(role).forEach((section) => {
    section.items.forEach((item) => {
      labels[item.to] = item.label;
    });
  });
  return labels;
}
