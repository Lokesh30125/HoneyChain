import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader, CardFooter } from '@/components/ui/Card';
import { AnomalyList } from '@/components/ai/AnomalyList';
import { AssessmentDisclaimer } from '@/components/ai/AssessmentDisclaimer';
import { ContributionList } from '@/components/ai/ContributionList';
import { ScoreDial } from '@/components/ai/ScoreDial';
import { formatConfidence, healthMeta, TREND_LABELS } from '@/constants/ai';

/**
 * The colony-health indicator, its evidence and its caveats.
 *
 * The score, the band and the factor list always appear together: an assessment
 * whose arithmetic is not shown next to it is exactly the "trust me" output this
 * phase is required to avoid. When the engine declined to score — too little
 * telemetry, a stale window — the card says so instead of showing a zero.
 */
export function HealthAssessmentCard({ health = null, className = '' }) {
  if (!health) {
    return (
      <Card className={className}>
        <CardHeader title="Colony health indicator" />
        <CardBody>
          <p className="text-sm text-ink-muted">No health assessment has been stored for this hive.</p>
        </CardBody>
      </Card>
    );
  }

  const meta = healthMeta(health.status);
  const tone = { success: 'success', warning: 'warning', danger: 'warning', neutral: 'neutral' }[
    meta.tone
  ];
  const scored = typeof health.score === 'number';

  return (
    <Card className={className} data-testid="ai-health-card">
      <CardHeader
        title="Colony health indicator"
        description="Weighted from the recorded sensor patterns against reference bands."
        action={
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={meta.tone}>{meta.label}</Badge>
            <Badge variant="neutral" size="sm">
              Confidence {formatConfidence(health.confidence)}
            </Badge>
          </div>
        }
      />

      <CardBody className="space-y-4">
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
          <ScoreDial score={scored ? health.score : null} tone={tone} />
          <div className="min-w-0 flex-1 space-y-2">
            <p className="text-sm text-ink">{health.summary}</p>
            {meta.hint ? <p className="text-sm text-ink-muted">{meta.hint}</p> : null}
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="neutral" size="sm">
                Trend {TREND_LABELS[health.trend] || 'Unknown'}
              </Badge>
              {scored ? null : (
                <Badge variant="neutral" size="sm">
                  Not scored
                </Badge>
              )}
            </div>
            {health.basis ? <p className="text-xs text-ink-muted">{health.basis}</p> : null}
          </div>
        </div>

        {health.factors?.length ? (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
              What built this score
            </h3>
            <ContributionList items={health.factors} />
          </div>
        ) : (
          <p className="text-sm text-ink-muted">
            {scored
              ? 'No individual factor was recorded with this analysis.'
              : 'Contributing factors are listed once the hive has enough telemetry.'}
          </p>
        )}

        {health.anomalies?.length ? (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
              Patterns outside their band
            </h3>
            <AnomalyList anomalies={health.anomalies} />
          </div>
        ) : null}
      </CardBody>

      <CardFooter>
        <AssessmentDisclaimer text={health.disclaimer} />
      </CardFooter>
    </Card>
  );
}

export default HealthAssessmentCard;
