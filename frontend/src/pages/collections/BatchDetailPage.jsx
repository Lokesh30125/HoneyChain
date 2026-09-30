import { useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { BatchDetailView } from '@/components/collections/BatchDetailView';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

const COPY = {
  [ROLES.BEEKEEPER]: { crumb: 'Beekeeper', base: '/beekeeper' },
  [ROLES.KVIC_OFFICER]: { crumb: 'KVIC', base: '/kvic' },
  [ROLES.ADMIN]: { crumb: 'Admin', base: '/admin' },
  [ROLES.PROCESSOR]: { crumb: 'Processing', base: '/processor' },
};

/** One batch: identity, source hives, the collection behind it, AI context, timeline. */
export default function BatchDetailPage() {
  const { batchId } = useParams();
  const { user } = useAuth();
  const role = user?.role || ROLES.BEEKEEPER;
  const copy = COPY[role] || COPY[ROLES.BEEKEEPER];

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: copy.crumb, to: copy.base },
          { label: 'Honey batches', to: `${copy.base}/batches` },
          { label: 'Batch' },
        ]}
      />
      <PageHeader title="Honey batch" description="The batch, where its honey came from, and how far it has travelled." />
      <BatchDetailView
        batchId={batchId}
        collectionPath={`${copy.base}/collections`}
        hivePath={`${copy.base}/hives`}
      />
    </div>
  );
}
