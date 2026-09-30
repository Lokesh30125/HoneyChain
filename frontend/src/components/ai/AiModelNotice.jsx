import { Badge } from '@/components/ui/Badge';
import { MODEL_NOTICE } from '@/constants/ai';

/**
 * The model identity, printed wherever a score is.
 *
 * A number with no provenance invites the reader to assume more than the engine
 * claims, so the type, the version and the "not a diagnosis" sentence travel
 * with every assessment rather than living in a footnote.
 */
export function AiModelNotice({ model = null, modelType, modelVersion, className = '' }) {
  const type = model?.type || modelType;
  const version = model?.version || modelVersion;

  return (
    <div
      className={`flex flex-wrap items-center gap-2 text-xs text-ink-muted ${className}`}
      data-testid="ai-model-notice"
    >
      <Badge variant="forest" size="sm">
        Rule-based baseline
      </Badge>
      {type ? (
        <span>
          <code className="rounded bg-sand-100 px-1 py-0.5">{type}</code>
          {version ? ` v${version}` : ''}
        </span>
      ) : null}
      <span>{model?.note || MODEL_NOTICE}</span>
    </div>
  );
}

export default AiModelNotice;
