/**
 * Error normalisation.
 *
 * The backend always answers with
 *   { success: false, error: { code, message, details } }
 * so the UI never has to guess a shape. `normaliseError` converts anything —
 * axios error, thrown Error, unknown value — into that one shape, which is what
 * `ErrorState` and the forms render.
 */

import { API_ERROR_CODES, ERROR_MESSAGES_BY_STATUS } from '@/constants/api';

/**
 * Framework messages are precise but not written for end users. Translate the
 * few that reach a form (`"value is not a valid email address: …"`) and drop the
 * `"Value error, "` prefix the validator adds, so a message can be shown as-is.
 */
const MESSAGE_REWRITES = [
  [/^value is not a valid email address/i, 'Enter a valid email address.'],
  [/^value is not a valid (integer|number)/i, 'Enter a valid number.'],
  [/^string should have at least (\d+) characters/i, (_, count) => `Use at least ${count} characters.`],
  [/^string should have at most (\d+) characters/i, (_, count) => `Use at most ${count} characters.`],
  [/^field required/i, 'This field is required.'],
  [/^input should be a valid (integer|number)/i, 'Enter a whole number.'],
];

export function humaniseMessage(message) {
  if (typeof message !== 'string' || !message) return message;
  let text = message.replace(/^Value error,\s*/i, '').trim();
  for (const [pattern, replacement] of MESSAGE_REWRITES) {
    if (pattern.test(text)) {
      text = typeof replacement === 'function' ? text.replace(pattern, replacement) : replacement;
      break;
    }
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The server's generic 422 message ("Invalid request") says nothing a person can
 * act on. When the details carry the actual reason, lead with it instead, so every
 * screen that shows `error.message` shows the reason.
 */
function specificMessage(message, details) {
  if (!Array.isArray(details) || !details.length) return message;
  if (typeof message === 'string' && message && !/^invalid request$/i.test(message.trim())) {
    return message;
  }
  const first = details.find((detail) => detail?.message);
  if (!first) return message;
  const reason = humaniseMessage(first.message);
  const extra = details.length > 1 ? ` (and ${details.length - 1} more)` : '';
  return first.field ? `${first.field.replace(/_/g, ' ')}: ${reason}${extra}` : `${reason}${extra}`;
}

export class ApiError extends Error {
  constructor({ code, message, status, details }) {
    super(humaniseMessage(specificMessage(message, details)));
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details || null;
  }

  /**
   * Field-level messages keyed by input name, ready for form errors.
   *
   * Two shapes reach the client: a list of per-field validation details, and a
   * single `{ field }` marker attached to conflict errors (duplicate email or
   * phone). Both are mapped onto the input that caused them.
   */
  /**
   * Messages that belong to the whole form rather than one input — cross-field
   * rules such as "Passwords do not match" arrive with an empty field name.
   */
  get formErrors() {
    if (!Array.isArray(this.details)) return [];
    return this.details
      .filter((detail) => detail && !detail.field && detail.message)
      .map((detail) => humaniseMessage(detail.message));
  }

  get fieldErrors() {
    if (Array.isArray(this.details)) {
      return this.details.reduce((accumulator, detail) => {
        if (detail?.field) accumulator[detail.field] = humaniseMessage(detail.message);
        return accumulator;
      }, {});
    }
    if (this.details && typeof this.details === 'object' && this.details.field) {
      return { [this.details.field]: this.message };
    }
    return {};
  }
}

export function normaliseError(error) {
  if (error instanceof ApiError) return error;

  // Request reached the server and came back with the standard envelope.
  const payload = error?.response?.data;
  if (payload?.error) {
    return new ApiError({
      code: payload.error.code || API_ERROR_CODES.INTERNAL_ERROR,
      message: payload.error.message || 'Request failed',
      status: error.response.status,
      details: payload.error.details,
    });
  }

  // Server responded without our envelope (proxy error page, wrong host, …).
  if (error?.response) {
    const status = error.response.status;
    return new ApiError({
      code: API_ERROR_CODES.INTERNAL_ERROR,
      message:
        ERROR_MESSAGES_BY_STATUS[status] ||
        `The server responded with an unexpected status (${status}).`,
      status,
    });
  }

  // No response at all: offline, DNS failure, backend not running.
  if (error?.request) {
    return new ApiError({
      code: API_ERROR_CODES.NETWORK_ERROR,
      message:
        'We could not reach the HoneyChain API. Check that the backend is running and try again.',
    });
  }

  return new ApiError({
    code: API_ERROR_CODES.INTERNAL_ERROR,
    message: error?.message || 'An unexpected error occurred.',
  });
}

/** True when the request failed because the user needs to sign in again. */
export function isSessionExpired(error) {
  const normalised = normaliseError(error);
  return [
    API_ERROR_CODES.AUTHENTICATION_ERROR,
    API_ERROR_CODES.TOKEN_EXPIRED,
    API_ERROR_CODES.TOKEN_INVALID,
  ].includes(normalised.code);
}
