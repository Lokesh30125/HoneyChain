import { Breadcrumb } from '@/components/common/Breadcrumb';
import { HiveRegistry } from '@/components/hives/HiveRegistry';

/**
 * `/kvic/hives` — hive registry for the cluster the officer oversees.
 *
 * Read-only on purpose: an officer inspects what beekeepers have registered and
 * how their devices are behaving. Editing and pairing stay with the beekeeper
 * who owns the hive, which is also what the API enforces (a KVIC session that
 * tried to write would be rejected server-side regardless of this screen).
 */
export default function KvicHivesPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC', to: '/kvic' }, { label: 'Hives' }]} />
      <HiveRegistry
        mode="oversight"
        title="Hive registry"
        description="Hives registered by the beekeepers you oversee, with their device and latest reading. Open a hive to see its detail and history."
        detailBasePath="/kvic/hives"
        emptyTitle="No hives in scope yet"
        emptyDescription="Hives appear here once the beekeepers you oversee register them."
      />
    </div>
  );
}
