/**
 * Role catalogue.
 *
 * The backend remains the source of truth (`GET /api/v1/roles`); these values
 * mirror it for routing decisions and for rendering before that request
 * completes. `roleService` refreshes the catalogue at runtime and any mismatch
 * is a bug in this file, not in the API.
 */

export const ROLES = Object.freeze({
  ADMIN: 'ADMIN',
  BEEKEEPER: 'BEEKEEPER',
  COLLECTION_CENTER: 'COLLECTION_CENTER',
  PROCESSOR: 'PROCESSOR',
  LAB_TECHNICIAN: 'LAB_TECHNICIAN',
  PACKAGING_UNIT: 'PACKAGING_UNIT',
  DISTRIBUTOR: 'DISTRIBUTOR',
  RETAILER: 'RETAILER',
  CONSUMER: 'CONSUMER',
  KVIC_OFFICER: 'KVIC_OFFICER',
});

/**
 * Landing route per role — mirrors `ROLE_HOME_ROUTES` on the backend exactly.
 * Keeping the two lists identical is what lets `home_route` from the login
 * response be trusted, and lets the sidebar mark "your workspace" correctly.
 */
export const ROLE_HOME_ROUTES = Object.freeze({
  [ROLES.ADMIN]: '/admin',
  [ROLES.BEEKEEPER]: '/beekeeper',
  [ROLES.COLLECTION_CENTER]: '/collection-center',
  [ROLES.PROCESSOR]: '/processor',
  [ROLES.LAB_TECHNICIAN]: '/laboratory',
  [ROLES.PACKAGING_UNIT]: '/packaging',
  [ROLES.DISTRIBUTOR]: '/distributor',
  [ROLES.RETAILER]: '/retailer',
  [ROLES.CONSUMER]: '/consumer',
  [ROLES.KVIC_OFFICER]: '/kvic',
});

/** Short description of what each role does, shown on the dashboard shell. */
export const ROLE_DESCRIPTIONS = Object.freeze({
  [ROLES.ADMIN]: 'Platform administration, account provisioning and oversight.',
  [ROLES.BEEKEEPER]: 'Hive registry, harvest records and apiary operations.',
  [ROLES.COLLECTION_CENTER]: 'Intake, weighing and onward dispatch of raw honey.',
  [ROLES.PROCESSOR]: 'Processing events and quality documentation.',
  [ROLES.LAB_TECHNICIAN]: 'Laboratory quality tests and adulteration screening.',
  [ROLES.PACKAGING_UNIT]: 'Packaging, batch labelling and QR association.',
  [ROLES.DISTRIBUTOR]: 'Distribution and cold-chain movement records.',
  [ROLES.RETAILER]: 'Retail shelf records and consumer-facing verification.',
  [ROLES.CONSUMER]: 'Scan a QR code to verify a jar and view its journey.',
  [ROLES.KVIC_OFFICER]: 'Cluster-level monitoring, scheme support and analytics.',
});

/**
 * Every role an administrator may assign, in the order the administration
 * screen lists them.
 *
 * This mirrors `ADMINISTRATION_ROLE_ORDER` on the backend, which is also the
 * order `GET /api/v1/roles` returns — so the picker an administrator uses and
 * the catalogue the API publishes cannot drift into different orders, and the
 * labels below are the backend's own `UserRole.label` values.
 */
export const ASSIGNABLE_ROLES = Object.freeze([
  ROLES.ADMIN,
  ROLES.BEEKEEPER,
  ROLES.CONSUMER,
  ROLES.KVIC_OFFICER,
  ROLES.COLLECTION_CENTER,
  ROLES.PROCESSOR,
  ROLES.LAB_TECHNICIAN,
  ROLES.PACKAGING_UNIT,
  ROLES.DISTRIBUTOR,
  ROLES.RETAILER,
]);

/**
 * Roles a visitor may pick on the public registration form.
 *
 * Restricted to the two roles that carry no platform privileges, matching the
 * backend's `UserRole.self_registrable()`. The remaining eight — including
 * supply-chain participants — are provisioned by an administrator once the
 * organisation has been verified, through Administration → Users → Create user.
 */
export const SELF_REGISTRABLE_ROLES = Object.freeze([ROLES.BEEKEEPER, ROLES.CONSUMER]);

/** Roles provisioned by an administrator rather than by open sign-up. */
export const PRIVILEGED_ROLES = Object.freeze(
  Object.values(ROLES).filter((role) => !SELF_REGISTRABLE_ROLES.includes(role)),
);

/**
 * What each role does, in one line — used by the create-user form and the role
 * change dialog so the choice is informed rather than an acronym.
 */
export const ROLE_ASSIGNMENT_HINTS = Object.freeze({
  [ROLES.ADMIN]: 'Full platform administration, including creating accounts and assigning roles.',
  [ROLES.BEEKEEPER]: 'Own apiary: hives, devices, harvests and the journey of their honey.',
  [ROLES.CONSUMER]: 'Verifies a jar and reads the journey of the honey inside it.',
  [ROLES.KVIC_OFFICER]: 'Cluster oversight: members, apiaries, harvests and quality outcomes.',
  [ROLES.COLLECTION_CENTER]: 'Intake and onward handover of honey from beekeepers.',
  [ROLES.PROCESSOR]: 'Processing runs: what went in, what came out and where it happened.',
  [ROLES.LAB_TECHNICIAN]: 'Samples, measurements and the tests that decide a batch.',
  [ROLES.PACKAGING_UNIT]: 'Packing approved batches into consumer units.',
  [ROLES.DISTRIBUTOR]: 'Movement of packed honey to the retail shelf.',
  [ROLES.RETAILER]: 'Retail shelf records and consumer-facing verification.',
});

/** Admin and KVIC officer — the roles that review beekeepers. */
export const VERIFIER_ROLES = Object.freeze([ROLES.ADMIN, ROLES.KVIC_OFFICER]);

/**
 * Display name per role — the backend's `UserRole.label` values, kept identical
 * on purpose so an account reads the same in the API, the audit log and here.
 * Written out rather than derived, because deriving "KVIC_OFFICER" produced
 * "Kvic Officer" and "COLLECTION_CENTER" produced "Collection Center".
 */
const ROLE_LABELS = Object.freeze({
  [ROLES.ADMIN]: 'Administrator',
  [ROLES.BEEKEEPER]: 'Beekeeper',
  [ROLES.CONSUMER]: 'Consumer',
  [ROLES.KVIC_OFFICER]: 'KVIC officer',
  [ROLES.COLLECTION_CENTER]: 'Collection centre',
  [ROLES.PROCESSOR]: 'Processor',
  [ROLES.LAB_TECHNICIAN]: 'Lab technician',
  [ROLES.PACKAGING_UNIT]: 'Packaging unit',
  [ROLES.DISTRIBUTOR]: 'Distributor',
  [ROLES.RETAILER]: 'Retailer',
});

export function roleLabel(role) {
  return ROLE_LABELS[role] || role || 'Unknown role';
}

export function homeRouteForRole(role) {
  return ROLE_HOME_ROUTES[role] || '/dashboard';
}

export function isSelfRegistrable(role) {
  return SELF_REGISTRABLE_ROLES.includes(role);
}

export function canVerifyBeekeepers(role) {
  return VERIFIER_ROLES.includes(role);
}
