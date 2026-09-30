import { useCallback, useEffect, useState } from 'react';
import { UserPlus, X } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Select } from '@/components/ui/Select';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingState } from '@/components/common/LoadingState';
import { VerificationBadge } from '@/components/beekeepers/VerificationBadge';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as beekeeperService from '@/services/beekeeperService';
import * as clusterService from '@/services/clusterService';

/**
 * Cluster membership.
 *
 * Adding a member searches the beekeeper directory rather than asking for a
 * UUID: an officer knows the person, not the identifier. Removal clears the
 * membership and leaves the beekeeper record untouched.
 */
export function ClusterMembersModal({ open, cluster, onClose, onChanged }) {
  const toast = useToast();

  const [members, setMembers] = useState([]);
  const [meta, setMeta] = useState(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState('');
  const [saving, setSaving] = useState(false);

  const loadMembers = useCallback(async () => {
    if (!cluster) return;
    setLoading(true);
    setError(null);
    try {
      const { members: rows, meta: pageMeta } = await clusterService.listClusterMembers(cluster.id, {
        page,
        pageSize: 10,
      });
      setMembers(rows);
      setMeta(pageMeta);
    } catch (caught) {
      setError(normaliseError(caught));
    } finally {
      setLoading(false);
    }
  }, [cluster, page]);

  useEffect(() => {
    if (!open) return;
    setPage(1);
    setSelected('');
  }, [open, cluster]);

  useEffect(() => {
    if (open) loadMembers();
  }, [open, loadMembers]);

  // Candidates: beekeepers in the same district who are not in this cluster.
  useEffect(() => {
    if (!open || !cluster) return;
    let active = true;
    (async () => {
      try {
        const { beekeepers } = await beekeeperService.listBeekeepers({
          page: 1,
          pageSize: 50,
          district: cluster.district,
        });
        if (!active) return;
        setCandidates(
          beekeepers
            .filter((row) => row.cluster_id !== cluster.id)
            .map((row) => ({
              value: row.id,
              label: `${row.beekeeper_code} · ${row.name}`,
            })),
        );
      } catch {
        if (active) setCandidates([]);
      }
    })();
    return () => {
      active = false;
    };
  }, [open, cluster]);

  const addMember = async () => {
    if (!selected) {
      toast.warning('Choose a beekeeper to add first');
      return;
    }
    setSaving(true);
    try {
      await clusterService.addClusterMember(cluster.id, selected);
      toast.success('Beekeeper added to the cluster');
      setSelected('');
      await loadMembers();
      onChanged?.();
    } catch (caught) {
      toast.error('Could not add that beekeeper', normaliseError(caught).message);
    } finally {
      setSaving(false);
    }
  };

  const removeMember = async (beekeeperId) => {
    setSaving(true);
    try {
      await clusterService.removeClusterMember(cluster.id, beekeeperId);
      toast.success('Beekeeper removed from the cluster');
      await loadMembers();
      onChanged?.();
    } catch (caught) {
      toast.error('Could not remove that beekeeper', normaliseError(caught).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={cluster ? `Members of ${cluster.cluster_name}` : 'Cluster members'}
      description={cluster ? cluster.cluster_code : undefined}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Add a beekeeper"
            name="candidate"
            placeholder={candidates.length ? 'Choose a beekeeper' : 'No eligible beekeepers'}
            options={candidates}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            containerClassName="min-w-[16rem] flex-1"
            disabled={!candidates.length}
          />
          <Button
            onClick={addMember}
            loading={saving}
            leftIcon={<UserPlus size={15} />}
            disabled={!candidates.length}
          >
            Add
          </Button>
        </div>

        {error ? <Alert variant="danger">{error.message}</Alert> : null}

        {loading ? <LoadingState message="Loading members…" /> : null}

        {!loading && !members.length ? (
          <EmptyState
            title="No members yet"
            description="Assign beekeepers from the same district to build this cluster."
          />
        ) : null}

        {members.length ? (
          <ul className="divide-y divide-sand-200 rounded-lg border border-sand-200">
            {members.map((member) => (
              <li key={member.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">
                    {member.name} <span className="text-ink-muted">· {member.beekeeper_code}</span>
                  </p>
                  <p className="truncate text-xs text-ink-muted">
                    {[member.village, member.district].filter(Boolean).join(', ') || member.email}
                  </p>
                </div>
                <div className="flex flex-none items-center gap-2">
                  <VerificationBadge status={member.verification_status} size="sm" />
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Remove ${member.name} from the cluster`}
                    onClick={() => removeMember(member.id)}
                  >
                    <X size={15} aria-hidden="true" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}

        {meta && meta.total_pages > 1 ? (
          <div className="flex items-center justify-between">
            <p className="text-xs text-ink-muted">
              Page {meta.page} of {meta.total_pages} · {meta.total_items} member
              {meta.total_items === 1 ? '' : 's'}
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={meta.page <= 1 || loading}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={meta.page >= meta.total_pages || loading}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

export default ClusterMembersModal;
