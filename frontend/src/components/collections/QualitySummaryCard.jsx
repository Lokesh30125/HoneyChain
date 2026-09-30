import { Check, FlaskConical, X } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { unitLabel } from '@/constants/collection';
import { LAB_MESSAGES, LAB_PARAMETER_STATUS_META, LAB_RESULT_META, measurementText } from '@/constants/laboratory';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * The quality summary of a batch.
 *
 * Batch info, source, collection, processing and laboratory in one card, with the
 * parameter rows exactly as they were measured — "Moisture 17.4 % Pass",
 * "HMF … Not evaluated". Two rules are visible in the rendering:
 *
 * 1. Only recorded values are shown. A parameter with no measurement is absent
 *    from the table rather than filled with a plausible number.
 * 2. A parameter with no configured reference range reads *Not evaluated*, never
 *    "Pass" — the platform does not own a scientific standard, so it does not
 *    imply one.
 */

function Row({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

function ParameterRow({ result }) {
  const status = LAB_PARAMETER_STATUS_META[result.status] || LAB_PARAMETER_STATUS_META.NOT_EVALUATED;
  return (
    <tr data-parameter={result.parameter_code}>
      <td className="px-4 py-3">
        <span className="font-medium text-ink">{result.parameter_name}</span>
        <span className="ml-2 text-xs text-ink-muted">{result.parameter_code}</span>
      </td>
      <td className="px-4 py-3 text-ink">{measurementText(result)}</td>
      <td className="px-4 py-3 text-sm text-ink-soft">
        {result.reference_min === null && result.reference_max === null ? (
          <span className="text-ink-muted">No range configured</span>
        ) : (
          <span>
            {result.reference_min ?? '—'} – {result.reference_max ?? '—'}
            {result.reference_source ? (
              <span className="ml-1 text-xs text-ink-muted">({result.reference_source})</span>
            ) : null}
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <Badge variant={status.variant} size="sm">
          {status.label}
        </Badge>
      </td>
    </tr>
  );
}

export function QualitySummaryCard({ batch, loading = false }) {
  // The batch payload carries the *latest* processing run and the *latest*
  // laboratory test — each read from its own record, not copied onto the batch —
  // plus the counts of everything behind them. So the summary shows one run and
  // one test, and says how many more exist rather than implying they are all here.
  const latestRun = batch?.processing || null;
  const latestTest = batch?.laboratory || null;
  const results = Array.isArray(latestTest?.results) ? latestTest.results : [];
  const runCount = batch?.processing_count ?? (latestRun ? 1 : 0);
  const testCount = batch?.test_count ?? (latestTest ? 1 : 0);
  const otherTests = Math.max(testCount - (latestTest ? 1 : 0), 0);
  const unit = unitLabel(batch?.unit);

  return (
    <Card data-testid="quality-summary">
      <CardHeader
        title="Quality summary"
        description="The batch, where it came from, what was done to it, and what was measured in it."
        icon={<FlaskConical size={18} aria-hidden="true" />}
        action={
          latestTest ? (
            <Badge variant={(LAB_RESULT_META[latestTest.overall_result] || {}).variant || 'neutral'}>
              {(LAB_RESULT_META[latestTest.overall_result] || {}).label || latestTest.overall_result}
            </Badge>
          ) : null
        }
      />
      <CardBody className="space-y-5">
        {/* Batch info */}
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Batch information</h3>
          <dl className="mt-2 divide-y divide-sand-100">
            <Row label="Batch code">
              <span className="font-mono text-sm">{batch?.batch_code || '—'}</span>
            </Row>
            <Row label="Status">
              <Badge variant={(LAB_RESULT_META[latestTest?.overall_result] || {}).variant || 'info'} size="sm">
                {batch?.status_label || batch?.status || '—'}
              </Badge>
            </Row>
            <Row label="Quantity">
              {batch ? `${Number(batch.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}` : '—'}
            </Row>
            <Row label="Harvest date">{batch?.collection_date ? formatDate(batch.collection_date) : '—'}</Row>
          </dl>
        </section>

        {/* Where it came from */}
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Source</h3>
          <dl className="mt-2 divide-y divide-sand-100">
            <Row label="Beekeeper">
              {batch?.beekeeper_name || batch?.beekeeper_code || '—'}
            </Row>
            <Row label="Cluster">
              {batch?.cluster_code ? batch.cluster_name || batch.cluster_code : <span className="text-ink-muted">Not in a cluster</span>}
            </Row>
            <Row label="Source hives">{batch?.source_hive_count ?? '—'}</Row>
          </dl>
        </section>

        {/* The harvest behind it */}
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Collection</h3>
          <dl className="mt-2 divide-y divide-sand-100">
            <Row label="Collection code">
              <span className="font-mono text-sm">{batch?.collection?.collection_code || '—'}</span>
            </Row>
            <Row label="Recorded by">
              {batch?.collection?.beekeeper_name || batch?.beekeeper_name || '—'}
            </Row>
            <Row label="Harvested">
              {batch?.collection
                ? `${Number(batch.collection.total_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}`
                : '—'}
            </Row>
          </dl>
        </section>

        {/* What was done to it */}
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Processing</h3>
          {latestRun ? (
            <dl className="mt-2 divide-y divide-sand-100">
              <Row label="Run">
                <span className="font-mono text-sm">{latestRun.processing_code}</span>
                {runCount > 1 ? (
                  <span className="ml-2 text-xs text-ink-muted">{runCount} runs recorded on this batch</span>
                ) : null}
              </Row>
              <Row label="Type">{latestRun.processing_type_display || latestRun.processing_type_label || latestRun.processing_type}</Row>
              <Row label="Input">
                {latestRun.input_quantity === null || latestRun.input_quantity === undefined
                  ? 'Not recorded'
                  : `${Number(latestRun.input_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${latestRun.unit_label || unit}`}
              </Row>
              <Row label="Output">
                {latestRun.output_quantity === null || latestRun.output_quantity === undefined
                  ? 'Not recorded'
                  : `${Number(latestRun.output_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${latestRun.unit_label || unit}`}
              </Row>
              <Row label="Difference (measured)">
                {latestRun.loss_quantity === null || latestRun.loss_quantity === undefined ? (
                  <span className="text-ink-muted">—</span>
                ) : (
                  `${Number(latestRun.loss_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${latestRun.unit_label || unit}`
                )}
              </Row>
            </dl>
          ) : (
            <p className="mt-2 text-sm text-ink-muted">
              {PROCESSING_ABSENT}
            </p>
          )}
        </section>

        {/* What was measured */}
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Laboratory</h3>
          {latestTest ? (
            <div className="mt-2 space-y-3">
              <dl className="divide-y divide-sand-100">
                <Row label="Test code">
                  <span className="font-mono text-sm">{latestTest.test_code}</span>
                </Row>
                <Row label="Sample">
                  <span className="font-mono text-sm">{latestTest.sample_code}</span>
                  <span className="ml-2 text-xs text-ink-muted">
                    {Number(latestTest.sample_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}{' '}
                    {latestTest.sample_unit_label}
                  </span>
                </Row>
                <Row label="Laboratory">{latestTest.laboratory_name || latestTest.laboratory_code || '—'}</Row>
                <Row label="Test date">{formatDate(latestTest.test_date)}</Row>
                <Row label="Status">{latestTest.status_label || latestTest.status}</Row>
                {otherTests ? (
                  <Row label="Earlier tests">
                    {otherTests} earlier round(s) kept on this batch — a retest never replaces one
                  </Row>
                ) : null}
                <Row label="Result">
                  <Badge variant={(LAB_RESULT_META[latestTest.overall_result] || {}).variant || 'neutral'} size="sm">
                    {(LAB_RESULT_META[latestTest.overall_result] || {}).label || latestTest.overall_result}
                  </Badge>
                  {latestTest.is_override ? (
                    <span className="ml-2 text-xs text-ink-muted">authorised override</span>
                  ) : null}
                </Row>
                {latestTest.decided_at || latestTest.completed_at ? (
                  <Row label="Decided">{formatDateTime(latestTest.completed_at)}</Row>
                ) : null}
              </dl>

              {results.length ? (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-sand-200 text-sm">
                    <thead className="bg-sand-100/70">
                      <tr>
                        {['Parameter', 'Measured', 'Configured range', 'Outcome'].map((header) => (
                          <th
                            key={header}
                            scope="col"
                            className={`px-4 py-2 text-xs font-semibold uppercase tracking-wide text-ink-soft ${
                              header === 'Outcome' ? 'text-right' : 'text-left'
                            }`}
                          >
                            {header}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-sand-100">
                      {results.map((result) => (
                        <ParameterRow key={result.id} result={result} />
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="flex items-center gap-2 text-sm text-ink-muted">
                  <X size={14} aria-hidden="true" /> {LAB_MESSAGES.resultsEmpty}
                </p>
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm text-ink-muted">
              This batch has not been tested yet. {LAB_MESSAGES.resultsEmpty}
            </p>
          )}
        </section>

        {loading ? <p className="text-xs text-ink-muted">Loading batch information...</p> : null}
        <p className="flex items-start gap-1.5 text-xs text-ink-muted">
          <Check size={14} className="mt-0.5 flex-none" aria-hidden="true" />
          HoneyChain shows the values a laboratory recorded and the ranges it was given. It issues no
          purity certificate and asserts no regulatory standard of its own.
        </p>
      </CardBody>
    </Card>
  );
}

const PROCESSING_ABSENT =
  'No processing run has been recorded against this batch yet, so no input or output quantity exists for it.';

export default QualitySummaryCard;
