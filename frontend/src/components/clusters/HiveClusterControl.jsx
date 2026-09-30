import { useCallback, useEffect, useState } from 'react';
import { Building2 } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Select } from '@/components/ui/Select';
import { Input } from '@/components/ui/Input';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as clusterService from '@/services/clusterService';
import * as hiveService from '@/services/hiveService';

/**
 * Staff-only placement of one hive into a cluster.
 *
 * A hive normally inherits its owner's cluster, and that is the path this screen
 * nudges people towards: the honest fix for a hive with no cluster is usually to
 * place the *beekeeper*. This control exists for the exceptions — a hive that
 * predates the relationship, or one that must sit in a different cluster from
 * its owner — and it says so, because quietly re-homing hives is exactly what
 * this phase is meant to stop.
 *
 * A beekeeper never sees this panel: their hive's cluster is derived from their
 * own membership, and the API refuses the call with 403 regardless.
 */
export function HiveClusterControl({ hive, onChanged }) {
  const toast = useToast();

  const [clusters, setClusters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selection, setSelection] = useState(hive?.cluster?.id || '');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const currentClusterId = hive?.cluster?.id || '';

  useEffect(() => {
    setSelection(currentClusterId);
  }, [currentClusterId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { clusters: rows } = await clusterService.listClusters({ page: 1, pageSize: 100 });
      setClusters(rows);
    } catch {
      // The selector is an aid; a failed lookup must not block reading the hive.
      setClusters([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const active = clusters.filter((cluster) => cluster.is_active);
  const options = [
    { value: '', label: 'Not in a cluster' },
    ...active.map((cluster) => ({
      value: cluster.id,
      label: `${cluster.cluster_code} — ${cluster.cluster_name}`,
    })),
    // An inactive cluster the hive currently sits in is still shown, so the
    // selector reflects reality instead of silently suggesting a change.
    ...clusters
      .filter((cluster) => !cluster.is_active && cluster.id === currentClusterId)
      .map((cluster) => ({
        value: cluster.id,
        label: `${cluster.cluster_code} — ${cluster.cluster_name} (inactive)`,
      })),
  ];

  const changed = selection !== currentClusterId;

  const submit = async () => {
    if (!changed) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await hiveService.setHiveCluster(
        hive.id,
        selection || null,
        reason.trim() || undefined,
      );
      toast.success(
        updated.cluster
          ? `Placed in ${updated.cluster.cluster_code}`
          : 'Placement cleared',
        updated.cluster
          ? 'The cluster view now includes this hive.'
          : 'The hive is unassigned again and listed for the officers to resolve.',
      );
      setReason('');
      onChanged?.(updated);
    } catch (caught) {
      const failure = normaliseError(caught);
      setError(failure);
      toast.error('Could not change the placement', failure.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Cluster placement"
        description="Where this hive sits in the KVIC structure. Staff only."
        action={<Building2 size={16} className="text-ink-muted" aria-hidden="true" />}
      />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-ink-muted">Currently:</span>
          {hive?.cluster ? (
            <Badge variant="forest" size="sm">
              {hive.cluster.cluster_code} — {hive.cluster.cluster_name}
            </Badge>
          ) : (
            <Badge variant="warning" size="sm">
              No cluster — owner not assigned
            </Badge>
          )}
        </div>

        {!hive?.cluster ? (
          <Alert variant="info" title="This hive has no cluster">
            A hive inherits its owner&apos;s cluster. If this beekeeper belongs to one, assigning them
            moves every hive they own — which is usually the better fix. Place a single hive here
            only when it genuinely differs from its owner&apos;s cluster.
          </Alert>
        ) : null}

        <Select
          name="hive-cluster"
          label="Cluster"
          options={options}
          value={selection}
          disabled={loading || saving}
          onChange={(event) => setSelection(event.target.value)}
          hint={
            loading
              ? 'Loading clusters…'
              : `${active.length} active cluster(s) available. Inactive clusters cannot receive hives.`
          }
        />

        <Input
          name="hive-cluster-reason"
          label="Reason (recorded in the audit log)"
          placeholder="e.g. Registered before the beekeeper joined the cluster"
          value={reason}
          maxLength={200}
          disabled={saving}
          onChange={(event) => setReason(event.target.value)}
        />

        {error ? (
          <Alert variant="danger" title="The change was refused">
            {error.message}
          </Alert>
        ) : null}

        <div className="flex items-center gap-2">
          <Button
            onClick={submit}
            disabled={!changed || saving}
            loading={saving}
            size="sm"
            variant="primary"
          >
            {selection ? 'Save placement' : 'Clear placement'}
          </Button>
          {changed ? (
            <Button variant="ghost" size="sm" onClick={() => setSelection(currentClusterId)} disabled={saving}>
              Reset
            </Button>
          ) : null}
        </div>

        <p className="text-xs text-ink-muted">
          The movement is written to the audit log with the previous and new cluster, so an officer
          can answer months later who moved a hive, when and why.
        </p>
      </CardBody>
    </Card>
  );
}

export default HiveClusterControl;
