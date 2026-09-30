import { ROLES } from '@/constants/roles';

/**
 * Modules that are declared but not built.
 *
 * This file is a *roadmap*, not a navigation source. Nothing here is routed and
 * nothing here appears in a sidebar: a module is described to the role it belongs
 * to, on that role's own workspace home, and it is deleted from this list the
 * moment a real screen replaces it. That is what keeps the honest description of
 * what is missing from turning into a link to a screen that does not exist.
 *
 * Every role now reaches a workspace of its own, so nothing in the router renders a
 * roadmap page any more — the note that remains is a line on the dashboard.
 *
 * An entry is deleted the moment a real screen replaces it: processing and the
 * laboratory were built in Phase 6, packaging, distribution and retail in Phase
 * 7, the collection centre's intake in the integration phase, and consumer
 * verification — the QR identity and the public traceability page — in Phase 8,
 * so their entries are gone and working pages stand in their place. Leaving one
 * behind would tell a role that its module is unbuilt while the module is
 * running, which is exactly what the consumer's own workspace did until this
 * entry was removed: its home screen read "the QR identity and the public
 * verification page are part of a later phase" while both were live.
 */

export const PLANNED_MODULES = [
  {
    path: '/kvic/production',
    roles: [ROLES.KVIC_OFFICER],
    title: 'Production reports',
    phase: 'Analytics phase',
    description:
      'Aggregated production and quality reporting over the records the platform already holds for your clusters.',
    features: [
      'Harvest volumes by cluster and season',
      'Quality outcome trends',
      'District-level roll-ups',
      'Export-ready summaries',
    ],
  },
  {
    path: '/admin/system',
    roles: [ROLES.ADMIN],
    title: 'System settings',
    phase: 'Operations phase',
    description:
      'Platform configuration and operational status: integrations, retention and the service health page.',
    features: [
      'Integration configuration (MQTT, storage)',
      'Service health and version information',
      'Retention settings for logs',
    ],
  },
];

export const PLANNED_MODULE_BY_PATH = Object.fromEntries(
  PLANNED_MODULES.map((module) => [module.path, module]),
);
