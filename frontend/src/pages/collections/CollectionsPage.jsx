import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { CollectionWorkspace } from '@/components/collections/CollectionWorkspace';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

/**
 * Harvest records, for every role that may read them.
 *
 * One page serves the beekeeper, the KVIC officer and the administrator because
 * the difference between them is *scope*, and scope is decided by the API. The
 * role only changes the routes the page links to and the copy on it.
 */
const COPY = {
  [ROLES.BEEKEEPER]: { crumb: 'Beekeeper', base: '/beekeeper' },
  [ROLES.KVIC_OFFICER]: { crumb: 'KVIC', base: '/kvic' },
  [ROLES.ADMIN]: { crumb: 'Admin', base: '/admin' },
  [ROLES.COLLECTION_CENTER]: { crumb: 'Collection centre', base: '/collection-center' },
};

export default function CollectionsPage() {
  const { user } = useAuth();
  const role = user?.role || ROLES.BEEKEEPER;
  const copy = COPY[role] || COPY[ROLES.BEEKEEPER];

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: copy.crumb, to: copy.base }, { label: 'Collections' }]} />
      <PageHeader
        title="Collections"
        description={
          role === ROLES.BEEKEEPER
            ? 'Record a harvest, then complete it to create the honey batch it becomes.'
            : role === ROLES.COLLECTION_CENTER
              ? 'Harvests received at the centre, read-only — each row is the beekeeper\u2019s own record, not a copy.'
              : 'Harvests recorded in your scope, read-only — each row belongs to its beekeeper.'
        }
      />
      <CollectionWorkspace role={role} basePath={copy.base} />
    </div>
  );
}
