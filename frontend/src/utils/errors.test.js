import { describe, expect, it } from 'vitest';

import { ApiError } from '@/utils/errors';

describe('ApiError', () => {
  it('replaces the generic 422 message with the reason the server gave', () => {
    const error = new ApiError({
      code: 'VALIDATION_ERROR',
      message: 'Invalid request',
      status: 422,
      details: [{ field: '', message: 'Value error, Passwords do not match' }],
    });
    expect(error.message).toBe('Passwords do not match');
    expect(error.formErrors).toEqual(['Passwords do not match']);
    expect(error.fieldErrors).toEqual({});
  });

  it('names the field and counts the rest when several fail', () => {
    const error = new ApiError({
      code: 'VALIDATION_ERROR',
      message: 'Invalid request',
      status: 422,
      details: [
        { field: 'phone', message: 'Value error, Phone must be a valid number' },
        { field: 'email', message: 'value is not a valid email address: x' },
      ],
    });
    expect(error.message).toBe('Phone: Phone must be a valid number (and 1 more)');
    expect(error.fieldErrors.email).toBe('Enter a valid email address.');
  });

  it('keeps a specific server message untouched', () => {
    const error = new ApiError({
      code: 'CONFLICT',
      message: 'An account with this email already exists',
      status: 409,
      details: [{ field: 'email', message: 'taken' }],
    });
    expect(error.message).toBe('An account with this email already exists');
  });
});
