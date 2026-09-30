import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BellRing, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/common/EmptyState';
import { ErrorState } from '@/components/common/ErrorState';
import { LoadingState } from '@/components/common/LoadingState';
import { AlertCard } from '@/components/ai/AlertCard';
import { AnalysisHistoryTable } from '@/components/ai/AnalysisHistoryTable';
import { AnalysisMetaBar } from '@/components/ai/AnalysisMetaBar';
import { DataQualityPanel } from '@/components/ai/DataQualityPanel';
import { HealthAssessmentCard } from '@/components/ai/HealthAssessmentCard';
import { RecommendationList } from '@/components/ai/RecommendationList';
import { RiskAssessmentCard } from '@/components/ai/RiskAssessmentCard';
import { YieldProjectionPanel } from '@/components/ai/YieldProjectionPanel';
import { formatConfidence } from '@/constants/ai';
import { formatDateTime } from '@/utils/format';
import { normaliseError } from '@/utils/errors';
import { useToast } from '@/hooks/useToast';
import * as aiService from '@/services/aiService';

const HISTORY_PAGE_SIZE = 5;

/**
 * The AI section of one hive's page.
 *
 * The read is *read-through*: opening the page reuses the stored analysis when it
 * is fresh, recomputes it when it is stale or when enough new telemetry has
 * arrived, and forces a run when the reader asks. Which of those happened is
 * printed above the numbers (`compute_reason`), because a score whose age is
 * invisible is a score nobody can judge.
 *
 * Nothing here is estimated: with no analysis the section explains what is
 * missing and offers the one action that changes it.
 */
export function HiveAiSection({ hiveId, hiveCode = null, alertsHref = '/beekeeper/alerts', className = '' }) {
  const toast = useToast();
  const [insight, setInsight] = useState(null);
  const [hiveAlerts, setHiveAlerts] = useState([]);
  const [history, setHistory] = useState([]);
  const [historyMeta, setHistoryMeta] = useState(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(
    async ({ refresh = null } = {}) => {
      if (!hiveId) return;
      setLoading(true);
      setError(null);
      try {
        const payload = await aiService.getInsight(hiveId, { refresh });
        setInsight(payload);
        const [alerts, historyResult] = await Promise.all([
          aiService.listHiveAlerts(hiveId, { includeResolved: false, limit: 10 }),
          aiService.getHistory(hiveId, { page: historyPage, pageSize: HISTORY_PAGE_SIZE }),
        ]);
        setHiveAlerts(alerts);
        setHistory(historyResult.analyses);
        setHistoryMeta(historyResult.meta);
      } catch (caught) {
        setError(normaliseError(caught));
      } finally {
        setLoading(false);
      }
    },
    [hiveId, historyPage],
  );

  useEffect(() => {
    load();
  }, [load]);

  const recompute = async () => {
    setRunning(true);
    try {
      const result = await aiService.analyzeHive(hiveId, 'manual run from the hive page');
      toast.success(
        'Analysis stored',
        `${result.health_status.toLowerCase().replace(/_/g, ' ')} · ${
          typeof result.health_score === 'number' ? `indicator ${result.health_score}` : 'not scored'
        } · ${result.alerts_created} new alert(s), ${result.alerts_bumped} repeated.`,
      );
      await load({ refresh: false });
    } catch (caught) {
      const normalised = normaliseError(caught);
      toast.error('The analysis did not complete', normalised.message);
    } finally {
      setRunning(false);
    }
  };

  if (loading && !insight) {
    return (
      <Card className={className}>
        <CardHeader title="AI insights" icon={<Sparkles size={18} aria-hidden="true" />} />
        <CardBody>
          <LoadingState label="Loading the analysis for this hive…" />
        </CardBody>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={className}>
        <CardHeader title="AI insights" icon={<Sparkles size={18} aria-hidden="true" />} />
        <CardBody>
          <ErrorState error={error} onRetry={() => load()} />
        </CardBody>
      </Card>
    );
  }

  if (!insight?.analyzed) {
    const disabled = insight?.compute_reason === 'auto_disabled';
    return (
      <Card className={className} data-testid="ai-section-empty">
        <CardHeader
          title="AI insights"
          description="Colony health, risk indicators and yield projection from this hive's telemetry."
          icon={<Sparkles size={18} aria-hidden="true" />}
        />
        <CardBody>
          <EmptyState
            icon={<Sparkles size={22} aria-hidden="true" />}
            title="No analysis for this hive yet"
            description={
              disabled
                ? 'Automatic analysis is disabled on this deployment, so no assessment is produced until one is requested. Run one now to see what the recorded telemetry supports.'
                : 'An assessment is produced from stored telemetry. Run one now to see what the recorded readings support — and if there is not enough yet, the engine will say so rather than guess.'
            }
            action={
              <Button onClick={recompute} loading={running} data-testid="ai-empty-run">
                Run analysis
              </Button>
            }
          />
          <AnalysisMetaBar insight={insight} busy={running} onRecompute={recompute} className="mt-4" />
        </CardBody>
      </Card>
    );
  }

  return (
    <div className={`space-y-4 ${className}`} data-testid="ai-section">
      <Card>
        <CardHeader
          title="AI insights"
          description="Rule-based assessment of this hive's recorded telemetry. Indicators and prompts — not diagnoses."
          icon={<Sparkles size={18} aria-hidden="true" />}
        />
        <CardBody className="space-y-4">
          <AnalysisMetaBar
            insight={insight}
            busy={running}
            onRead={() => load({ refresh: false })}
            onRecompute={recompute}
          />
          {insight.summary ? <p className="text-sm text-ink">{insight.summary}</p> : null}
        </CardBody>
      </Card>

      {hiveAlerts.length ? (
        <Card>
          <CardHeader
            title="Open alerts for this hive"
            description="Raised by the same analysis run, de-duplicated within the cooldown window."
            icon={<BellRing size={18} aria-hidden="true" />}
            action={
              <Link to={alertsHref} className="text-sm font-medium text-forest-700 hover:underline">
                Handle in Alerts
              </Link>
            }
          />
          <CardBody className="space-y-3">
            {hiveAlerts.map((alert) => (
              <AlertCard key={alert.id} alert={alert} />
            ))}
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <HealthAssessmentCard health={insight.health} className="lg:col-span-2" />
        <Card>
          <CardHeader title="Yield projection" description="Extrapolated from the measured weight trend." />
          <CardBody className="space-y-4">
            <YieldProjectionPanel prediction={insight.yield_prediction} />
            <div className="border-t border-sand-200 pt-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Evidence behind this analysis
              </h3>
              <DataQualityPanel
                quality={insight.quality}
                source={insight.analysis_source}
                sourceLabel={insight.analysis_source_label}
              />
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <RiskAssessmentCard
          assessment={insight.disease_risk}
          title="Disease risk indicator"
          description="Stress patterns associated with disease pressure. A prompt to inspect — never a diagnosis."
        />
        <RiskAssessmentCard
          assessment={insight.swarming_risk}
          title="Swarming risk indicator"
          description="Patterns commonly seen around swarming. It does not predict that a swarm will happen."
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="What is worth checking"
            description="Each item names the observation it came from."
          />
          <CardBody>
            <RecommendationList recommendations={insight.recommendations} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader
            title="Where these numbers come from"
            description="The model that produced them, and the telemetry it was allowed to read."
          />
          <CardBody className="space-y-3">
            <dl className="grid gap-y-2 text-sm">
              <Row label="Model" value={`${insight.model_type} v${insight.model_version}`} />
              <Row label="Overall confidence" value={formatConfidence(insight.overall_confidence)} />
              <Row label="Readings considered" value={insight.sample_count} />
              <Row
                label="Telemetry source"
                value={insight.analysis_source_label || insight.analysis_source}
              />
              <Row
                label="Window"
                value={`${formatDateTime(insight.window_start)} → ${formatDateTime(insight.window_end)}`}
              />
              <Row label="Stored analysis" value={formatDateTime(insight.analyzed_at)} />
            </dl>
            {hiveCode ? (
              <p className="text-xs text-ink-muted">
                Every figure above belongs to {hiveCode} and to the window it names. Nothing is
                carried across hives or between runs.
              </p>
            ) : null}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Stored analyses"
          description="Newest first. Each row keeps the model version and the bands it was produced with."
        />
        <CardBody>
          <AnalysisHistoryTable
            analyses={history}
            meta={historyMeta}
            onPageChange={setHistoryPage}
            loading={loading && !history.length}
          />
        </CardBody>
      </Card>
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

export default HiveAiSection;
