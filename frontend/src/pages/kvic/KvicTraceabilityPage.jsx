import { ROLES } from '@/constants/roles';
import TraceabilityPage from '@/pages/traceability/TraceabilityPage';

/** Traceability for the batches produced in the clusters an officer oversees. */
export default function KvicTraceabilityPage() {
  return <TraceabilityPage role={ROLES.KVIC_OFFICER} basePath="/kvic" />;
}
