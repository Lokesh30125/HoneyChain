import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/common/Breadcrumb';
import { PageHeader } from '@/components/common/PageHeader';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ProcessingRunPanel } from '@/components/processing/ProcessingRunPanel';
import { ProcessingRunTable } from '@/components/processing/ProcessingRunTable';
import { PROCESSING_MESSAGES } from '@/constants/processing';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import * as processingService from '@/services/processingService';
import { normaliseError } from '@/utils/errors';

/**
 * One processing run, with the batch's other runs beside it.
 *
 * Immutability is visible here rather than described: a completed run shows the
 * figures as recorded and no edit controls, and the history below lists every run
 * the batch carries. A correction is a new run, not a rewrite.
 */
export default function ProcessingRunDetailPage({ basePath = '/processor' }) {
  const { processingId } = useParams();
  const { user } = useAuth();
  const role = user?.role;
  const canWrite = role === ROLES.PROCESSOR || role === ROLES.ADMIN;

  const [history, setHistory] = useState([]);
  const [units, setUnits] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const runs = await processingService.getRunHistory(processingId);
      setHistory(runs);
      if (canWrite) {
        const payload = await processingService.listUnits();
        setUnits(payload.units);
      }
    } catch (caught) {
      setError(normaliseError(caught));
    }
  }, [processingId, canWrite]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: 'Processing', to: basePath },
          // Only the processor workspace has a separate runs list; elsewhere the
          // processing page itself is the list.
          ...(basePath === '/processor' ? [{ label: 'Processing runs', to: `${basePath}/runs` }] : []),
          { label: 'Run' },
        ]}
      />
      <PageHeader
        title="Processing run"
        description="What was done to the honey, and the quantities that were measured while it was done."
      />
      <ProcessingRunPanel
        processingId={processingId}
        canWrite={canWrite}
        units={units}
        onChanged={load}
      />
      <Card>
        <CardHeader
          title="This batch's processing history"
          description="Every run the batch carries, newest first. Nothing is overwritten when a run is corrected or repeated."
        />
        <CardBody>
          <ProcessingRunTable
            runs={history}
            loading={false}
            error={error}
            onRetry={load}
            detailPath={`${basePath}/runs`}
            emptyTitle={PROCESSING_MESSAGES.runsEmpty}
          />
        </CardBody>
      </Card>
    </div>
  );
}
