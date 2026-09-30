/** White surface with a subtle border — the base container for content. */

export function Card({ children, className = '', as: Component = 'div', ...rest }) {
  return (
    <Component className={`hc-card ${className}`} {...rest}>
      {children}
    </Component>
  );
}

export function CardHeader({ title, description, action = null, icon = null, className = '' }) {
  return (
    <div
      className={`flex flex-wrap items-start justify-between gap-3 border-b border-sand-200 px-5 py-4 ${className}`}
    >
      <div className="flex min-w-0 items-start gap-3">
        {icon ? (
          <span className="mt-0.5 flex h-9 w-9 flex-none items-center justify-center rounded-lg bg-honey-50 text-honey-700">
            {icon}
          </span>
        ) : null}
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold text-ink">{title}</h2>
          {description ? <p className="mt-0.5 text-sm text-ink-muted">{description}</p> : null}
        </div>
      </div>
      {action}
    </div>
  );
}

export function CardBody({ children, className = '' }) {
  return <div className={`px-5 py-4 ${className}`}>{children}</div>;
}

export function CardFooter({ children, className = '' }) {
  return (
    <div className={`border-t border-sand-200 bg-sand-100/60 px-5 py-3 ${className}`}>{children}</div>
  );
}

export default Card;
