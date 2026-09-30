import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Hash, Info, Package } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { BatchBlockchainSection } from '@/components/blockchain/BatchBlockchainSection';
import { BatchTimeline } from '@/components/collections/BatchTimeline';
import { QualitySummaryCard } from '@/components/collections/QualitySummaryCard';
import { BATCH_STATUS_META, COLLECTION_MESSAGES, unitLabel } from '@/constants/collection';
import * as batchService from '@/services/batchService';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * One honey batch, in four sections.
 *
 * **HONEY BATCH** — the batch identity and the life stage it is in. There is no
 * control to change it: this phase can only read ``COLLECTED``, and every later
 * status belongs to a module that does not exist yet.
 *
 * **SOURCE** — the hives the honey actually came from, each with its contribution,
 * read through the collection. Never a count, never a name without a hive behind it.
 *
 * **COLLECTION** — the harvest record this batch was created from, with a link
 * back to it so the batch and the harvest can be read as one story.
 *
 * **AI CONTEXT** — the estimated yield beside the harvested quantity, or an honest
 * "there was no estimate" when there was none.
 */

function Row({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-2">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

export function BatchDetailView({ batchId, collectionPath = null, hivePath = null }) {
  const [batch, setBatch] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setBatch(await batchService.getBatch(batchId));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId]);

  if (loading) return <LoadingState message={COLLECTION_MESSAGES.loadingCollections} />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!batch) return null;

  const unit = unitLabel(batch.unit);
  const ai = batch.ai_context || {};
  const predicted = ai.predicted_yield_kg === null || ai.predicted_yield_kg === undefined ? null : Number(ai.predicted_yield_kg);
  const difference = ai.difference_kg === null || ai.difference_kg === undefined ? null : Number(ai.difference_kg);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Honey batch"
          description="Created by completing a collection. Its identity and harvest figures are fixed."
          icon={<Package size={18} aria-hidden="true" />}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={(BATCH_STATUS_META[batch.status] || {}).variant || 'info'}>
                {batch.status_label || batch.status}
              </Badge>
              <Badge variant="neutral" size="sm">{batch.current_stage_label || batch.current_stage}</Badge>
            </div>
          }
        />
        <CardBody className="space-y-3">
          <dl className="divide-y divide-sand-100">
            <Row label="Batch code">
              <span className="font-mono text-sm">{batch.batch_code}</span>
            </Row>
            <Row label="Life stage">
              {batch.current_stage_label || batch.current_stage}
              {batch.status_label ? (
                <span className="ml-2 text-xs text-ink-muted">· {batch.status_label}</span>
              ) : null}
            </Row>
            <Row label="Harvest date">{formatDate(batch.collection_date)}</Row>
            <Row label="Quantity">
              {Number(batch.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
            </Row>
            <Row label="Source hives">{batch.source_hive_count}</Row>
            <Row label="Beekeeper">
              {batch.beekeeper_name || batch.beekeeper_code || '—'}
              {batch.beekeeper_code ? <span className="ml-2 text-xs text-ink-muted">{batch.beekeeper_code}</span> : null}
            </Row>
            <Row label="Cluster">
              {batch.cluster_code ? batch.cluster_name || batch.cluster_code : <span className="text-ink-muted">Not in a cluster</span>}
            </Row>
            <Row label="Created">{formatDateTime(batch.created_at)}</Row>
          </dl>
          <Alert variant="info" icon={<Info size={16} aria-hidden="true" />}>
            A batch identity is never rewritten. Processing and laboratory work is recorded against it
            by the people who do that work; a correction is a new run or a new test round, and every
            change is written to the audit log.
          </Alert>
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Source"
            description="The hives this honey came from, through the collection that recorded them."
          />
          <CardBody>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-sand-200 text-sm">
                <thead className="bg-sand-100/70">
                  <tr>
                    {['Hive', 'Contribution', 'Share'].map((header) => (
                      <th key={header} scope="col" className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-sand-100">
                  {batch.sources.map((source) => (
                    <tr key={source.hive_id}>
                      <td className="px-4 py-3">
                        {hivePath ? (
                          <Link className="font-medium text-forest-700 hover:underline" to={`${hivePath}/${source.hive_id}`}>
                            {source.hive_code}
                          </Link>
                        ) : (
                          <span className="font-medium text-ink">{source.hive_code}</span>
                        )}
                        {source.village ? <span className="ml-2 text-xs text-ink-muted">{source.village}</span> : null}
                      </td>
                      <td className="px-4 py-3">
                        {Number(source.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
                      </td>
                      <td className="px-4 py-3 text-ink-soft">
                        {source.contribution_share === null || source.contribution_share === undefined
                          ? '—'
                          : `${Math.round(Number(source.contribution_share) * 100)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Collection"
            description="The harvest this batch was created from — one batch per completed collection."
            icon={<Hash size={18} aria-hidden="true" />}
          />
          <CardBody className="space-y-3">
            <dl className="divide-y divide-sand-100">
              <Row label="Collection code">
                {collectionPath ? (
                  <Link className="font-medium text-forest-700 hover:underline" to={`${collectionPath}/${batch.collection.id}`}>
                    {batch.collection.collection_code}
                  </Link>
                ) : (
                  <span className="font-mono text-sm">{batch.collection.collection_code}</span>
                )}
              </Row>
              <Row label="Status">{batch.collection.status}</Row>
              <Row label="Harvest date">{formatDate(batch.collection.collection_date)}</Row>
              <Row label="Harvested quantity">
                {Number(batch.collection.total_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
              </Row>
              <Row label="Source hives">{batch.collection.source_hive_count}</Row>
              {batch.collection.completed_at ? (
                <Row label="Completed">{formatDateTime(batch.collection.completed_at)}</Row>
              ) : null}
              {batch.collection.notes ? <Row label="Notes">{batch.collection.notes}</Row> : null}
            </dl>
            <p className="text-xs text-ink-muted">
              The batch repeats these figures as a snapshot taken when the harvest was completed, so
              a later stage always reads what was harvested rather than a current guess.
            </p>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="AI Context"
          description="Estimated yield beside the quantity actually harvested. Context, not a quality score."
        />
        <CardBody className="space-y-4">
          <dl className="divide-y divide-sand-100">
            <Row label="Predicted yield (AI estimate)">
              {predicted === null ? <span className="text-ink-muted">—</span> : `${predicted.toLocaleString()} ${unit}`}
            </Row>
            <Row label="Actual harvested">
              {Number(batch.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
            </Row>
            <Row label="Difference (actual − predicted)">
              {difference === null ? (
                <span className="text-ink-muted">—</span>
              ) : (
                <span className={difference >= 0 ? 'text-forest-700' : 'text-red-600'}>
                  {difference > 0 ? '+' : ''}
                  {difference.toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
                </span>
              )}
            </Row>
          </dl>
          {batch.ai_context?.per_hive?.length ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-sand-200 text-sm">
                <thead className="bg-sand-100/70">
                  <tr>
                    {['Hive', 'Harvested', 'AI estimate'].map((header) => (
                      <th key={header} scope="col" className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-sand-100">
                  {batch.ai_context.per_hive.map((row) => (
                    <tr key={row.hive_id}>
                      <td className="px-4 py-3 font-medium text-ink">{row.hive_code}</td>
                      <td className="px-4 py-3">
                        {Number(row.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
                      </td>
                      <td className="px-4 py-3">
                        {row.ai_predicted_yield_kg === null || row.ai_predicted_yield_kg === undefined ? (
                          <span className="text-xs text-ink-muted">No estimate</span>
                        ) : (
                          `${Number(row.ai_predicted_yield_kg).toLocaleString()} kg`
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="text-xs text-ink-muted">{ai.note}</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Processing"
          description="What was done to this honey, and the quantities measured while it was done."
        />
        <CardBody>
          {batch.processing ? (
            <ul className="divide-y divide-sand-100">
              <li className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <span className="font-mono text-sm text-ink">{batch.processing.processing_code}</span>
                <span className="text-xs text-ink-muted">
                  {batch.processing.processing_type_display || batch.processing.processing_type_label || batch.processing.processing_type} ·{' '}
                  {batch.processing.input_quantity === null || batch.processing.input_quantity === undefined
                    ? 'input not recorded'
                    : Number(batch.processing.input_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })}
                  {' → '}
                  {batch.processing.output_quantity === null || batch.processing.output_quantity === undefined
                    ? 'output not recorded'
                    : `${Number(batch.processing.output_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${batch.processing.unit_label}`}
                  {batch.processing.loss_quantity !== null && batch.processing.loss_quantity !== undefined
                    ? ` · ${Number(batch.processing.loss_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${batch.processing.unit_label} less than the input`
                    : ''}
                </span>
                <Badge variant="neutral" size="sm">
                  {batch.processing.status_label || batch.processing.status}
                </Badge>
              </li>
              {batch.processing_count > 1 ? (
                <li className="py-2 text-xs text-ink-muted">
                  {batch.processing_count} runs are recorded against this batch; the latest is shown here.
                </li>
              ) : null}
            </ul>
          ) : (
            <p className="text-sm text-ink-muted">
              No processing run has been recorded against this batch yet, so no input or output
              quantity exists for it.
            </p>
          )}
        </CardBody>
      </Card>

      <QualitySummaryCard batch={batch} />

      <BatchTimeline stages={batch.timeline} />

      {/* The batch's own events, with their chain status — read from the
          traceability layer, which applies the same scope rule as this screen. */}
      <BatchBlockchainSection batchId={batch.id} />
    </div>
  );
}

export default BatchDetailView;
