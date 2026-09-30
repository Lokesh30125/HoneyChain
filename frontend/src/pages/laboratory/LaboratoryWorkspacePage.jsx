import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { LaboratoryWorkspace } from '@/components/laboratory/LaboratoryWorkspace';
import { ROLES } from '@/constants/roles';

/**
 * The laboratory workspace page.
 *
 * One page serves the technician's views — overview, pending tests, the test list,
 * samples and completed tests — because they are the same records read through
 * different filters. The route decides which view opens.
 */
const VIEW_COPY = {
  overview: {
    title: 'Laboratory workspace',
    description: 'Samples waiting to be tested, the measurements recorded against them, and the tests they decided.',
  },
  awaiting: {
    title: 'Awaiting a sample',
    description:
      'Batches whose processing is complete and whose honey is waiting for a sample to be booked in.',
  },
  pending: {
    title: 'Pending lab tests',
    description:
      'Samples nobody is responsible for yet. They stay on this list until a technician is named, so unallocated work cannot fall off the bench.',
  },
  assigned: {
    title: 'Assigned lab tests',
    description:
      'Samples allocated to a named technician. Accept one to take it on, then record the measurements it needs.',
  },
  tests: {
    title: 'Laboratory tests',
    description: 'Every test opened against a batch, including retests — a retest adds a round, it never replaces one.',
  },
  completed: {
    title: 'Completed tests',
    description: 'Closed tests with the outcome the platform computed from the recorded values.',
  },
  held: {
    title: 'On hold',
    description:
      'Tests the laboratory closed without deciding — a value was missing, a reading was disputed, the honey needs re-sampling, or the analysis flagged something. The measurements and the reason are kept, the batch cannot be packed while it is held, and a further test releases it.',
  },
  samples: {
    title: 'Samples',
    description: 'Every sample taken, with the batch it came from and the test it belongs to.',
  },
};

export default function LaboratoryWorkspacePage({ view = 'overview' }) {
  const copy = VIEW_COPY[view] || VIEW_COPY.overview;
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: 'Laboratory', to: '/laboratory' }, { label: copy.title }]} />
      <PageHeader title={copy.title} description={copy.description} />
      <LaboratoryWorkspace role={ROLES.LAB_TECHNICIAN} view={view} />
    </div>
  );
}
