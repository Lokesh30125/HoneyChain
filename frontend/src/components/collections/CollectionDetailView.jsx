import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, Hash, Info, Package, XCircle } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { CollectionAiContextCard, CollectionIotContextCard } from '@/components/collections/CollectionContextPanels';
import { COLLECTION_MESSAGES, COLLECTION_STATUS_META, unitLabel } from '@/constants/collection';
import * as collectionService from '@/services/collectionService';
import { normaliseError } from '@/utils/errors';
import { formatDate, formatDateTime } from '@/utils/format';

/**
 * One harvest, in full.
 *
 * Sections: the harvest itself, the source hives (one row each, with the quantity
 * measured at that hive), the AI Context and IoT Context panels, and the batch it
 * produced — or an explicit statement that it has not produced one yet.
 *
 * Actions are only offered when the API says they are available
 * (`can_edit` / `can_complete` / `can_cancel`), so a completed harvest shows no
 * buttons at all rather than buttons that would fail. Staff see the same record
 * read-only.
 */

function Row({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 py-2">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="text-sm font-medium text-ink">{children}</dd>
    </div>
  );
}

export function CollectionDetailView({ collectionId, batchPath = null, hivePath = null, onChanged }) {
  const [collection, setCollection] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setCollection(await collectionService.getCollection(collectionId));
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      // Always cleared: a spinner that never stops hides the empty state too, and
      // is the kind of bug that only shows up in a browser.
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectionId]);

  const run = async (action) => {
    setBusy(true);
    setActionError(null);
    try {
      const result = await action();
      setNotice(result?.notice || null);
      await load();
      if (onChanged) onChanged();
    } catch (caught) {
      setActionError(normaliseError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <LoadingState message={COLLECTION_MESSAGES.loadingCollections} />;
  if (error) return <ErrorState error={error} onRetry={load} />;
  if (!collection) return null;

  const statusMeta = COLLECTION_STATUS_META[collection.status] || { label: collection.status, variant: 'neutral', hint: '' };
  const unit = unitLabel(collection.unit);

  return (
    <div className="space-y-6">
      {notice ? <Alert variant="success" title={notice} onClose={() => setNotice(null)} /> : null}
      {actionError ? (
        <Alert variant="danger" title="That action could not be completed" onClose={() => setActionError(null)}>
          {actionError.message || String(actionError)}
        </Alert>
      ) : null}

      <Card>
        <CardHeader
          title={collection.collection_code}
          description={statusMeta.hint}
          icon={<Hash size={18} aria-hidden="true" />}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
              {collection.has_batch ? (
                batchPath ? (
                  <Button as={Link} to={`${batchPath}/${collection.batch_id}`} variant="secondary" size="sm" leftIcon={<Package size={14} aria-hidden="true" />}>
                    {collection.batch_code}
                  </Button>
                ) : (
                  <Badge variant="success" size="sm">{collection.batch_code}</Badge>
                )
              ) : null}
            </div>
          }
        />
        <CardBody className="space-y-4">
          <dl className="divide-y divide-sand-100">
            <Row label="Collection date">{formatDate(collection.collection_date)}</Row>
            <Row label="Actual harvested quantity">
              {Number(collection.total_quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
            </Row>
            <Row label="Source hives">
              <span className="flex flex-wrap justify-end gap-1">
                {collection.source_hive_codes.map((code) => (
                  <Badge key={code} variant="neutral" size="sm">
                    {code}
                  </Badge>
                ))}
              </span>
            </Row>
            <Row label="Beekeeper">
              {collection.beekeeper_name || collection.beekeeper_code || '—'}
              {collection.beekeeper_code ? (
                <span className="ml-2 text-xs text-ink-muted">{collection.beekeeper_code}</span>
              ) : null}
            </Row>
            <Row label="Cluster">
              {collection.cluster_code ? (
                <span>
                  {collection.cluster_name || collection.cluster_code}
                  {!collection.cluster_id ? null : null}
                </span>
              ) : (
                <span className="text-ink-muted">Not in a cluster</span>
              )}
            </Row>
            <Row label="Recorded">{formatDateTime(collection.created_at)}</Row>
            {collection.completed_at ? <Row label="Completed">{formatDateTime(collection.completed_at)}</Row> : null}
            {collection.cancelled_at ? <Row label="Cancelled">{formatDateTime(collection.cancelled_at)}</Row> : null}
            {collection.cancellation_reason ? <Row label="Reason">{collection.cancellation_reason}</Row> : null}
            {collection.notes ? <Row label="Notes">{collection.notes}</Row> : null}
          </dl>

          {collection.can_edit || collection.can_complete || collection.can_cancel ? (
            <div className="flex flex-col gap-2 border-t border-sand-100 pt-4 sm:flex-row sm:items-center sm:justify-end">
              <p className="mr-auto text-xs text-ink-muted">
                Completing creates the batch that carries this harvest through the supply chain.
              </p>
              <Button
                variant="secondary"
                size="sm"
                loading={busy}
                disabled={!collection.can_cancel}
                leftIcon={<XCircle size={14} aria-hidden="true" />}
                onClick={() =>
                  run(async () => {
                    await collectionService.cancelCollection(collection.id);
                    return { notice: 'Collection cancelled. It can no longer produce a batch.' };
                  })
                }
              >
                Cancel collection
              </Button>
              <Button
                size="sm"
                loading={busy}
                disabled={!collection.can_complete}
                leftIcon={<CheckCircle2 size={14} aria-hidden="true" />}
                onClick={() =>
                  run(async () => {
                    const { meta } = await collectionService.completeCollection(collection.id);
                    return {
                      notice:
                        meta?.batch_created === false
                          ? 'This harvest was already completed — its existing batch was returned.'
                          : `Collection completed. Batch ${meta?.batch?.batch_code || ''} created.`.trim(),
                    };
                  })
                }
              >
                Complete & create batch
              </Button>
            </div>
          ) : (
            <Alert variant="info" icon={<Info size={16} aria-hidden="true" />}>
              {collection.status === 'COMPLETED'
                ? 'This harvest is complete. Its date, hives, quantity, beekeeper and cluster are kept exactly as they were recorded.'
                : 'This harvest was cancelled and cannot be completed. Record a new collection for honey that was harvested.'}
            </Alert>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Source hives"
          description="Every hive that contributed, and what was taken from it. The total is the sum of these."
        />
        <CardBody>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-sand-200 text-sm">
              <thead className="bg-sand-100/70">
                <tr>
                  {['Hive', 'Quantity', 'AI estimate', 'Village'].map((header) => (
                    <th key={header} scope="col" className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-sand-100">
                {collection.sources.map((source) => (
                  <tr key={source.hive_id}>
                    <td className="px-4 py-3">
                      {hivePath ? (
                        <Link className="font-medium text-forest-700 hover:underline" to={`${hivePath}/${source.hive_id}`}>
                          {source.hive_code}
                        </Link>
                      ) : (
                        <span className="font-medium text-ink">{source.hive_code}</span>
                      )}
                      {source.hive_status ? (
                        <span className="ml-2 text-xs text-ink-muted">{source.hive_status}</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      {Number(source.quantity).toLocaleString(undefined, { maximumFractionDigits: 3 })} {unit}
                    </td>
                    <td className="px-4 py-3">
                      {source.ai_predicted_yield_kg === null || source.ai_predicted_yield_kg === undefined ? (
                        <span className="text-xs text-ink-muted">No estimate</span>
                      ) : (
                        `${Number(source.ai_predicted_yield_kg).toLocaleString()} kg`
                      )}
                    </td>
                    <td className="px-4 py-3 text-ink-soft">{source.village || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <CollectionAiContextCard context={collection.ai_context} unit={collection.unit} />
        <CollectionIotContextCard context={collection.iot_context} />
      </div>
    </div>
  );
}

export default CollectionDetailView;
