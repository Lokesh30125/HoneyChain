import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { PackageRegisterTable } from '@/components/packaging/PackageRegisterTable';
import { PACKAGING_STATUS_META, PACKAGING_TYPE_LABELS } from '@/constants/packaging';
import { formatDate, formatDateTime, formatNumber } from '@/utils/format';

/**
 * One packaging run, in full.
 *
 * The quantities are shown as four separate facts rather than one number that
 * might be mistaken for another: what the laboratory approved, what has been
 * packed on this batch in total, what this run packed, and what is left. The
 * collection quantity is displayed beside them for reference and is never editable
 * — the harvest is what it is, whatever happens downstream.
 *
 * Read-only by design: the actions live in the table that opened the panel, so
 * there is exactly one place that can move a run's state.
 */

function Fact({ label, value, hint = null }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-sm text-ink">{value ?? '—'}</p>
      {hint ? <p className="mt-0.5 text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );
}

export function PackagingRunPanel({ run, packages = [], packagesLoading = false, onOpenPackage = null }) {
  if (!run) return null;

  const statusMeta = PACKAGING_STATUS_META[run.status] || { label: run.status_label, variant: 'neutral' };
  const quantities = run.quantities || {};
  const unit = run.unit_label || '';

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={run.packaging_code}
          description={`${run.batch_code} · ${PACKAGING_TYPE_LABELS[run.packaging_type] || run.packaging_type}`}
          icon={<Badge variant={statusMeta.variant}>{run.status_label || statusMeta.label}</Badge>}
        />
        <CardBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Fact label="Packaging unit" value={run.packaging_unit_name || '—'} hint={run.packaging_unit_code} />
          <Fact label="Packed by" value={run.packaged_by_name || '—'} />
          <Fact label="Packaging date" value={formatDate(run.packaging_date)} />
          <Fact
            label="Approved by the laboratory"
            value={`${formatNumber(quantities.approved_quantity)} ${unit}`}
            hint="The measured output of the completed processing run."
          />
          <Fact
            label="Packed on this batch"
            value={`${formatNumber(quantities.packaged_quantity)} ${unit}`}
            hint="All completed runs against this batch, including this one."
          />
          <Fact
            label="Left to pack"
            value={`${formatNumber(quantities.remaining_quantity)} ${unit}`}
            hint="Approved minus packed. Never negative."
          />
          <Fact
            label="This run"
            value={
              run.packaged_quantity
                ? `${formatNumber(run.packaged_quantity)} ${unit}`
                : 'Not recorded yet'
            }
            hint={
              run.number_of_packages
                ? `${run.number_of_packages} × ${formatNumber(run.package_size)} ${unit}`
                : 'Recorded when the run is completed.'
            }
          />
          <Fact
            label="Collection quantity"
            value={
              quantities.collection_quantity
                ? `${formatNumber(quantities.collection_quantity)} ${unit}`
                : '—'
            }
            hint="The harvest itself — read-only, and never changed by packaging."
          />
          <Fact
            label="Timeline"
            value={run.start_time ? `Started ${formatDateTime(run.start_time)}` : 'Not started'}
            hint={run.completion_time ? `Completed ${formatDateTime(run.completion_time)}` : null}
          />
          {run.notes ? <Fact label="Notes" value={run.notes} /> : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Packages from this run"
          description={
            run.package_count
              ? `${run.package_count} package(s), each with its own stable code.`
              : 'No package exists until the run is completed.'
          }
        />
        <PackageRegisterTable
          packages={packages}
          loading={packagesLoading}
          onOpen={onOpenPackage}
          showBatch={false}
          emptyTitle="No packages yet"
          emptyDescription="Completing the run fills the packages and issues their codes."
        />
      </Card>

      {run.traceability?.length ? (
        <Card>
          <CardHeader
            title="Where this honey came from"
            description="The same chain the batch, the package and the shipment show."
          />
          <CardBody className="text-sm text-ink-soft">
            <ul className="space-y-2">
              {run.traceability.map((node) => (
                <li key={`${node.kind}-${node.identifier}`} className="flex flex-wrap gap-2">
                  <span className="text-ink-muted">{node.label}:</span>
                  <span className="font-mono text-xs text-ink">{node.identifier}</span>
                  {node.detail ? <span className="text-xs text-ink-muted">{node.detail}</span> : null}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      ) : null}
    </div>
  );
}

export default PackagingRunPanel;
