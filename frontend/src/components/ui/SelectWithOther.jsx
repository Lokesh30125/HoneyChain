import { Select } from '@/components/ui/Select';
import { Input } from '@/components/ui/Input';

/**
 * A dropdown that can also say "Other" — and, when it does, ask what that was.
 *
 * The platform has several fields whose real answer is one of a known set *or*
 * something outside it: what a processing run did, what a batch was packed into,
 * what hardware a device is, how a laboratory measured a sample. Recording the
 * word "Other" on its own would say that something happened and nothing about
 * what — so this control keeps the pair together:
 *
 * * choosing **Other** reveals the "specify" field, which takes continuous typing
 *   like any other input;
 * * choosing a listed value again **hides** that field and clears whatever was
 *   typed into it, so a stale description can never sit behind a listed choice;
 * * the two are submitted as a pair (`value` + `otherValue`), which the server
 *   validates independently — a description with a listed value is refused there
 *   too, so the rule does not depend on this component being used.
 *
 * It is one component rather than a pattern copied per page, because "Other" that
 * behaves differently in two places is the same defect as "Other" that does not
 * work at all.
 *
 * ## Props
 *
 * - `value` / `onChange` — the selected option, as a normal `Select` would give it.
 * - `otherValue` / `onOtherChange` — the free text, held by the caller alongside
 *   the value so both are submitted together.
 * - `otherValueKey` — which option counts as "Other" (defaults to `OTHER`).
 * - everything else (`label`, `name`, `options`, `hint`, `error`, `placeholder`,
 *   `required`) is passed straight to the underlying `Select`.
 */
export function SelectWithOther({
  label,
  name,
  options = [],
  value,
  onChange,
  otherValue = '',
  onOtherChange,
  otherValueKey = 'OTHER',
  otherLabel = 'Specify other',
  otherPlaceholder = 'Describe it in your own words',
  otherHint = null,
  error = null,
  hint,
  required = false,
  containerClassName = '',
  ...rest
}) {
  const isOther = String(value ?? '') === otherValueKey;

  return (
    <div className={containerClassName}>
      <Select
        label={label}
        name={name}
        options={options}
        value={value}
        onChange={(event) => {
          const next = event.target.value;
          onChange?.(event);
          // Leaving "Other" clears the description: it belonged to the choice that
          // has just been replaced, and keeping it would attach it to the wrong one.
          if (String(next) !== otherValueKey) {
            onOtherChange?.('');
          }
        }}
        hint={hint}
        error={error}
        required={required}
        {...rest}
      />

      {isOther ? (
        <div className="mt-3">
          <Input
            label={otherLabel}
            name={`${name || 'field'}_other`}
            value={otherValue}
            onChange={(event) => onOtherChange?.(event.target.value)}
            placeholder={otherPlaceholder}
            hint={otherHint || `Recorded as the ${String(label || 'value').toLowerCase()} for this record.`}
            required
            // The description is part of the same answer, so it is marked invalid
            // with the same error the select would carry when it is missing: the
            // server refuses the pair, and the form says so before submitting.
            error={isOther && !String(otherValue || '').trim() ? error : null}
            data-testid={`${name || 'field'}-other`}
          />
        </div>
      ) : null}
    </div>
  );
}

export default SelectWithOther;
