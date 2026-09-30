import { Badge } from '@/components/ui/Badge';
import { READING_SOURCE_LABELS, SENSOR_TYPES } from '@/constants/hive';
import { formatDateTime } from '@/utils/format';

/**
 * The newest values the platform holds, one tile per sensor.
 *
 * Used wherever "what is happening right now" is shown. A sensor with no stored
 * value renders "No data" rather than a zero, and the source of the reading is
 * always spelled out — so simulator and manually entered values can never be
 * mistaken for a hardware measurement.
 */
export function LatestValuesStrip({ reading = null, sensors = SENSOR_TYPES, emptyMessage }) {
  const hasData = Boolean(reading);

  if (!hasData) {
    return (
      <div className="rounded-lg border border-dashed border-sand-300 bg-sand-50/60 px-4 py-6 text-center">
        <p className="text-sm font-medium text-ink">No telemetry data available yet</p>
        <p className="mx-auto mt-1 max-w-md text-xs text-ink-muted">
          {emptyMessage ||
            'Once a paired device sends its first packet, its temperature, humidity, weight, vibration and acoustic readings appear here.'}
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        <Badge variant={reading.source === 'REAL_DEVICE' ? 'success' : 'warning'} size="sm">
          {READING_SOURCE_LABELS[reading.source] || reading.source}
        </Badge>
        <span>{formatDateTime(reading.timestamp)}</span>
        {reading.source === 'SIMULATOR' ? (
          <span>· produced by the development simulator, not hardware</span>
        ) : null}
      </div>

      <dl className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {sensors.map((sensor) => {
          const value = reading[sensor.readingKey];
          return (
            <div key={sensor.value} className="rounded-lg border border-sand-200 bg-sand-50/60 px-3 py-2">
              <dt className="text-xs text-ink-muted">{sensor.label}</dt>
              <dd className="mt-0.5 text-sm font-semibold text-ink">
                {value === null || value === undefined
                  ? 'No data'
                  : `${Number(value).toFixed(sensor.precision)} ${sensor.unit}`}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

export default LatestValuesStrip;
