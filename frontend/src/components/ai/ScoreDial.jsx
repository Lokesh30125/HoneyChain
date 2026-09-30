/**
 * The health indicator as a ring gauge.
 *
 * Built from two SVG circles rather than a charting library: it is one arc, and
 * a library would add a dependency for pixels. The number in the middle is the
 * value the engine stored — the ring never animates towards a value that was not
 * measured.
 */

const TONE_CLASSES = {
  success: 'text-status-success',
  warning: 'text-status-warning',
  danger: 'text-status-danger',
  neutral: 'text-ink-muted',
};

export function ScoreDial({ score = null, tone = 'neutral', caption = null, size = 132 }) {
  const value = typeof score === 'number' ? Math.max(0, Math.min(100, score)) : null;
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const filled = value === null ? 0 : (value / 100) * circumference;

  return (
    <div className="flex flex-col items-center" data-testid="ai-score-dial">
      <svg
        width={size}
        height={size}
        viewBox="0 0 132 132"
        className={TONE_CLASSES[tone] || TONE_CLASSES.neutral}
        role="img"
        aria-label={value === null ? 'No health indicator available' : `Health indicator ${value} out of 100`}
      >
        <circle
          cx="66"
          cy="66"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.14"
          strokeWidth="10"
        />
        <circle
          cx="66"
          cy="66"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          transform="rotate(-90 66 66)"
        />
        <text
          x="66"
          y="62"
          textAnchor="middle"
          className="fill-ink font-semibold"
          style={{ fontSize: '30px' }}
        >
          {value === null ? '—' : value}
        </text>
        <text
          x="66"
          y="82"
          textAnchor="middle"
          className="fill-ink-muted"
          style={{ fontSize: '12px' }}
        >
          {value === null ? 'not scored' : 'of 100'}
        </text>
      </svg>
      {caption ? <p className="mt-1 text-center text-xs text-ink-muted">{caption}</p> : null}
    </div>
  );
}

export default ScoreDial;
