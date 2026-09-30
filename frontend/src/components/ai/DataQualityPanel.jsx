import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { formatAge, formatCoverage, qualityMeta, sourceMeta } from '@/constants/ai';
import { formatDateTime } from '@/utils/format';

/**
 * What the analysis actually had to work with.
 *
 * This panel exists because an assessment is only as good as its inputs, and the
 * two facts a reader needs are *how much* telemetry there was and *where it came
 * from*. A `LIMITED` grade with a `SIMULATOR` source is a perfectly valid state
 * of the platform; hiding either one would make the score misleading.
 */

const QUALITY_TONE = { GOOD: 'success', LIMITED: 'warning', INSUFFICIENT: 'neutral' };

export function DataQualityPanel({ quality = null, source = null, sourceLabel = null, className = '' }) {
  if (!quality) return null;

  const meta = qualityMeta(quality.level);
  const origin = sourceMeta(source || quality.source);
  // The API's own label wins when it sent one: it is the wording the engine was
  // written with, and it stays correct if the vocabulary ever changes.
  const originLabel = sourceLabel || origin.label;
  const coverage = formatCoverage(quality.coverage);
  const age = formatAge(quality.newest_age_minutes);

  return (
    <div className={`space-y-3 ${className}`} data-testid="ai-data-quality">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={QUALITY_TONE[quality.level] || 'neutral'}>Data quality: {meta.label}</Badge>
        <Badge variant={origin.tone} size="sm">
          {originLabel}
        </Badge>
        {quality.is_stale ? (
          <Badge variant="warning" size="sm">
            Stale telemetry
          </Badge>
        ) : null}
        {quality.device_online === false ? (
          <Badge variant="danger" size="sm">
            Device {quality.device_status || 'offline'}
          </Badge>
        ) : null}
      </div>

      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Row label="Readings in window" value={quality.sample_count} />
        <Row label="History covered" value={`${(quality.covered_hours ?? 0).toFixed(1)} h`} />
        <Row
          label="Newest reading"
          value={quality.newest_reading_at ? formatDateTime(quality.newest_reading_at) : '—'}
        />
        <Row label="Age of newest reading" value={age ? `${age} ago` : '—'} />
        {coverage ? <Row label="Reporting cadence" value={coverage} /> : null}
        {quality.expected_samples ? (
          <Row label="Expected readings" value={`≈ ${quality.expected_samples}`} />
        ) : null}
      </dl>

      {quality.summary ? <p className="text-sm text-ink-soft">{quality.summary}</p> : null}

      {quality.issues?.length ? (
        <Alert variant={quality.level === 'GOOD' ? 'info' : 'warning'} title="What limited this analysis">
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {quality.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </Alert>
      ) : null}

      {quality.missing_sensors?.length ? (
        <p className="text-sm text-ink-muted">
          No readings for: {quality.missing_sensors.join(', ')}. Those checks were skipped rather
          than estimated.
        </p>
      ) : null}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-sand-200 py-1.5 last:border-b-0">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="font-medium text-ink">{value ?? '—'}</dd>
    </div>
  );
}

export default DataQualityPanel;
