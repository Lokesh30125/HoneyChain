/**
 * Section header used by every landing-page block: an eyebrow label, a heading
 * and an optional lead paragraph. Keeps typography consistent site-wide.
 */
export function SectionHeading({
  eyebrow,
  title,
  description,
  align = 'left',
  className = '',
  as: Heading = 'h2',
}) {
  const alignment = align === 'center' ? 'text-center mx-auto items-center' : 'text-left';

  return (
    <div className={`flex max-w-3xl flex-col ${alignment} ${className}`}>
      {eyebrow ? (
        <span className="mb-3 inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-honey-700">
          <span className="h-px w-6 bg-honey-400" aria-hidden="true" />
          {eyebrow}
        </span>
      ) : null}
      <Heading className="text-2xl font-semibold tracking-tight text-ink sm:text-3xl">{title}</Heading>
      {description ? (
        <p className="mt-3 text-base leading-relaxed text-ink-soft">{description}</p>
      ) : null}
    </div>
  );
}

export default SectionHeading;
