import { AlertTriangle, CheckCircle2, Clock, Package, Sprout, XCircle } from 'lucide-react';

import { StatCard } from '@/components/common/StatCard';

/**
 * Counters for the collection workspace.
 *
 * Every number is counted from stored rows by the API — nothing here derives a
 * figure the database does not hold, and totals are reported **per unit** rather
 * than added together: kilograms and grams are both mass, but a total that mixed
 * them would be a conversion the beekeeper never made.
 */

/** Render a `{ KG: 12.5, GRAM: 300 }` totals map as "12.5 kg · 300 g". */
export function formatTotals(totals = {}) {
  const parts = Object.entries(totals)
    .filter(([, value]) => Number(value) > 0)
    .map(([unit, value]) => `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit === 'GRAM' ? 'g' : 'kg'}`);
  return parts.length ? parts.join(' · ') : '—';
}

export function CollectionSummaryCards({ summary, loading = false }) {
  const totals = summary?.harvested_totals || {};
  const open = summary?.open_quantity || {};

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <StatCard
        label="Total collections"
        value={summary?.total ?? 0}
        helper="Every harvest on record"
        icon={<Sprout size={16} aria-hidden="true" />}
        tone="honey"
        loading={loading}
      />
      <StatCard
        label="Planned"
        value={summary?.planned ?? 0}
        helper="Scheduled, not harvested yet"
        icon={<Clock size={16} aria-hidden="true" />}
        loading={loading}
      />
      <StatCard
        label="In progress"
        value={summary?.in_progress ?? 0}
        helper="Harvesting under way"
        icon={<AlertTriangle size={16} aria-hidden="true" />}
        loading={loading}
      />
      <StatCard
        label="Completed"
        value={summary?.completed ?? 0}
        helper={formatTotals(totals) === '—' ? 'Nothing harvested yet' : `Harvested: ${formatTotals(totals)}`}
        icon={<CheckCircle2 size={16} aria-hidden="true" />}
        tone="forest"
        loading={loading}
      />
      <StatCard
        label="Cancelled"
        value={summary?.cancelled ?? 0}
        helper="Harvests that did not happen"
        icon={<XCircle size={16} aria-hidden="true" />}
        loading={loading}
      />
      <StatCard
        label="Batches created"
        value={summary?.batches_created ?? 0}
        helper={
          Object.keys(open).length ? `Open records: ${formatTotals(open)}` : 'One batch per completed harvest'
        }
        icon={<Package size={16} aria-hidden="true" />}
        loading={loading}
      />
    </div>
  );
}

export default CollectionSummaryCards;
