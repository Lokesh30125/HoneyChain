import { forwardRef, useId } from 'react';

/**
 * Text input with label, hint, error and optional leading/trailing adornments.
 *
 * Accessible by construction: the label is always bound to the input, and
 * `aria-invalid` / `aria-describedby` are wired from the error and hint props,
 * so screen readers announce validation problems.
 */

export const Input = forwardRef(function Input(
  {
    label,
    name,
    type = 'text',
    error,
    hint,
    required = false,
    leftIcon = null,
    rightSlot = null,
    className = '',
    containerClassName = '',
    ...rest
  },
  ref,
) {
  const generatedId = useId();
  const inputId = rest.id || `${name || 'field'}-${generatedId}`;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;
  const describedBy = [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(' ');

  return (
    <div className={containerClassName}>
      {label ? (
        <label htmlFor={inputId} className="hc-label">
          {label}
          {required ? (
            <span className="ml-1 text-status-danger" aria-hidden="true">
              *
            </span>
          ) : null}
        </label>
      ) : null}

      <div className="relative">
        {leftIcon ? (
          <span
            className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-ink-muted"
            aria-hidden="true"
          >
            {leftIcon}
          </span>
        ) : null}

        <input
          ref={ref}
          id={inputId}
          name={name}
          type={type}
          required={required}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={describedBy || undefined}
          className={[
            'h-11 w-full rounded-lg border bg-white px-3 text-sm text-ink placeholder:text-ink-muted/70',
            'transition-colors focus:outline-none focus:ring-2 focus:ring-honey-500 focus:ring-offset-0',
            leftIcon ? 'pl-10' : '',
            rightSlot ? 'pr-11' : '',
            error ? 'border-status-danger focus:ring-status-danger' : 'border-sand-300',
            rest.disabled ? 'cursor-not-allowed bg-sand-100 text-ink-muted' : '',
            className,
          ]
            .filter(Boolean)
            .join(' ')}
          {...rest}
        />

        {rightSlot ? <div className="absolute inset-y-0 right-0 flex items-center pr-2">{rightSlot}</div> : null}
      </div>

      {error ? (
        <p id={errorId} className="mt-1.5 text-sm text-status-danger">
          {error}
        </p>
      ) : null}
      {hint && !error ? (
        <p id={hintId} className="mt-1.5 text-sm text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
});

export default Input;
