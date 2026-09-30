import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { ProcessingWorkspace } from '@/components/processing/ProcessingWorkspace';
import { ROLES } from '@/constants/roles';

/**
 * Processing oversight for a KVIC officer.
 *
 * The same component the processor uses, in read-only mode and scoped by the API to
 * the clusters the officer oversees: identical rows, identical quantities, no
 * actions.
 */
export default function KvicProcessingPage({ view = 'runs' }) {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'KVIC', to: '/kvic' }, { label: 'Processing' }]} />
      <PageHeader
        title="Processing oversight"
        description="How the honey from your clusters was processed, with the quantities recorded by the operator."
      />
      <ProcessingWorkspace role={ROLES.KVIC_OFFICER} view={view} basePath="/kvic/processing" />
    </div>
  );
}
