import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { BatchWorkspace } from '@/components/collections/BatchWorkspace';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

const COPY = {
  [ROLES.BEEKEEPER]: { crumb: 'Beekeeper', base: '/beekeeper' },
  [ROLES.KVIC_OFFICER]: { crumb: 'KVIC', base: '/kvic' },
  [ROLES.ADMIN]: { crumb: 'Admin', base: '/admin' },
  [ROLES.PROCESSOR]: { crumb: 'Processing', base: '/processor' },
};

/** Honey batches — the traceable units that completed harvests produced. */
export default function BatchesPage() {
  const { user } = useAuth();
  const role = user?.role || ROLES.BEEKEEPER;
  const copy = COPY[role] || COPY[ROLES.BEEKEEPER];

  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: copy.crumb, to: copy.base }, { label: 'Honey batches' }]} />
      <PageHeader
        title="Honey batches"
        description={
          role === ROLES.BEEKEEPER
            ? 'Every batch your harvests produced, with the hives behind it.'
            : 'Batches produced by the beekeepers in your scope, read-only.'
        }
      />
      <BatchWorkspace role={role} basePath={copy.base} />
    </div>
  );
}
