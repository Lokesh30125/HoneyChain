import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { Alert } from '@/components/ui/Alert';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { PageHeader } from '@/components/common/PageHeader';
import { PackagingRunPanel } from '@/components/packaging/PackagingRunPanel';
import { TraceabilityChain } from '@/components/common/TraceabilityChain';
import { PACKAGING_MESSAGES } from '@/constants/packaging';
import { ROLES } from '@/constants/roles';
import { useAuth } from '@/hooks/useAuth';
import * as packagingService from '@/services/packagingService';
import { normaliseError } from '@/utils/errors';

/**
 * Packaging information — one packaging record in full.
 *
 * Everything the run holds (its code, the batch it packed, the unit, who packed it,
 * when, into what, how much, how many packages, the quantities either side of it
 * and its notes) plus the chain the honey travelled to get there: collection →
 * batch → processing → laboratory verdict → this packaging run → the package codes
 * it issued.
 *
 * The chain is the *same* payload the batch screen and the package register read,
 * so a reader following the honey from any direction arrives at identical rows.
 * Nothing is editable here: a correction is a new run, never a rewrite of history.
 */
export default function PackagingInformationPage({ basePath = '/packaging' }) {
  const { packagingId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const role = user?.role;

  const [run, setRun] = useState(null);
  const [packages, setPackages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const detail = await packagingService.getPackaging(packagingId);
      setRun(detail);
      // The detail carries a first page of packages; the register is asked for the
      // full set so "every package from this run" means every one of them.
      if (detail?.batch_id) {
        const payload = await packagingService.listPackagesForBatch(detail.batch_id, {
          pageSize: 100,
        });
        setPackages((payload.packages || []).filter((row) => row.packaging_id === packagingId));
      }
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [packagingId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: 'Packaging', to: basePath },
          { label: 'Packaging runs', to: `${basePath}/runs` },
          { label: run?.packaging_code || 'Packaging record' },
        ]}
      />
      <PageHeader
        title="Packaging information"
        description="One packaging record with every field it holds, and the journey the honey made to reach it."
      />

      {error ? <Alert variant={error.status === 404 ? 'warning' : 'error'}>{error.message}</Alert> : null}

      {run ? (
        <>
          <PackagingRunPanel
            run={run}
            packages={packages}
            packagesLoading={loading}
            onOpenPackage={(row) => navigate(`${basePath}/packages/${row.id}`)}
          />
          <TraceabilityChain
            nodes={run.traceability || []}
            title="Collection → Batch → Processing → Laboratory → Packaging → Packages"
            description="Read from the records themselves: the harvest, the batch it became, the processing output the laboratory approved, this packaging run and the package codes it issued."
          />
        </>
      ) : null}

      {!run && !error ? (
        <Card>
          <CardHeader title="Packaging record" description={PACKAGING_MESSAGES.loadFailed} />
          <CardBody className="text-sm text-ink-soft">{loading ? 'Loading…' : ''}</CardBody>
        </Card>
      ) : null}

      {role && role !== ROLES.PACKAGING_UNIT && role !== ROLES.ADMIN ? (
        <Alert variant="info">This screen is read-only for your role.</Alert>
      ) : null}
    </div>
  );
}
