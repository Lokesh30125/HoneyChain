import { Info } from 'lucide-react';

/**
 * The sentence that must accompany an assessment.
 *
 * Rendered from the payload's own `disclaimer` field wherever the API sent one,
 * so the wording the engine was written with travels with the number it
 * qualifies, and falls back to the shared constant otherwise.
 */
export function AssessmentDisclaimer({ text, className = '' }) {
  if (!text) return null;

  return (
    <p className={`flex items-start gap-2 text-xs text-ink-muted ${className}`} data-testid="ai-disclaimer">
      <Info size={14} className="mt-0.5 flex-none" aria-hidden="true" />
      <span>{text}</span>
    </p>
  );
}

export default AssessmentDisclaimer;
