import { ROLES } from '@/constants/roles';
import TraceabilityPage from '@/pages/traceability/TraceabilityPage';

/** Traceability for a beekeeper's own batches — including the laboratory outcome. */
export default function BeekeeperTraceabilityPage() {
  return <TraceabilityPage role={ROLES.BEEKEEPER} basePath="/beekeeper" />;
}
