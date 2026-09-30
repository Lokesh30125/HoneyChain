import { ShieldAlert } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Card, CardBody, CardFooter, CardHeader } from '@/components/ui/Card';
import { AnomalyList } from '@/components/ai/AnomalyList';
import { AssessmentDisclaimer } from '@/components/ai/AssessmentDisclaimer';
import { ContributionList } from '@/components/ai/ContributionList';
import { formatConfidence, riskMeta } from '@/constants/ai';

/**
 * A risk band — for disease and for swarming — with the indicators behind it.
 *
 * The heading says "risk", the copy says "prompt to inspect", and the level is
 * never rendered without the disclaimer underneath it. `UNKNOWN` is a real
 * answer here: with no telemetry, "not assessed" is more truthful than "low".
 */
export function RiskAssessmentCard({ assessment = null, title, description, className = '' }) {
  if (!assessment) {
    return (
      <Card className={className}>
        <CardHeader title={title} />
        <CardBody>
          <p className="text-sm text-ink-muted">No assessment has been stored for this hive.</p>
        </CardBody>
      </Card>
    );
  }

  const meta = riskMeta(assessment.level);
  const scored = typeof assessment.score === 'number';

  return (
    <Card className={className} data-testid="ai-risk-card">
      <CardHeader
        title={title}
        description={description}
        icon={<ShieldAlert size={18} aria-hidden="true" />}
        action={
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={meta.tone}>Risk {meta.label}</Badge>
            <Badge variant="neutral" size="sm">
              Confidence {formatConfidence(assessment.confidence)}
            </Badge>
          </div>
        }
      />

      <CardBody className="space-y-4">
        <div>
          <p className="text-3xl font-semibold tracking-tight text-ink">
            {scored ? assessment.score : '—'}
            <span className="text-base font-medium text-ink-soft"> / 100</span>
          </p>
          <p className="mt-1 text-sm text-ink">{assessment.summary}</p>
        </div>

        {assessment.indicators?.length ? (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
              Indicators
            </h3>
            <ContributionList
              items={assessment.indicators}
              emptyLabel="No indicators were recorded for this window."
            />
          </div>
        ) : null}

        {assessment.anomalies?.length ? (
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">
              Patterns outside their band
            </h3>
            <AnomalyList anomalies={assessment.anomalies} />
          </div>
        ) : null}

        {assessment.recommendation ? (
          <div className="rounded-lg border border-sand-200 bg-sand-50/60 p-3">
            <p className="text-sm font-semibold text-ink">{assessment.recommendation.title}</p>
            <p className="mt-1 text-sm text-ink-soft">{assessment.recommendation.detail}</p>
            <p className="mt-1.5 text-xs text-ink-muted">{assessment.recommendation.reason}</p>
          </div>
        ) : null}
      </CardBody>

      <CardFooter>
        <AssessmentDisclaimer text={assessment.disclaimer} />
      </CardFooter>
    </Card>
  );
}

export default RiskAssessmentCard;
