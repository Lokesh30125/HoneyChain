import { useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { CollectionDetailView } from '@/components/collections/CollectionDetailView';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';

const COPY = {
  [ROLES.BEEKEEPER]: { crumb: 'Beekeeper', base: '/beekeeper' },
  [ROLES.KVIC_OFFICER]: { crumb: 'KVIC', base: '/kvic' },
  [ROLES.ADMIN]: { crumb: 'Admin', base: '/admin' },
  [ROLES.COLLECTION_CENTER]: { crumb: 'Collection centre', base: '/collection-center' },
};

/** One harvest, addressed by id. The same record whichever role opens it. */
export default function CollectionDetailPage() {
  const { collectionId } = useParams();
  const { user } = useAuth();
  const role = user?.role || ROLES.BEEKEEPER;
  const copy = COPY[role] || COPY[ROLES.BEEKEEPER];

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: copy.crumb, to: copy.base },
          { label: 'Collections', to: `${copy.base}/collections` },
          { label: 'Collection' },
        ]}
      />
      <PageHeader title="Collection" description="The harvest, its source hives and the batch it produced." />
      <CollectionDetailView
        collectionId={collectionId}
        batchPath={role === ROLES.COLLECTION_CENTER ? null : `${copy.base}/batches`}
        hivePath={role === ROLES.COLLECTION_CENTER ? null : `${copy.base}/hives`}
      />
    </div>
  );
}
