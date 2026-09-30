import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { ProcessingWorkspace } from '@/components/processing/ProcessingWorkspace';
import { ROLES } from '@/constants/roles';

/** The processing workspace: the queue, the runs, and the units the work happens in. */
const VIEW_COPY = {
  overview: {
    title: 'Processing workspace',
    description: 'Batches waiting to be processed, the quantities measured in and out, and what is ready for the laboratory.',
  },
  awaiting: { title: 'Collected batches', description: 'Collected batches in your scope, waiting for a run.' },
  pending: {
    title: 'Pending batches',
    description:
      'Open runs nobody is responsible for yet, and collected batches with no run at all. Take one on, or allocate it to a processor.',
  },
  assigned: {
    title: 'Assigned batches',
    description:
      'Work allocated to a named processor. Accept it to take it on, then start it when the honey is actually being processed.',
  },
  processing: {
    title: 'Processing',
    description: 'Runs under way, with the quantities recorded so far.',
  },
  completed: {
    title: 'Completed processing',
    description:
      'Runs that finished: the measured input and output, and the batch that left for the laboratory on the same record.',
  },
  history: {
    title: 'Processing history',
    description:
      'Every run recorded against a batch, newest first, including cancelled ones — history is kept, never deleted.',
  },
  runs: { title: 'Processing runs', description: 'Every run with the quantities actually recorded on it.' },
  units: { title: 'Processing units', description: 'The facilities runs are recorded against.' },
};

export default function ProcessorWorkspacePage({ view = 'overview' }) {
  const copy = VIEW_COPY[view] || VIEW_COPY.overview;
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Processing', to: '/processor' }, { label: copy.title }]} />
      <PageHeader title={copy.title} description={copy.description} />
      <ProcessingWorkspace role={ROLES.PROCESSOR} view={view} basePath="/processor" />
    </div>
  );
}
