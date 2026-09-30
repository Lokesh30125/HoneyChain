import { Activity, Brain, Info } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { unitLabel } from '@/constants/collection';
import { formatDateTime } from '@/utils/format';

/**
 * The two contexts that sit *beside* a harvest — and never inside it.
 *
 * **AI Context** shows the yield the engine estimated for the source hives next to
 * the quantity the beekeeper actually weighed. The difference is reported as a
 * comparison for this one harvest; it is not presented as model accuracy, which a
 * single harvest cannot establish.
 *
 * **IoT Context** shows the most recent sensor readings from the source hives.
 * Hive weight contains the box, the frames and the bees, and this platform has no
 * validated hive-weight-to-honey rule, so no honey figure is derived from it. The
 * panel says exactly that, and labels a simulated feed as simulated.
 *
 * When there is nothing to show, both panels say so — they never render a zero
 * that could be mistaken for a measurement.
 */

function DifferenceRow({ label, value, unit, tone = 'default' }) {
  const toneClass =
    tone === 'positive' ? 'text-forest-700' : tone === 'negative' ? 'text-red-600' : 'text-ink';
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className={`text-sm font-medium ${toneClass}`}>
        {value === null || value === undefined
          ? '—'
          : `${value > 0 ? '+' : ''}${Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 })} ${unit}`}
      </dd>
    </div>
  );
}

export function CollectionAiContextCard({ context, unit = 'KG' }) {
  if (!context) return null;
  const unitText = unitLabel(unit);
  const predicted = context.predicted_yield_kg === null || context.predicted_yield_kg === undefined
    ? null
    : Number(context.predicted_yield_kg);
  const actual = context.actual_quantity === null || context.actual_quantity === undefined
    ? null
    : Number(context.actual_quantity);
  const difference = context.difference_kg === null || context.difference_kg === undefined
    ? null
    : Number(context.difference_kg);

  return (
    <Card>
      <CardHeader
        title="AI Context"
        description="The yield the AI estimated for these hives, kept next to what was actually harvested."
        icon={<Brain size={18} aria-hidden="true" />}
      />
      <CardBody className="space-y-4">
        <dl className="space-y-2">
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-sm text-ink-muted">Predicted yield (AI estimate)</dt>
            <dd className="text-sm font-medium text-ink">
              {predicted === null ? '—' : `${predicted.toLocaleString()} ${unitText}`}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-sm text-ink-muted">Actual harvested</dt>
            <dd className="text-sm font-medium text-ink">
              {actual === null ? '—' : `${actual.toLocaleString()} ${unitText}`}
            </dd>
          </div>
          <DifferenceRow
            label="Difference (actual − predicted)"
            value={difference}
            unit={unitText}
            tone={difference === null ? 'default' : difference >= 0 ? 'positive' : 'negative'}
          />
        </dl>

        {predicted === null ? (
          <Alert variant="info" icon={<Info size={16} aria-hidden="true" />}>
            {context.note ||
              'No AI yield estimate existed for the source hives when this harvest was recorded.'}
          </Alert>
        ) : (
          <p className="text-xs text-ink-muted">
            {context.note}
            {context.prediction_hive_count
              ? ` Estimate covered ${context.prediction_hive_count} of the source hives.`
              : ''}
            {context.captured_at ? ` Captured ${formatDateTime(context.captured_at)}.` : ''}
          </p>
        )}
      </CardBody>
    </Card>
  );
}

export function CollectionIotContextCard({ context }) {
  if (!context) return null;

  return (
    <Card>
      <CardHeader
        title="IoT Context"
        description="What the sensors reported around this harvest. Not a honey measurement."
        icon={<Activity size={18} aria-hidden="true" />}
      />
      <CardBody className="space-y-4">
        {context.has_data ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {context.hive_code ? (
                <Badge variant="neutral" size="sm">
                  {context.hive_code}
                </Badge>
              ) : null}
              {context.source ? (
                <Badge variant={context.source === 'SIMULATOR' ? 'warning' : 'info'} size="sm">
                  {context.source_label || context.source}
                </Badge>
              ) : null}
              {context.recorded_at ? (
                <span className="text-xs text-ink-muted">{formatDateTime(context.recorded_at)}</span>
              ) : null}
            </div>
            <dl className="grid gap-3 sm:grid-cols-2">
              {[
                ['Hive weight', context.weight, 'kg'],
                ['Temperature', context.temperature, '°C'],
                ['Humidity', context.humidity, '%'],
                ['Vibration', context.vibration, ''],
                ['Acoustic level', context.acoustic_level, 'dB'],
              ]
                .filter(([, value]) => value !== null && value !== undefined)
                .map(([label, value, suffix]) => (
                  <div key={label} className="rounded-lg bg-sand-50 px-3 py-2">
                    <dt className="text-xs text-ink-muted">{label}</dt>
                    <dd className="text-sm font-medium text-ink">
                      {Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      {suffix ? ` ${suffix}` : ''}
                    </dd>
                  </div>
                ))}
            </dl>
            <p className="text-xs text-ink-muted">{context.note}</p>
          </>
        ) : (
          <Alert variant="info" icon={<Info size={16} aria-hidden="true" />}>
            No sensor readings are stored for the source hives, so there is no IoT context for this
            harvest.
          </Alert>
        )}
      </CardBody>
    </Card>
  );
}

export default CollectionAiContextCard;
