import { Breadcrumb } from '@/components/common/Breadcrumb';
import { HiveRegistry } from '@/components/hives/HiveRegistry';

/**
 * `/admin/hives` — platform-wide hive registry.
 *
 * Read-only oversight: the registry is the beekeeper's own record, and an
 * administrator inspects it rather than editing someone's apiary from here.
 */
export default function AdminHivesPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Administration', to: '/admin' }, { label: 'Hives' }]} />
      <HiveRegistry
        mode="oversight"
        title="Hive registry"
        description="Every hive on the platform, with its owner's device and latest reading. Use the filters to narrow by district or status."
        detailBasePath="/admin/hives"
        emptyTitle="No hives registered yet"
        emptyDescription="Hives appear here as soon as beekeepers register them."
      />
    </div>
  );
}
