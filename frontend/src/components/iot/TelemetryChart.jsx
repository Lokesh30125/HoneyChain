import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Activity, RefreshCw } from 'lucide-react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { SkeletonBlock } from '@/components/common/LoadingState';
import {
  CONFIGURABLE_SENSOR_TYPES,
  describeSourceMix,
  includesSimulatedData,
  READING_SOURCE_LABELS,
  sensorMeta,
  TELEMETRY_RANGES,
} from '@/constants/hive';
import { normaliseError } from '@/utils/errors';
import { formatDateTime } from '@/utils/format';
import * as iotService from '@/services/iotService';

/**
 * Sensor history for one hive, drawn with Recharts.
 *
 * What this chart does and does not do matters:
 *
 *  - it plots what was stored, averaged into buckets when the API says so, and
 *    labels the axis with the bucket interval it was given;
 *  - it never claims a reading is healthy or unhealthy — the lines are values,
 *    not verdicts;
 *  - if any point came from the simulator or a manual entry it says so, in the
 *    legend and in a notice, so simulated data can never be mistaken for
 *    hardware data.
 */

const COLORS = {
  temperature: '#b45309',
  humidity: '#0369a1',
  weight: '#15803d',
  vibration: '#7c3aed',
  acoustic_level: '#be123c',
  battery_level: '#475569',
  signal_strength: '#64748b',
};

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload || {};
  return (
    <div className="rounded-lg border border-sand-300 bg-white p-3 text-xs shadow-card">
      <p className="font-medium text-ink">{formatDateTime(label)}</p>
      {point.samples ? (
        <p className="text-ink-muted">{point.samples} reading(s) averaged</p>
      ) : null}
      <ul className="mt-1.5 space-y-0.5">
        {payload.map((entry) => {
          const meta = sensorMeta(entry.dataKey);
          return (
            <li key={entry.dataKey} className="flex items-center justify-between gap-3">
              <span className="text-ink-muted">{meta?.label || entry.dataKey}</span>
              <span className="font-medium text-ink">
                {entry.value === null || entry.value === undefined
                  ? '—'
                  : `${Number(entry.value).toFixed(meta?.precision ?? 2)}${meta?.unit ? ` ${meta.unit}` : ''}`}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-1 text-[11px] text-ink-muted">
        {READING_SOURCE_LABELS[point.source] || point.source || 'Source not recorded'}
      </p>
    </div>
  );
}

export function TelemetryChart({ hiveId, hiveCode, defaultDeviceId = null, height = 280 }) {
  const [rangeKey, setRangeKey] = useState('24h');
  const [sensorType, setSensorType] = useState('');
  const [series, setSeries] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!hiveId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await iotService.getHistory(hiveId, {
        rangeKey,
        sensorType: sensorType || undefined,
      });
      setSeries(data);
    } catch (caught) {
      setError(normaliseError(caught));
      setSeries(null);
    } finally {
      setLoading(false);
    }
  }, [hiveId, rangeKey, sensorType]);

  useEffect(() => {
    load();
  }, [load]);

  const plottedKeys = useMemo(() => {
    const points = series?.points || [];
    if (!points.length) return [];
    const candidates = sensorType
      ? (sensorMeta(sensorType)?.readingKey ? [sensorMeta(sensorType).readingKey] : [])
      : CONFIGURABLE_SENSOR_TYPES.map((sensor) => sensor.readingKey);
    return candidates.filter((key) => points.some((point) => point[key] !== null && point[key] !== undefined));
  }, [series, sensorType]);

  const simulated = includesSimulatedData(series?.source_mix);
  const sourceSummary = describeSourceMix(series?.source_mix);

  return (
    <section className="rounded-card border border-sand-300 bg-white p-4 shadow-card">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
            <Activity size={17} aria-hidden="true" />
            Sensor history
            {hiveCode ? <span className="text-sm font-normal text-ink-muted">· {hiveCode}</span> : null}
          </h2>
          <p className="mt-0.5 text-xs text-ink-muted">
            {series?.interval
              ? `Averaged into ${series.interval} buckets to keep the chart readable.`
              : 'Raw readings as stored.'}
            {defaultDeviceId ? ` Device ${defaultDeviceId}.` : ''}
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <Select
            name="telemetry-range"
            aria-label="Time range"
            options={TELEMETRY_RANGES}
            value={rangeKey}
            onChange={(event) => setRangeKey(event.target.value)}
            containerClassName="w-40"
          />
          <Select
            name="telemetry-sensor"
            aria-label="Sensor"
            options={[
              { value: '', label: 'All sensors' },
              ...CONFIGURABLE_SENSOR_TYPES.map((sensor) => ({
                value: sensor.value,
                label: `${sensor.label} (${sensor.unit})`,
              })),
            ]}
            value={sensorType}
            onChange={(event) => setSensorType(event.target.value)}
            containerClassName="w-48"
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={load}
            loading={loading}
            leftIcon={<RefreshCw size={15} aria-hidden="true" />}
          >
            Refresh
          </Button>
        </div>
      </header>

      {simulated ? (
        <Alert variant="warning" className="mt-3" title="This series includes simulated data">
          Every reading is labelled with its source. Points from the development simulator or a
          manual entry are shown here alongside hardware readings — {sourceSummary}.
        </Alert>
      ) : null}

      <div className="mt-4">
        {loading ? (
          <SkeletonBlock className="h-64 w-full" />
        ) : error ? (
          <ErrorState error={error} onRetry={load} />
        ) : !series?.points?.length ? (
          <EmptyState
            icon={<Activity size={22} aria-hidden="true" />}
            title="No readings in this window"
            description={
              series?.message ||
              'Nothing has been received for this hive in the selected period. The chart stays empty rather than showing a placeholder line.'
            }
          />
        ) : (
          <div style={{ height }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series.points} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e7dfd1" />
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={(value) => formatDateTime(value)}
                  tick={{ fontSize: 11 }}
                  minTickGap={40}
                />
                <YAxis tick={{ fontSize: 11 }} width={54} />
                <Tooltip content={<ChartTooltip />} />
                <Legend formatter={(value) => sensorMeta(value)?.label || value} wrapperStyle={{ fontSize: 12 }} />
                {plottedKeys.map((key) => (
                  <Line
                    key={key}
                    type="monotone"
                    dataKey={key}
                    stroke={COLORS[key] || '#0369a1'}
                    dot={false}
                    strokeWidth={2}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {sourceSummary && series?.points?.length ? (
        <p className="mt-3 text-xs text-ink-muted">
          Sources in this window: {sourceSummary} · {series.count} point(s)
        </p>
      ) : null}
    </section>
  );
}

export default TelemetryChart;
