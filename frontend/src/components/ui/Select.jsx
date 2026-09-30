import { forwardRef, useId } from 'react';
import { ChevronDown } from 'lucide-react';

/**
 * Native select styled to match `Input`.
 *
 * A native element is deliberate: it is keyboard accessible, works on low-end
 * Android devices common in the field, and needs no custom listbox code.
 */

export const Select = forwardRef(function Select(
  {
    label,
    name,
    options = [],
    placeholder,
    error,
    hint,
    required = false,
    className = '',
    containerClassName = '',
    children,
    ...rest
  },
  ref,
) {
  const generatedId = useId();
  const selectId = rest.id || `${name || 'select'}-${generatedId}`;
  const errorId = `${selectId}-error`;
  // An option may carry a short note (an email address, how much work a person is
  // already holding). A native <option> cannot render it, so it is shown for
  // whichever option is currently chosen — the moment it is worth reading.
  const selectedOption = options.find((option) => String(option.value) === String(rest.value ?? ''));
  const optionNote = !error && selectedOption?.helper ? selectedOption.helper : null;

  return (
    <div className={containerClassName}>
      {label ? (
        <label htmlFor={selectId} className="hc-label">
          {label}
          {required ? (
            <span className="ml-1 text-status-danger" aria-hidden="true">
              *
            </span>
          ) : null}
        </label>
      ) : null}

      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          name={name}
          required={required}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? errorId : undefined}
          className={[
            'h-11 w-full appearance-none rounded-lg border bg-white px-3 pr-10 text-sm text-ink',
            'transition-colors focus:outline-none focus:ring-2 focus:ring-honey-500',
            error ? 'border-status-danger focus:ring-status-danger' : 'border-sand-300',
            rest.disabled ? 'cursor-not-allowed bg-sand-100 text-ink-muted' : '',
            className,
          ]
            .filter(Boolean)
            .join(' ')}
          {...rest}
        >
          {placeholder ? <option value="">{placeholder}</option> : null}
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
          {children}
        </select>
        <ChevronDown
          size={16}
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-ink-muted"
          aria-hidden="true"
        />
      </div>

      {error ? (
        <p id={errorId} className="mt-1.5 text-sm text-status-danger">
          {error}
        </p>
      ) : null}
      {hint && !error ? <p className="mt-1.5 text-sm text-ink-muted">{hint}</p> : null}
      {optionNote ? <p className="mt-1 text-xs text-ink-muted">{optionNote}</p> : null}
    </div>
  );
});

export default Select;
